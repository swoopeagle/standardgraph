"""Fetch and ingest Japan MEXT elementary math standards from the English translation PDF.

Covered system: jp-mext
Source:
  - Course of Study for Elementary School (2008) — Section 3: Arithmetic
    https://www.mext.go.jp/component/english/__icsFiles/afieldfile/2011/03/17/1303755_004.pdf
    Grades 1-6

Structure:
  [Grade N]
    A. Numbers and Calculations
      (1) topic description
        a. leaf objective
        b. leaf objective
    B. Quantities and Measurements
      ...

ID format: JP_MEXT.MATH.{grade}.{strand}.{topic}.{obj}
  e.g. JP_MEXT.MATH.1.A.1.a
"""
import json
import re
import sqlite3
import sys
import urllib.request
from datetime import date
from pathlib import Path

import httpx
import pdfplumber

from shared.config import DB_PATH, OLLAMA_BASE_URL

SYSTEM = "jp-mext"
SOURCE_URL = "https://www.mext.go.jp/component/english/__icsFiles/afieldfile/2011/03/17/1303755_004.pdf"
VERIFIED_DATE = date.today().isoformat()
RAW_DIR = DB_PATH.parent / "raw" / "japan"

OLLAMA_MODEL = "gemma4:31b-it-q8_0"

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each",
    "such", "both", "also", "into", "more", "most", "some", "other",
    "these", "those", "about", "able", "after", "where", "while", "make",
    "used", "given", "find", "show", "know", "understand", "apply",
}

STRAND_NAMES = {
    "A": "Numbers and Calculations",
    "B": "Quantities and Measurements",
    "C": "Geometrical Figures",
    "D": "Mathematical Relations",
}

EXTRACT_PROMPT = """\
Extract all math learning objectives from this Japan MEXT Course of Study syllabus text for Grade {grade}.

The structure is:
  A/B/C/D. Strand name
    (1) Topic description
      a. Leaf objective
      b. Leaf objective
    (2) Another topic
      ...

Return ONLY a JSON array (no other text, no markdown). Each element must have:
  "strand"      : strand letter (A, B, C, or D)
  "strand_name" : full strand name (e.g. "Numbers and Calculations")
  "topic_num"   : topic number as string (e.g. "1", "2", "3")
  "topic_text"  : full text of the topic-level description (the numbered (1)(2) item)
  "obj_letter"  : objective letter (a, b, c, d, ...) — empty string if the topic has no sub-items
  "obj_text"    : full text of the leaf objective (the lettered sub-item); if no sub-items, use the topic_text

Rules:
- Only include leaf-level items (lettered sub-items a/b/c). If a topic has no lettered sub-items, include the topic itself as a single objective with empty obj_letter.
- Do NOT include strand headers or bare topic descriptions without objectives.
- Preserve exact wording from the source.

SYLLABUS TEXT FOR GRADE {grade}:
{text}
"""


def _download_pdf(pdf_path: Path) -> None:
    print(f"  Downloading {SOURCE_URL} ...")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(SOURCE_URL, pdf_path)
    print(f"  Saved to {pdf_path}")


def _extract_pages(pdf_path: Path) -> list[tuple[int, str]]:
    results = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            if text.strip():
                results.append((i + 1, text))
    return results


def _split_by_grade(pages: list[tuple[int, str]]) -> dict[str, str]:
    """Split pages into per-grade blocks using [Grade N] markers."""
    grade_re = re.compile(r"^\[Grade\s+(\d+)\]", re.IGNORECASE)
    current: str | None = None
    blocks: dict[str, list[str]] = {}

    for _pnum, text in pages:
        for line in text.splitlines():
            m = grade_re.match(line.strip())
            if m:
                current = m.group(1)
                blocks.setdefault(current, [])
        if current:
            blocks.setdefault(current, []).append(text)

    return {g: "\n".join(texts) for g, texts in blocks.items()}


def _call_gemma(grade: str, text: str) -> list[dict]:
    prompt = EXTRACT_PROMPT.format(grade=grade, text=text[:12000])
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

    m = re.search(r"\[.*\]", content, re.DOTALL)
    if not m:
        print(f"    WARN: no JSON array in Gemma response for grade {grade}")
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
    grade: str,
    conn: sqlite3.Connection,
    seen_ids: set[str],
) -> tuple[int, int]:
    std_count = kw_count = 0

    for obj in objectives:
        obj_text = (obj.get("obj_text") or "").strip()
        if not obj_text:
            continue

        strand = (obj.get("strand") or "").strip().upper()
        strand_name = (obj.get("strand_name") or STRAND_NAMES.get(strand, "")).strip()
        topic_num = (obj.get("topic_num") or "").strip()
        obj_letter = (obj.get("obj_letter") or "").strip()

        if not strand or not topic_num:
            continue

        if obj_letter:
            notation = f"{strand}.{topic_num}.{obj_letter}"
        else:
            notation = f"{strand}.{topic_num}"

        std_id = f"JP_MEXT.MATH.{grade}.{notation}"
        if std_id in seen_ids:
            continue
        seen_ids.add(std_id)

        conn.execute(
            """INSERT OR REPLACE INTO standards
               (id, system, subject, grade, grade_band, domain, cluster,
                standard_text, last_verified_date, source_url)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (std_id, SYSTEM, "mathematics", grade, None,
             strand_name, obj.get("topic_text", "").strip(), obj_text,
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


def main() -> None:
    pdf_path = RAW_DIR / "jp_mext_elementary_arithmetic.pdf"
    if not pdf_path.exists():
        _download_pdf(pdf_path)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    print("Extracting Japan MEXT elementary math standards (Grades 1-6)...")
    pages = _extract_pages(pdf_path)
    grade_blocks = _split_by_grade(pages)

    if not grade_blocks:
        print("  WARN: no grade blocks found — check PDF page range")
        conn.close()
        return

    grand_std = grand_kw = 0
    for grade in sorted(grade_blocks.keys(), key=int):
        text = grade_blocks[grade]
        print(f"  grade {grade}: {len(text)} chars → Gemma...", end="", flush=True)
        try:
            objectives = _call_gemma(grade, text)
        except Exception as e:
            print(f" ERROR: {e}")
            continue

        seen_ids: set[str] = set()
        with conn:
            s, k = _ingest_objectives(objectives, grade, conn, seen_ids)
        grand_std += s
        grand_kw += k
        print(f" {len(objectives)} extracted, {s} ingested")

    conn.close()
    print(f"\nTotal: {grand_std} standards, {grand_kw} keywords")
    print("Done.")


if __name__ == "__main__":
    main()
