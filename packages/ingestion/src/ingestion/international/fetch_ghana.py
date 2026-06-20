"""Fetch and ingest Ghana NaCCA Mathematics curriculum — SHS 1-3.

Covered system: gh-nacca
Source (auto-downloaded):
  https://nacca.gov.gh/wp-content/uploads/2025/04/Mathematics-Curriculum.pdf

This PDF covers Senior High School (SHS) 1-3 only (≈ grades 10-12).
B1-B9 (Primary / JHS) PDFs are not yet found — extend when URLs are confirmed.

Grade mapping: SHS1→10, SHS2→11, SHS3→HS  (all stored with grade_band="9-12")
Indicator code format: {year}.{strand}.{substrand}.LI.{n}  (e.g. 1.3.2.LI.1)
IDs: GH_NACCA.MATH.{grade}.{code|hash}

Page boundaries (0-indexed):
  Intro:  pages 0-23 (skip)
  SHS 1:  pages 24-155
  SHS 2:  pages 156-303
  SHS 3:  pages 304-384
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

SYSTEM = "gh-nacca"
SOURCE_URL = "https://nacca.gov.gh/secondary-education-curriculum/"
PDF_URL = "https://nacca.gov.gh/wp-content/uploads/2025/04/Mathematics-Curriculum.pdf"
VERIFIED_DATE = date.today().isoformat()
RAW_DIR = DB_PATH.parent / "raw" / "ghana"
PDF_PATH = RAW_DIR / "ghana_nacca_mathematics.pdf"

# Page ranges are 0-indexed (PDF page index, not page number)
PHASES = [
    {"label": "SHS1", "grade": "10",  "start": 24,  "end": 155},
    {"label": "SHS2", "grade": "11",  "start": 156, "end": 303},
    {"label": "SHS3", "grade": "HS",  "start": 304, "end": 384},
]

EXTRACT_PROMPT = """\
Extract all mathematics learning indicators from this Ghana NaCCA Senior High School curriculum text ({phase_label}).

The curriculum uses this structure:
- Strand (e.g. "NUMBERS FOR EVERYDAY LIFE", "ALGEBRAIC REASONING", "GEOMETRY AND MEASUREMENT", "DATA")
- Sub-Strand (topic within a strand)
- Content Standards (what learners should know/do)
- Learning Indicators (specific observable outcomes, coded as {year}.strand.substrand.LI.n, e.g. 1.3.2.LI.1)

Return ONLY a JSON array (no other text, no markdown). Each element must have:
  "strand"          : strand name
  "sub_strand"      : sub-strand or topic name
  "indicator_code"  : learning indicator code if present (e.g. "1.3.2.LI.1"); empty string if absent
  "indicator_text"  : full text of the learning indicator

Rules:
- Extract every learning indicator — the specific, measurable outcome statements.
- Do NOT include content standard headers, pedagogical notes, teaching activities, or GESI guidance.
- Preserve exact wording.

CURRICULUM TEXT ({phase_label}):
{text}
"""

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each",
    "such", "both", "also", "into", "more", "most", "some", "other",
    "these", "those", "about", "able", "after", "where", "while", "make",
    "used", "given", "find", "show", "know", "understand", "apply",
}


def _download(path: Path) -> None:
    print(f"  Downloading {PDF_URL} ...")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(PDF_URL, path)
    print(f"  Saved: {path.stat().st_size:,} bytes")


def _extract_pages(pdf_path: Path) -> list[str]:
    """Return per-page text for all pages (empty string for blank pages)."""
    with pdfplumber.open(pdf_path) as pdf:
        return [page.extract_text() or "" for page in pdf.pages]


def _call_gemma(text: str, phase_label: str, year: str) -> list[dict]:
    prompt = EXTRACT_PROMPT.format(
        phase_label=phase_label,
        year=year,
        text=text[:5000],
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


def _ingest(objectives: list[dict], grade: str, conn: sqlite3.Connection, seen_ids: set[str]) -> tuple[int, int]:
    std_count = kw_count = 0
    for obj in objectives:
        ind_text = (obj.get("indicator_text") or "").strip()
        if not ind_text:
            continue
        strand = (obj.get("strand") or "").strip()
        sub_strand = (obj.get("sub_strand") or "").strip()
        ind_code = (obj.get("indicator_code") or "").strip()

        if ind_code:
            std_id = f"GH_NACCA.MATH.{grade}.{ind_code}"
        else:
            std_id = f"GH_NACCA.MATH.{grade}.{abs(hash(ind_text[:40])) % 100000}"

        if std_id in seen_ids:
            continue
        seen_ids.add(std_id)

        conn.execute(
            """INSERT OR REPLACE INTO standards
               (id, system, subject, grade, grade_band, domain, cluster,
                standard_text, last_verified_date, source_url)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (std_id, SYSTEM, "mathematics", grade, "9-12",
             strand, sub_strand, ind_text, VERIFIED_DATE, SOURCE_URL),
        )
        std_count += 1
        for kw in _extract_keywords(ind_text):
            conn.execute("INSERT OR IGNORE INTO keywords (standard_id, keyword) VALUES (?,?)", (std_id, kw))
            kw_count += 1
    return std_count, kw_count


def main() -> None:
    if not PDF_PATH.exists():
        _download(PDF_PATH)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    # Clear any stale gh-nacca data from previous bad runs
    with conn:
        deleted = conn.execute("DELETE FROM standards WHERE system='gh-nacca'").rowcount
    if deleted:
        print(f"  Cleared {deleted} stale gh-nacca records.")

    print("Extracting Ghana NaCCA Mathematics standards (SHS 1-3)...")
    all_pages = _extract_pages(PDF_PATH)
    print(f"  PDF: {len(all_pages)} pages total")

    grand_std = grand_kw = 0
    seen_ids: set[str] = set()
    chunk_size = 3

    for phase in PHASES:
        label = phase["label"]
        grade = phase["grade"]
        year = label[-1]  # "1", "2", or "3"
        pages = [(i + 1, all_pages[i]) for i in range(phase["start"], phase["end"] + 1)
                 if all_pages[i].strip()]

        print(f"\n  {label} (grade {grade}): {len(pages)} content pages")
        phase_std = phase_kw = 0

        for i in range(0, len(pages), chunk_size):
            chunk = pages[i:i + chunk_size]
            chunk_text = "\n\n".join(t for _, t in chunk)
            page_nums = f"{chunk[0][0]}-{chunk[-1][0]}"
            print(f"    pages {page_nums}: {len(chunk_text)} chars → Gemma...", end="", flush=True)
            try:
                objectives = _call_gemma(chunk_text, label, year)
            except Exception as e:
                print(f" ERROR: {e}")
                continue
            with conn:
                s, k = _ingest(objectives, grade, conn, seen_ids)
            phase_std += s
            phase_kw += k
            print(f" {len(objectives)} extracted, {s} ingested")

        print(f"  {label} total: {phase_std} standards, {phase_kw} keywords")
        grand_std += phase_std
        grand_kw += phase_kw

    conn.close()
    print(f"\nTotal: {grand_std} standards, {grand_kw} keywords")
    print("Note: B1-B9 (Primary/JHS) PDFs not yet found — SHS only.")
    print("Done.")


if __name__ == "__main__":
    main()
