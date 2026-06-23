"""Fetch and ingest Uruguay ANEP EBI 2023 math achievement criteria (Grades 3-6).

System: uy-anep
Source: Educación Básica Integrada (EBI) Programas 2.do ciclo 2023
  PDF: ANEP (anep.edu.uy)

Covers: Tramo 3 (grades 3-4) and Tramo 4 (grades 5-6)
Math section: "Matemática" within "Espacio Científico-Matemático"

Standards extracted from "Criterios de logro" (achievement criteria) sections,
organized by competency (CE1-CE6):
  CE1 = Language and communication of mathematical ideas
  CE2 = Mathematical problem solving
  CE3 = Patterns, regularities, and data
  CE4 = Mathematical thinking and generalization
  CE5 = Persistence and error analysis
  CE6 = Financial and commercial reasoning

ID format: UY_ANEP.MATH.G{grade:02d}.{comp}.{seq:03d}
  e.g. UY_ANEP.MATH.G03.CE1.001
"""
import json
import re
import sqlite3
from datetime import date
from pathlib import Path

import fitz  # PyMuPDF
import httpx

from shared.config import DB_PATH, OLLAMA_BASE_URL, OLLAMA_MODEL

SYSTEM = "uy-anep"
VERIFIED_DATE = date.today().isoformat()
RAW_DIR = DB_PATH.parent / "raw" / "uy"
PDF_URL = "https://www.anep.edu.uy/sites/default/files/images/te-programas/2023/Compilaci%C3%B3n%20Programas%202do%20Ciclo.pdf"
PDF_FILE = "uy_ebi_2023_programas_2do_ciclo.pdf"

# 0-indexed page ranges for "Criterios de logro" per grade
GRADE_CRITERIA_PAGES = [
    (3, "Tramo 3 / Grade 3", [31, 32]),   # pages 32-33
    (4, "Tramo 3 / Grade 4", [34, 35, 36]),  # pages 35-37
    (5, "Tramo 4 / Grade 5", [45, 46]),   # pages 46-47
    (6, "Tramo 4 / Grade 6", [48, 49]),   # pages 49-50
]

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each",
    "such", "both", "also", "into", "more", "most", "some", "other",
    "these", "those", "about", "able", "after", "where", "while", "make",
    "used", "given", "find", "show", "know", "understand", "apply",
    "students", "student", "numbers", "values", "different",
}

EXTRACT_PROMPT = """\
Below are the "Criterios de logro" (achievement criteria / learning standards) for
Uruguay's EBI 2023 mathematics curriculum, {grade_label}.

The criteria are organized by competency (CE1, CE2, etc.):
  CE1 = Incorporates mathematical language and communicates ideas
  CE2 = Solves mathematical problems using strategies
  CE3 = Discovers regularities, patterns, and data
  CE4 = Explores mathematical thinking and makes generalizations
  CE5 = Identifies errors and persists in finding alternative strategies
  CE6 = Applies financial and commercial concepts

Format: bullet points (•) under competency labels (CE1, CE2, ...).
Extract ALL individual bullet-point criteria (NOT the competency description lines).
Number them sequentially within each competency.

Return ONLY a JSON array (no markdown). Each element:
  "competency" : competency code (CE1, CE2, CE3, CE4, CE5, CE6)
  "seq"        : integer — sequence number within this competency for this grade
  "text_es"    : Spanish text verbatim (the bullet point, without the •)
  "text_en"    : accurate English translation

CRITERIA TEXT ({grade_label}):
{text}
"""


def _extract_pages_text(pdf_path: Path, page_indices: list[int]) -> str:
    doc = fitz.open(str(pdf_path))
    parts = []
    for i in page_indices:
        if i < doc.page_count:
            t = doc[i].get_text().strip()
            # Remove page number prefix
            t = re.sub(r'^\d+\s*\n', '', t)
            if t:
                parts.append(t)
    doc.close()
    return "\n\n".join(parts)


def _call_model(grade_label: str, text: str) -> list[dict]:
    prompt = EXTRACT_PROMPT.format(grade_label=grade_label, text=text[:9000])
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

    if not pdf_path.exists():
        print(f"ERROR: PDF not found at {pdf_path}")
        print(f"Download from: {PDF_URL}")
        return

    print(f"Using {PDF_FILE} ({pdf_path.stat().st_size:,} bytes)")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")

    print(f"Clearing existing {SYSTEM} data …")
    with conn:
        conn.execute("DELETE FROM keywords WHERE standard_id LIKE 'UY_ANEP.%'")
        conn.execute("DELETE FROM standards WHERE system = ?", (SYSTEM,))

    seen_ids: set[str] = set()
    grand_std = grand_kw = 0

    for grade, grade_label, page_indices in GRADE_CRITERIA_PAGES:
        text = _extract_pages_text(pdf_path, page_indices)
        print(f"  Grade {grade} ({grade_label}, {len(text)} chars) → model …", end="", flush=True)
        try:
            criteria = _call_model(grade_label, text)
        except Exception as e:
            print(f" ERROR: {e}")
            continue

        grade_band = "3-4" if grade <= 4 else "5-6"
        grade_std = grade_kw = 0
        with conn:
            for crit in criteria:
                comp = (crit.get("competency") or "").strip().upper()
                seq = crit.get("seq")
                text_es = (crit.get("text_es") or "").strip()
                text_en = (crit.get("text_en") or "").strip()
                if not comp or not seq or not text_en or len(text_en) < 10:
                    continue
                if not re.match(r'^CE\d+$', comp):
                    continue
                try:
                    seq_int = int(seq)
                except (TypeError, ValueError):
                    continue

                std_id = f"UY_ANEP.MATH.G{grade:02d}.{comp}.{seq_int:03d}"
                if std_id in seen_ids:
                    continue
                seen_ids.add(std_id)

                comp_domain = {
                    "CE1": "Mathematical Language and Communication",
                    "CE2": "Problem Solving",
                    "CE3": "Patterns, Regularities, and Data",
                    "CE4": "Mathematical Thinking",
                    "CE5": "Error Analysis and Persistence",
                    "CE6": "Financial and Commercial Reasoning",
                }.get(comp, comp)

                conn.execute(
                    """INSERT OR REPLACE INTO standards
                       (id, system, subject, grade, grade_band, domain, cluster,
                        standard_text, last_verified_date, source_url)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        std_id, SYSTEM, "mathematics", str(grade), grade_band,
                        comp_domain,
                        text_es,
                        text_en,
                        VERIFIED_DATE,
                        PDF_URL,
                    ),
                )
                grade_std += 1
                for kw in _extract_keywords(text_en + " " + text_es):
                    conn.execute(
                        "INSERT OR IGNORE INTO keywords (standard_id, keyword) VALUES (?,?)",
                        (std_id, kw),
                    )
                    grade_kw += 1

        grand_std += grade_std
        grand_kw += grade_kw
        print(f" {len(criteria)} extracted, {grade_std} ingested")

    conn.close()
    print(f"\nTotal: {grand_std} standards, {grand_kw} keywords")
    print("Done.")


if __name__ == "__main__":
    main()
