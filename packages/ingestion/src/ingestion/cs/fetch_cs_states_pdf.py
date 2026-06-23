"""Fetch and ingest CS standards from state PDFs that aren't in CSP.

Covered systems:
  nh-cs  — New Hampshire CS Standards (2018), CSTA-aligned
             PDFs: data/raw/cs_states_pdf/new hampshire standards-part2.pdf
                   (part1 is context/background only — skip it)
  wi-cs  — Wisconsin CS Standards (December 2025), WI-specific framework
             PDF:  data/raw/cs_states_pdf/wi_cs.pdf

NH uses CSTA-style IDs (1A-CS-03, 2-AP-18, etc.) organised by level:
  1A → K-2   1B → 3-5   2 → 6-8   3A → 9-10   3B → 9-12

WI uses a grade-band table format with WI-specific standard codes (ALG.4, etc.)
and three learning-priority columns (PK-5, 6-8, 9-12).
"""
import json
import re
import sqlite3
from datetime import date
from pathlib import Path

import httpx
import pdfplumber

from shared.config import DB_PATH, OLLAMA_BASE_URL, OLLAMA_MODEL

VERIFIED_DATE = date.today().isoformat()
RAW_DIR = DB_PATH.parent / "raw" / "cs_states_pdf"

SYSTEMS = {
    "nh-cs": {
        "label": "New Hampshire",
        "subject": "cs",
        "source_url": "https://www.education.nh.gov/who-we-are/division-of-learner-support/bureau-of-educational-innovation/computer-science",
        "pdfs": ["new hampshire standards-part2.pdf"],
    },
    "wi-cs": {
        "label": "Wisconsin",
        "subject": "cs",
        "source_url": "https://dpi.wi.gov/computer-science/standards",
        "pdfs": ["wi_cs.pdf"],
    },
}

NH_LEVEL_TO_GRADE = {
    "1A": "K", "1B": "3", "2": "6", "3A": "9", "3B": "9",
}
NH_LEVEL_TO_BAND = {
    "1A": "K-2", "1B": "3-5", "2": "6-8", "3A": "9-10", "3B": "9-12",
}

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each",
    "such", "both", "also", "into", "more", "most", "some", "other",
    "these", "those", "about", "able", "after", "where", "while", "make",
    "used", "given", "find", "show", "know", "understand", "apply",
}

NH_EXTRACT_PROMPT = """\
Extract all computer science learning standards from this New Hampshire CS Standards document excerpt.

Each standard begins with an ID in the format: {{Level}}-{{Domain}}-{{Number}}
  Level is one of: 1A (K-2), 1B (3-5), 2 (6-8), 3A (9-10), 3B (9-12)
  Domain is 2-letter code: CS, NI, DA, AP, IC
  Number is a 2-digit number: 01, 02, ...

The ID is followed by the standard text on the same line. Clarifying notes follow on subsequent lines.

Return ONLY a JSON array (no other text, no markdown). Each element must have:
  "level"       : level string exactly as written (e.g. "1A", "1B", "2", "3A", "3B")
  "domain_code" : 2-letter domain code (e.g. "CS", "NI", "DA", "AP", "IC")
  "std_num"     : number as string (e.g. "03", "07")
  "std_id"      : full ID as written (e.g. "1A-CS-03")
  "std_text"    : the standard statement only (first sentence/line after the ID) — not the clarifying notes

Rules:
- Only extract lines that start with a valid standard ID pattern like 1A-CS-03, 2-AP-18, 3B-IC-01.
- Do NOT include table of contents entries, page headers, or clarifying note paragraphs.
- Preserve exact wording of the standard statement.

DOCUMENT TEXT:
{text}
"""

WI_EXTRACT_PROMPT = """\
Extract all computer science learning standards from this Wisconsin CS Standards document excerpt.

Wisconsin standards are organised by concept (e.g. ALG, DL, CT, IC) with a table showing
learning priorities at three grade bands: PK-5 (elementary), 6-8 (middle), 9-12 (high school).

Each cell in the table contains a standard code like ALG.4.a.e.1 (elementary),
ALG.4.a.m.1 (middle), or ALG.4.a.h.1 (high school) followed by its text.

Return ONLY a JSON array (no other text, no markdown). Each element must have:
  "std_code"   : full code as written (e.g. "ALG.4.a.e.1", "DL.2.b.m.3")
  "grade_band" : one of "PK-5", "6-8", "9-12"
  "concept"    : top-level concept name (e.g. "Algorithms", "Data Literacy", "Computational Thinking")
  "std_text"   : the learning standard text for that cell

Rules:
- Extract standards from all three grade-band columns.
- Determine grade_band from the column suffix: .e. = PK-5, .m. = 6-8, .h. = 9-12
- Skip introductory paragraphs, section headers, and acknowledgement pages.
- Skip cells that say "N/A" or are empty.

DOCUMENT TEXT:
{text}
"""

WI_GRADE_BAND_MAP = {
    "PK-5": ("K", "K-5"),
    "6-8":  ("6", "6-8"),
    "9-12": ("9", "9-12"),
}


def _extract_pages(pdf_path: Path) -> list[str]:
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if text.strip():
                pages.append(text)
    return pages


def _call_gemma(prompt: str) -> list[dict]:
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "keep_alive": "4h",
        "options": {"temperature": 0.0},
    }
    resp = httpx.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload, timeout=1800)
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


def _ingest_nh(pages: list[str], conn: sqlite3.Connection,
               source_url: str, seen_ids: set[str]) -> tuple[int, int]:
    std_count = kw_count = 0
    chunk_size = 4

    for i in range(0, len(pages), chunk_size):
        chunk = "\n\n".join(pages[i: i + chunk_size])
        prompt = NH_EXTRACT_PROMPT.format(text=chunk[:8000])
        try:
            items = _call_gemma(prompt)
        except Exception as e:
            print(f"    chunk {i//chunk_size+1}: ERROR {e}")
            continue

        ingested = 0
        for item in items:
            std_id_raw = (item.get("std_id") or "").strip()
            std_text = (item.get("std_text") or "").strip()
            level = (item.get("level") or "").strip()
            domain_code = (item.get("domain_code") or "").strip()

            if not std_id_raw or not std_text or len(std_text) < 10:
                continue
            if not re.match(r"^(1A|1B|2|3A|3B)-[A-Z]{2}-\d{2}$", std_id_raw):
                continue

            std_id = f"nh-cs.{std_id_raw}"
            if std_id in seen_ids:
                continue
            seen_ids.add(std_id)

            grade = NH_LEVEL_TO_GRADE.get(level, "K")
            grade_band = NH_LEVEL_TO_BAND.get(level)

            conn.execute(
                """INSERT OR REPLACE INTO standards
                   (id, system, subject, grade, grade_band, domain, cluster,
                    standard_text, last_verified_date, source_url)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (std_id, "nh-cs", "cs", grade, grade_band,
                 domain_code, None, std_text, VERIFIED_DATE, source_url),
            )
            std_count += 1
            ingested += 1
            for kw in _extract_keywords(std_text):
                conn.execute(
                    "INSERT OR IGNORE INTO keywords (standard_id, keyword) VALUES (?,?)",
                    (std_id, kw),
                )
                kw_count += 1

        print(f"    chunk {i//chunk_size+1} (pp {i+1}-{min(i+chunk_size, len(pages))}): "
              f"{len(items)} extracted, {ingested} ingested")

    return std_count, kw_count


def _ingest_wi(pages: list[str], conn: sqlite3.Connection,
               source_url: str, seen_ids: set[str]) -> tuple[int, int]:
    std_count = kw_count = 0
    chunk_size = 3

    for i in range(0, len(pages), chunk_size):
        chunk = "\n\n".join(pages[i: i + chunk_size])
        prompt = WI_EXTRACT_PROMPT.format(text=chunk[:8000])
        try:
            items = _call_gemma(prompt)
        except Exception as e:
            print(f"    chunk {i//chunk_size+1}: ERROR {e}")
            continue

        ingested = 0
        for item in items:
            std_code = (item.get("std_code") or "").strip()
            grade_band_raw = (item.get("grade_band") or "").strip()
            concept = (item.get("concept") or "").strip()
            std_text = (item.get("std_text") or "").strip()

            if not std_code or not std_text or len(std_text) < 10:
                continue
            if grade_band_raw not in WI_GRADE_BAND_MAP:
                continue

            std_id = f"wi-cs.{std_code}"
            if std_id in seen_ids:
                continue
            seen_ids.add(std_id)

            grade, grade_band = WI_GRADE_BAND_MAP[grade_band_raw]

            conn.execute(
                """INSERT OR REPLACE INTO standards
                   (id, system, subject, grade, grade_band, domain, cluster,
                    standard_text, last_verified_date, source_url)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (std_id, "wi-cs", "cs", grade, grade_band,
                 concept, None, std_text, VERIFIED_DATE, source_url),
            )
            std_count += 1
            ingested += 1
            for kw in _extract_keywords(std_text):
                conn.execute(
                    "INSERT OR IGNORE INTO keywords (standard_id, keyword) VALUES (?,?)",
                    (std_id, kw),
                )
                kw_count += 1

        print(f"    chunk {i//chunk_size+1} (pp {i+1}-{min(i+chunk_size, len(pages))}): "
              f"{len(items)} extracted, {ingested} ingested")

    return std_count, kw_count


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    for system, cfg in SYSTEMS.items():
        with conn:
            deleted = conn.execute(
                "DELETE FROM standards WHERE system=?", (system,)
            ).rowcount
        if deleted:
            print(f"  Cleared {deleted} existing {system} standards")

        seen_ids: set[str] = set()
        total_std = total_kw = 0

        for fname in cfg["pdfs"]:
            pdf_path = RAW_DIR / fname
            if not pdf_path.exists():
                print(f"  SKIP {fname} — not found at {pdf_path}")
                continue

            pages = _extract_pages(pdf_path)
            print(f"\n{system} ({cfg['label']}) — {fname}: {len(pages)} pages")

            with conn:
                if system == "nh-cs":
                    s, k = _ingest_nh(pages, conn, cfg["source_url"], seen_ids)
                else:
                    s, k = _ingest_wi(pages, conn, cfg["source_url"], seen_ids)

            total_std += s
            total_kw += k

        print(f"  {system}: {total_std} standards, {total_kw} keywords")

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
