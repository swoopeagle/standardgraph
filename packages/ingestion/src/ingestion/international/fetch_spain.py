"""Fetch and ingest Spain LOMLOE 2022 primary math standards (Grades 1-6).

System: es-lomloe
Source: Real Decreto 157/2022 — Educación Primaria (LOMLOE)
  PDF: BOE (boe.es) — consolidated text

Covers 3 grade cycles of Educación Primaria:
  Cycle 1 = grades 1-2  (Primer ciclo)
  Cycle 2 = grades 3-4  (Segundo ciclo)
  Cycle 3 = grades 5-6  (Tercer ciclo)

6 Competencias específicas (math subject competencies):
  CE1 = Interpret real-world situations mathematically
  CE2 = Problem solving and strategies
  CE3 = Mathematical reasoning and proof
  CE4 = Mathematical connections and modeling
  CE5 = Mathematical communication and representation
  CE6 = Computational thinking

Standards are "Criterios de evaluación" (evaluation criteria), coded N.M
where N = competency number (1-6) and M = criterion number within competency.

ID format: ES_LOMLOE.MATH.PRIM.C{cycle}.CE{n}.{m:02d}
  e.g. ES_LOMLOE.MATH.PRIM.C1.CE1.01
"""
import json
import re
import sqlite3
import urllib.request
from datetime import date
from pathlib import Path

import fitz  # PyMuPDF
import httpx

from shared.config import DB_PATH, OLLAMA_BASE_URL, OLLAMA_MODEL

SYSTEM = "es-lomloe"
VERIFIED_DATE = date.today().isoformat()
RAW_DIR = DB_PATH.parent / "raw" / "es"
PDF_URL = "https://www.boe.es/buscar/pdf/2022/BOE-A-2022-3296-consolidado.pdf"
PDF_FILE = "es_lomloe_primaria.pdf"

# 0-indexed page indices for "Criterios de evaluación" per cycle
CYCLE_CRITERIA_PAGES = [
    (1, "Primer ciclo (grades 1-2)",  "1-2",  96),   # page 97
    (2, "Segundo ciclo (grades 3-4)", "3-4",  99),   # page 100
    (3, "Tercer ciclo (grades 5-6)",  "5-6", 103),   # page 104
]

GRADE_FOR_CYCLE = {1: "1", 2: "3", 3: "5"}  # lower bound of cycle

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each",
    "such", "both", "also", "into", "more", "most", "some", "other",
    "these", "those", "about", "able", "after", "where", "while", "make",
    "used", "given", "find", "show", "know", "understand", "apply",
    "students", "student", "numbers", "values", "different", "life",
}

EXTRACT_PROMPT = """\
Below are the "Criterios de evaluación" (evaluation criteria / learning standards) for
Spain's LOMLOE 2022 primary mathematics curriculum, {cycle_label}.

The criteria are coded N.M where N is the "Competencia específica" (CE) number (1-6)
and M is the sequential criterion within that competency.

The 6 competencies are:
  CE1 = Interpreting real-world situations mathematically
  CE2 = Problem solving strategies
  CE3 = Mathematical reasoning and proof
  CE4 = Mathematical connections and modeling
  CE5 = Mathematical communication and representation
  CE6 = Computational thinking

Extract all individual criteria (N.M format). Each criterion is a brief description
of what students should be able to do.

Return ONLY a JSON array (no markdown). Each element:
  "ce"     : integer competency number (1-6)
  "m"      : integer criterion number within competency
  "text_es": Spanish text verbatim (the full criterion statement, trimmed)
  "text_en": accurate English translation

CRITERIA TEXT ({cycle_label}):
{text}
"""


def _download(url: str, path: Path) -> None:
    print(f"  Downloading {path.name} …")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(path, "wb") as f:
        f.write(r.read())
    print(f"  Saved {path.stat().st_size:,} bytes")


def _extract_page_text(pdf_path: Path, page_idx: int) -> str:
    doc = fitz.open(str(pdf_path))
    t = doc[page_idx].get_text().strip()
    doc.close()
    return t


def _call_model(cycle_label: str, text: str) -> list[dict]:
    prompt = EXTRACT_PROMPT.format(cycle_label=cycle_label, text=text[:8000])
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "keep_alive": "4h",
        "options": {"temperature": 0.0, "num_ctx": 8192},
    }
    resp = httpx.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload, timeout=1800)
    resp.raise_for_status()
    content = resp.json()["message"]["content"].strip()
    content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.MULTILINE)
    content = re.sub(r"\s*```$", "", content, flags=re.MULTILINE)
    m = re.search(r"\[.*\]", content, re.DOTALL)
    if not m:
        return []
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as e:
        print(f"    WARN JSON: {e}")
        return []


def _extract_keywords(text: str) -> list[str]:
    words = re.findall(r'\b[a-zA-Z][a-zA-Z-]{3,}\b', text.lower())
    seen: set[str] = set()
    result = []
    for w in words:
        if w not in STOP_WORDS and w not in seen:
            seen.add(w)
            result.append(w)
    return result[:20]


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = RAW_DIR / PDF_FILE

    if pdf_path.exists():
        print(f"Using cached {PDF_FILE} ({pdf_path.stat().st_size:,} bytes)")
    else:
        try:
            _download(PDF_URL, pdf_path)
        except Exception as e:
            print(f"ERROR downloading PDF: {e}")
            return

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")

    print(f"Clearing existing {SYSTEM} primary math data …")
    with conn:
        conn.execute("DELETE FROM keywords WHERE standard_id LIKE 'ES_LOMLOE.MATH.PRIM.%'")
        conn.execute("DELETE FROM standards WHERE id LIKE 'ES_LOMLOE.MATH.PRIM.%'")

    seen_ids: set[str] = set()
    grand_std = grand_kw = 0

    for cycle, cycle_label, grade_band, page_idx in CYCLE_CRITERIA_PAGES:
        text = _extract_page_text(pdf_path, page_idx)
        print(f"  Cycle {cycle} / {cycle_label} ({len(text)} chars) → model …", end="", flush=True)
        try:
            criteria = _call_model(cycle_label, text)
        except Exception as e:
            print(f" ERROR: {e}")
            continue

        ce_domain = {
            1: "Interpreting Mathematical Situations",
            2: "Mathematical Problem Solving",
            3: "Mathematical Reasoning and Proof",
            4: "Mathematical Connections and Modeling",
            5: "Mathematical Communication and Representation",
            6: "Computational Thinking",
        }

        cycle_std = cycle_kw = 0
        with conn:
            for crit in criteria:
                ce = crit.get("ce")
                m_num = crit.get("m")
                text_es = (crit.get("text_es") or "").strip()
                text_en = (crit.get("text_en") or "").strip()
                if not ce or not m_num or not text_en or len(text_en) < 10:
                    continue
                try:
                    ce_int = int(ce)
                    m_int = int(m_num)
                except (TypeError, ValueError):
                    continue
                if ce_int not in range(1, 7):
                    continue

                std_id = f"ES_LOMLOE.MATH.PRIM.C{cycle}.CE{ce_int}.{m_int:02d}"
                if std_id in seen_ids:
                    continue
                seen_ids.add(std_id)

                conn.execute(
                    """INSERT OR REPLACE INTO standards
                       (id, system, subject, grade, grade_band, domain, cluster,
                        standard_text, last_verified_date, source_url)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        std_id, SYSTEM, "mathematics",
                        GRADE_FOR_CYCLE[cycle], grade_band,
                        ce_domain.get(ce_int, f"CE{ce_int}"),
                        text_es,
                        text_en,
                        VERIFIED_DATE,
                        PDF_URL,
                    ),
                )
                cycle_std += 1
                for kw in _extract_keywords(text_en + " " + text_es):
                    conn.execute(
                        "INSERT OR IGNORE INTO keywords (standard_id, keyword) VALUES (?,?)",
                        (std_id, kw),
                    )
                    cycle_kw += 1

        grand_std += cycle_std
        grand_kw += cycle_kw
        print(f" {len(criteria)} extracted, {cycle_std} ingested")

    conn.close()
    print(f"\nTotal: {grand_std} standards, {grand_kw} keywords")
    print("Done.")


if __name__ == "__main__":
    main()
