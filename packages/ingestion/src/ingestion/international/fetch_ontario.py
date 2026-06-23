"""Fetch and ingest Ontario elementary math standards (Grades 1–8).

Covered system: ca-on (extends existing HS-only CSP data with K–8)
Source: Ontario Ministry of Education — The Ontario Curriculum, Mathematics, 2020
  URL: https://www.dcp.edu.gov.on.ca/en/curriculum/elementary-mathematics/downloads

PDF to download and place in ~/.standardgraph/raw/ontario/ before running:
  math-1-8-2020.pdf   (Grades 1–8 Mathematics, Ontario Ministry, 2020)
  math-k-2020.pdf     (Kindergarten Mathematics, Ontario Ministry, 2018)  [optional]

Pipeline:
  1. Extract text from PDF pages using pdfplumber
  2. Split into per-grade sections using grade headings
  3. Call Gemma 4 31B on Mac Studio to extract structured expectations as JSON
  4. Ingest into standards DB under ca-on, appending to existing HS standards

Grade mapping:
  Grade 1–8 → grades 1–8
  Kindergarten → grade K  (if kindergarten PDF is present)
"""
import json
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

import httpx
import pdfplumber

from shared.config import DB_PATH, OLLAMA_BASE_URL

SYSTEM = "ca-on"
SOURCE_URL = "https://www.dcp.edu.gov.on.ca/en/curriculum/elementary-mathematics"
VERIFIED_DATE = date.today().isoformat()
RAW_DIR = DB_PATH.parent / "raw" / "ontario"

OLLAMA_MODEL = "gemma4:31b-it-q8_0"

# Ontario curriculum grade headings appear as "Grade 1", "Grade 2" … "Grade 8"
# or "Kindergarten" in the 2020 curriculum document.
GRADE_RE = re.compile(
    r"^(grade\s+[1-8]|kindergarten)$", re.IGNORECASE
)
GRADE_MAP = {
    "kindergarten": "K",
    "grade 1": "1", "grade 2": "2", "grade 3": "3", "grade 4": "4",
    "grade 5": "5", "grade 6": "6", "grade 7": "7", "grade 8": "8",
}

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each",
    "such", "both", "also", "into", "more", "most", "some", "other",
    "these", "those", "about", "able", "after", "where", "while", "make",
    "used", "given", "find", "show", "know", "understand", "apply",
}

EXTRACT_PROMPT = """\
Extract all specific learning expectations from this Ontario Ministry of Education \
mathematics curriculum excerpt for {grade}.

Return ONLY a JSON array (no other text, no markdown). Each element must have:
  "strand"     : curriculum strand (e.g. "Number", "Algebra", "Data", "Spatial Sense", "Financial Literacy")
  "substrand"  : sub-strand or topic (e.g. "Number Sense", "Fractions", "Variables and Expressions")
  "code"       : the expectation code if visible (e.g. "B1.1", "C2.3"); empty string if none
  "text"       : the full text of the learning expectation (the specific, assessable item)

Rules:
- Extract ONLY specific expectations (the numbered/lettered leaf items students are expected to learn)
- Do NOT include overall expectations, strand headings, or general statements
- Do NOT include pedagogical notes, teacher guidance, or example boxes
- Each expectation must be assessable and specific (not vague)
- Preserve the exact wording from the curriculum

ONTARIO MATHEMATICS CURRICULUM — {grade}:
{text}
"""


def _extract_pages(pdf_path: Path) -> list[tuple[int, str]]:
    results = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            if text.strip():
                results.append((i + 1, text))
    return results


def _split_by_grade(pages: list[tuple[int, str]]) -> dict[str, str]:
    """Group page text by grade using Ontario curriculum grade headings."""
    current_grade: str | None = None
    blocks: dict[str, list[str]] = {}

    for _page_num, text in pages:
        for line in text.splitlines():
            match = GRADE_RE.match(line.strip())
            if match:
                grade_key = match.group(0).lower().strip()
                grade_key = re.sub(r"\s+", " ", grade_key)
                current_grade = GRADE_MAP.get(grade_key)
                if current_grade and current_grade not in blocks:
                    blocks[current_grade] = []
        if current_grade:
            blocks.setdefault(current_grade, []).append(text)

    return {g: "\n".join(texts) for g, texts in blocks.items()}


def _call_gemma(grade: str, text: str) -> list[dict]:
    """Send text to Gemma 4 on Mac Studio, return parsed list of expectations."""
    prompt = EXTRACT_PROMPT.format(grade=f"Grade {grade}", text=text[:5000])
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0.0},
    }
    resp = httpx.post(
        f"{OLLAMA_BASE_URL}/api/chat",
        json=payload,
        timeout=1800,
    )
    resp.raise_for_status()
    content = resp.json()["message"]["content"].strip()

    content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.MULTILINE)
    content = re.sub(r"\s*```$", "", content, flags=re.MULTILINE)

    match = re.search(r"\[.*\]", content, re.DOTALL)
    if not match:
        print(f"    WARN: no JSON array in Gemma response for grade {grade}")
        return []
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as e:
        print(f"    WARN: JSON parse error for grade {grade}: {e}")
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


def _ingest_expectations(
    expectations: list[dict],
    grade: str,
    conn: sqlite3.Connection,
    seen_ids: set[str],
) -> tuple[int, int]:
    std_count = kw_count = 0

    for exp in expectations:
        exp_text = (exp.get("text") or "").strip()
        if not exp_text:
            continue

        strand = (exp.get("strand") or "").strip()
        substrand = (exp.get("substrand") or "").strip()
        code = re.sub(r"[^A-Za-z0-9.]", "", (exp.get("code") or "").strip())

        if code:
            notation = code
        else:
            # Fall back to hash of text to ensure uniqueness
            notation = str(abs(hash(exp_text[:40])) % 100000)

        std_id = f"CA-ON.MATH.{grade}.{notation}"
        if std_id in seen_ids:
            # If code collision, try appending text hash suffix
            std_id = f"CA-ON.MATH.{grade}.{notation}.{abs(hash(exp_text)) % 1000}"
        if std_id in seen_ids:
            continue
        seen_ids.add(std_id)

        # Skip if same (grade, text) already in DB — prevents duplicates across runs
        if conn.execute(
            "SELECT 1 FROM standards WHERE system=? AND grade=? AND standard_text=?",
            (SYSTEM, grade, exp_text),
        ).fetchone():
            continue

        conn.execute(
            """INSERT OR REPLACE INTO standards
               (id, system, subject, grade, domain, cluster,
                standard_text, last_verified_date, source_url)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (std_id, SYSTEM, "mathematics", grade,
             strand, substrand, exp_text,
             VERIFIED_DATE, SOURCE_URL),
        )
        std_count += 1

        for kw in _extract_keywords(exp_text):
            conn.execute(
                "INSERT OR IGNORE INTO keywords (standard_id, keyword) VALUES (?,?)",
                (std_id, kw),
            )
            kw_count += 1

    return std_count, kw_count


def _process_pdf(pdf_path: Path, conn: sqlite3.Connection) -> tuple[int, int]:
    print(f"  Extracting pages from {pdf_path.name}...")
    pages = _extract_pages(pdf_path)
    print(f"  → {len(pages)} non-empty pages")

    grade_blocks = _split_by_grade(pages)
    print(f"  → grades found: {sorted(grade_blocks.keys())}")

    total_std = total_kw = 0
    seen_ids: set[str] = set()

    # Pre-populate seen_ids from existing ca-on standards to avoid ID collisions
    for row in conn.execute("SELECT id FROM standards WHERE system=?", (SYSTEM,)):
        seen_ids.add(row[0])

    for grade in sorted(grade_blocks.keys(), key=lambda g: (0 if g == "K" else int(g))):
        text = grade_blocks[grade]
        print(f"  Grade {grade}: {len(text)} chars → calling Gemma...")
        expectations = _call_gemma(grade, text)
        print(f"    Gemma returned {len(expectations)} expectations")
        with conn:
            s, k = _ingest_expectations(expectations, grade, conn, seen_ids)
        print(f"    Ingested: {s} new standards, {k} keywords")
        total_std += s
        total_kw += k

    return total_std, total_kw


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    pdfs = {
        "grades_1_8": RAW_DIR / "math-1-8-2020.pdf",
        "kindergarten": RAW_DIR / "math-k-2020.pdf",
    }

    # Check at least the main PDF is present
    if not pdfs["grades_1_8"].exists():
        print(f"""
ERROR: Ontario Grades 1–8 PDF not found at:
  {pdfs['grades_1_8']}

Download it from:
  https://www.dcp.edu.gov.on.ca/en/curriculum/elementary-mathematics/downloads

Save as: {pdfs['grades_1_8']}
Then re-run this script.
""")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")

    total_std = total_kw = 0

    for label, pdf_path in pdfs.items():
        if not pdf_path.exists():
            print(f"  Skipping {label} — PDF not found at {pdf_path}")
            continue
        print(f"\n── Processing {label} ({pdf_path.name}) ────────────────")
        s, k = _process_pdf(pdf_path, conn)
        total_std += s
        total_kw += k

    conn.close()

    print(f"\n── Summary ─────────────────────────────────────────────")
    print(f"  New ca-on standards ingested: {total_std}")
    print(f"  Keywords written:             {total_kw}")

    # Show final grade distribution
    conn2 = sqlite3.connect(DB_PATH)
    rows = conn2.execute(
        "SELECT grade, COUNT(*) FROM standards WHERE system='ca-on' GROUP BY grade ORDER BY grade"
    ).fetchall()
    conn2.close()
    print(f"  ca-on grade distribution:")
    for grade, count in rows:
        print(f"    Grade {grade:3s}: {count}")


if __name__ == "__main__":
    main()
