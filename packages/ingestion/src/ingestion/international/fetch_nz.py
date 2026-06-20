"""Fetch and ingest New Zealand Mathematics and Statistics curriculum standards.

Covered system: nz-moe
Source:
  - Mathematics and Statistics Years 0–10 (2025)
    data/raw/nz/nz_years0_10.pdf
    (Download from NZ Curriculum Online: nzcurriculum.tki.org.nz)

Phase page ranges (1-indexed):
  Phase 1 (Years 0-3):  pages  6-14
  Phase 2 (Years 4-6):  pages 16-25
  Phase 3 (Years 7-8):  pages 27-34
  Phase 4 (Years 9-10): pages 36-42

Grade mapping:
  "first six months" → K    (Phase 1)
  Year 1–8           → 1–8
  Year 9             → 9
  Year 10            → HS

IDs: NZ_MOE.MATH.{grade}.{hash(obj_text[:40]) % 100000}
"""
import json
import re
import sqlite3
from datetime import date
from pathlib import Path

import httpx
import pdfplumber

from shared.config import DB_PATH, OLLAMA_BASE_URL, OLLAMA_MODEL

SYSTEM = "nz-moe"
SOURCE_URL = "https://nzcurriculum.tki.org.nz/the-nzc/learning-areas/mathematics-and-statistics"
VERIFIED_DATE = date.today().isoformat()
RAW_DIR = DB_PATH.parent / "raw" / "nz"
COMBINED_PDF = RAW_DIR / "nz_years0_10.pdf"

# Page ranges are inclusive, 1-indexed; excludes language/vocab summary pages
PHASES = [
    {
        "name": "Phase 1",
        "years": "Years 0-3",
        "pages": (6, 13),
        "valid_grades": {"K", "1", "2", "3"},
        "grade_hint": (
            'Columns are labelled "During the first six months" (→ grade "K"), '
            '"During the first year" (→ grade "1"), '
            '"During the second year" (→ grade "2"), '
            '"During the third year" (→ grade "3"). '
            'Use "year" values: "K", "1", "2", "3".'
        ),
    },
    {
        "name": "Phase 2",
        "years": "Years 4-6",
        "pages": (16, 24),
        "valid_grades": {"4", "5", "6"},
        "grade_hint": (
            'Columns are labelled "During Year 4", "During Year 5", "During Year 6". '
            'Use "year" values: "4", "5", "6".'
        ),
    },
    {
        "name": "Phase 3",
        "years": "Years 7-8",
        "pages": (27, 34),
        "valid_grades": {"7", "8"},
        "grade_hint": (
            'Columns are labelled "During Year 7" and "During Year 8". '
            'Use "year" values: "7", "8".'
        ),
    },
    {
        "name": "Phase 4",
        "years": "Years 9-10",
        "pages": (36, 42),
        "valid_grades": {"9", "HS"},
        "grade_hint": (
            'Columns are labelled "During Year 9" and "During Year 10". '
            'Use "year" values: "9" for Year 9, "HS" for Year 10.'
        ),
    },
]

EXTRACT_PROMPT = """\
Extract all mathematics learning objectives from this New Zealand Curriculum page.

Phase: {phase_name} ({years})
{grade_hint}

The page has "Knowledge" and "Practices" sub-columns within each year column.
Strands include: Number, Algebra, Measurement, Geometry, Statistics, Probability.

Return ONLY a JSON array (no other text, no markdown). Each element must have:
  "strand"   : strand name (e.g. "Number", "Algebra", "Measurement", "Geometry", "Statistics", "Probability")
  "sub_area" : sub-area or topic (e.g. "Number structures", "Operations", "Equations and expressions")
  "year"     : the year/grade string as described above
  "obj_text" : full text of the single learning objective (one bullet point or sentence)

Rules:
- Extract every distinct bullet-point objective for every year shown on this page.
- Do NOT include strand headers, sub-area titles, column labels, page numbers, or teaching notes.
- Each bullet becomes one array element — do not merge bullets.
- Preserve exact wording from the source.
- If the strand name is not explicit on this page, infer it from context.

CURRICULUM TEXT:
{text}
"""

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each",
    "such", "both", "also", "into", "more", "most", "some", "other",
    "these", "those", "about", "able", "after", "where", "while", "make",
    "used", "given", "find", "show", "know", "understand", "apply",
}


def _extract_pages(pdf_path: Path) -> list[tuple[int, str]]:
    results = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            if text.strip():
                results.append((i + 1, text))
    return results


def _call_gemma(page_num: int, text: str, phase: dict) -> list[dict]:
    prompt = EXTRACT_PROMPT.format(
        phase_name=phase["name"],
        years=phase["years"],
        grade_hint=phase["grade_hint"],
        text=text[:4000],
    )
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "format": "json",
        "keep_alive": "4h",
        "options": {"temperature": 0.0},
    }
    resp = httpx.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload, timeout=3600)
    resp.raise_for_status()
    content = resp.json()["message"]["content"].strip()
    content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.MULTILINE)
    content = re.sub(r"\s*```$", "", content, flags=re.MULTILINE)
    m = re.search(r"\[.*\]", content, re.DOTALL)
    if not m:
        print(f"    WARN: no JSON for page {page_num}")
        return []
    return json.loads(m.group(0))


def _extract_keywords(text: str) -> list[str]:
    words = re.findall(r'\b[a-zA-Z][a-zA-Z-]{3,}\b', text.lower())
    seen: set[str] = set()
    result = []
    for w in words:
        if w not in STOP_WORDS and w not in seen:
            seen.add(w)
            result.append(w)
    return result[:20]


def _ingest_objectives(
    objectives: list[dict],
    valid_grades: set[str],
    conn: sqlite3.Connection,
    seen_ids: set[str],
) -> tuple[int, int]:
    std_count = kw_count = 0

    for obj in objectives:
        obj_text = (obj.get("obj_text") or "").strip()
        year = str(obj.get("year") or "").strip()
        if not obj_text or year not in valid_grades:
            continue

        strand = (obj.get("strand") or "").strip()
        sub_area = (obj.get("sub_area") or "").strip()
        grade_band = "9-12" if year == "HS" else None

        std_id = f"NZ_MOE.MATH.{year}.{abs(hash(obj_text[:40])) % 100000}"
        if std_id in seen_ids:
            continue
        seen_ids.add(std_id)

        conn.execute(
            """INSERT OR REPLACE INTO standards
               (id, system, subject, grade, grade_band, domain, cluster,
                standard_text, last_verified_date, source_url)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (std_id, SYSTEM, "mathematics", year, grade_band,
             strand, sub_area, obj_text, VERIFIED_DATE, SOURCE_URL),
        )
        std_count += 1
        for kw in _extract_keywords(obj_text):
            conn.execute(
                "INSERT OR IGNORE INTO keywords (standard_id, keyword) VALUES (?,?)",
                (std_id, kw),
            )
            kw_count += 1

    return std_count, kw_count


def main() -> None:
    if not COMBINED_PDF.exists():
        print(f"ERROR: {COMBINED_PDF} not found.")
        print("Download 'Mathematics and Statistics Years 0-10 (2025)' from")
        print("  nzcurriculum.tki.org.nz")
        print(f"and save as {COMBINED_PDF}")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    print("Extracting New Zealand Mathematics and Statistics standards (Years 0-10)...")
    all_pages = _extract_pages(COMBINED_PDF)
    page_map = {n: t for n, t in all_pages}

    grand_std = grand_kw = 0
    seen_ids: set[str] = set()

    for phase in PHASES:
        p_start, p_end = phase["pages"]
        print(f"\n  {phase['name']} ({phase['years']}) — pages {p_start}-{p_end}")
        phase_std = phase_kw = 0

        for page_num in range(p_start, p_end + 1):
            text = page_map.get(page_num, "")
            if not text.strip():
                continue
            print(f"    page {page_num}: {len(text)} chars → Gemma...", end="", flush=True)
            try:
                objectives = _call_gemma(page_num, text, phase)
            except Exception as e:
                print(f" ERROR: {e}")
                continue
            with conn:
                s, k = _ingest_objectives(objectives, phase["valid_grades"], conn, seen_ids)
            phase_std += s
            phase_kw += k
            print(f" {len(objectives)} extracted, {s} ingested")

        print(f"  {phase['name']} total: {phase_std} standards, {phase_kw} keywords")
        grand_std += phase_std
        grand_kw += phase_kw

    conn.close()
    print(f"\nTotal: {grand_std} standards, {grand_kw} keywords")
    print("Done.")


if __name__ == "__main__":
    main()
