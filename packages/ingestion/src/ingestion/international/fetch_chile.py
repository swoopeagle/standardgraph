"""Fetch and ingest Chile MINEDUC 2012 math objectives (Grades 1-6).

System: cl-mineduc
Source: Bases Curriculares 2012 — Matemática 1° a 6° Básico
  PDF from Curriculum Nacional (curriculumnacional.cl / mineduc.cl)

Covers Educación Básica grades 1-6 (ages 6-11).
Grades 7-8 are in a separate document (7° Básico a 2° Medio) — future work.

Strand codes used for IDs:
  NO = Números y Operaciones (Numbers and Operations)
  PA = Patrones y Álgebra (Patterns and Algebra)
  GE = Geometría (Geometry)
  ME = Medición (Measurement)
  DP = Datos y Probabilidades (Data and Probability)

ID format: CL_MINEDUC.MATH.G{grade:02d}.{strand_code}.{seq:03d}
  e.g. CL_MINEDUC.MATH.G01.NO.003  (grade 1, Numbers, objective 3)
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
PDF_URL = "https://www.curriculumnacional.cl/614/articles-22394_bases.pdf"
PDF_FILE = "cl_math_bases_curriculares_1_6.pdf"

# 0-indexed page range for the math section in this PDF
MATH_START = 226   # page 227
MATH_END   = 264   # exclusive (page 264 inclusive has glosario)

# Spanish grade names → int
GRADE_NAMES = {
    "Primero": 1, "Segundo": 2, "Tercero": 3,
    "Cuarto": 4, "Quinto": 5, "Sexto": 6,
}

# Strand name patterns → ID code
STRAND_MAP = [
    (re.compile(r"N[úu]meros?\s+y\s+[Oo]peraciones?", re.I), "NO"),
    (re.compile(r"Patrones?\s+y\s+[ÁA]lgebra", re.I),        "PA"),
    (re.compile(r"Geometr[íi]a", re.I),                        "GE"),
    (re.compile(r"Medici[óo]n", re.I),                         "ME"),
    (re.compile(r"Datos?\s+y\s+Probabilidades?", re.I),        "DP"),
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
Below is text from Chile's official mathematics curriculum (Bases Curriculares 2012),
Grade {grade} (año {grade}° básico).

The objectives are grouped into strands: Números y Operaciones, Patrones y Álgebra,
Geometría, Medición, Datos y Probabilidades. Within each strand, objectives are
numbered (1, 2, 3, ...).

Extract every numbered learning objective (Objetivo de Aprendizaje) for this grade.
Do NOT include skill descriptors (habilidades like "Resolver problemas",
"Argumentar y comunicar") — only the content objectives.

Return ONLY a JSON array (no markdown). Each element:
  "obj_num"    : integer — the objective number within its strand
  "strand"     : strand name in Spanish (e.g. "Números y Operaciones")
  "strand_code": 2-letter code (NO, PA, GE, ME, DP)
  "text_es"    : Spanish text of the objective (verbatim, trimmed)
  "text_en"    : accurate English translation

TEXT FOR GRADE {grade}:
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


def _call_model(grade: int, text: str) -> list[dict]:
    prompt = EXTRACT_PROMPT.format(grade=grade, text=text[:10000])
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


def _strand_name_en(code: str) -> str:
    return {
        "NO": "Numbers and Operations",
        "PA": "Patterns and Algebra",
        "GE": "Geometry",
        "ME": "Measurement",
        "DP": "Data and Probability",
    }.get(code, code)


def _extract_grade_blocks(pdf_path: Path) -> dict[int, str]:
    """Return {grade: text} for each grade's math content."""
    doc = fitz.open(str(pdf_path))
    # Collect all pages in math section
    pages_text: list[tuple[int, str]] = []
    for i in range(MATH_START, min(MATH_END, doc.page_count)):
        t = doc[i].get_text().strip()
        pages_text.append((i + 1, t))
    doc.close()

    # Split by grade headers (pages that contain only the grade name)
    grade_blocks: dict[int, list[str]] = {}
    current_grade: int | None = None

    for pg, text in pages_text:
        # Check if this page is a grade header
        detected = None
        for name, gnum in GRADE_NAMES.items():
            if re.search(rf"\b{name}\b", text) and "Básico" in text and len(text) < 80:
                detected = gnum
                break
        if detected is not None:
            current_grade = detected
            if current_grade not in grade_blocks:
                grade_blocks[current_grade] = []
        elif current_grade is not None and text:
            grade_blocks[current_grade].append(text)

    # Join and trim each grade block
    result: dict[int, str] = {}
    for grade, parts in grade_blocks.items():
        combined = "\n\n".join(parts)
        # Remove glosario (glossary) if present — starts with "Glosario" header
        glosario_m = re.search(r"\n\s*Glosario\s*\n", combined, re.I)
        if glosario_m:
            combined = combined[:glosario_m.start()]
        result[grade] = combined.strip()
    return result


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

    print("Extracting grade blocks from math section …")
    try:
        grade_blocks = _extract_grade_blocks(pdf_path)
    except Exception as e:
        print(f"ERROR extracting grade blocks: {e}")
        return

    print(f"  Found grade blocks: {sorted(grade_blocks.keys())}")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")

    print(f"Clearing existing {SYSTEM} data …")
    with conn:
        conn.execute("DELETE FROM keywords WHERE standard_id LIKE 'CL_MINEDUC.%'")
        conn.execute("DELETE FROM standards WHERE system = ?", (SYSTEM,))

    seen_ids: set[str] = set()
    grand_std = grand_kw = 0

    for grade in sorted(grade_blocks.keys()):
        text = grade_blocks[grade]
        print(f"  Grade {grade} ({len(text)} chars) → model …", end="", flush=True)
        try:
            objectives = _call_model(grade, text)
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
                        "1-6",
                        _strand_name_en(strand_code),
                        text_es,
                        text_en,
                        VERIFIED_DATE,
                        "https://www.curriculumnacional.cl/614/articles-22394_bases.pdf",
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
