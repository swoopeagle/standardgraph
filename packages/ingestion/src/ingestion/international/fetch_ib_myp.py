"""Fetch and ingest IB Middle Years Programme curriculum standards.

Covered systems:
  ib-myp-science   — IB MYP Sciences (grades 6-10)
  ib-myp-english   — IB MYP Language and Literature (grades 6-10)
  ib-myp-ss        — IB MYP Individuals and Societies (grades 6-10)
  ib-myp-design    — IB MYP Design (grades 6-10)

Source strategy:
  1. Try to download publicly available IB MYP subject brief PDFs from ibo.org
  2. Fall back to scraping the public IBO curriculum web pages
  3. Use Gemma to structure content from either source

IDs: IB.MYP.{SUBJECT}.{code_or_seq}  e.g. IB.MYP.SCI.AO1
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

VERIFIED_DATE = date.today().isoformat()
RAW_DIR = DB_PATH.parent / "raw" / "ib_myp"
SOURCE_BASE = "https://www.ibo.org"

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each",
    "such", "both", "also", "into", "more", "most", "some", "other",
    "these", "those", "about", "able", "after", "where", "while", "make",
    "used", "given", "find", "show", "know", "understand", "apply",
    "students", "student", "should", "middle", "years", "programme",
}

SUBJECTS = [
    {
        "key":        "science",
        "system":     "ib-myp-science",
        "name":       "IB MYP Sciences",
        "subject_db": "science",
        "grade":      "6-10",
        "grade_band": "6-10",
        "pdf_file":   "ib_myp_science.pdf",
        "brief_url":  "https://www.ibo.org/contentassets/5895a05412144fe0adc8709b8e76d927/myp-sciences-en.pdf",
        "page_url":   "https://www.ibo.org/programmes/middle-years-programme/curriculum/sciences/",
    },
    {
        "key":        "english",
        "system":     "ib-myp-english",
        "name":       "IB MYP Language and Literature",
        "subject_db": "ela",
        "grade":      "6-10",
        "grade_band": "6-10",
        "pdf_file":   "ib_myp_english.pdf",
        "brief_url":  "https://www.ibo.org/contentassets/5895a05412144fe0adc8709b8e76d927/myp-language-and-literature-en.pdf",
        "page_url":   "https://www.ibo.org/programmes/middle-years-programme/curriculum/language-and-literature/",
    },
    {
        "key":        "ss",
        "system":     "ib-myp-ss",
        "name":       "IB MYP Individuals and Societies",
        "subject_db": "social-studies",
        "grade":      "6-10",
        "grade_band": "6-10",
        "pdf_file":   "ib_myp_ss.pdf",
        "brief_url":  "https://www.ibo.org/contentassets/5895a05412144fe0adc8709b8e76d927/myp-individuals-and-societies-en.pdf",
        "page_url":   "https://www.ibo.org/programmes/middle-years-programme/curriculum/individuals-and-societies/",
    },
    {
        "key":        "design",
        "system":     "ib-myp-design",
        "name":       "IB MYP Design",
        "subject_db": "cs",
        "grade":      "6-10",
        "grade_band": "6-10",
        "pdf_file":   "ib_myp_design.pdf",
        "brief_url":  "https://www.ibo.org/contentassets/5895a05412144fe0adc8709b8e76d927/myp-design-en.pdf",
        "page_url":   "https://www.ibo.org/programmes/middle-years-programme/curriculum/design/",
    },
]

IB_MYP_PROMPT = """\
Extract all learning objectives and assessment criteria from this IB Middle Years Programme \
{subject_name} curriculum document.

IB MYP subjects use four assessment criteria (A, B, C, D) with specific achievement descriptors.
They also have:
  Key concepts and related concepts
  Global contexts
  ATL skills (Approaches to Learning)
  Specific content or skill statements by grade band (years 1-3, years 4-5)

Extract assessment criteria descriptions AND specific skill/content statements as standards.
Each standard should be a specific, assessable learning outcome.

Return ONLY a JSON array (no other text, no markdown). Each element must have:
  "objective_num" : a code or identifier (e.g. "A1", "B2", "CRIT-A", "SKILL-01")
  "topic"         : the criterion label, concept, or category (e.g. "Criterion A: Knowing and understanding")
  "objective_text": the full text of the criterion descriptor, skill, or content statement

If the text has no extractable learning outcomes, return [].

TEXT:
{text}
"""

IB_MYP_PAGE_PROMPT = """\
Extract all learning objectives, assessment criteria, skills, and content areas from this IB \
Middle Years Programme {subject_name} curriculum webpage.

Look for:
- Assessment Criteria (A, B, C, D) with their descriptors
- Key concepts and related concepts
- Skills and content by grade band
- ATL skills specific to this subject

Return ONLY a JSON array (no other text, no markdown). Each element must have:
  "objective_num" : a code or sequential identifier (e.g. "A", "B", "CRIT-A", "SKILL-01")
  "topic"         : the criterion, concept, or category name
  "objective_text": the full text of the criterion, skill, or content statement

If no clear learning outcomes are found, return [].

TEXT:
{text}
"""


def _try_download(url: str, path: Path) -> bool:
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/pdf,*/*",
        }
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as r:
            content_type = r.headers.get("Content-Type", "")
            data = r.read()
        if len(data) < 1000:
            return False
        if b"<!DOCTYPE" in data[:200] and b"pdf" not in content_type.lower():
            return False
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        print(f"  Downloaded: {path.stat().st_size:,} bytes")
        return True
    except Exception as e:
        print(f"  Download failed ({url}): {e}")
        return False


def _fetch_page_text(url: str) -> str:
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode("utf-8", errors="replace")
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&[a-zA-Z]+;", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_pdf_pages(pdf_path: Path) -> list[str]:
    results = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if text.strip():
                results.append(text)
    return results


def _call_gemma(text: str, prompt_template: str, subject_name: str) -> list[dict]:
    prompt = prompt_template.format(subject_name=subject_name, text=text[:5500])
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "format": "json",
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


def _ingest(
    objectives: list[dict], subject: dict,
    conn: sqlite3.Connection, seen_ids: set[str],
) -> tuple[int, int]:
    std_count = kw_count = 0
    system = subject["system"]
    for obj in objectives:
        obj_text = (obj.get("objective_text") or "").strip()
        obj_num = (obj.get("objective_num") or "").strip()
        if not obj_text or not obj_num:
            continue
        topic = (obj.get("topic") or obj.get("big_idea") or "").strip()
        std_id = f"IB.MYP.{subject['key'].upper()}.{obj_num}"
        if std_id in seen_ids:
            continue
        seen_ids.add(std_id)
        conn.execute(
            """INSERT OR REPLACE INTO standards
               (id, system, subject, grade, grade_band, domain, cluster,
                standard_text, last_verified_date, source_url)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (std_id, system, subject["subject_db"],
             subject["grade"], subject["grade_band"],
             topic, "", obj_text, VERIFIED_DATE, subject["page_url"]),
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

    grand_std = grand_kw = 0

    for subject in SUBJECTS:
        system = subject["system"]
        with conn:
            conn.execute("DELETE FROM keywords WHERE standard_id LIKE ?", (f"IB.MYP.{subject['key'].upper()}.%",))
            conn.execute("DELETE FROM standards WHERE system = ?", (system,))

        pdf_path = RAW_DIR / subject["pdf_file"]
        all_objectives: list[dict] = []

        if not pdf_path.exists():
            print(f"\n{subject['name']}: trying subject brief PDF...")
            _try_download(subject["brief_url"], pdf_path)

        if pdf_path.exists() and pdf_path.stat().st_size > 1000:
            pages = _extract_pdf_pages(pdf_path)
            print(f"\nExtracting {subject['name']} from PDF ({len(pages)} pages)...")
            chunk_size = 3
            for i in range(0, len(pages), chunk_size):
                chunk_text = "\n\n".join(pages[i:i + chunk_size])
                page_label = f"pages {i+1}-{min(i+chunk_size, len(pages))}"
                print(f"  {page_label}: {len(chunk_text)} chars → Gemma...", end="", flush=True)
                try:
                    objs = _call_gemma(chunk_text, IB_MYP_PROMPT, subject["name"])
                    all_objectives.extend(objs)
                    print(f" {len(objs)} extracted")
                except Exception as e:
                    print(f" ERROR: {e}")
        else:
            print(f"\n{subject['name']}: PDF unavailable, fetching curriculum page...")
            try:
                page_text = _fetch_page_text(subject["page_url"])
                chunk_size = 4000
                for i in range(0, min(len(page_text), 20000), chunk_size):
                    chunk = page_text[i:i + chunk_size]
                    try:
                        objs = _call_gemma(chunk, IB_MYP_PAGE_PROMPT, subject["name"])
                        all_objectives.extend(objs)
                    except Exception as e:
                        print(f" ERROR: {e}")
                        break
                print(f" {len(all_objectives)} extracted from page")
            except Exception as e:
                print(f"  Page fetch failed: {e}")

        seen_ids: set[str] = set()
        with conn:
            s, k = _ingest(all_objectives, subject, conn, seen_ids)
        print(f"  Ingested: {s} standards, {k} keywords")
        grand_std += s
        grand_kw += k

    conn.close()
    print(f"\nGrand total: {grand_std} standards, {grand_kw} keywords")
    print("Done.")


if __name__ == "__main__":
    main()
