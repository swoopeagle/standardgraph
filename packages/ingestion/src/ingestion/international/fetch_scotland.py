"""Fetch and ingest Scotland Curriculum for Excellence (CfE) mathematics standards.

Covered system: gb-sco
Source:
  - Numeracy and Mathematics Experiences and Outcomes (Education Scotland)
    https://education.gov.scot/media/sz2lnh1g/numeracy-maths-eo.pdf

Structure:
  Organisers: Number, money and measure | Shape, position and movement | Information handling
  Levels: Early | First | Second | Third | Fourth
    Level descriptions and individual outcomes per organiser

Level → approximate grade mapping (used as 'grade' field):
  early   → K
  first   → 1-2 (stored as "first")
  second  → 3-4 (stored as "second")
  third   → 5-7 (stored as "third")
  fourth  → 8-9 (stored as "fourth")

IDs: GB_SCO.MATH.{level}.{hash}
"""
import json
import re
import sqlite3
import urllib.request
from datetime import date
from pathlib import Path

import httpx
import pdfplumber

from shared.config import DB_PATH, OLLAMA_BASE_URL, OLLAMA_MODEL

SYSTEM = "gb-sco"
SOURCE_URL = "https://education.gov.scot/curriculum-for-excellence/curriculum-areas/numeracy-and-mathematics/"
PDF_URL = "https://education.gov.scot/media/sz2lnh1g/numeracy-maths-eo.pdf"
VERIFIED_DATE = date.today().isoformat()
RAW_DIR = DB_PATH.parent / "raw" / "scotland"

LEVELS = ["early", "first", "second", "third", "fourth"]

LEVEL_TO_GRADE = {
    "early": "K",
    "first": "first",
    "second": "second",
    "third": "third",
    "fourth": "fourth",
}

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each",
    "such", "both", "also", "into", "more", "most", "some", "other",
    "these", "those", "about", "able", "after", "where", "while", "make",
    "used", "given", "find", "show", "know", "understand", "apply",
}

EXTRACT_PROMPT = """\
This is a page from the Scotland Curriculum for Excellence (CfE) Numeracy and Mathematics document.
The page is a TABLE with columns: Early | First | Second | Third | Fourth
Each row is a sub-topic. Each cell contains the learning outcomes for that level.

Extract every "I can..." or "I am..." or "I have..." outcome statement from this page.

Return ONLY a JSON array (no other text, no markdown). Each element must have:
  "level"      : one of "early", "first", "second", "third", "fourth"
  "organiser"  : the section name — one of "Number, money and measure", "Shape, position and movement", "Information handling"
  "sub_area"   : the row topic (e.g. "Estimation and rounding", "Fractions, decimal fractions and percentages")
  "outcome"    : the full text of the learning outcome

Rules:
- Include every individual "I can...", "I am...", or "I have..." statement.
- Each outcome gets its own array entry with its correct level.
- Do NOT include level descriptions, headers, or teacher guidance notes.
- Preserve exact wording from the document.

TABLE TEXT:
{text}
"""


def _download_pdf(path: Path) -> None:
    print(f"  Downloading {PDF_URL} ...")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(PDF_URL, path)
    print(f"  Saved: {path.stat().st_size} bytes")


def _extract_pages(pdf_path: Path) -> list[tuple[int, str]]:
    results = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            if text.strip():
                results.append((i + 1, text))
    return results


def _split_by_level(pages: list[tuple[int, str]]) -> dict[str, str]:
    """Group pages by CfE level."""
    level_re = re.compile(
        r"^(early level|first level|second level|third level|fourth level)\s*$",
        re.IGNORECASE,
    )
    current: str | None = None
    blocks: dict[str, list[str]] = {}

    for _pnum, text in pages:
        for line in text.splitlines():
            m = level_re.match(line.strip())
            if m:
                current = m.group(1).split()[0].lower()  # "early", "first", etc.
                blocks.setdefault(current, [])
        if current:
            blocks.setdefault(current, []).append(text)

    return {lv: "\n".join(texts) for lv, texts in blocks.items()}


def _call_gemma(text: str, page_num: int) -> list[dict]:
    prompt = EXTRACT_PROMPT.format(text=text[:5000])
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
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
        print(f"    WARN: no JSON array for page {page_num}")
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


def _ingest_objectives(objectives: list[dict], conn: sqlite3.Connection, seen_ids: set[str]) -> tuple[int, int]:
    std_count = kw_count = 0

    for obj in objectives:
        outcome = (obj.get("outcome") or "").strip()
        if not outcome:
            continue
        level = (obj.get("level") or "").strip().lower()
        organiser = (obj.get("organiser") or "").strip()
        sub_area = (obj.get("sub_area") or "").strip()
        grade = LEVEL_TO_GRADE.get(level, level or "unknown")

        std_id = f"GB_SCO.MATH.{level}.{abs(hash(outcome[:40])) % 100000}"
        if std_id in seen_ids:
            continue
        seen_ids.add(std_id)

        conn.execute(
            """INSERT OR REPLACE INTO standards
               (id, system, subject, grade, grade_band, domain, cluster,
                standard_text, last_verified_date, source_url)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (std_id, SYSTEM, "mathematics", grade, None,
             organiser, sub_area, outcome, VERIFIED_DATE, SOURCE_URL),
        )
        std_count += 1

        for kw in _extract_keywords(outcome):
            conn.execute("INSERT OR IGNORE INTO keywords (standard_id, keyword) VALUES (?,?)", (std_id, kw))
            kw_count += 1

    return std_count, kw_count


def main() -> None:
    pdf_path = RAW_DIR / "scotland_cfe_numeracy_maths.pdf"
    if not pdf_path.exists():
        _download_pdf(pdf_path)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    print("Extracting Scotland CfE Numeracy and Mathematics...")
    pages = _extract_pages(pdf_path)
    print(f"  {len(pages)} content pages")

    grand_std = grand_kw = 0
    seen_ids: set[str] = set()

    for pnum, text in pages:
        # Skip pages with no table content (intro/cover/appendix pages)
        if "I can" not in text and "I am" not in text and "I have" not in text:
            continue
        print(f"  page {pnum}: {len(text)} chars → Gemma...", end="", flush=True)
        try:
            objectives = _call_gemma(text, pnum)
        except Exception as e:
            print(f" ERROR: {e}")
            continue
        with conn:
            s, k = _ingest_objectives(objectives, conn, seen_ids)
        grand_std += s
        grand_kw += k
        print(f" {len(objectives)} extracted, {s} ingested")

    conn.close()
    print(f"\nTotal: {grand_std} standards, {grand_kw} keywords")
    print("Done.")


if __name__ == "__main__":
    main()
