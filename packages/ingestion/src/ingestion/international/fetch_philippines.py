"""Fetch and ingest Philippines DepEd MATATAG Mathematics curriculum.

Covered system: ph-deped
Source (manual download required — DepEd blocks automated downloads):
  MATATAG K-10 Mathematics Curriculum Guide
  Download from: https://www.deped.gov.ph/curriculum-guides/
  Save as: data/raw/philippines/deped_math_k10.pdf

Grade mapping: Kindergarten→K, Grades 1-10 (10→HS)
IDs: PH_DEPED.MATH.{grade}.{hash}
"""
import json
import re
import sqlite3
import time
from datetime import date
from pathlib import Path

import httpx
import pdfplumber

from shared.config import DB_PATH, OLLAMA_BASE_URL

SYSTEM = "ph-deped"
SOURCE_URL = "https://www.deped.gov.ph/curriculum-guides/"
VERIFIED_DATE = date.today().isoformat()
RAW_DIR = DB_PATH.parent / "raw" / "philippines"
OLLAMA_MODEL = "gemma4:31b-it-q8_0"
PDF_PATH = RAW_DIR / "deped_math_k10.pdf"

EXTRACT_PROMPT = """\
Extract all mathematics learning competencies from this Philippines DepEd MATATAG curriculum text.

The curriculum is organized by Grade level, then by Content Domain/Strand, then by Quarter.
Each competency has a code (e.g. M1NS-Ia-1.1) and a learning competency statement.

Return ONLY a JSON array (no other text, no markdown). Each element must have:
  "grade"      : grade as string ("K","1","2","3","4","5","6","7","8","9","10")
  "domain"     : content domain (e.g. "Number Sense", "Algebra", "Geometry", "Measurement",
                  "Statistics and Probability", "Patterns and Algebra")
  "code"       : competency code if present (e.g. "M1NS-Ia-1.1"); empty string if absent
  "obj_text"   : full text of the learning competency

Rules:
- Extract every individual learning competency.
- Do NOT include quarter headers, time allotments, or general descriptions.
- Preserve exact wording.

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

GRADE_MAP = {
    "k": "K", "kindergarten": "K",
    "1": "1", "2": "2", "3": "3", "4": "4", "5": "5",
    "6": "6", "7": "7", "8": "8", "9": "9", "10": "HS",
}


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


def _ingest(objectives: list[dict], conn: sqlite3.Connection, seen_ids: set[str]) -> tuple[int, int]:
    std_count = kw_count = 0
    for obj in objectives:
        obj_text = (obj.get("obj_text") or "").strip()
        raw_grade = str(obj.get("grade") or "").strip().lower()
        grade = GRADE_MAP.get(raw_grade)
        if not obj_text or not grade:
            continue
        domain = (obj.get("domain") or "").strip()
        code = (obj.get("code") or "").strip()
        grade_band = "9-12" if grade == "HS" else None

        if code:
            std_id = f"PH_DEPED.MATH.{grade}.{code}"
        else:
            std_id = f"PH_DEPED.MATH.{grade}.{abs(hash(obj_text[:40])) % 100000}"

        if std_id in seen_ids:
            continue
        seen_ids.add(std_id)
        conn.execute(
            """INSERT OR REPLACE INTO standards
               (id, system, subject, grade, grade_band, domain, cluster,
                standard_text, last_verified_date, source_url)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (std_id, SYSTEM, "mathematics", grade, grade_band,
             domain, "", obj_text, VERIFIED_DATE, SOURCE_URL),
        )
        std_count += 1
        for kw in _extract_keywords(obj_text):
            conn.execute("INSERT OR IGNORE INTO keywords (standard_id, keyword) VALUES (?,?)", (std_id, kw))
            kw_count += 1
    return std_count, kw_count


def main() -> None:
    if not PDF_PATH.exists():
        print(f"SKIP: {PDF_PATH} not found.")
        print("DepEd blocks automated downloads (HTTP 403).")
        print("Manual steps:")
        print("  1. Go to https://www.deped.gov.ph/curriculum-guides/")
        print("  2. Download the MATATAG Mathematics Curriculum Guide (K-10)")
        print(f"  3. Save as {PDF_PATH}")
        return

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    print("Extracting Philippines DepEd MATATAG Mathematics standards...")
    pages = _extract_pages(PDF_PATH)
    seen_ids: set[str] = set()
    grand_std = grand_kw = 0
    chunk_size = 3

    for i in range(0, len(pages), chunk_size):
        chunk = pages[i:i + chunk_size]
        chunk_text = "\n\n".join(t for _, t in chunk)
        page_nums = f"{chunk[0][0]}-{chunk[-1][0]}"
        print(f"  pages {page_nums}: {len(chunk_text)} chars → Gemma...", end="", flush=True)
        try:
            objectives = _call_gemma(chunk_text)
        except Exception as e:
            print(f" ERROR: {e}")
            continue
        with conn:
            s, k = _ingest(objectives, conn, seen_ids)
        grand_std += s
        grand_kw += k
        print(f" {len(objectives)} extracted, {s} ingested")
        time.sleep(0.3)

    conn.close()
    print(f"\nTotal: {grand_std} standards, {grand_kw} keywords")
    print("Done.")


if __name__ == "__main__":
    main()
