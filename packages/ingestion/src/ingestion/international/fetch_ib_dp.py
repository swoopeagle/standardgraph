"""Fetch and ingest IB Diploma Programme curriculum standards.

Covered systems:
  ib-dp-bio        — IB DP Biology
  ib-dp-chem       — IB DP Chemistry
  ib-dp-physics    — IB DP Physics
  ib-dp-ess        — IB DP Environmental Systems and Societies
  ib-dp-english-a  — IB DP English A: Literature and Language & Literature
  ib-dp-history    — IB DP History
  ib-dp-geography  — IB DP Geography
  ib-dp-economics  — IB DP Economics
  ib-dp-psych      — IB DP Psychology
  ib-dp-cs         — IB DP Computer Science

Source strategy:
  1. Try to download publicly available IB DP subject brief PDFs from ibo.org
  2. Fall back to scraping the public IBO curriculum web pages
  3. Use Gemma to structure content from either source

IB subject brief PDFs are publicly available at ibo.org (no auth required).
Full subject guides require IB World School access — not used here.

IDs: IB.DP.{SUBJECT}.{code_or_seq}  e.g. IB.DP.BIO.T1.1
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
RAW_DIR = DB_PATH.parent / "raw" / "ib_dp"
SOURCE_BASE = "https://www.ibo.org"

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each",
    "such", "both", "also", "into", "more", "most", "some", "other",
    "these", "those", "about", "able", "after", "where", "while", "make",
    "used", "given", "find", "show", "know", "understand", "apply",
    "students", "student", "should", "diploma", "programme",
}

# IB DP subject brief PDFs — publicly available from ibo.org
# Subject briefs are 2-page documents summarizing aims, assessment objectives, and content
SUBJECTS = [
    {
        "key":        "bio",
        "system":     "ib-dp-bio",
        "name":       "IB DP Biology",
        "subject_db": "science",
        "grade":      "HS",
        "grade_band": "9-12",
        "pdf_file":   "ib_dp_bio.pdf",
        "brief_url":  "https://www.ibo.org/contentassets/5895a05412144fe0adc8709b8e76d927/dp-biology-en.pdf",
        "page_url":   "https://www.ibo.org/programmes/diploma-programme/curriculum/sciences/biology/",
    },
    {
        "key":        "chem",
        "system":     "ib-dp-chem",
        "name":       "IB DP Chemistry",
        "subject_db": "science",
        "grade":      "HS",
        "grade_band": "9-12",
        "pdf_file":   "ib_dp_chem.pdf",
        "brief_url":  "https://www.ibo.org/contentassets/5895a05412144fe0adc8709b8e76d927/dp-chemistry-en.pdf",
        "page_url":   "https://www.ibo.org/programmes/diploma-programme/curriculum/sciences/chemistry/",
    },
    {
        "key":        "physics",
        "system":     "ib-dp-physics",
        "name":       "IB DP Physics",
        "subject_db": "science",
        "grade":      "HS",
        "grade_band": "9-12",
        "pdf_file":   "ib_dp_physics.pdf",
        "brief_url":  "https://www.ibo.org/contentassets/5895a05412144fe0adc8709b8e76d927/dp-physics-en.pdf",
        "page_url":   "https://www.ibo.org/programmes/diploma-programme/curriculum/sciences/physics/",
    },
    {
        "key":        "ess",
        "system":     "ib-dp-ess",
        "name":       "IB DP Environmental Systems and Societies",
        "subject_db": "science",
        "grade":      "HS",
        "grade_band": "9-12",
        "pdf_file":   "ib_dp_ess.pdf",
        "brief_url":  "https://www.ibo.org/contentassets/5895a05412144fe0adc8709b8e76d927/dp-environmental-systems-and-societies-en.pdf",
        "page_url":   "https://www.ibo.org/programmes/diploma-programme/curriculum/sciences/environmental-systems-and-societies/",
    },
    {
        "key":        "english_a",
        "system":     "ib-dp-english-a",
        "name":       "IB DP English A: Literature",
        "subject_db": "ela",
        "grade":      "HS",
        "grade_band": "9-12",
        "pdf_file":   "ib_dp_english_a.pdf",
        "brief_url":  "https://www.ibo.org/contentassets/5895a05412144fe0adc8709b8e76d927/dp-language-a-literature-en.pdf",
        "page_url":   "https://www.ibo.org/programmes/diploma-programme/curriculum/studies-in-language-and-literature/language-a-literature/",
    },
    {
        "key":        "history",
        "system":     "ib-dp-history",
        "name":       "IB DP History",
        "subject_db": "social-studies",
        "grade":      "HS",
        "grade_band": "9-12",
        "pdf_file":   "ib_dp_history.pdf",
        "brief_url":  "https://www.ibo.org/contentassets/5895a05412144fe0adc8709b8e76d927/dp-history-en.pdf",
        "page_url":   "https://www.ibo.org/programmes/diploma-programme/curriculum/individuals-and-societies/history/",
    },
    {
        "key":        "geography",
        "system":     "ib-dp-geography",
        "name":       "IB DP Geography",
        "subject_db": "social-studies",
        "grade":      "HS",
        "grade_band": "9-12",
        "pdf_file":   "ib_dp_geography.pdf",
        "brief_url":  "https://www.ibo.org/contentassets/5895a05412144fe0adc8709b8e76d927/dp-geography-en.pdf",
        "page_url":   "https://www.ibo.org/programmes/diploma-programme/curriculum/individuals-and-societies/geography/",
    },
    {
        "key":        "economics",
        "system":     "ib-dp-economics",
        "name":       "IB DP Economics",
        "subject_db": "social-studies",
        "grade":      "HS",
        "grade_band": "9-12",
        "pdf_file":   "ib_dp_economics.pdf",
        "brief_url":  "https://www.ibo.org/contentassets/5895a05412144fe0adc8709b8e76d927/dp-economics-en.pdf",
        "page_url":   "https://www.ibo.org/programmes/diploma-programme/curriculum/individuals-and-societies/economics/",
    },
    {
        "key":        "psych",
        "system":     "ib-dp-psych",
        "name":       "IB DP Psychology",
        "subject_db": "social-studies",
        "grade":      "HS",
        "grade_band": "9-12",
        "pdf_file":   "ib_dp_psych.pdf",
        "brief_url":  "https://www.ibo.org/contentassets/5895a05412144fe0adc8709b8e76d927/dp-psychology-en.pdf",
        "page_url":   "https://www.ibo.org/programmes/diploma-programme/curriculum/individuals-and-societies/psychology/",
    },
    {
        "key":        "cs",
        "system":     "ib-dp-cs",
        "name":       "IB DP Computer Science",
        "subject_db": "cs",
        "grade":      "HS",
        "grade_band": "9-12",
        "pdf_file":   "ib_dp_cs.pdf",
        "brief_url":  "https://www.ibo.org/contentassets/5895a05412144fe0adc8709b8e76d927/dp-computer-science-en.pdf",
        "page_url":   "https://www.ibo.org/programmes/diploma-programme/curriculum/computer-science/",
    },
]

IB_DP_PROMPT = """\
Extract all learning objectives, assessment objectives, and topic content statements from this \
IB Diploma Programme {subject_name} curriculum document.

IB DP subjects use this structure:
  Aims: broad goals
  Assessment Objectives (AOs): AO1 (Knowledge and understanding), AO2 (Application and analysis),
    AO3 (Synthesis and evaluation), AO4 (Use and application of skills) — with specific sub-skills
  Topics: numbered content topics (e.g. Topic 1: Cell biology) with sub-topics
  Concepts/Understandings: specific content statements within each topic

Extract Assessment Objectives AND specific topic/content statements as standards.
Each should be a specific, assessable learning outcome.

Return ONLY a JSON array (no other text, no markdown). Each element must have:
  "objective_num" : a code or identifier (e.g. "AO1", "T1.1", "T3.2a", or sequential "OBJ-01")
  "topic"         : the topic or assessment objective area name
  "objective_text": the full text of the objective, topic statement, or content point

If the text has no extractable learning outcomes, return [].

TEXT:
{text}
"""

IB_PAGE_PROMPT = """\
Extract all learning objectives, skills, assessment objectives, and topic areas from this \
IB Diploma Programme {subject_name} curriculum webpage content.

Look for:
- Assessment Objectives (AO1, AO2, AO3, AO4) with their descriptions
- Topic list with content descriptions
- Aims and skills statements
- Assessment components that reveal what students need to know/do

Return ONLY a JSON array (no other text, no markdown). Each element must have:
  "objective_num" : a code or sequential identifier (e.g. "AO1", "T1", "SKILL-01")
  "topic"         : the category, topic, or assessment objective area
  "objective_text": the full text of the objective, topic, or skill statement

If no clear learning outcomes are found, return [].

TEXT:
{text}
"""


def _try_download(url: str, path: Path) -> bool:
    """Attempt to download from url; return True on success."""
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
        # Reject HTML error pages returned as 200
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
    """Fetch a web page and return plain text (strip HTML tags)."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode("utf-8", errors="replace")
    # Strip tags
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
    sys_key = system.replace("-", "_").upper()
    for obj in objectives:
        obj_text = (obj.get("objective_text") or "").strip()
        obj_num = (obj.get("objective_num") or "").strip()
        if not obj_text or not obj_num:
            continue
        topic = (obj.get("topic") or obj.get("big_idea") or "").strip()
        std_id = f"IB.DP.{subject['key'].upper()}.{obj_num}"
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
        sys_key = system.replace("-", "_").upper()
        with conn:
            conn.execute("DELETE FROM keywords WHERE standard_id LIKE ?", (f"IB.DP.{subject['key'].upper()}.%",))
            conn.execute("DELETE FROM standards WHERE system = ?", (system,))

        pdf_path = RAW_DIR / subject["pdf_file"]
        all_objectives: list[dict] = []

        # Strategy 1: subject brief PDF
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
                    objs = _call_gemma(chunk_text, IB_DP_PROMPT, subject["name"])
                    all_objectives.extend(objs)
                    print(f" {len(objs)} extracted")
                except Exception as e:
                    print(f" ERROR: {e}")
        else:
            # Strategy 2: public IBO curriculum web page
            print(f"\n{subject['name']}: PDF unavailable, fetching curriculum page...")
            try:
                page_text = _fetch_page_text(subject["page_url"])
                print(f"  Page: {len(page_text)} chars → Gemma...", end="", flush=True)
                # Process in chunks if page is long
                chunk_size = 4000
                for i in range(0, min(len(page_text), 20000), chunk_size):
                    chunk = page_text[i:i + chunk_size]
                    try:
                        objs = _call_gemma(chunk, IB_PAGE_PROMPT, subject["name"])
                        all_objectives.extend(objs)
                    except Exception as e:
                        print(f" ERROR: {e}")
                        break
                print(f" {len(all_objectives)} extracted")
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
