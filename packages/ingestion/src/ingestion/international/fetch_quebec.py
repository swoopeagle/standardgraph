"""Fetch and ingest Quebec MEES Progression of Learning — Mathematics.

Covered system: ca-qc
Sources (auto-downloaded):
  Elementary (Cycles 1-3, Grades 1-6):
    https://www.education.gouv.qc.ca/fileadmin/site_web/documents/education/jeunes/pfeq/
    PDA_PFEQ_mathematique-primaire_2009_EN.pdf
  Secondary (Secondary I-V, Grades 7-11):
    https://www.education.gouv.qc.ca/fileadmin/site_web/documents/education/jeunes/pfeq/
    PDA_PFEQ_mathematique-secondaire_2016_EN.pdf

Grade mapping:
  Elementary: Cycle 1 (Gr 1-2), Cycle 2 (Gr 3-4), Cycle 3 (Gr 5-6) → grades 1-6
  Secondary: Sec I→7, Sec II→8, Sec III→9, Sec IV→10, Sec V→HS

IDs: CA_QC.MATH.{grade}.{hash}
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

SYSTEM = "ca-qc"
SOURCE_URL = "https://www.education.gouv.qc.ca/en/teachers/programs/mathematics/"
VERIFIED_DATE = date.today().isoformat()
RAW_DIR = DB_PATH.parent / "raw" / "quebec"

PDFS = [
    (
        "quebec_elementary.pdf",
        "https://www.education.gouv.qc.ca/fileadmin/site_web/documents/education/jeunes/pfeq/PDA_PFEQ_mathematique-primaire_2009_EN.pdf",
        ["1", "2", "3", "4", "5", "6"],
        "elementary",
    ),
    (
        "quebec_secondary.pdf",
        "https://www.education.gouv.qc.ca/fileadmin/site_web/documents/education/jeunes/pfeq/PDA_PFEQ_mathematique-secondaire_2016_EN.pdf",
        ["7", "8", "9", "10", "HS"],
        "secondary",
    ),
]

ELEMENTARY_PROMPT = """\
Extract all mathematics learning competencies from this Quebec Progression of Learning document (Elementary).

Quebec organizes elementary math into topics: Arithmetic (numbers, operations), Geometry, Measurement,
Statistics, Probability. Each topic lists numbered learning statements.

The document uses a table format where columns represent grades 1-6. In the extracted text, grade numbers
appear as section headers like "A. Natural Numbers 1 2 3 4 5 6". Each numbered item is a learning competency.

Return ONLY a JSON array (no other text, no markdown). Each element must have:
  "topic"      : broad topic (e.g. "Arithmetic", "Geometry", "Measurement", "Statistics", "Probability")
  "sub_topic"  : sub-topic (e.g. "Natural numbers", "Fractions", "Angles", "Areas")
  "grade"      : best estimate of which grade this applies to ("1","2","3","4","5","6"); use "1-6" if grade unclear
  "obj_text"   : full text of the learning competency (the numbered statement)

Rules:
- Extract every numbered learning competency.
- Do NOT include vocabulary lists, example notes, or section headers.
- Preserve exact wording.

DOCUMENT TEXT:
{text}
"""

SECONDARY_PROMPT = """\
Extract all mathematics learning competencies from this Quebec Progression of Learning document (Secondary).

Quebec secondary math covers: Arithmetic, Algebra, Geometry, Statistics, Probability.
Secondary levels: Secondary I (grade 7), Secondary II (grade 8), Secondary III (grade 9),
Secondary IV (grade 10), Secondary V (grade 11 = HS).
Tracks in Secondary IV-V: CST (Cultural/Social/Technical), SN (Science/Natural), TS (Techno-Sciences).

Return ONLY a JSON array (no other text, no markdown). Each element must have:
  "topic"      : broad topic (e.g. "Arithmetic", "Algebra", "Geometry", "Statistics", "Probability")
  "sub_topic"  : sub-topic (e.g. "Real numbers", "Equations", "Trigonometry")
  "grade"      : "7","8","9","10", or "HS"; use "HS" for Secondary IV-V content
  "obj_text"   : full text of the learning competency

Rules:
- Extract every numbered learning competency.
- Do NOT include vocabulary lists, example notes, or track labels alone.
- Preserve exact wording.

DOCUMENT TEXT:
{text}
"""

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each",
    "such", "both", "also", "into", "more", "most", "some", "other",
    "these", "those", "about", "able", "after", "where", "while", "make",
    "used", "given", "find", "show", "know", "understand", "apply",
}

VALID_GRADES = {"1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "HS", "1-6"}


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


def _call_gemma(text: str, prompt_template: str) -> list[dict]:
    prompt = prompt_template.format(text=text[:5000])
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


def _ingest(objectives: list[dict], conn: sqlite3.Connection, seen_ids: set[str]) -> tuple[int, int]:
    std_count = kw_count = 0
    for obj in objectives:
        obj_text = (obj.get("obj_text") or "").strip()
        grade = str(obj.get("grade") or "").strip()
        if not obj_text or grade not in VALID_GRADES:
            continue
        # Normalize "1-6" band → store as grade 1 with grade_band
        if grade == "1-6":
            grade, grade_band = "1", "K-6"
        else:
            grade_band = "9-12" if grade == "HS" else None

        topic = (obj.get("topic") or "").strip()
        sub_topic = (obj.get("sub_topic") or "").strip()
        std_id = f"CA_QC.MATH.{grade}.{abs(hash(obj_text[:40])) % 100000}"
        if std_id in seen_ids:
            continue
        seen_ids.add(std_id)

        conn.execute(
            """INSERT OR REPLACE INTO standards
               (id, system, subject, grade, grade_band, domain, cluster,
                standard_text, last_verified_date, source_url)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (std_id, SYSTEM, "mathematics", grade, grade_band,
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

    print("Extracting Quebec MEES Progression of Learning — Mathematics...")
    grand_std = grand_kw = 0
    seen_ids: set[str] = set()

    for fname, url, _grades, level in PDFS:
        pdf_path = RAW_DIR / fname
        if not pdf_path.exists():
            _download(url, pdf_path)

        prompt_template = ELEMENTARY_PROMPT if level == "elementary" else SECONDARY_PROMPT
        pages = _extract_pages(pdf_path)
        # Skip intro/TOC pages (first 3), process rest in chunks of 3 pages
        content_pages = pages[3:]
        chunk_size = 3

        print(f"\n  {level.capitalize()} ({fname}): {len(content_pages)} content pages")
        level_std = level_kw = 0

        for i in range(0, len(content_pages), chunk_size):
            chunk = content_pages[i:i + chunk_size]
            chunk_text = "\n\n".join(t for _, t in chunk)
            page_nums = f"{chunk[0][0]}-{chunk[-1][0]}"
            print(f"    pages {page_nums}: {len(chunk_text)} chars → Gemma...", end="", flush=True)
            try:
                objectives = _call_gemma(chunk_text, prompt_template)
            except Exception as e:
                print(f" ERROR: {e}")
                continue
            with conn:
                s, k = _ingest(objectives, conn, seen_ids)
            level_std += s
            level_kw += k
            print(f" {len(objectives)} extracted, {s} ingested")

        print(f"  {level.capitalize()} total: {level_std} standards, {level_kw} keywords")
        grand_std += level_std
        grand_kw += level_kw

    conn.close()
    print(f"\nTotal: {grand_std} standards, {grand_kw} keywords")
    print("Done.")


if __name__ == "__main__":
    main()
