"""Fetch and ingest Singapore MOE math standards from PDF syllabuses.

Covered system: sg-moe
Sources:
  - 2021 Primary Mathematics Syllabus P1-P6
  - 2020 Secondary Mathematics G2/G3 (Express + Normal Academic), Sec 1-4
  - 2020 Secondary Mathematics G1 (Normal Technical), Sec 1-4

Pipeline:
  1. Extract text from PDF pages using pdfplumber
  2. Split into per-grade sections
  3. Call Gemma 4 31B on Mac Studio to extract structured objectives as JSON
  4. Ingest into standards DB

Grade mapping:
  P1-P6  →  grades 1-6
  Sec 1  →  grade 7
  Sec 2  →  grade 8
  Sec 3  →  grade HS (first half of secondary 3/4 block)
  Sec 4  →  grade HS
"""
import json
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

import httpx
import pdfplumber

from shared.config import DB_PATH, OLLAMA_BASE_URL, OLLAMA_MODEL

SYSTEM = "sg-moe"
SOURCE_URL = "https://www.moe.gov.sg/primary/curriculum/syllabus"
VERIFIED_DATE = date.today().isoformat()
RAW_DIR = DB_PATH.parent / "raw" / "singapore"


GRADE_MAP = {
    "primary one":   "1",  "p1": "1",
    "primary two":   "2",  "p2": "2",
    "primary three": "3",  "p3": "3",
    "primary four":  "4",  "p4": "4",
    "primary five":  "5",  "p5": "5",
    "primary six":   "6",  "p6": "6",
    "secondary one":   "7",  "sec 1": "7", "sec1": "7",
    "secondary two":   "8",  "sec 2": "8", "sec2": "8",
    "secondary three": "HS", "sec 3": "HS", "sec3": "HS",
    "secondary four":  "HS", "sec 4": "HS", "sec4": "HS",
    "secondary three/four": "HS",
}

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each",
    "such", "both", "also", "into", "more", "most", "some", "other",
    "these", "those", "about", "able", "after", "where", "while", "make",
    "used", "given", "find", "show", "know", "understand", "apply",
}

EXTRACT_PROMPT = """\
Extract all math learning objectives from this Singapore Ministry of Education syllabus text.

Return ONLY a JSON array (no other text, no markdown). Each element must have:
  "strand"     : content strand (e.g. "Number and Algebra", "Measurement and Geometry", "Statistics and Probability")
  "sub_strand" : sub-strand or topic group (e.g. "Whole Numbers", "Fractions", "Numbers and their operations")
  "topic_code" : alphanumeric code if present (e.g. "1", "N1", "G2", "S1"); empty string if none
  "obj_code"   : specific objective code (e.g. "1.1", "1.2", "N1.1", "G2.3"); empty string if none
  "obj_text"   : full text of the learning objective (the leaf-level item)

Rules:
- Only extract leaf-level learning objectives (the numbered sub-items like "1.1 counting to tell...")
- Do NOT include section headers, strand headers, or topic names as objectives
- Include bullet-point sub-items as part of the parent objective's obj_text
- Skip any text about pedagogy, assessment, or administrative notes

SYLLABUS TEXT FOR GRADE {grade}:
{text}
"""


# ── PDF extraction helpers ────────────────────────────────────────────────────

def _extract_pages(pdf_path: Path) -> list[tuple[int, str]]:
    """Return list of (page_number, text) for all non-empty pages."""
    results = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            if text.strip():
                results.append((i + 1, text))
    return results


def _split_by_grade(pages: list[tuple[int, str]], grade_pattern: re.Pattern) -> dict[str, str]:
    """
    Group page text by grade using a regex that matches grade headers.
    Returns {grade_code: combined_text}.
    """
    current_grade: str | None = None
    blocks: dict[str, list[str]] = {}

    for _page_num, text in pages:
        for line in text.splitlines():
            line_lower = line.strip().lower()
            match = grade_pattern.match(line_lower)
            if match:
                found = match.group(0).strip()
                current_grade = GRADE_MAP.get(found)
                if current_grade and current_grade not in blocks:
                    blocks[current_grade] = []
        if current_grade:
            blocks.setdefault(current_grade, []).append(text)

    return {g: "\n".join(texts) for g, texts in blocks.items()}


# ── Gemma extraction ──────────────────────────────────────────────────────────

def _call_gemma(grade: str, text: str) -> list[dict]:
    """Send text to Gemma 4 on Mac Studio, return parsed list of objectives."""
    prompt = EXTRACT_PROMPT.format(grade=grade, text=text[:4000])  # cap to ~4k chars
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

    # Strip markdown code fences if present
    content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.MULTILINE)
    content = re.sub(r"\s*```$", "", content, flags=re.MULTILINE)

    # Find the JSON array
    match = re.search(r"\[.*\]", content, re.DOTALL)
    if not match:
        print(f"    WARN: no JSON array in Gemma response for grade {grade}")
        return []
    return json.loads(match.group(0))


def _extract_keywords(text: str) -> list[str]:
    words = re.findall(r'\b[a-zA-Z][a-zA-Z-]{3,}\b', text.lower())
    seen: set[str] = set()
    result = []
    for w in words:
        if w not in STOP_WORDS and w not in seen:
            seen.add(w)
            result.append(w)
    return result[:20]


# ── Ingestion ─────────────────────────────────────────────────────────────────

def _ingest_objectives(
    objectives: list[dict],
    grade: str,
    conn: sqlite3.Connection,
    seen_ids: set[str],
) -> tuple[int, int]:
    """Write extracted objectives to the standards table."""
    std_count = kw_count = 0
    grade_band = "9-12" if grade == "HS" else None

    for obj in objectives:
        obj_text = (obj.get("obj_text") or "").strip()
        if not obj_text:
            continue

        strand = (obj.get("strand") or "").strip()
        sub_strand = (obj.get("sub_strand") or "").strip()
        topic_code = (obj.get("topic_code") or "").strip()
        obj_code = (obj.get("obj_code") or "").strip()

        # Build standard ID — always include grade since codes repeat across grades
        if obj_code:
            notation = f"{topic_code}.{obj_code}" if topic_code else obj_code
        elif topic_code:
            notation = topic_code
        else:
            # Fallback: hash the first 40 chars of text
            notation = str(abs(hash(obj_text[:40])) % 10000)

        std_id = f"SG_MOE.MATH.{grade}.{notation}"
        if std_id in seen_ids:
            continue
        seen_ids.add(std_id)

        # Also skip if same (grade, text) already in DB — prevents dupes across tracks
        # (G2/G3 and G1/NT PDFs overlap; Gemma may emit different codes for same objective)
        if conn.execute(
            "SELECT 1 FROM standards WHERE system=? AND grade=? AND standard_text=?",
            (SYSTEM, grade, obj_text),
        ).fetchone():
            continue

        conn.execute(
            """INSERT OR REPLACE INTO standards
               (id, system, subject, grade, grade_band, domain, cluster,
                standard_text, last_verified_date, source_url)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (std_id, SYSTEM, "mathematics", grade, grade_band,
             strand, sub_strand or topic_code, obj_text,
             VERIFIED_DATE, SOURCE_URL),
        )
        std_count += 1

        for kw in _extract_keywords(obj_text):
            conn.execute(
                "INSERT OR IGNORE INTO keywords (standard_id, keyword) VALUES (?,?)",
                (std_id, kw),
            )
            kw_count += 1

    return std_count, kw_count


# ── Per-document processors ───────────────────────────────────────────────────

PRIMARY_GRADE_RE = re.compile(
    r"^(primary one|primary two|primary three|primary four|primary five|primary six)"
)
SECONDARY_GRADE_RE = re.compile(
    r"^(secondary one|secondary two|secondary three/four|secondary three|secondary four)"
)


def _process_pdf(
    pdf_path: Path,
    grade_pattern: re.Pattern,
    start_page: int,
    end_page: int | None,
    conn: sqlite3.Connection,
    label: str,
) -> tuple[int, int]:
    print(f"  {label}...")
    pages = _extract_pages(pdf_path)
    pages = [(n, t) for n, t in pages if start_page <= n <= (end_page or 9999)]

    grade_blocks = _split_by_grade(pages, grade_pattern)
    if not grade_blocks:
        print(f"    WARN: no grades found in {pdf_path.name}")
        return 0, 0

    total_std = total_kw = 0
    for grade in sorted(grade_blocks.keys(), key=lambda g: {"K":0,"1":1,"2":2,"3":3,"4":4,"5":5,"6":6,"7":7,"8":8,"HS":9}.get(g,99)):
        text = grade_blocks[grade]
        print(f"    grade {grade}: {len(text)} chars → Gemma...", end="", flush=True)
        try:
            objectives = _call_gemma(grade, text)
        except Exception as e:
            print(f" ERROR: {e}")
            continue

        seen_ids: set[str] = set()
        with conn:
            s, k = _ingest_objectives(objectives, grade, conn, seen_ids)
        total_std += s
        total_kw += k
        print(f" {len(objectives)} extracted, {s} ingested")

    return total_std, total_kw


# ── Main ──────────────────────────────────────────────────────────────────────

def main(tracks: list[str] | None = None) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    pdfs = {
        "primary":   (RAW_DIR / "sg_primary_p1p6.pdf",    PRIMARY_GRADE_RE,   31, 44),
        "secondary": (RAW_DIR / "sg_sec_g2g3_math.pdf",   SECONDARY_GRADE_RE, 17, 35),
        "nt":        (RAW_DIR / "sg_sec_g1_math.pdf",      SECONDARY_GRADE_RE, 18, 30),
    }

    if tracks:
        pdfs = {k: v for k, v in pdfs.items() if k in tracks}

    print(f"Extracting Singapore MOE math standards ({', '.join(pdfs)})...")
    grand_std = grand_kw = 0

    for track, (pdf_path, grade_re, start, end) in pdfs.items():
        if not pdf_path.exists():
            print(f"  SKIP {track}: {pdf_path.name} not found")
            continue
        s, k = _process_pdf(pdf_path, grade_re, start, end, conn, track)
        grand_std += s
        grand_kw += k

    conn.close()
    print(f"\nTotal: {grand_std} standards, {grand_kw} keywords")
    print("Done.")


if __name__ == "__main__":
    filter_args = sys.argv[1:] if len(sys.argv) > 1 else None
    if filter_args:
        print(f"Filtering to tracks: {filter_args}")
    main(filter_args)
