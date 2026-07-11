"""Fetch and ingest South Africa CAPS Mathematics standards.

Covered system: za-caps
Sources (CAPS PDFs from education.gov.za):
  Foundation Phase (Gr R-3):
    https://www.education.gov.za/Portals/0/CD/National%20Curriculum%20Statements%20and%20Vocational/CAPS%20MATHS%20%20ENGLISH%20GR%201-3%20FS.pdf
  Intermediate Phase (Gr 4-6):
    https://www.education.gov.za/Portals/0/CD/National%20Curriculum%20Statements%20and%20Vocational/CAPS%20IP%20%20MATHEMATICS%20GR%204-6%20web.pdf
  Senior Phase (Gr 7-9):
    https://www.education.gov.za/Portals/0/CD/National%20Curriculum%20Statements%20and%20Vocational/CAPS%20SP%20%20MATHEMATICS%20GR%207-9.pdf
  FET Phase (Gr 10-12):
    https://www.education.gov.za/portals/0/documents/policies/caps/final%20maths%2010%2011%2012%20%20september%202010.pdf

Grade R is mapped to grade "K" (Reception/Kindergarten).
IDs: ZA_CAPS.MATH.{grade}.{hash}
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

SYSTEM = "za-caps"
SOURCE_URL = "https://www.education.gov.za/Curriculum/NationalCurriculumStatementsGradesR-12.aspx"
VERIFIED_DATE = date.today().isoformat()
RAW_DIR = DB_PATH.parent / "raw" / "southafrica"

PHASES = [
    (
        "foundation.pdf",
        "https://www.education.gov.za/Portals/0/CD/National%20Curriculum%20Statements%20and%20Vocational/CAPS%20MATHS%20%20ENGLISH%20GR%201-3%20FS.pdf",
        ["K", "1", "2", "3"],
        "Foundation Phase (Grade R-3)",
    ),
    (
        "intermediate.pdf",
        "https://www.education.gov.za/Portals/0/CD/National%20Curriculum%20Statements%20and%20Vocational/CAPS%20IP%20%20MATHEMATICS%20GR%204-6%20web.pdf",
        ["4", "5", "6"],
        "Intermediate Phase (Grade 4-6)",
    ),
    (
        "senior.pdf",
        "https://www.education.gov.za/Portals/0/CD/National%20Curriculum%20Statements%20and%20Vocational/CAPS%20SP%20%20MATHEMATICS%20GR%207-9.pdf",
        ["7", "8", "9"],
        "Senior Phase (Grade 7-9)",
    ),
    (
        "fet.pdf",
        "https://www.education.gov.za/portals/0/documents/policies/caps/final%20maths%2010%2011%2012%20%20september%202010.pdf",
        ["HS"],
        "FET Phase (Grade 10-12)",
    ),
]

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each",
    "such", "both", "also", "into", "more", "most", "some", "other",
    "these", "those", "about", "able", "after", "where", "while", "make",
    "used", "given", "find", "show", "know", "understand", "apply",
}

EXTRACT_PROMPT = """\
Extract ALL mathematics skills, concepts, and learning objectives from this South Africa CAPS curriculum text for Grade {grade_label}.

The CAPS document organises content into:
- Content areas (e.g. "Numbers, Operations and Relationships", "Patterns, Functions and Algebra", "Space and Shape (Geometry)", "Measurement", "Data Handling")
- Topics within each content area
- Specific skills/concepts listed as bullet points or numbered items

You MUST extract EVERY single listed skill and concept, even if there are many.

Return ONLY a JSON array (no other text, no markdown). Each element must have:
  "content_area" : content area name (e.g. "Numbers Operations and Relationships")
  "topic"        : topic or sub-topic name
  "grade"        : grade as string (e.g. "1", "7", "K" for Grade R)
  "obj_text"     : full text of the learning objective or skill

Rules:
- Extract EVERY specific skill, concept, or learning objective listed — do not skip or summarize.
- Include single-word concepts, short phrases, and full sentences.
- Do NOT include time allocations, assessment notes, or general phase descriptions.
- Preserve exact wording.

CAPS MATHEMATICS TEXT (Grade {grade_label}):
{text}
"""


def _download_pdf(url: str, path: Path) -> None:
    print(f"  Downloading {url} ...")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, path)
    print(f"  Saved: {path.stat().st_size} bytes")


def _extract_pages(pdf_path: Path) -> list[tuple[int, str]]:
    results = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            if text.strip():
                results.append((i + 1, text))
    return results


def _split_by_grade(pages: list[tuple[int, str]], expected: list[str]) -> dict[str, str]:
    """Split by Grade N header."""
    grade_re = re.compile(r"^\s*grade\s+(r|\d{1,2})\b", re.IGNORECASE)
    current: str | None = None
    blocks: dict[str, list[str]] = {}

    for _pnum, text in pages:
        for line in text.splitlines():
            m = grade_re.match(line.strip())
            if m:
                raw = m.group(1).lower()
                if raw == "r":
                    current = "K"
                else:
                    current = str(int(raw))
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


def _ingest_objectives(objectives: list[dict], default_grade: str, conn: sqlite3.Connection, seen_ids: set[str]) -> tuple[int, int]:
    std_count = kw_count = 0
    grade_band = "9-12" if default_grade == "HS" else None

    for obj in objectives:
        obj_text = (obj.get("obj_text") or "").strip()
        if not obj_text:
            continue
        content_area = (obj.get("content_area") or "").strip()
        topic = (obj.get("topic") or "").strip()
        raw_grade = str(obj.get("grade") or default_grade).strip()
        grade = raw_grade if raw_grade else default_grade

        std_id = f"ZA_CAPS.MATH.{grade}.{abs(hash(obj_text[:40])) % 100000}"
        if std_id in seen_ids:
            continue
        seen_ids.add(std_id)

        conn.execute(
            """INSERT OR REPLACE INTO standards
               (id, system, subject, grade, grade_band, domain, cluster,
                standard_text, last_verified_date, source_url)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (std_id, SYSTEM, "mathematics", grade, grade_band,
             content_area, topic, obj_text, VERIFIED_DATE, SOURCE_URL),
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

    print("Extracting South Africa CAPS Mathematics standards...")
    grand_std = grand_kw = 0
    seen_ids: set[str] = set()

    for fname, url, expected_grades, phase_label in PHASES:
        pdf_path = RAW_DIR / fname
        if not pdf_path.exists():
            _download_pdf(url, pdf_path)

        pages = _extract_pages(pdf_path)
        grade_blocks = _split_by_grade(pages, expected_grades)

        if not grade_blocks:
            print(f"  WARN: no grade splits in {phase_label} — processing whole PDF")
            all_text = "\n".join(t for _, t in pages)
            grade_blocks = {expected_grades[0]: all_text}

        for grade in expected_grades:
            text = grade_blocks.get(grade, "")
            if not text:
                print(f"  grade {grade}: not found in {phase_label}, skipping")
                continue
            label = "R" if grade == "K" else grade
            print(f"  grade {grade} (Grade {label}): {len(text)} chars → Gemma...", end="", flush=True)
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

    conn.close()
    print(f"\nTotal: {grand_std} standards, {grand_kw} keywords")
    print("Done.")


if __name__ == "__main__":
    main()
