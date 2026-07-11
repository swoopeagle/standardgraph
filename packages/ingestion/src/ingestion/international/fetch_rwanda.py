"""Fetch and ingest Rwanda REB Competence-Based Curriculum — Mathematics.

Covered system: rw-reb
Sources (auto-downloaded):
  Upper Primary P4-P6 (2025):
    https://elearning.reb.rw/pluginfile.php/177314/mod_folder/content/0/P4-P6%20Mathematics%20Syllabus.pdf

Grade mapping: P4→4, P5→5, P6→6
IDs: RW_REB.MATH.{grade}.{hash}

Note: P1-P3 and secondary PDFs not yet found — extend when URLs are confirmed.
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

SYSTEM = "rw-reb"
SOURCE_URL = "https://reb.rw/index.php/competence-based-curriculum/"
VERIFIED_DATE = date.today().isoformat()
RAW_DIR = DB_PATH.parent / "raw" / "rwanda"

PDFS = [
    (
        "p4_p6.pdf",
        "https://elearning.reb.rw/pluginfile.php/177314/mod_folder/content/0/P4-P6%20Mathematics%20Syllabus.pdf",
        {"P4": "4", "P5": "5", "P6": "6"},
    ),
    # Optional: P1-P3 and secondary syllabi may be at elearning.reb.rw — add if found
]

EXTRACT_PROMPT = """\
Extract all mathematics learning competencies from this Rwanda REB Competence-Based Curriculum text.

The document is organized into units. Each unit has:
- A grade label (e.g. "P4 MATHEMATICS", "P5 MATHEMATICS", "P6 MATHEMATICS")
- A Topic Area (e.g. "NUMBERS", "FRACTIONS, DECIMALS AND PROPORTIONAL REASONING", "GEOMETRY")
- A Sub-Topic Area
- Key Unit Competence (1 sentence describing what pupils can do)
- Learning Objectives split into: Knowledge and Understanding | Skills | Attitudes and Values
- Content (bullet list of content items)

Return ONLY a JSON array (no other text, no markdown). Each element must have:
  "grade"       : "4", "5", or "6" based on the "P4/P5/P6 MATHEMATICS" header
  "topic_area"  : Topic Area (e.g. "Numbers", "Geometry", "Measurement")
  "sub_topic"   : Sub-Topic Area (e.g. "Types of numbers", "Length measurements")
  "unit_name"   : Unit title (e.g. "Classifying numbers by their properties")
  "obj_text"    : the Key Unit Competence statement (one sentence per unit)

Rules:
- Extract one entry per unit using the Key Unit Competence as the objective text.
- Use the most recent P4/P5/P6 header above the unit to assign grade.
- Do NOT include activity descriptions, teaching notes, or assessment guidance.
- Preserve exact wording of the Key Unit Competence.

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


def _download(url: str, path: Path) -> None:
    print(f"  Downloading {url} ...")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    req = urllib.request.Request(url, headers=headers)
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


def _ingest(objectives: list[dict], valid_grades: set[str], conn: sqlite3.Connection, seen_ids: set[str]) -> tuple[int, int]:
    std_count = kw_count = 0
    for obj in objectives:
        obj_text = (obj.get("obj_text") or "").strip()
        grade = str(obj.get("grade") or "").strip()
        if not obj_text or grade not in valid_grades:
            continue
        topic = (obj.get("topic_area") or "").strip()
        sub_topic = (obj.get("sub_topic") or obj.get("unit_name") or "").strip()
        std_id = f"RW_REB.MATH.{grade}.{abs(hash(obj_text[:40])) % 100000}"
        if std_id in seen_ids:
            continue
        seen_ids.add(std_id)
        conn.execute(
            """INSERT OR REPLACE INTO standards
               (id, system, subject, grade, grade_band, domain, cluster,
                standard_text, last_verified_date, source_url)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (std_id, SYSTEM, "mathematics", grade, None,
             topic, sub_topic, obj_text, VERIFIED_DATE, SOURCE_URL),
        )
        std_count += 1
        for kw in _extract_keywords(obj_text):
            conn.execute("INSERT OR IGNORE INTO keywords (standard_id, keyword) VALUES (?,?)", (std_id, kw))
            kw_count += 1
    return std_count, kw_count


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    print("Extracting Rwanda REB Mathematics standards...")
    grand_std = grand_kw = 0
    seen_ids: set[str] = set()

    for fname, url, grade_map in PDFS:
        pdf_path = RAW_DIR / fname
        if not pdf_path.exists():
            _download(url, pdf_path)

        pages = _extract_pages(pdf_path)
        # Skip intro/foreword (~first 25 pages), process in chunks of 4
        content_pages = [(n, t) for n, t in pages if n >= 25]
        valid_grades = set(grade_map.values())
        chunk_size = 4

        print(f"\n  {fname}: {len(content_pages)} content pages")
        file_std = file_kw = 0

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
                s, k = _ingest(objectives, valid_grades, conn, seen_ids)
            file_std += s
            file_kw += k
            print(f" {len(objectives)} extracted, {s} ingested")

        print(f"  Total: {file_std} standards, {file_kw} keywords")
        grand_std += file_std
        grand_kw += file_kw

    conn.close()
    print(f"\nGrand total: {grand_std} standards, {grand_kw} keywords")
    print("Done.")


if __name__ == "__main__":
    main()
