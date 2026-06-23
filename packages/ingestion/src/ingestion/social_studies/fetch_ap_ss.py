"""Fetch and ingest College Board AP Social Studies / Humanities courses.

Covered systems:
  ap-us-history            — AP United States History
  ap-world-history         — AP World History: Modern
  ap-euro-history          — AP European History
  ap-us-gov                — AP United States Government and Politics
  ap-comp-gov              — AP Comparative Government and Politics
  ap-human-geo             — AP Human Geography
  ap-psych                 — AP Psychology
  ap-macro-econ            — AP Macroeconomics
  ap-micro-econ            — AP Microeconomics
  ap-art-history           — AP Art History
  ap-african-american-stud — AP African American Studies
  ap-seminar               — AP Seminar (Capstone)
  ap-research              — AP Research (Capstone)

Sources: College Board Course and Exam Descriptions (auto-downloaded).
Structure: Big Ideas → Key Concepts → Learning Objectives
IDs: AP.{SYSTEM}.{objective_num}  e.g. AP.AP_US_HISTORY.POL-1.A
"""
import json
import os
import re
import sqlite3
import urllib.request
from datetime import date
from pathlib import Path

import httpx
import pdfplumber

from shared.config import DB_PATH, OLLAMA_BASE_URL, OLLAMA_MODEL

VERIFIED_DATE = date.today().isoformat()
RAW_DIR = DB_PATH.parent / "raw" / "ap_ss"
SOURCE_URL = "https://apcentral.collegeboard.org"

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each",
    "such", "both", "also", "into", "more", "most", "some", "other",
    "these", "those", "about", "able", "after", "where", "while", "make",
    "used", "given", "find", "show", "know", "understand", "apply",
    "students", "student", "should", "history", "society", "political",
    "social", "economic", "cultural", "global", "national",
}

COURSES = [
    {
        "key":        "us_history",
        "system":     "ap-us-history",
        "name":       "AP United States History",
        "pdf_file":   "ap_us_history.pdf",
        "url":        "https://apcentral.collegeboard.org/media/pdf/ap-us-history-course-and-exam-description.pdf",
        "start_page": 30,
        "end_page":   350,
    },
    {
        "key":        "world_history",
        "system":     "ap-world-history",
        "name":       "AP World History: Modern",
        "pdf_file":   "ap_world_history.pdf",
        "url":        "https://apcentral.collegeboard.org/media/pdf/ap-world-history-modern-course-and-exam-description.pdf",
        "start_page": 30,
        "end_page":   350,
    },
    {
        "key":        "euro_history",
        "system":     "ap-euro-history",
        "name":       "AP European History",
        "pdf_file":   "ap_euro_history.pdf",
        "url":        "https://apcentral.collegeboard.org/media/pdf/ap-european-history-course-and-exam-description.pdf",
        "start_page": 30,
        "end_page":   350,
    },
    {
        "key":        "us_gov",
        "system":     "ap-us-gov",
        "name":       "AP United States Government and Politics",
        "pdf_file":   "ap_us_gov.pdf",
        "url":        "https://apcentral.collegeboard.org/media/pdf/ap-us-government-and-politics-course-and-exam-description.pdf",
        "start_page": 25,
        "end_page":   300,
    },
    {
        "key":        "comp_gov",
        "system":     "ap-comp-gov",
        "name":       "AP Comparative Government and Politics",
        "pdf_file":   "ap_comp_gov.pdf",
        "url":        "https://apcentral.collegeboard.org/media/pdf/ap-comparative-government-and-politics-course-and-exam-description.pdf",
        "start_page": 25,
        "end_page":   300,
    },
    {
        "key":        "human_geo",
        "system":     "ap-human-geo",
        "name":       "AP Human Geography",
        "pdf_file":   "ap_human_geo.pdf",
        "url":        "https://apcentral.collegeboard.org/media/pdf/ap-human-geography-course-and-exam-description.pdf",
        "start_page": 25,
        "end_page":   300,
    },
    {
        "key":        "psych",
        "system":     "ap-psych",
        "name":       "AP Psychology",
        "pdf_file":   "ap_psych.pdf",
        "url":        "https://apcentral.collegeboard.org/media/pdf/ap-psychology-course-and-exam-description.pdf",
        "start_page": 25,
        "end_page":   300,
    },
    {
        "key":        "macro_econ",
        "system":     "ap-macro-econ",
        "name":       "AP Macroeconomics",
        "pdf_file":   "ap_macro_econ.pdf",
        "url":        "https://apcentral.collegeboard.org/media/pdf/ap-macroeconomics-course-and-exam-description.pdf",
        "start_page": 25,
        "end_page":   300,
    },
    {
        "key":        "micro_econ",
        "system":     "ap-micro-econ",
        "name":       "AP Microeconomics",
        "pdf_file":   "ap_micro_econ.pdf",
        "url":        "https://apcentral.collegeboard.org/media/pdf/ap-microeconomics-course-and-exam-description.pdf",
        "start_page": 25,
        "end_page":   300,
    },
    {
        "key":        "art_history",
        "system":     "ap-art-history",
        "name":       "AP Art History",
        "pdf_file":   "ap_art_history.pdf",
        "url":        "https://apcentral.collegeboard.org/media/pdf/ap-art-history-course-and-exam-description.pdf",
        "start_page": 25,
        "end_page":   350,
    },
    {
        "key":        "african_american_stud",
        "system":     "ap-african-american-stud",
        "name":       "AP African American Studies",
        "pdf_file":   "ap_african_american_stud.pdf",
        "url":        "https://apcentral.collegeboard.org/media/pdf/ap-african-american-studies-course-and-exam-description.pdf",
        "start_page": 25,
        "end_page":   350,
    },
    {
        "key":        "seminar",
        "system":     "ap-seminar",
        "name":       "AP Seminar",
        "pdf_file":   "ap_seminar.pdf",
        "url":        "https://apcentral.collegeboard.org/media/pdf/ap-seminar-course-and-exam-description.pdf",
        "start_page": 20,
        "end_page":   200,
    },
    {
        "key":        "research",
        "system":     "ap-research",
        "name":       "AP Research",
        "pdf_file":   "ap_research.pdf",
        "url":        "https://apcentral.collegeboard.org/media/pdf/ap-research-course-and-exam-description.pdf",
        "start_page": 20,
        "end_page":   200,
    },
]

SS_PROMPT = """\
Extract all AP {course_name} learning objectives from this College Board Course and Exam Description text.

AP History, Government, and Social Studies courses use this hierarchy:
  Big Ideas: identified by 2-4 letter codes (e.g. POL, WOR, CUL, NAT, ECD, GOV, GEO,
             MIG, ARC, WXT, PCE, ENV, CDI, SCD, CON, LIB, CIV, REP, MIA, etc.)
  Key Concepts or Enduring Understandings: Big Idea code + number (e.g. POL-1, WOR-2)
  Learning Objectives: Key Concept + letter (e.g. POL-1.A, WOR-2.B) ← extract these
  Historical Developments / Essential Knowledge: supporting detail, include in objective_text

AP Capstone (Seminar/Research) uses QUEST skills (Question and Explore, Understand and Analyze,
Evaluate Multiple Perspectives, Synthesize Ideas, Team, Transform) or similar coded skills —
extract these as learning objectives.

Return ONLY a JSON array (no other text, no markdown). Each element must have:
  "objective_num" : the learning objective code (e.g. "POL-1.A" or "QUEST-1.A")
  "big_idea"      : big idea full name (e.g. "Politics and Power")
  "objective_text": full text of the learning objective including essential knowledge detail

If no learning objectives appear in this text, return [].
Do NOT include key concepts or enduring understandings alone as separate items.

TEXT:
{text}
"""


def _download(url: str, path: Path) -> None:
    print(f"  Downloading {url} ...")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as r, open(path, "wb") as f:
        f.write(r.read())
    print(f"  Saved: {path.stat().st_size:,} bytes")


def _extract_pages(pdf_path: Path, start: int, end: int) -> list[tuple[int, str]]:
    results = []
    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages)
        for i in range(start, min(end, total)):
            text = pdf.pages[i].extract_text() or ""
            if text.strip():
                results.append((i + 1, text))
    return results


def _call_gemma(text: str, course_name: str) -> list[dict]:
    prompt = SS_PROMPT.format(course_name=course_name, text=text[:12000])
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


def _ingest(objectives: list[dict], system: str, conn: sqlite3.Connection, seen_ids: set[str]) -> tuple[int, int]:
    std_count = kw_count = 0
    sys_key = system.replace("-", "_").upper()
    for obj in objectives:
        obj_text = (obj.get("objective_text") or "").strip()
        obj_num = (obj.get("objective_num") or "").strip()
        if not obj_text or not obj_num:
            continue
        big_idea = (obj.get("big_idea") or "").strip()
        std_id = f"AP.{sys_key}.{obj_num}"
        if std_id in seen_ids:
            continue
        seen_ids.add(std_id)
        conn.execute(
            """INSERT OR REPLACE INTO standards
               (id, system, subject, grade, grade_band, domain, cluster,
                standard_text, last_verified_date, source_url)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (std_id, system, "social-studies", "HS", "9-12",
             big_idea, "", obj_text, VERIFIED_DATE, SOURCE_URL),
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
    conn.execute("PRAGMA busy_timeout = 30000")

    grand_std = grand_kw = 0

    # AP_SS_KEYS=key1,key2,... runs only those courses (for parallel machines).
    _keys_env = os.getenv("AP_SS_KEYS", "")
    _allowed = {k.strip() for k in _keys_env.split(",") if k.strip()} if _keys_env else None

    for course in COURSES:
        if _allowed and course["key"] not in _allowed:
            continue
        pdf_path = RAW_DIR / course["pdf_file"]
        if not pdf_path.exists():
            try:
                _download(course["url"], pdf_path)
            except Exception as e:
                print(f"  SKIP {course['name']}: download failed — {e}")
                continue

        system = course["system"]
        sys_key = system.replace("-", "_").upper()
        with conn:
            conn.execute("DELETE FROM keywords WHERE standard_id LIKE ?", (f"AP.{sys_key}.%",))
            conn.execute("DELETE FROM standards WHERE system = ?", (system,))

        pages = _extract_pages(pdf_path, course["start_page"], course["end_page"])
        chunk_size = 4
        course_std = course_kw = 0
        seen_ids: set[str] = set()

        print(f"\nExtracting {course['name']} ({len(pages)} content pages)...")

        for i in range(0, len(pages), chunk_size):
            chunk = pages[i:i + chunk_size]
            chunk_text = "\n\n".join(t for _, t in chunk)
            page_nums = f"{chunk[0][0]}-{chunk[-1][0]}"
            print(f"  pages {page_nums}: {len(chunk_text)} chars → Gemma...", end="", flush=True)
            try:
                objectives = _call_gemma(chunk_text, course["name"])
            except Exception as e:
                print(f" ERROR: {e}")
                continue
            with conn:
                s, k = _ingest(objectives, system, conn, seen_ids)
            course_std += s
            course_kw += k
            print(f" {len(objectives)} extracted, {s} ingested" if objectives else " 0 extracted")

        print(f"  Total: {course_std} standards, {course_kw} keywords")
        grand_std += course_std
        grand_kw += course_kw

    conn.close()
    print(f"\nGrand total: {grand_std} standards, {grand_kw} keywords")
    print("Done.")


if __name__ == "__main__":
    main()
