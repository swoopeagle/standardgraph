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

STRAND_NAMES = {
    "1": "Statistics and Probability",
    "2": "Geometry and Trigonometry",
    "3": "Number",
    "4": "Algebra",
    "5": "Functions",
}

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each",
    "such", "both", "also", "into", "more", "most", "some", "other",
    "these", "those", "about", "able", "after", "where", "while", "make",
    "used", "given", "find", "show", "know", "understand", "apply",
}

EXTRACT_PROMPT = """\
Extract all mathematics learning outcomes from this Ireland Junior Cycle Mathematics specification text.

Strand numbering:
  Strand 1: Statistics and Probability  (outcomes numbered 1.1, 1.2, ...)
  Strand 2: Geometry and Trigonometry   (outcomes numbered 2.1, 2.2, ...)
  Strand 3: Number                       (outcomes numbered 3.1, 3.2, ...)
  Strand 4: Algebra                      (outcomes numbered 4.1, 4.2, ...)
  Strand 5: Functions                    (outcomes numbered 5.1, 5.2, ...)

Learning outcomes start with "students should be able to..." and are numbered (e.g. 1.1, 1.2).
Some outcomes have sub-items (a, b, c).

Return ONLY a JSON array (no other text, no markdown). Each element must have:
  "strand_num"   : strand number as a string (e.g. "1", "2")
  "strand_name"  : strand name (e.g. "Statistics and Probability")
  "outcome_num"  : outcome number (e.g. "1.1", "2.3")
  "outcome_text" : full text of the learning outcome

If no learning outcomes appear in this text, return an empty array [].

Rules:
- Include every numbered learning outcome you can find.
- If an outcome has sub-items (a, b, c), include them as part of outcome_text.
- Do NOT include strand headers, level descriptors, or general introductory notes.
- Preserve exact wording.

TEXT:
{text}
"""


def _download_pdf(path: Path) -> None:
    print(f"  Downloading {PDF_URL} ...")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    req = urllib.request.Request(PDF_URL, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r, open(path, "wb") as f:
        f.write(r.read())
    print(f"  Saved: {path.stat().st_size:,} bytes")


def _extract_pages(pdf_path: Path) -> list[tuple[int, str]]:
    results = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            if text.strip():
                results.append((i + 1, text))
    return results


def _call_gemma(text: str) -> list[dict]:
    prompt = EXTRACT_PROMPT.format(text=text[:5500])
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
        strand_name = (obj.get("strand_name") or STRAND_NAMES.get(strand_num, "")).strip()
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

    # Clear stale ie-ncca records so re-runs are idempotent
    with conn:
        conn.execute("DELETE FROM keywords WHERE standard_id LIKE 'IE_NCCA%'")
        conn.execute("DELETE FROM standards WHERE system = ?", (SYSTEM,))

    print("Extracting Ireland NCCA Junior Cycle Mathematics...")
    pages = _extract_pages(pdf_path)

    # Skip first 12 intro/cover pages; process content in 3-page chunks
    content_pages = pages[12:]
    chunk_size = 3
    grand_std = grand_kw = 0
    seen_ids: set[str] = set()

    print(f"  {len(content_pages)} content pages, {len(content_pages) // chunk_size + 1} chunks")

    for i in range(0, len(content_pages), chunk_size):
        chunk = content_pages[i:i + chunk_size]
        chunk_text = "\n\n".join(t for _, t in chunk)
        page_nums = f"{chunk[0][0]}-{chunk[-1][0]}"
        print(f"    pages {page_nums}: {len(chunk_text)} chars → Gemma...", end="", flush=True)
        try:
            objectives = _call_gemma(chunk_text)
        except Exception as e:
            print(f" ERROR: {e}")
            continue
        with conn:
            s, k = _ingest_objectives(objectives, conn, seen_ids)
        grand_std += s
        grand_kw += k
        print(f" {len(objectives)} extracted, {s} ingested")
        time.sleep(0.3)

    conn.close()
    print(f"\nTotal: {grand_std} standards, {grand_kw} keywords")
    print("Done.")


if __name__ == "__main__":
    main()
