"""Fetch and ingest Czech Republic RVP ZV math expected outcomes (Grades 1-9).

System: cz-msmt
Source: Rámcový vzdělávací program pro základní vzdělávání (RVP ZV) 2017
  Framework Educational Programme for Basic Education
  Published by: MŠMT — Czech Ministry of Education

Covers základní vzdělávání (basic education, grades 1-9):
  1. stupeň, 1. období (1st stage, 1st period): exit grade 3 (grades 1-3)
  1. stupeň, 2. období (1st stage, 2nd period): exit grade 5 (grades 4-5)
  2. stupeň (2nd stage): exit grade 9 (grades 6-9)

Standards are "Očekávané výstupy" (expected outcomes), coded M-{exit_grade}-{strand}-{seq:02d}
where:
  exit_grade = 3, 5, or 9
  strand = 1-4 (content strand number)
  seq = sequence number within strand and exit level

Content strands (tematické okruhy):
  Strand 1: Čísla a početní operace / Číslo a proměnná (Numbers and Operations)
  Strand 2: Závislosti, vztahy a práce s daty (Relations, Dependencies, and Data)
  Strand 3: Geometrie v rovině a v prostoru (Geometry)
  Strand 4: Nestandardní aplikační úlohy a problémy (Non-standard Applications)

Note: "Minimální doporučená úroveň" (minimum level, codes with "p" suffix) are
adapted outcomes for students with special needs — these are NOT ingested.
"Učivo" (subject matter) sections describe knowledge content — also NOT ingested.

ID format: CZ_MSMT.MATH.G{exit_grade:02d}.S{strand}.{seq:03d}
  e.g. CZ_MSMT.MATH.G03.S1.001
       CZ_MSMT.MATH.G09.S3.013
"""
import json
import re
import sqlite3
import urllib.request
from datetime import date
from pathlib import Path

import fitz  # PyMuPDF
import httpx

from shared.config import DB_PATH, OLLAMA_BASE_URL, OLLAMA_MODEL

SYSTEM = "cz-msmt"
VERIFIED_DATE = date.today().isoformat()
RAW_DIR = DB_PATH.parent / "raw" / "cz"
PDF_URL = "https://www.msmt.cz/file/43792_1_1/"
PDF_FILE = "cz_rvp_zv.pdf"

# Math section: pages idx 30-37 (inclusive)
MATH_PAGES_START = 30
MATH_PAGES_END = 38  # exclusive

GRADE_MAP = {
    "3": ("3", "1-3"),
    "5": ("5", "4-5"),
    "9": ("9", "6-9"),
}

STRAND_DOMAIN_MAP = {
    "1": "Numbers and Operations",
    "2": "Relations, Dependencies, and Data",
    "3": "Geometry",
    "4": "Non-standard Applications and Problem Solving",
}

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each",
    "such", "both", "also", "into", "more", "most", "some", "other",
    "these", "those", "about", "able", "after", "where", "while", "make",
    "used", "given", "find", "show", "know", "understand", "apply",
    "students", "student", "numbers", "values", "different", "pupil",
}

EXTRACT_PROMPT = """\
Below is the mathematics section from the Czech Republic Framework Educational Programme
for Basic Education (RVP ZV 2017). It covers grades 1-9 with three exit levels.

The EXPECTED OUTCOMES (Očekávané výstupy) are what we want to extract.
They are coded M-{{exit_grade}}-{{strand}}-{{seq:02d}}:
  - exit_grade: 3 (end of grades 1-3), 5 (end of grades 4-5), or 9 (end of grades 6-9)
  - strand: 1 (Numbers), 2 (Relations/Data), 3 (Geometry), 4 (Non-standard)
  - seq: sequential number within that level and strand

IMPORTANT — DO NOT extract:
1. "Minimální doporučená úroveň" outcomes (marked with "p" suffix like M-5-1-02p) — these are
   adapted outcomes for students with special needs. SKIP THEM.
2. Lines starting with "–" or "•" under "Učivo" headings — these are content knowledge, not outcomes.
3. Entries with "-" prefix (after Minimální úroveň) — these are general notes.

Each expected outcome starts with "žák" (pupil/student) and then lists the outcome code
and the Czech description.

Return ONLY a JSON array (no markdown). Each element:
  "code"     : string — exact original code (e.g. "M-3-1-01", "M-9-3-07")
  "exit_grade": integer — 3, 5, or 9
  "strand"   : integer — 1, 2, 3, or 4
  "seq"      : integer — sequence number
  "text_cz"  : Czech text verbatim (the outcome statement, trimmed)
  "text_en"  : accurate English translation

MATHEMATICS SECTION TEXT:
{text}
"""


def _download(url: str, path: Path) -> None:
    print(f"  Downloading {path.name} …")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(path, "wb") as f:
        f.write(r.read())
    print(f"  Saved {path.stat().st_size:,} bytes")


def _extract_math_text(pdf_path: Path) -> str:
    doc = fitz.open(str(pdf_path))
    parts = []
    for i in range(MATH_PAGES_START, min(MATH_PAGES_END, doc.page_count)):
        t = doc[i].get_text().strip()
        # Remove running header lines
        t = re.sub(r'^Část C\s*\n', '', t)
        t = re.sub(r'^Rámcový vzdělávací program.*?\n', '', t)
        t = re.sub(r'^MŠMT Praha \d+\s*\n', '', t)
        t = re.sub(r'^\s*\d+\s*\n', '', t)  # page number
        if t.strip():
            parts.append(t.strip())
    doc.close()
    return "\n\n".join(parts)


def _call_model(text: str) -> list[dict]:
    prompt = EXTRACT_PROMPT.format(text=text[:14000])
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "keep_alive": "4h",
        "options": {"temperature": 0.0, "num_ctx": 16384},
    }
    resp = httpx.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload, timeout=1800)
    resp.raise_for_status()
    content = resp.json()["message"]["content"].strip()
    content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.MULTILINE)
    content = re.sub(r"\s*```$", "", content, flags=re.MULTILINE)
    m = re.search(r"\[.*\]", content, re.DOTALL)
    if not m:
        return []
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as e:
        print(f"    WARN JSON: {e}")
        return []


def _extract_keywords(text: str) -> list[str]:
    words = re.findall(r'\b[a-zA-Z][a-zA-Z-]{3,}\b', text.lower())
    seen: set[str] = set()
    result = []
    for w in words:
        if w not in STOP_WORDS and w not in seen:
            seen.add(w)
            result.append(w)
    return result[:20]


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = RAW_DIR / PDF_FILE

    if pdf_path.exists():
        print(f"Using {PDF_FILE} ({pdf_path.stat().st_size:,} bytes)")
    else:
        try:
            _download(PDF_URL, pdf_path)
        except Exception as e:
            print(f"ERROR downloading PDF: {e}")
            return

    text = _extract_math_text(pdf_path)
    print(f"Math section: {len(text)} chars → model …", end="", flush=True)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")

    print(f"\nClearing existing {SYSTEM} data …")
    with conn:
        conn.execute("DELETE FROM keywords WHERE standard_id LIKE 'CZ_MSMT.%'")
        conn.execute("DELETE FROM standards WHERE system = ?", (SYSTEM,))

    try:
        outcomes = _call_model(text)
    except Exception as e:
        print(f" ERROR: {e}")
        conn.close()
        return

    print(f" {len(outcomes)} extracted …", end="", flush=True)

    seen_ids: set[str] = set()
    total_std = total_kw = 0

    with conn:
        for out in outcomes:
            code = (out.get("code") or "").strip()
            exit_grade_raw = out.get("exit_grade")
            strand_raw = out.get("strand")
            seq_raw = out.get("seq")
            text_cz = (out.get("text_cz") or "").strip()
            text_en = (out.get("text_en") or "").strip()

            if not text_en or len(text_en) < 10:
                continue
            # Skip "p"-suffix (minimum level) entries
            if code.endswith("p"):
                continue

            try:
                exit_grade = int(exit_grade_raw)
                strand = int(strand_raw)
                seq = int(seq_raw)
            except (TypeError, ValueError):
                continue

            if exit_grade not in (3, 5, 9):
                continue
            if strand not in (1, 2, 3, 4):
                continue

            grade, grade_band = GRADE_MAP[str(exit_grade)]

            std_id = f"CZ_MSMT.MATH.G{exit_grade:02d}.S{strand}.{seq:03d}"
            if std_id in seen_ids:
                continue
            seen_ids.add(std_id)

            conn.execute(
                """INSERT OR REPLACE INTO standards
                   (id, system, subject, grade, grade_band, domain, cluster,
                    standard_text, last_verified_date, source_url)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    std_id, SYSTEM, "mathematics",
                    grade, grade_band,
                    STRAND_DOMAIN_MAP.get(str(strand), f"Strand {strand}"),
                    text_cz,
                    text_en,
                    VERIFIED_DATE,
                    PDF_URL,
                ),
            )
            total_std += 1
            for kw in _extract_keywords(text_en + " " + text_cz):
                conn.execute(
                    "INSERT OR IGNORE INTO keywords (standard_id, keyword) VALUES (?,?)",
                    (std_id, kw),
                )
                total_kw += 1

    conn.close()
    print(f" {total_std} ingested")
    print(f"\nTotal: {total_std} standards, {total_kw} keywords")
    print("Done.")


if __name__ == "__main__":
    main()
