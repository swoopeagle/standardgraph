"""Fetch and ingest Chile MINEDUC 2015 math objectives (Grades 7-10).

System: cl-mineduc (same as grades 1-6, extending with grades 7-10)
Source: Bases Curriculares 2015 — 7° básico a 2° medio — Matemática
  PDF: curriculumnacional.cl

Covers:
  Grade 7  = 7° Básico
  Grade 8  = 8° Básico
  Grade 9  = 1° Medio
  Grade 10 = 2° Medio

Strand codes (different from grades 1-6):
  NU = Números (Numbers)
  AF = Álgebra y funciones (Algebra and Functions)
  GE = Geometría (Geometry)
  EP = Estadística y Probabilidad (Statistics and Probability)

ID format: CL_MINEDUC.MATH.G{grade:02d}.{strand_code}.{seq:03d}
  e.g. CL_MINEDUC.MATH.G07.AF.003
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

SYSTEM = "cl-mineduc"
VERIFIED_DATE = date.today().isoformat()
RAW_DIR = DB_PATH.parent / "raw" / "cl"
PDF_URL = "https://www.curriculumnacional.cl/614/articles-37136_bases.pdf"
PDF_FILE = "cl_math_bases_curriculares_7_medio.pdf"

# 0-indexed content page ranges for each grade (skip grade header and blank separator pages)
GRADE_PAGES = [
    (7,  "7-10", 107, 111),   # Grade 7: pages 108-111
    (8,  "7-10", 113, 117),   # Grade 8: pages 114-117
    (9,  "9-10", 119, 122),   # Grade 9 (1° Medio): pages 120-122
    (10, "9-10", 123, 127),   # Grade 10 (2° Medio): pages 124-127
]

STRAND_MAP = {
    "NU": "Numbers",
    "AF": "Algebra and Functions",
    "GE": "Geometry",
    "EP": "Statistics and Probability",
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
Below is text from Chile's official mathematics curriculum (Bases Curriculares 2015),
Grade {grade} ({grade_label}).

The objectives (Objetivos de Aprendizaje) are numbered (1, 2, 3, ...) and are organized
under four strand headings:
  - Números (strand_code: NU)
  - Álgebra y funciones (strand_code: AF)
  - Geometría (strand_code: GE)
  - Estadística y Probabilidad (strand_code: EP)

The text may also include "Habilidades" (skills, lettered a-m) — do NOT include habilidades.
Extract only the numbered learning objectives (Objetivo de Aprendizaje).

Return ONLY a JSON array (no markdown). Each element:
  "obj_num"    : integer — the objective number (sequential across all strands)
  "strand_code": 2-letter code (NU, AF, GE, EP)
  "text_es"    : Spanish text of the objective (verbatim, trimmed)
  "text_en"    : accurate English translation

TEXT FOR GRADE {grade} ({grade_label}):
{text}
"""


def _download(url: str, path: Path) -> None:
    print(f"  Downloading {path.name} …")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
    )
    with urllib.request.urlopen(req, timeout=120) as r, open(path, "wb") as f:
        f.write(r.read())
    print(f"  Saved {path.stat().st_size:,} bytes")


def _extract_grade_text(pdf_path: Path, pg_start: int, pg_end: int) -> str:
    doc = fitz.open(str(pdf_path))
    parts = []
    for i in range(pg_start, min(pg_end, doc.page_count)):
        t = doc[i].get_text().strip()
        # Strip header line
        t = re.sub(r'^\d+\s*\nBases Curriculares.*?\n', '', t, flags=re.MULTILINE)
        if t:
            parts.append(t)
    doc.close()
    return "\n\n".join(parts)


def _call_model(grade: int, grade_label: str, text: str) -> list[dict]:
    prompt = EXTRACT_PROMPT.format(grade=grade, grade_label=grade_label, text=text[:10000])
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

    # Only delete grades 7-10 CL_MINEDUC standards (preserve grades 1-6)
    print(f"Clearing existing {SYSTEM} grades 7-10 data …")
    with conn:
        for g in (7, 8, 9, 10):
            conn.execute(
                "DELETE FROM keywords WHERE standard_id LIKE ?",
                (f"CL_MINEDUC.MATH.G{g:02d}.%",),
            )
            conn.execute(
                "DELETE FROM standards WHERE id LIKE ?",
                (f"CL_MINEDUC.MATH.G{g:02d}.%",),
            )

    grade_labels = {
        7: "7° Básico",
        8: "8° Básico",
        9: "1° Medio",
        10: "2° Medio",
    }

    seen_ids: set[str] = set()
    grand_std = grand_kw = 0

    for grade, grade_band, pg_start, pg_end in GRADE_PAGES:
        text = _extract_grade_text(pdf_path, pg_start, pg_end)
        grade_label = grade_labels[grade]
        print(f"  Grade {grade} / {grade_label} ({len(text)} chars) → model …", end="", flush=True)
        try:
            objectives = _call_model(grade, grade_label, text)
        except Exception as e:
            print(f" ERROR: {e}")
            continue

        grade_std = grade_kw = 0
        with conn:
            for obj in objectives:
                text_en = (obj.get("text_en") or "").strip()
                text_es = (obj.get("text_es") or "").strip()
                strand_code = (obj.get("strand_code") or "").strip().upper()
                obj_num = obj.get("obj_num")
                if not text_en or len(text_en) < 15 or not strand_code or not obj_num:
                    continue
                if strand_code not in STRAND_MAP:
                    continue
                try:
                    seq = int(obj_num)
                except (TypeError, ValueError):
                    continue

                std_id = f"CL_MINEDUC.MATH.G{grade:02d}.{strand_code}.{seq:03d}"
                if std_id in seen_ids:
                    continue
                seen_ids.add(std_id)

                conn.execute(
                    """INSERT OR REPLACE INTO standards
                       (id, system, subject, grade, grade_band, domain, cluster,
                        standard_text, last_verified_date, source_url)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        std_id, SYSTEM, "mathematics", str(grade),
                        grade_band,
                        STRAND_MAP[strand_code],
                        text_es,
                        text_en,
                        VERIFIED_DATE,
                        "https://www.curriculumnacional.cl/614/articles-37136_bases.pdf",
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
        print(f" {len(objectives)} extracted, {grade_std} ingested")

    conn.close()
    print(f"\nTotal: {grand_std} standards, {grand_kw} keywords")
    print("Done.")


if __name__ == "__main__":
    main()
