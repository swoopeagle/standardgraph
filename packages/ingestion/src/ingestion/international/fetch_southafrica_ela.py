"""Fetch and ingest South Africa CAPS English Home Language (ELA).

Covered system: za-caps-ela
Sources (CAPS PDFs from education.gov.za):
  Intermediate Phase (Gr 4-6):
    https://www.education.gov.za/Portals/0/CD/National%20Curriculum%20Statements%20and%20Vocational/CAPS%20IP%20%20HOME%20ENGLISH%20GR%204-6%20%20WEB.pdf
  Senior Phase (Gr 7-9):
    https://www.education.gov.za/Portals/0/Documents/HOME%20LANGUAGE%20Sen.pdf
  FET Phase (Gr 10-12):
    https://www.education.gov.za/Portals/0/CD/National%20Curriculum%20Statements%20and%20Vocational/CAPS%20FET%20_%20HOME%20_%20ENGLISH%20GR%2010-12%20_%20WEB_5478.pdf

IDs: ZA_CAPS_ELA.ELA.{grade}.{hash}
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

SYSTEM = "za-caps-ela"
SOURCE_URL = "https://www.education.gov.za/Curriculum/NationalCurriculumStatementsGradesR-12.aspx"
VERIFIED_DATE = date.today().isoformat()
RAW_DIR = DB_PATH.parent / "raw" / "southafrica_ela"

PHASES = [
    (
        "ip.pdf",
        "https://www.education.gov.za/Portals/0/CD/National%20Curriculum%20Statements%20and%20Vocational/CAPS%20IP%20%20HOME%20ENGLISH%20GR%204-6%20%20WEB.pdf",
        ["4", "5", "6"],
        "Intermediate Phase (Grade 4-6)",
    ),
    (
        "sp.pdf",
        "https://www.education.gov.za/Portals/0/Documents/HOME%20LANGUAGE%20Sen.pdf",
        ["7", "8", "9"],
        "Senior Phase (Grade 7-9)",
    ),
    (
        "fet.pdf",
        "https://www.education.gov.za/Portals/0/CD/National%20Curriculum%20Statements%20and%20Vocational/CAPS%20FET%20_%20HOME%20_%20ENGLISH%20GR%2010-12%20_%20WEB_5478.pdf",
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
Extract all English Home Language learning objectives from this South Africa CAPS curriculum text for Grade {grade_label}.

The CAPS document organises ELA into:
- Strands or focus areas (e.g. "Listening", "Speaking", "Reading", "Writing", "Language structures")
- Topics or skills within each strand
- Specific learning objectives or competencies

Return ONLY a JSON array (no other text, no markdown). Each element must have:
  "strand"       : strand or focus area (e.g. "Reading and Viewing", "Writing and Presenting")
  "topic"        : topic or skill
  "grade"        : grade as string (e.g. "4", "9", "HS")
  "obj_text"     : full text of the learning objective

Rules:
- Extract every specific learning objective, skill, or competency.
- Do NOT include time allocations, assessment notes, or general phase descriptions.
- Preserve exact wording.

CAPS ELA TEXT (Grade {grade_label}):
{text}
"""


def _download_pdf(url: str, path: Path) -> None:
    print(f"  Downloading {url} ...")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, path, timeout=30)
    print(f"  Saved: {path.stat().st_size:,} bytes")


def _extract_pages(pdf_path: Path) -> list[tuple[int, str]]:
    results = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            if text.strip():
                results.append((i + 1, text))
    return results


def _call_gemma(text: str, grade_label: str) -> list[dict]:
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


def _ingest(objectives: list[dict], default_grade: str, conn: sqlite3.Connection, seen_ids: set[str]) -> tuple[int, int]:
    std_count = kw_count = 0
    grade_band = "9-12" if default_grade == "HS" else None

    for obj in objectives:
        obj_text = (obj.get("obj_text") or "").strip()
        if not obj_text:
            continue
        strand = (obj.get("strand") or "").strip()
        topic = (obj.get("topic") or "").strip()
        grade = str(obj.get("grade") or default_grade).strip()

        std_id = f"ZA_CAPS_ELA.ELA.{grade}.{abs(hash(obj_text[:40])) % 100000}"
        if std_id in seen_ids:
            continue
        seen_ids.add(std_id)

        conn.execute(
            """INSERT OR REPLACE INTO standards
               (id, system, subject, grade, grade_band, domain, cluster,
                standard_text, last_verified_date, source_url)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (std_id, SYSTEM, "ela", grade, grade_band,
             strand, topic, obj_text, VERIFIED_DATE, SOURCE_URL),
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

    print("Extracting South Africa CAPS English Home Language standards...")
    grand_std = grand_kw = 0
    seen_ids: set[str] = set()

    for fname, url, grades, phase_label in PHASES:
        pdf_path = RAW_DIR / fname
        if not pdf_path.exists():
            try:
                _download_pdf(url, pdf_path)
            except Exception as e:
                print(f"  WARN: failed to download {phase_label}: {e}, skipping")
                continue

        pages = _extract_pages(pdf_path)
        if not pages:
            print(f"  WARN: no pages extracted from {phase_label}")
            continue

        print(f"\n  {phase_label}: {len(pages)} content pages")
        phase_std = phase_kw = 0

        chunk_size = 4
        for i in range(0, len(pages), chunk_size):
            chunk = pages[i:i + chunk_size]
            chunk_text = "\n\n".join(t for _, t in chunk)
            page_nums = f"{chunk[0][0]}-{chunk[-1][0]}"
            print(f"    pages {page_nums}: {len(chunk_text)} chars → Gemma...", end="", flush=True)
            try:
                objectives = _call_gemma(chunk_text, grades[0])
            except Exception as e:
                print(f" ERROR: {e}")
                continue

            with conn:
                s, k = _ingest(objectives, grades[0], conn, seen_ids)
            phase_std += s
            phase_kw += k
            print(f" {len(objectives)} extracted, {s} ingested")

        print(f"  {phase_label} total: {phase_std} standards, {phase_kw} keywords")
        grand_std += phase_std
        grand_kw += phase_kw

    conn.close()
    print(f"\nTotal: {grand_std} standards, {grand_kw} keywords")
    print("Done.")


if __name__ == "__main__":
    main()
