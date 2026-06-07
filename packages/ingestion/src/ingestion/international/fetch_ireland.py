"""Fetch and ingest Ireland NCCA Junior Cycle Mathematics standards.

Covered system: ie-ncca
Source:
  - Junior Cycle Mathematics Specification (NCCA, 2015)
    https://www.curriculumonline.ie/getmedia/6a7f1ff5-9b9e-4d71-8e1f-6d4f932191db/JC_Mathematics_Specification.pdf

Structure:
  5 strands:
    1. Statistics and Probability
    2. Geometry and Trigonometry
    3. Number
    4. Algebra
    5. Functions
  Each strand has numbered learning outcomes (e.g. 1.1, 1.2 ...)

Grade: Junior Cycle = Grades 7-9
IDs: IE_NCCA.MATH.JC.{outcome_num}
"""
import json
import re
import sqlite3
import time
import urllib.request
from datetime import date
from pathlib import Path

import httpx
import pdfplumber

from shared.config import DB_PATH, OLLAMA_BASE_URL

SYSTEM = "ie-ncca"
SOURCE_URL = "https://www.curriculumonline.ie/junior-cycle/junior-cycle-subjects/mathematics/"
PDF_URL = "https://www.curriculumonline.ie/getmedia/6a7f1ff5-9b9e-4d71-8e1f-6d4f932191db/JC_Mathematics_Specification.pdf"
VERIFIED_DATE = date.today().isoformat()
RAW_DIR = DB_PATH.parent / "raw" / "ireland"
OLLAMA_MODEL = "gemma4:31b-it-q8_0"

STRANDS = [
    ("1", "Statistics and Probability"),
    ("2", "Geometry and Trigonometry"),
    ("3", "Number"),
    ("4", "Algebra"),
    ("5", "Functions"),
]

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each",
    "such", "both", "also", "into", "more", "most", "some", "other",
    "these", "those", "about", "able", "after", "where", "while", "make",
    "used", "given", "find", "show", "know", "understand", "apply",
}

EXTRACT_PROMPT = """\
Extract all mathematics learning outcomes from this Ireland Junior Cycle Mathematics specification.

Strand: {strand_num}. {strand_name}

Learning outcomes are numbered (e.g. 1.1, 1.2) and start with "students should be able to..."
Some outcomes have sub-points (a, b, c).

Return ONLY a JSON array (no other text, no markdown). Each element must have:
  "strand_num"   : strand number (e.g. "1")
  "strand_name"  : strand name
  "outcome_num"  : outcome number (e.g. "1.1", "1.2")
  "outcome_text" : full text of the learning outcome

Rules:
- Include every numbered learning outcome.
- If an outcome has sub-items (a, b, c), include them as part of outcome_text.
- Do NOT include strand headers, level descriptors, or general introductory notes.
- Preserve exact wording.

JC MATHEMATICS TEXT (Strand {strand_num}):
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


def _split_by_strand(pages: list[tuple[int, str]]) -> dict[str, str]:
    strand_re = re.compile(
        r"^strand\s+(\d)\s*[:\-–]?\s*(statistics|geometry|number|algebra|functions)",
        re.IGNORECASE,
    )
    current: str | None = None
    blocks: dict[str, list[str]] = {}

    for _pnum, text in pages:
        for line in text.splitlines():
            m = strand_re.match(line.strip())
            if m:
                current = m.group(1)
                blocks.setdefault(current, [])
        if current:
            blocks.setdefault(current, []).append(text)

    return {k: "\n".join(v) for k, v in blocks.items()}


def _call_gemma(strand_num: str, strand_name: str, text: str) -> list[dict]:
    prompt = EXTRACT_PROMPT.format(
        strand_num=strand_num, strand_name=strand_name, text=text[:4000]
    )
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
        print(f"    WARN: no JSON for strand {strand_num}")
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
        outcome_text = (obj.get("outcome_text") or "").strip()
        if not outcome_text:
            continue
        strand_num = str(obj.get("strand_num") or "").strip()
        strand_name = (obj.get("strand_name") or "").strip()
        outcome_num = (obj.get("outcome_num") or "").strip()

        if outcome_num:
            std_id = f"IE_NCCA.MATH.JC.{outcome_num}"
        else:
            std_id = f"IE_NCCA.MATH.JC.{strand_num}.{abs(hash(outcome_text[:40])) % 10000}"

        if std_id in seen_ids:
            continue
        seen_ids.add(std_id)

        conn.execute(
            """INSERT OR REPLACE INTO standards
               (id, system, subject, grade, grade_band, domain, cluster,
                standard_text, last_verified_date, source_url)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (std_id, SYSTEM, "mathematics", "7", None,
             strand_name, "", outcome_text, VERIFIED_DATE, SOURCE_URL),
        )
        std_count += 1
        for kw in _extract_keywords(outcome_text):
            conn.execute("INSERT OR IGNORE INTO keywords (standard_id, keyword) VALUES (?,?)", (std_id, kw))
            kw_count += 1

    return std_count, kw_count


def main() -> None:
    pdf_path = RAW_DIR / "ireland_jc_mathematics.pdf"
    if not pdf_path.exists():
        _download_pdf(pdf_path)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    print("Extracting Ireland NCCA Junior Cycle Mathematics...")
    pages = _extract_pages(pdf_path)
    strand_blocks = _split_by_strand(pages)

    if not strand_blocks:
        print("  WARN: strand splitting failed — sending full PDF by page groups")
        all_text = "\n".join(t for _, t in pages)
        strand_blocks = {sn: all_text for sn, _ in STRANDS}

    print(f"  Strands found: {list(strand_blocks.keys())}")
    grand_std = grand_kw = 0
    seen_ids: set[str] = set()

    for strand_num, strand_name in STRANDS:
        text = strand_blocks.get(strand_num, "")
        if not text:
            print(f"  strand {strand_num} ({strand_name}): not found")
            continue
        print(f"  strand {strand_num}: {len(text)} chars → Gemma...", end="", flush=True)
        try:
            objectives = _call_gemma(strand_num, strand_name, text)
        except Exception as e:
            print(f" ERROR: {e}")
            continue
        with conn:
            s, k = _ingest_objectives(objectives, conn, seen_ids)
        grand_std += s
        grand_kw += k
        print(f" {len(objectives)} extracted, {s} ingested")
        time.sleep(0.5)

    conn.close()
    print(f"\nTotal: {grand_std} standards, {grand_kw} keywords")
    print("Done.")


if __name__ == "__main__":
    main()
