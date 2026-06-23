"""Fetch and ingest College Board AP English Language Arts courses.

Covered systems:
  ap-english-lang  — AP English Language and Composition
  ap-english-lit   — AP English Literature and Composition

Sources: College Board Course and Exam Descriptions (auto-downloaded).
Structure: Big Ideas → Enduring Understandings → Learning Objectives
IDs: AP.{SYSTEM}.{objective_num}  e.g. AP.AP_ENGLISH_LANG.RHS-1.A
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
RAW_DIR = DB_PATH.parent / "raw" / "ap_ela"
SOURCE_URL = "https://apcentral.collegeboard.org"

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each",
    "such", "both", "also", "into", "more", "most", "some", "other",
    "these", "those", "about", "able", "after", "where", "while", "make",
    "used", "given", "find", "show", "know", "understand", "apply",
    "students", "student", "should", "english", "language", "composition",
    "literature", "writing", "reading", "text", "texts",
}

COURSES = [
    {
        "key":        "english_lang",
        "system":     "ap-english-lang",
        "name":       "AP English Language and Composition",
        "pdf_file":   "ap_english_lang.pdf",
        "url":        "https://apcentral.collegeboard.org/media/pdf/ap-english-language-and-composition-course-and-exam-description.pdf",
        "start_page": 25,
        "end_page":   300,
    },
    {
        "key":        "english_lit",
        "system":     "ap-english-lit",
        "name":       "AP English Literature and Composition",
        "pdf_file":   "ap_english_lit.pdf",
        "url":        "https://apcentral.collegeboard.org/media/pdf/ap-english-literature-and-composition-course-and-exam-description.pdf",
        "start_page": 25,
        "end_page":   300,
    },
]

ELA_PROMPT = """\
Extract all AP {course_name} learning objectives from this College Board Course and Exam Description text.

AP English courses use this hierarchy:
  Big Ideas: identified by 3-letter codes
    AP English Language: RHS (Rhetorical Situation), CLE (Claims and Evidence),
                         REO (Reasoning and Organization), STL (Style)
    AP English Literature: CHR (Character), SET (Setting), STR (Structure),
                           NAR (Narrator and Point of View), FIG (Figurative Language),
                           LAN (Literary Argumentation)
  Enduring Understandings: Big Idea code + number (e.g. RHS-1, CLE-2)
  Learning Objectives: Enduring Understanding + letter (e.g. RHS-1.A, CLE-2.B) ← extract these
  Essential Knowledge: supporting detail — include in objective_text

Return ONLY a JSON array (no other text, no markdown). Each element must have:
  "objective_num" : the learning objective code (e.g. "RHS-1.A")
  "big_idea"      : big idea full name (e.g. "Rhetorical Situation")
  "objective_text": full text of the learning objective including essential knowledge detail

If no learning objectives appear in this text, return [].
Do NOT include enduring understandings alone as separate items.

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
    prompt = ELA_PROMPT.format(course_name=course_name, text=text[:12000])
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
            (std_id, system, "ela", "HS", "9-12",
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

    grand_std = grand_kw = 0

    for course in COURSES:
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
