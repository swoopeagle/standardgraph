"""Fetch and ingest India NCERT Mathematics syllabus standards.

Covered system: in-ncert
Sources (NCERT syllabus PDFs):
  - Classes I-V:    https://ncert.nic.in/pdf/syllabus/06Math%20(I-V).pdf
  - Classes VI-VIII: https://ncert.nic.in/pdf/syllabus/07Math%20(VI-VIII).pdf
  - Classes IX-XII:  https://ncert.nic.in/pdf/syllabus/05%20Mathmetics%20(class%20IX-XII).pdf

The PDFs use a 3-column table layout (VI/VII/VIII side-by-side) or continuous unit-based
text (IX-XII), so we process them in page chunks and ask Gemma to identify the grade.

Grade mapping: Class I → grade 1, ... Class XII → grade HS (11/12)
IDs: IN_NCERT.MATH.{grade}.{hash}
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

SYSTEM = "in-ncert"
SOURCE_URL = "https://ncert.nic.in/syllabus.php?ln=en"
VERIFIED_DATE = date.today().isoformat()
RAW_DIR = DB_PATH.parent / "raw" / "india"

PDFS = [
    ("classes_1_5.pdf",  "https://ncert.nic.in/pdf/syllabus/06Math%20(I-V).pdf"),
    ("classes_6_8.pdf",  "https://ncert.nic.in/pdf/syllabus/07Math%20(VI-VIII).pdf"),
    ("classes_9_12.pdf", "https://ncert.nic.in/pdf/syllabus/05%20Mathmetics%20(class%20IX-XII).pdf"),
]

CLASS_TO_GRADE: dict[str, str] = {
    "i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5",
    "vi": "6", "vii": "7", "viii": "8", "ix": "9", "x": "10",
    "xi": "HS", "xii": "HS",
    "1": "1", "2": "2", "3": "3", "4": "4", "5": "5",
    "6": "6", "7": "7", "8": "8", "9": "9", "10": "10",
    "11": "HS", "12": "HS",
}

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each",
    "such", "both", "also", "into", "more", "most", "some", "other",
    "these", "those", "about", "able", "after", "where", "while", "make",
    "used", "given", "find", "show", "know", "understand", "apply",
}

EXTRACT_PROMPT = """\
Extract all mathematics content learning objectives from this NCERT syllabus excerpt.

The text may cover multiple classes (I through XII). For each objective, identify which class it belongs to.

Return ONLY a JSON array (no other text, no markdown). Each element must have:
  "class"      : class number as Arabic numeral string — "1","2",...,"10","11","12"
                 (Roman numerals I=1, II=2, III=3, IV=4, V=5, VI=6, VII=7, VIII=8, IX=9, X=10, XI=11, XII=12)
  "unit"       : unit or topic name (e.g. "Number System", "Algebra", "Geometry")
  "sub_topic"  : sub-topic if present (e.g. "Rational Numbers", "Linear Equations"); empty string if none
  "obj_text"   : full text of the content learning objective

Rules:
- Extract CONTENT STANDARDS only — specific mathematical topics, concepts, or skills students will learn.
- SKIP these: general pedagogical goals ("develop a sense of estimation"), time allotments ("60 hrs"),
  assessment instructions, and document preamble text.
- A valid objective describes specific mathematical content, e.g. "Understand HCF and LCM using prime factorisation".
- If the text is a multi-column table (Class VI / Class VII / Class VIII), extract from all columns.
- Preserve exact wording. Do not paraphrase.

SYLLABUS TEXT:
{text}
"""

PAGES_PER_CHUNK = 3


def _download_pdf(url: str, path: Path) -> bool:
    print(f"  Downloading {url} ...")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as r, open(path, "wb") as f:
            f.write(r.read())
        print(f"  Saved: {path.stat().st_size:,} bytes")
        return True
    except Exception as e:
        print(f"  Download failed: {e}")
        if path.exists():
            path.unlink()
        return False


def _extract_pages(pdf_path: Path) -> list[str]:
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if text.strip():
                pages.append(text)
    return pages


def _call_gemma(text: str) -> list[dict]:
    prompt = EXTRACT_PROMPT.format(text=text[:8000])
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


def _ingest_objectives(
    objectives: list[dict], conn: sqlite3.Connection, seen_ids: set[str]
) -> tuple[int, int]:
    std_count = kw_count = 0

    for obj in objectives:
        obj_text = (obj.get("obj_text") or "").strip()
        if not obj_text or len(obj_text) < 15:
            continue

        raw_class = str(obj.get("class") or "").strip().lower()
        grade = CLASS_TO_GRADE.get(raw_class)
        if not grade:
            continue

        unit = (obj.get("unit") or "General").strip()
        sub_topic = (obj.get("sub_topic") or "").strip()
        grade_band = "9-12" if grade == "HS" else None

        std_id = f"IN_NCERT.MATH.{grade}.{abs(hash(obj_text[:60])) % 100000}"
        if std_id in seen_ids:
            continue
        seen_ids.add(std_id)

        conn.execute(
            """INSERT OR REPLACE INTO standards
               (id, system, subject, grade, grade_band, domain, cluster,
                standard_text, last_verified_date, source_url)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (std_id, SYSTEM, "mathematics", grade, grade_band,
             unit, sub_topic, obj_text, VERIFIED_DATE, SOURCE_URL),
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
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    # Delete existing NCERT standards so we start clean
    with conn:
        deleted = conn.execute("DELETE FROM standards WHERE system=?", (SYSTEM,)).rowcount
    if deleted:
        print(f"  Cleared {deleted} existing {SYSTEM} standards")

    print("Extracting India NCERT Mathematics standards...")
    grand_std = grand_kw = 0
    seen_ids: set[str] = set()

    for fname, url in PDFS:
        pdf_path = RAW_DIR / fname
        if not pdf_path.exists():
            ok = _download_pdf(url, pdf_path)
            if not ok:
                print(f"  SKIP {fname} — ncert.nic.in blocked automated download.")
                print(f"  Manual step: save {url} as {pdf_path}")
                continue

        pages = _extract_pages(pdf_path)
        print(f"  {fname}: {len(pages)} pages → processing in chunks of {PAGES_PER_CHUNK}...")

        chunk_std = 0
        for i in range(0, len(pages), PAGES_PER_CHUNK):
            chunk = "\n\n".join(pages[i : i + PAGES_PER_CHUNK])
            chunk_n = i // PAGES_PER_CHUNK + 1
            try:
                objectives = _call_gemma(chunk)
            except Exception as e:
                print(f"    chunk {chunk_n}: ERROR {e}")
                continue
            with conn:
                s, k = _ingest_objectives(objectives, conn, seen_ids)
            chunk_std += s
            grand_std += s
            grand_kw += k
            print(f"    chunk {chunk_n} (pp {i+1}-{min(i+PAGES_PER_CHUNK, len(pages))}): {len(objectives)} extracted, {s} ingested")

        print(f"  {fname}: {chunk_std} standards ingested")

    conn.close()
    print(f"\nTotal: {grand_std} standards, {grand_kw} keywords")
    print("Done.")


if __name__ == "__main__":
    main()
