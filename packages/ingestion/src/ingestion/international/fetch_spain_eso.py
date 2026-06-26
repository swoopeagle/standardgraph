"""Fetch and ingest Spain LOMLOE 2022 secondary math standards (Grades 7-10 / ESO).

System: es-lomloe (same as primary, extending with ESO grades)
Source: Real Decreto 217/2022 — Educación Secundaria Obligatoria (LOMLOE)
  PDF: BOE (boe.es) — consolidated text

Covers ESO (Educación Secundaria Obligatoria):
  Grades 7-9 (1°-3° ESO): Shared criteria set ("Cursos de primero a tercero")
  Grade 10 (4° ESO): Two tracks
    MATEMÁTICAS A = practical/applied track
    MATEMÁTICAS B = academic/preparatory track

10 Competencias específicas (same structure as primary but extended):
  CE1 = Problem solving strategies
  CE2 = Mathematical verification and validation
  CE3 = Mathematical reasoning and conjecture
  CE4 = Computational thinking and algorithms
  CE5 = Mathematical connections
  CE6 = Real-world connections and modeling
  CE7 = Mathematical representation
  CE8 = Mathematical communication
  CE9 = Socio-emotional skills (self-regulation)
  CE10 = Collaborative mathematical work

Standards coded N.M where N = CE number and M = criterion within competency.

ID format: ES_LOMLOE.MATH.ESO.{section}.CE{n}.{m:02d}
  Sections:
    G7_9  = grades 7-9 shared criteria (1°-3° ESO)
    G10A  = grade 10 MATEMÁTICAS A
    G10B  = grade 10 MATEMÁTICAS B
  e.g. ES_LOMLOE.MATH.ESO.G7_9.CE1.01
       ES_LOMLOE.MATH.ESO.G10A.CE4.01
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
PDF_URL = "https://www.boe.es/buscar/pdf/2022/BOE-A-2022-4975-consolidado.pdf"
PDF_FILE = "es_lomloe_eso.pdf"

# Each entry: (section_id, label, grade, grade_band, page_indices)
# page_indices are 0-indexed
ESO_SECTIONS = [
    ("G7_9", "Cursos 1°-3° ESO / Grades 7-9 (shared)", "7", "7-9", [144, 145, 146]),
    ("G10A", "4° ESO MATEMÁTICAS A / Grade 10 Track A", "10", "10", [149, 150]),
    ("G10B", "4° ESO MATEMÁTICAS B / Grade 10 Track B", "10", "10", [153, 154]),
]

CE_DOMAIN = {
    1:  "Mathematical Problem Solving",
    2:  "Mathematical Verification and Validation",
    3:  "Mathematical Reasoning and Conjecture",
    4:  "Computational Thinking and Algorithms",
    5:  "Mathematical Connections",
    6:  "Real-World Connections and Modeling",
    7:  "Mathematical Representation",
    8:  "Mathematical Communication",
    9:  "Socio-Emotional Mathematical Skills",
    10: "Collaborative Mathematical Work",
}

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each",
    "such", "both", "also", "into", "more", "most", "some", "other",
    "these", "those", "about", "able", "after", "where", "while", "make",
    "used", "given", "find", "show", "know", "understand", "apply",
    "students", "student", "numbers", "values", "different",
}

EXTRACT_PROMPT = """\
Below is text from Spain's LOMLOE 2022 mathematics curriculum for ESO (secondary),
{section_label}.

The evaluation criteria (Criterios de evaluación) are coded N.M where N is the
Competencia específica number (1-10) and M is the sequential criterion number.

The 10 competencies are:
  CE1  = Problem solving strategies
  CE2  = Mathematical verification and validation
  CE3  = Mathematical reasoning and conjecture
  CE4  = Computational thinking and algorithms
  CE5  = Mathematical connections
  CE6  = Real-world connections and modeling
  CE7  = Mathematical representation
  CE8  = Mathematical communication
  CE9  = Socio-emotional mathematical skills
  CE10 = Collaborative mathematical work

Extract ONLY the numbered criteria (N.M format). Do NOT include:
- Saberes básicos (basic knowledge content, introduced with "Saberes básicos.")
- Bullet points starting with "−"
- Competency descriptions (paragraphs of explanation)

Return ONLY a JSON array (no markdown). Each element:
  "ce"     : integer competency number (1-10)
  "m"      : integer criterion number within competency
  "text_es": Spanish text verbatim (the full criterion statement, trimmed)
  "text_en": accurate English translation

CRITERIA TEXT ({section_label}):
{text}
"""


def _download(url: str, path: Path) -> None:
    print(f"  Downloading {path.name} …")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(path, "wb") as f:
        f.write(r.read())
    print(f"  Saved {path.stat().st_size:,} bytes")


def _extract_pages_text(pdf_path: Path, page_indices: list[int]) -> str:
    doc = fitz.open(str(pdf_path))
    parts = []
    for i in page_indices:
        if i < doc.page_count:
            t = doc[i].get_text().strip()
            # Strip BOE header/footer lines
            t = re.sub(r'BOLETÍN OFICIAL DEL ESTADO.*?\n', '', t, flags=re.MULTILINE)
            t = re.sub(r'LEGISLACIÓN CONSOLIDADA\s*\n', '', t, flags=re.MULTILINE)
            t = re.sub(r'Página \d+\s*\n?', '', t, flags=re.MULTILINE)
            if t.strip():
                parts.append(t.strip())
    doc.close()
    return "\n\n".join(parts)


def _call_model(section_label: str, text: str) -> list[dict]:
    prompt = EXTRACT_PROMPT.format(section_label=section_label, text=text[:10000])
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

    print(f"Clearing existing {SYSTEM} ESO data …")
    with conn:
        conn.execute("DELETE FROM keywords WHERE standard_id LIKE 'ES_LOMLOE.MATH.ESO.%'")
        conn.execute("DELETE FROM standards WHERE id LIKE 'ES_LOMLOE.MATH.ESO.%'")

    seen_ids: set[str] = set()
    grand_std = grand_kw = 0

    for section_id, section_label, grade, grade_band, page_indices in ESO_SECTIONS:
        text = _extract_pages_text(pdf_path, page_indices)
        print(f"  {section_id} / {section_label} ({len(text)} chars) → model …", end="", flush=True)
        try:
            criteria = _call_model(section_label, text)
        except Exception as e:
            print(f" ERROR: {e}")
            continue

        section_std = section_kw = 0
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
                if ce_int not in range(1, 11):
                    continue

                std_id = f"ES_LOMLOE.MATH.ESO.{section_id}.CE{ce_int}.{m_int:02d}"
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
                        grade, grade_band,
                        CE_DOMAIN.get(ce_int, f"CE{ce_int}"),
                        text_es,
                        text_en,
                        VERIFIED_DATE,
                        PDF_URL,
                    ),
                )
                section_std += 1
                for kw in _extract_keywords(text_en + " " + text_es):
                    conn.execute(
                        "INSERT OR IGNORE INTO keywords (standard_id, keyword) VALUES (?,?)",
                        (std_id, kw),
                    )
                    section_kw += 1

        grand_std += section_std
        grand_kw += section_kw
        print(f" {len(criteria)} extracted, {section_std} ingested")

    conn.close()
    print(f"\nTotal: {grand_std} standards, {grand_kw} keywords")
    print("Done.")


if __name__ == "__main__":
    main()
