"""Fetch and ingest South Africa CAPS Social Sciences.

Covered system: za-caps-ss
Sources (CAPS PDFs from education.gov.za):
  Intermediate Phase (Gr 4-6):
    https://www.education.gov.za/Portals/0/CD/National%20Curriculum%20Statements%20and%20Vocational/CAPS%20IP%20%20SOCIAL%20SCIENCES%20GR%204-6%20WEB.pdf
  Senior Phase (Gr 7-9):
    https://www.education.gov.za/Portals/0/CD/National%20Curriculum%20Statements%20and%20Vocational/CAPS%20SP%20%20SOCIAL%20SCIENCES%20GR%207-9%20WEB.pdf
  FET Phase (Gr 10-12):
    https://www.education.gov.za/Portals/0/CD/National%20Curriculum%20Statements%20and%20Vocational/CAPS%20FET%20_%20HISTORY%20GR%2010-12%20WEB.pdf

IDs: ZA_CAPS_SS.SOCIAL_STUDIES.{grade}.{hash}
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

def _norm(text: str) -> str:
    """Some official PDFs (education.gov.za CAPS, ZIMSEC) store glyphs character-reversed
    inside rotated tables. Detect that and reverse each whitespace token back. No-op for
    normal text."""
    import re as _re
    toks = _re.findall(r"[a-z]{2,}", text.lower())
    rev = sum(t in ("eht","dna","rof","era","htiw","ot","fo","srenrael") for t in toks)
    fwd = sum(t in ("the","and","for","are","with","to","of","learners") for t in toks)
    if rev > fwd and rev >= 3:
        return chr(10).join(" ".join(w[::-1] for w in ln.split()) for ln in text.splitlines())
    return text

SYSTEM = "za-caps-ss"
SOURCE_URL = "https://www.education.gov.za/Curriculum/NationalCurriculumStatementsGradesR-12.aspx"
VERIFIED_DATE = date.today().isoformat()
RAW_DIR = DB_PATH.parent / "raw" / "southafrica_ss"

PHASES = [
    (
        "ip.pdf",
        "https://sahistory.org.za/sites/default/files/archive-files/caps_gr4-6.pdf",
        ["4", "5", "6"],
        "Intermediate Phase Social Sciences (Grade 4-6)",
    ),
    (
        "fet.pdf",
        "https://www.education.gov.za/Portals/0/CD/National%20Curriculum%20Statements%20and%20Vocational/CAPS%20FET%20%20HISTORY%20GR%2010-12%20%20WEB.pdf",
        ["HS"],
        "FET Phase History (Grade 10-12)",
    ),
    # SP 7-9 Social Sciences: education.gov.za path unresolved — extend when URL confirmed
]

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each",
    "such", "both", "also", "into", "more", "most", "some", "other",
    "these", "those", "about", "able", "after", "where", "while", "make",
    "used", "given", "find", "show", "know", "understand", "apply",
}

EXTRACT_PROMPT = """\
Extract all social sciences learning objectives from this South Africa CAPS curriculum text for Grade {grade_label}.

The CAPS document organises social sciences into:
- Themes or topics (e.g. "People and their communities", "Our countries", "Historical events", "Geography and map skills")
- Subtopics or focus areas
- Specific learning outcomes, skills, or competencies

Return ONLY a JSON array (no other text, no markdown). Each element must have:
  "theme"        : theme or topic area (e.g. "South Africa and its surroundings", "Historical processes")
  "subtopic"     : subtopic or focus
  "grade"        : grade as string (e.g. "4", "9", "HS")
  "obj_text"     : full text of the learning outcome

Rules:
- Extract every specific learning outcome, competency, or skill.
- Do NOT include time allocations, assessment notes, or general phase descriptions.
- Preserve exact wording.

CAPS SOCIAL SCIENCES TEXT (Grade {grade_label}):
{text}
"""


def _download_pdf(url: str, path: Path) -> None:
    print(f"  Downloading {url} ...")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    _req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(_req, timeout=60) as _r, open(path, "wb") as _f:
        _f.write(_r.read())
    print(f"  Saved: {path.stat().st_size:,} bytes")


def _extract_pages(pdf_path: Path) -> list[tuple[int, str]]:
    results = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = _norm(page.extract_text() or "")
            if text.strip():
                results.append((i + 1, text))
    return results


def _call_gemma(text: str, grade_label: str) -> list[dict]:
    prompt = EXTRACT_PROMPT.format(grade_label=grade_label, text=text[:12000])
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


def _ingest(objectives: list[dict], grades: list[str], conn: sqlite3.Connection, seen_ids: set[str]) -> tuple[int, int]:
    std_count = kw_count = 0
    for obj in objectives:
        obj_text = (obj.get("obj_text") or "").strip()
        if not obj_text:
            continue
        theme = (obj.get("theme") or "").strip()
        subtopic = (obj.get("subtopic") or "").strip()

        for grade in grades:
            std_id = f"ZA_CAPS_SS.SOCIAL_STUDIES.{grade}.{abs(hash(obj_text[:40])) % 100000}"
            if std_id in seen_ids:
                continue
            seen_ids.add(std_id)

            grade_band = "9-12" if grade == "HS" else None
            conn.execute(
                """INSERT OR REPLACE INTO standards
                   (id, system, subject, grade, grade_band, domain, cluster,
                    standard_text, last_verified_date, source_url)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (std_id, SYSTEM, "social-studies", grade, grade_band,
                 theme, subtopic, obj_text, VERIFIED_DATE, SOURCE_URL),
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

    print("Extracting South Africa CAPS Social Sciences standards...")
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
                s, k = _ingest(objectives, grades, conn, seen_ids)
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
