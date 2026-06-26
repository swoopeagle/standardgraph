"""Fetch and ingest US state Social Studies standards via PDF for states not in CSP.

Covered systems: ca-ss, il-ss, ma-ss
Subject: social-studies
Crosswalk hub: c3

Sources:
  CA — California History-Social Science Content Standards (K-12)
       https://www.cde.ca.gov/be/st/ss/documents/histsocscistnd.pdf
  IL — Illinois Learning Standards for Social Science (K-12)
       https://www.isbe.net/Documents/K-12-SS-Standards.pdf
  MA — Massachusetts History and Social Science Curriculum Framework (2018)
       https://www.doe.mass.edu/frameworks/hss/2018-12.pdf
"""
import json
import re
import sqlite3
from datetime import date
from pathlib import Path

import httpx
import pdfplumber

from shared.config import DB_PATH, OLLAMA_BASE_URL, OLLAMA_MODEL
from shared.pdf_utils import is_standards_page

VERIFIED_DATE = date.today().isoformat()
RAW_DIR = DB_PATH.parent / "raw" / "ss_states_pdf"

STATES = [
    {
        "system":    "ca-ss",
        "name":      "California",
        "filename":  "ca_hss_standards.pdf",
        "url":       "https://www.cde.ca.gov/be/st/ss/documents/histsocscistnd.pdf",
        "source_url": "https://www.cde.ca.gov/be/st/ss/documents/histsocscistnd.pdf",
        "id_prefix": "CA.SS",
    },
    {
        "system":    "il-ss",
        "name":      "Illinois",
        "filename":  "il_ss_standards.pdf",
        "url":       "https://www.isbe.net/Documents/K-12-SS-Standards.pdf",
        "source_url": "https://www.isbe.net/Pages/Social-Science.aspx",
        "id_prefix": "IL.SS",
    },
    {
        "system":    "ma-ss",
        "name":      "Massachusetts",
        "filename":  "ma_hss_framework.pdf",
        "url":       "https://www.doe.mass.edu/frameworks/hss/2018-12.pdf",
        "source_url": "https://www.doe.mass.edu/instruction/hss/",
        "id_prefix": "MA.SS",
    },
]

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each",
    "such", "both", "also", "into", "more", "most", "some", "other",
    "these", "those", "about", "able", "after", "where", "while", "make",
    "used", "given", "find", "show", "know", "understand", "apply",
    "students", "student", "grade", "grades", "standard", "standards",
}

EXTRACT_PROMPT = """\
Extract all individual K-12 Social Studies / History standards from this page of a {state_name} standards document.

Social studies documents cover History, Geography, Civics/Government, and Economics.

Return ONLY a JSON array (no other text, no markdown). Each element must have:
  "grade"      : grade level as a string — use "K", "1"–"8", "HS", or a grade band like "6-8" or "9-12"
  "strand"     : subject area — one of "History", "Geography", "Civics", "Economics", or the document's own category name
  "sub_topic"  : specific topic or unit within the strand (e.g. "Ancient Civilizations", "Map Skills", "Rights and Responsibilities")
  "standard"   : the full text of the individual content standard or learning expectation

Rules:
- Extract every individual numbered or bulleted standard/expectation.
- Infer grade from context (section headers, grade band labels, etc.).
- If multiple standards appear under one heading, each becomes a separate array entry.
- Do NOT include introductory paragraphs, rationale, teacher notes, or assessment guidance.
- Do NOT include standards that are just repeating a header.
- Preserve exact wording.

PAGE TEXT:
{text}
"""


def _download(url: str, path: Path) -> None:
    print(f"  Downloading {url} ...")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    resp = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60, follow_redirects=True)
    resp.raise_for_status()
    path.write_bytes(resp.content)
    print(f"  Saved: {path.stat().st_size:,} bytes")


def _extract_pages(pdf_path: Path) -> list[tuple[int, str]]:
    results = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            if text.strip():
                results.append((i + 1, text))
    return results


def _call_gemma(text: str, state_name: str, page_num: int) -> list[dict]:
    prompt = EXTRACT_PROMPT.format(state_name=state_name, text=text[:5000])
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
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
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


def _normalise_grade(raw: str) -> str:
    """Normalise grade strings to K/1-8/HS."""
    g = str(raw).strip().upper()
    if g in ("K", "KG", "KINDERGARTEN"):
        return "K"
    if g in ("9", "10", "11", "12", "9-10", "11-12", "9-12", "HS", "HIGH SCHOOL"):
        return "HS"
    for d in ("1", "2", "3", "4", "5", "6", "7", "8"):
        if g == d:
            return d
    # grade bands like "6-8", "3-5" — keep as-is (relate step handles bands)
    return raw.strip()


def _ingest_standards(
    standards: list[dict],
    state: dict,
    conn: sqlite3.Connection,
    seen_ids: set[str],
) -> tuple[int, int]:
    std_count = kw_count = 0
    for item in standards:
        text = (item.get("standard") or "").strip()
        if not text or len(text) < 10:
            continue
        grade_raw = str(item.get("grade") or "").strip()
        grade = _normalise_grade(grade_raw) if grade_raw else "unknown"
        strand = (item.get("strand") or "").strip()
        sub_topic = (item.get("sub_topic") or "").strip()

        std_id = f"{state['id_prefix']}.{grade}.{abs(hash(text[:50])) % 1_000_000}"
        if std_id in seen_ids:
            continue
        seen_ids.add(std_id)

        conn.execute(
            """INSERT OR REPLACE INTO standards
               (id, system, subject, grade, grade_band, domain, cluster,
                standard_text, last_verified_date, source_url)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (std_id, state["system"], "social-studies", grade, None,
             strand, sub_topic, text, VERIFIED_DATE, state["source_url"]),
        )
        std_count += 1

        for kw in _extract_keywords(text):
            conn.execute(
                "INSERT OR IGNORE INTO keywords (standard_id, keyword) VALUES (?,?)",
                (std_id, kw),
            )
            kw_count += 1

    return std_count, kw_count


def _process_state(state: dict, conn: sqlite3.Connection) -> tuple[int, int]:
    pdf_path = RAW_DIR / state["filename"]
    if not pdf_path.exists():
        _download(state["url"], pdf_path)

    pages = _extract_pages(pdf_path)
    print(f"  {len(pages)} content pages")

    grand_std = grand_kw = 0
    seen_ids: set[str] = set()

    for pnum, text in pages:
        if len(text.strip()) < 100 or not is_standards_page(text):
            continue
        print(f"  page {pnum}: {len(text)} chars → Gemma...", end="", flush=True)
        try:
            standards = _call_gemma(text, state["name"], pnum)
        except Exception as e:
            print(f" ERROR: {e}")
            continue
        with conn:
            s, k = _ingest_standards(standards, state, conn, seen_ids)
        grand_std += s
        grand_kw += k
        print(f" {len(standards)} extracted, {s} ingested")

    return grand_std, grand_kw


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    for state in STATES:
        print(f"\nExtracting {state['name']} Social Studies ({state['system']})...")
        try:
            s, k = _process_state(state, conn)
            print(f"  Total: {s} standards, {k} keywords")
        except Exception as e:
            print(f"  FAILED: {e}")

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
