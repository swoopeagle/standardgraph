"""Fetch and ingest Hong Kong EDB Mathematics curriculum standards.

Covered system: hk-edb
Sources:
  - Mathematics Education Key Learning Area Curriculum Guide (Primary 1 - Secondary 3)
    https://www.edb.gov.hk/attachment/en/curriculum-development/kla/ma/curr/ME_KLACG_eng_2017_12_08.pdf

Key Stages:
  KS1: Primary 1-3  (Grades 1-3)
  KS2: Primary 4-6  (Grades 4-6)
  KS3: Secondary 1-3 (Grades 7-9)

IDs: HK_EDB.MATH.{grade}.{hash}
"""
import json
import re
import sqlite3
import urllib.request
from datetime import date
from pathlib import Path

import httpx
import pdfplumber

from shared.config import DB_PATH, OLLAMA_BASE_URL

SYSTEM = "hk-edb"
SOURCE_URL = "https://www.edb.gov.hk/en/curriculum-development/kla/ma/curr/index2.html"
PDF_URL = "https://www.edb.gov.hk/attachment/en/curriculum-development/kla/ma/curr/ME_KLACG_eng_2017_12_08.pdf"
VERIFIED_DATE = date.today().isoformat()
RAW_DIR = DB_PATH.parent / "raw" / "hongkong"
OLLAMA_MODEL = "gemma4:31b-it-q8_0"

KEY_STAGES = [
    ("KS1", ["1", "2", "3"], "Primary 1-3"),
    ("KS2", ["4", "5", "6"], "Primary 4-6"),
    ("KS3", ["7", "8", "9"], "Secondary 1-3"),
]

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each",
    "such", "both", "also", "into", "more", "most", "some", "other",
    "these", "those", "about", "able", "after", "where", "while", "make",
    "used", "given", "find", "show", "know", "understand", "apply",
}

EXTRACT_PROMPT = """\
Extract all mathematics learning objectives from this Hong Kong EDB curriculum guide.

Key Stage: {ks} ({ks_desc})

The guide organises learning objectives by:
- Number and Algebra Strand
- Measures, Shape and Space Strand
- Data Handling Strand

Learning objectives are numbered (e.g. N1, N2, A1, M1, S1, D1) or listed as bullet points under a topic.

Return ONLY a JSON array (no other text, no markdown). Each element must have:
  "strand"     : strand name (e.g. "Number and Algebra", "Measures Shape and Space", "Data Handling")
  "topic"      : topic or sub-topic name (e.g. "Whole Numbers", "Fractions", "Perimeter")
  "grade"      : which primary/secondary year this objective is for (e.g. "1", "2", "4", "7") — use "KS1", "KS2", or "KS3" if grade is not specified
  "obj_code"   : objective code if present (e.g. "N1", "A2"); empty string if none
  "obj_text"   : full text of the learning objective

Rules:
- Extract every learning objective listed under {ks}.
- Do NOT include explanatory notes, teacher guidance, or assessment notes.
- Preserve exact wording.

CURRICULUM TEXT ({ks}):
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


def _split_by_ks(pages: list[tuple[int, str]]) -> dict[str, str]:
    """Split pages by Key Stage header."""
    ks_re = re.compile(r"\bkey\s+stage\s+([123])\b", re.IGNORECASE)
    current: str | None = None
    blocks: dict[str, list[str]] = {}

    for _pnum, text in pages:
        m = ks_re.search(text[:200])  # Check start of page
        if m:
            current = f"KS{m.group(1)}"
            blocks.setdefault(current, [])
        if current:
            blocks.setdefault(current, []).append(text)

    return {k: "\n".join(v) for k, v in blocks.items()}


def _call_gemma(ks: str, ks_desc: str, text: str) -> list[dict]:
    prompt = EXTRACT_PROMPT.format(ks=ks, ks_desc=ks_desc, text=text[:4000])
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
        print(f"    WARN: no JSON for {ks}")
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


def _ingest_objectives(objectives: list[dict], ks: str, conn: sqlite3.Connection, seen_ids: set[str]) -> tuple[int, int]:
    std_count = kw_count = 0
    ks_grade_map = {"KS1": "1", "KS2": "4", "KS3": "7"}

    for obj in objectives:
        obj_text = (obj.get("obj_text") or "").strip()
        if not obj_text:
            continue
        strand = (obj.get("strand") or "").strip()
        topic = (obj.get("topic") or "").strip()
        obj_code = (obj.get("obj_code") or "").strip()
        raw_grade = str(obj.get("grade") or "").strip()
        grade = raw_grade if raw_grade in [str(i) for i in range(1, 13)] else ks_grade_map.get(ks, "1")

        if obj_code:
            std_id = f"HK_EDB.MATH.{grade}.{obj_code}"
        else:
            std_id = f"HK_EDB.MATH.{grade}.{abs(hash(obj_text[:40])) % 100000}"

        if std_id in seen_ids:
            continue
        seen_ids.add(std_id)

        conn.execute(
            """INSERT OR REPLACE INTO standards
               (id, system, subject, grade, grade_band, domain, cluster,
                standard_text, last_verified_date, source_url)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (std_id, SYSTEM, "mathematics", grade, None,
             strand, topic, obj_text, VERIFIED_DATE, SOURCE_URL),
        )
        std_count += 1
        for kw in _extract_keywords(obj_text):
            conn.execute("INSERT OR IGNORE INTO keywords (standard_id, keyword) VALUES (?,?)", (std_id, kw))
            kw_count += 1

    return std_count, kw_count


def main() -> None:
    pdf_path = RAW_DIR / "hk_edb_maths_curriculum_guide.pdf"
    if not pdf_path.exists():
        _download_pdf(pdf_path)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    print("Extracting Hong Kong EDB Mathematics curriculum (KS1-KS3)...")
    pages = _extract_pages(pdf_path)
    ks_blocks = _split_by_ks(pages)
    print(f"  Key stages found: {list(ks_blocks.keys())}")

    grand_std = grand_kw = 0
    seen_ids: set[str] = set()

    for ks, grades, ks_desc in KEY_STAGES:
        text = ks_blocks.get(ks, "")
        if not text:
            print(f"  {ks}: not found in PDF structure — sending full document")
            text = "\n".join(t for _, t in pages)
        print(f"  {ks}: {len(text)} chars → Gemma...", end="", flush=True)
        try:
            objectives = _call_gemma(ks, ks_desc, text)
        except Exception as e:
            print(f" ERROR: {e}")
            continue
        with conn:
            s, k = _ingest_objectives(objectives, ks, conn, seen_ids)
        grand_std += s
        grand_kw += k
        print(f" {len(objectives)} extracted, {s} ingested")

    conn.close()
    print(f"\nTotal: {grand_std} standards, {grand_kw} keywords")
    print("Done.")


if __name__ == "__main__":
    main()
