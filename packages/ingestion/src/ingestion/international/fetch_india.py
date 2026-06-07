"""Fetch and ingest India NCERT Mathematics syllabus standards.

Covered system: in-ncert
Sources (NCERT syllabus PDFs):
  - Classes I-V:    https://ncert.nic.in/pdf/syllabus/06Math%20(I-V).pdf
  - Classes VI-VIII: https://ncert.nic.in/pdf/syllabus/07Math%20(VI-VIII).pdf
  - Classes IX-XII:  https://ncert.nic.in/pdf/syllabus/05%20Mathmetics%20(class%20IX-XII).pdf

Grade mapping: Class I → grade 1, ... Class XII → grade HS (11/12)
IDs: IN_NCERT.MATH.{grade}.{hash}
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

SYSTEM = "in-ncert"
SOURCE_URL = "https://ncert.nic.in/syllabus.php?ln=en"
VERIFIED_DATE = date.today().isoformat()
RAW_DIR = DB_PATH.parent / "raw" / "india"
OLLAMA_MODEL = "gemma4:31b-it-q8_0"

PDFS = [
    ("classes_1_5.pdf",  "https://ncert.nic.in/pdf/syllabus/06Math%20(I-V).pdf",   ["1","2","3","4","5"]),
    ("classes_6_8.pdf",  "https://ncert.nic.in/pdf/syllabus/07Math%20(VI-VIII).pdf", ["6","7","8"]),
    ("classes_9_12.pdf", "https://ncert.nic.in/pdf/syllabus/05%20Mathmetics%20(class%20IX-XII).pdf", ["9","10","HS"]),
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
Extract all mathematics learning objectives from this India NCERT syllabus text for Class {grade_label}.

The syllabus is organised into units/topics. Under each topic there are numbered learning objectives or "learning outcomes."

Return ONLY a JSON array (no other text, no markdown). Each element must have:
  "unit"       : unit or topic name (e.g. "Number System", "Algebra", "Geometry")
  "sub_topic"  : sub-topic if present (e.g. "Rational Numbers", "Linear Equations")
  "obj_text"   : full text of the learning objective or expected learning outcome

Rules:
- Extract every individual learning objective/outcome.
- Include objectives stated as "Students will be able to...", "Consolidate...", numbered items, or bullet points.
- Do NOT include time allotments, unit introductions, or assessment guidelines.
- Preserve exact wording.

NCERT SYLLABUS TEXT (Class {grade_label}):
{text}
"""


def _download_pdf(url: str, path: Path) -> bool:
    """Return True if download succeeded, False otherwise."""
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


def _extract_pages(pdf_path: Path) -> list[tuple[int, str]]:
    results = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            if text.strip():
                results.append((i + 1, text))
    return results


def _split_by_class(pages: list[tuple[int, str]], expected_grades: list[str]) -> dict[str, str]:
    """Split PDF text by class/grade section headers."""
    class_re = re.compile(
        r"^\s*class(?:es)?\s+(i{1,3}v?|vi{0,3}|ix|x{1,2}i{0,2}|\d{1,2})\b",
        re.IGNORECASE,
    )
    current: str | None = None
    blocks: dict[str, list[str]] = {}

    for _pnum, text in pages:
        for line in text.splitlines():
            m = class_re.match(line.strip())
            if m:
                raw = m.group(1).lower()
                grade = CLASS_TO_GRADE.get(raw)
                if grade:
                    current = grade
                    blocks.setdefault(current, [])
        if current:
            blocks.setdefault(current, []).append(text)

    return {g: "\n".join(texts) for g, texts in blocks.items()}


def _call_gemma(grade: str, grade_label: str, text: str) -> list[dict]:
    prompt = EXTRACT_PROMPT.format(grade_label=grade_label, text=text[:4000])
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
        print(f"    WARN: no JSON for grade {grade}")
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


def _ingest_objectives(objectives: list[dict], grade: str, conn: sqlite3.Connection, seen_ids: set[str]) -> tuple[int, int]:
    std_count = kw_count = 0
    grade_band = "9-12" if grade == "HS" else None

    for obj in objectives:
        obj_text = (obj.get("obj_text") or "").strip()
        if not obj_text:
            continue
        unit = (obj.get("unit") or "").strip()
        sub_topic = (obj.get("sub_topic") or "").strip()

        std_id = f"IN_NCERT.MATH.{grade}.{abs(hash(obj_text[:40])) % 100000}"
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
            conn.execute("INSERT OR IGNORE INTO keywords (standard_id, keyword) VALUES (?,?)", (std_id, kw))
            kw_count += 1

    return std_count, kw_count


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    print("Extracting India NCERT Mathematics standards...")
    grand_std = grand_kw = 0
    seen_ids: set[str] = set()

    grade_labels = {
        "1": "I", "2": "II", "3": "III", "4": "IV", "5": "V",
        "6": "VI", "7": "VII", "8": "VIII", "9": "IX", "10": "X",
        "HS": "XI-XII",
    }

    for fname, url, expected_grades in PDFS:
        pdf_path = RAW_DIR / fname
        if not pdf_path.exists():
            ok = _download_pdf(url, pdf_path)
            if not ok:
                print(f"  SKIP {fname} — ncert.nic.in blocked automated download.")
                print(f"  Manual steps:")
                print(f"    1. Open {url} in a browser")
                print(f"    2. Save the PDF as {pdf_path}")
                continue

        pages = _extract_pages(pdf_path)
        grade_blocks = _split_by_class(pages, expected_grades)

        if not grade_blocks:
            print(f"  WARN: no grade blocks in {fname} — processing whole PDF")
            all_text = "\n".join(t for _, t in pages)
            grade_blocks = {expected_grades[0]: all_text}

        for grade in expected_grades:
            text = grade_blocks.get(grade, "")
            if not text:
                print(f"  grade {grade}: not found in {fname}, skipping")
                continue
            label = grade_labels.get(grade, grade)
            print(f"  grade {grade} (Class {label}): {len(text)} chars → Gemma...", end="", flush=True)
            try:
                objectives = _call_gemma(grade, label, text)
            except Exception as e:
                print(f" ERROR: {e}")
                continue
            with conn:
                s, k = _ingest_objectives(objectives, grade, conn, seen_ids)
            grand_std += s
            grand_kw += k
            print(f" {len(objectives)} extracted, {s} ingested")
            time.sleep(0.5)

    conn.close()
    print(f"\nTotal: {grand_std} standards, {grand_kw} keywords")
    print("Done.")


if __name__ == "__main__":
    main()
