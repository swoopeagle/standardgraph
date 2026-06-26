"""Fetch and ingest College Board AP World Language and AP Arts courses.

Covered systems:
  ap-spanish-lang  — AP Spanish Language and Culture
  ap-spanish-lit   — AP Spanish Literature and Culture
  ap-french        — AP French Language and Culture
  ap-german        — AP German Language and Culture
  ap-italian       — AP Italian Language and Culture
  ap-japanese      — AP Japanese Language and Culture
  ap-chinese       — AP Chinese Language and Culture
  ap-latin         — AP Latin
  ap-music-theory  — AP Music Theory
  ap-2d-art        — AP 2-D Art and Design
  ap-3d-art        — AP 3-D Art and Design
  ap-drawing       — AP Drawing

These courses do not map to an existing subject hub (world-languages and arts are not
currently hubbed). Standards are ingested for search and lookup; map_standard will return
no precomputed crosswalk but semantic fallback still works.

Sources: College Board Course and Exam Descriptions (auto-downloaded).
IDs: AP.{SYSTEM}.{objective_num}
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
RAW_DIR = DB_PATH.parent / "raw" / "ap_lang_arts"
SOURCE_URL = "https://apcentral.collegeboard.org"

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each",
    "such", "both", "also", "into", "more", "most", "some", "other",
    "these", "those", "about", "able", "after", "where", "while", "make",
    "used", "given", "find", "show", "know", "understand", "apply",
    "students", "student", "should",
}

LANGUAGE_COURSES = [
    {
        "key":        "spanish_lang",
        "system":     "ap-spanish-lang",
        "name":       "AP Spanish Language and Culture",
        "subject":    "world-languages",
        "pdf_file":   "ap_spanish_lang.pdf",
        "url":        "https://apcentral.collegeboard.org/media/pdf/ap-spanish-language-and-culture-course-and-exam-description.pdf",
        "start_page": 25,
        "end_page":   300,
        "prompt":     "LANG",
    },
    {
        "key":        "spanish_lit",
        "system":     "ap-spanish-lit",
        "name":       "AP Spanish Literature and Culture",
        "subject":    "world-languages",
        "pdf_file":   "ap_spanish_lit.pdf",
        "url":        "https://apcentral.collegeboard.org/media/pdf/ap-spanish-literature-and-culture-course-and-exam-description.pdf",
        "start_page": 25,
        "end_page":   300,
        "prompt":     "LIT_LANG",
    },
    {
        "key":        "french",
        "system":     "ap-french",
        "name":       "AP French Language and Culture",
        "subject":    "world-languages",
        "pdf_file":   "ap_french.pdf",
        "url":        "https://apcentral.collegeboard.org/media/pdf/ap-french-language-and-culture-course-and-exam-description.pdf",
        "start_page": 25,
        "end_page":   300,
        "prompt":     "LANG",
    },
    {
        "key":        "german",
        "system":     "ap-german",
        "name":       "AP German Language and Culture",
        "subject":    "world-languages",
        "pdf_file":   "ap_german.pdf",
        "url":        "https://apcentral.collegeboard.org/media/pdf/ap-german-language-and-culture-course-and-exam-description.pdf",
        "start_page": 25,
        "end_page":   300,
        "prompt":     "LANG",
    },
    {
        "key":        "italian",
        "system":     "ap-italian",
        "name":       "AP Italian Language and Culture",
        "subject":    "world-languages",
        "pdf_file":   "ap_italian.pdf",
        "url":        "https://apcentral.collegeboard.org/media/pdf/ap-italian-language-and-culture-course-and-exam-description.pdf",
        "start_page": 25,
        "end_page":   300,
        "prompt":     "LANG",
    },
    {
        "key":        "japanese",
        "system":     "ap-japanese",
        "name":       "AP Japanese Language and Culture",
        "subject":    "world-languages",
        "pdf_file":   "ap_japanese.pdf",
        "url":        "https://apcentral.collegeboard.org/media/pdf/ap-japanese-language-and-culture-course-and-exam-description.pdf",
        "start_page": 25,
        "end_page":   300,
        "prompt":     "LANG",
    },
    {
        "key":        "chinese",
        "system":     "ap-chinese",
        "name":       "AP Chinese Language and Culture",
        "subject":    "world-languages",
        "pdf_file":   "ap_chinese.pdf",
        "url":        "https://apcentral.collegeboard.org/media/pdf/ap-chinese-language-and-culture-course-and-exam-description.pdf",
        "start_page": 25,
        "end_page":   300,
        "prompt":     "LANG",
    },
    {
        "key":        "latin",
        "system":     "ap-latin",
        "name":       "AP Latin",
        "subject":    "world-languages",
        "pdf_file":   "ap_latin.pdf",
        "url":        "https://apcentral.collegeboard.org/media/pdf/ap-latin-course-and-exam-description.pdf",
        "start_page": 20,
        "end_page":   250,
        "prompt":     "LATIN",
    },
]

ARTS_COURSES = [
    {
        "key":        "music_theory",
        "system":     "ap-music-theory",
        "name":       "AP Music Theory",
        "subject":    "arts",
        "pdf_file":   "ap_music_theory.pdf",
        "url":        "https://apcentral.collegeboard.org/media/pdf/ap-music-theory-course-and-exam-description.pdf",
        "start_page": 20,
        "end_page":   250,
        "prompt":     "MUSIC",
    },
    {
        "key":        "2d_art",
        "system":     "ap-2d-art",
        "name":       "AP 2-D Art and Design",
        "subject":    "arts",
        "pdf_file":   "ap_art_design.pdf",
        "url":        "https://apcentral.collegeboard.org/media/pdf/ap-art-and-design-course-and-exam-description.pdf",
        "start_page": 15,
        "end_page":   150,
        "prompt":     "STUDIO_ART",
    },
    {
        "key":        "3d_art",
        "system":     "ap-3d-art",
        "name":       "AP 3-D Art and Design",
        "subject":    "arts",
        "pdf_file":   "ap_art_design.pdf",
        "url":        "https://apcentral.collegeboard.org/media/pdf/ap-art-and-design-course-and-exam-description.pdf",
        "start_page": 15,
        "end_page":   150,
        "prompt":     "STUDIO_ART",
    },
    {
        "key":        "drawing",
        "system":     "ap-drawing",
        "name":       "AP Drawing",
        "subject":    "arts",
        "pdf_file":   "ap_art_design.pdf",
        "url":        "https://apcentral.collegeboard.org/media/pdf/ap-art-and-design-course-and-exam-description.pdf",
        "start_page": 15,
        "end_page":   150,
        "prompt":     "STUDIO_ART",
    },
]

ALL_COURSES = LANGUAGE_COURSES + ARTS_COURSES

LANG_PROMPT = """\
Extract learning objectives, skill statements, can-do statements, proficiency descriptors, \
and assessment task descriptions from this AP {course_name} Course and Exam Description text.

AP World Language courses use this structure:
  - Learning Objectives coded like INTER-1.A, INTERP-1.B, PRES-1.C (or similar)
  - Enduring Understandings (e.g. "Students can negotiate meaning in spoken interaction")
  - Essential Knowledge bullets under each objective
  - Proficiency benchmarks (Advanced Low, Pre-Advanced, etc.)
  - Exam task types (e.g. "Email Reply", "Conversation", "Presentational Speaking")
  - Themes and recommended contexts

Extract EVERY skill statement, objective, proficiency descriptor, or exam task description \
that describes what students should be able to do. Use the explicit code if present; \
if no code is given, assign a sequential identifier (SKILL-01, SKILL-02, ...).

Return ONLY a JSON array (no other text, no markdown). Each element must have:
  "objective_num" : the code if present, otherwise SKILL-01, SKILL-02, ... (sequential)
  "big_idea"      : the communication mode, theme, or skill domain (e.g. "Interpersonal Communication")
  "objective_text": full text of the skill statement, objective, or descriptor

Return [] only if this page is purely administrative (table of contents, credits, glossary).

TEXT:
{text}
"""

LIT_LANG_PROMPT = """\
Extract learning objectives, skill statements, literary analysis criteria, and assessment \
task descriptions from this AP {course_name} Course and Exam Description text.

AP Literature and Culture language courses use coded learning objectives (e.g. INTERP-1.A, \
INTER-1.B, PRES-1.C, or literary codes like CHR-1.A, NAR-2.B) along with proficiency \
descriptors and exam task types. Also extract Enduring Understandings and Essential Knowledge.

Extract EVERY item that describes what students should be able to do. If no code is given, \
assign a sequential identifier (SKILL-01, SKILL-02, ...).

Return ONLY a JSON array (no other text, no markdown). Each element must have:
  "objective_num" : the code if present, otherwise SKILL-01, SKILL-02, ...
  "big_idea"      : the domain, communication mode, or literary skill area
  "objective_text": full text of the learning objective, skill statement, or descriptor

Return [] only if this page is purely administrative (table of contents, credits, glossary).

TEXT:
{text}
"""

LATIN_PROMPT = """\
Extract learning objectives, skill statements, and reading/analysis competencies from \
this AP Latin Course and Exam Description text.

AP Latin organizes skills around: Reading Comprehension (RC), Translation (TRANS), \
Contextual Analysis (CA), Textual Analysis (TA), Literary Analysis (LA), \
Argumentation (ARG), and Cultural and Historical Contexts (CHC). \
Objectives may be coded (e.g. RC-1.A, TRANS-2.B) or described in prose.

Extract EVERY skill or competency that describes what students should be able to do. \
Use the explicit code if present; otherwise assign SKILL-01, SKILL-02, ...

Return ONLY a JSON array (no other text, no markdown). Each element must have:
  "objective_num" : the code if present, otherwise SKILL-01, SKILL-02, ...
  "big_idea"      : the skill category (e.g. "Reading Comprehension", "Translation")
  "objective_text": full text of the skill or learning objective

Return [] only if this page is purely administrative (table of contents, credits, glossary).

TEXT:
{text}
"""

MUSIC_PROMPT = """\
Extract learning objectives, skill statements, and musical competencies from this \
AP Music Theory Course and Exam Description text.

AP Music Theory organizes skills around: Aural Skills (identifying melodies, harmonies, \
rhythms by ear), Written Theory (notation, voice leading, figured bass, formal analysis), \
and Score Analysis. Skills may be coded (e.g. AURAL-1.A, THEORY-2.B, SA-1.A) or described.

Extract EVERY skill or competency statement. Use the explicit code if present; \
otherwise assign SKILL-01, SKILL-02, ...

Return ONLY a JSON array (no other text, no markdown). Each element must have:
  "objective_num" : the code if present, otherwise SKILL-01, SKILL-02, ...
  "big_idea"      : the skill domain (e.g. "Aural Skills", "Written Theory", "Score Analysis")
  "objective_text": full text of the skill or learning objective

Return [] only if this page is purely administrative (table of contents, credits, glossary).

TEXT:
{text}
"""

STUDIO_ART_PROMPT = """\
Extract learning objectives, portfolio criteria, skill statements, and assessment \
requirements from this AP {course_name} Course and Exam Description text.

AP Studio Art courses assess through three portfolio components: Sustained Investigation, \
Selected Works, and Sustained Investigation Images. Scoring criteria address Inquiry, \
Skill, and Reflection. The course may also describe Artistic Processes and specific \
skill competencies students must demonstrate.

Extract EVERY criterion, skill statement, or requirement that describes what students \
must be able to do or demonstrate. Assign INQ-1, SKILL-1, REFL-1 etc. if coded; \
otherwise use SKILL-01, SKILL-02, ...

Return ONLY a JSON array (no other text, no markdown). Each element must have:
  "objective_num" : the code if present, otherwise SKILL-01, SKILL-02, ...
  "big_idea"      : the portfolio section or skill domain (e.g. "Sustained Investigation", "Inquiry")
  "objective_text": full text of the skill, criterion, or requirement

Return [] only if this page is purely administrative (table of contents, credits, glossary).

TEXT:
{text}
"""

PROMPTS = {
    "LANG":      LANG_PROMPT,
    "LIT_LANG":  LIT_LANG_PROMPT,
    "LATIN":     LATIN_PROMPT,
    "MUSIC":     MUSIC_PROMPT,
    "STUDIO_ART": STUDIO_ART_PROMPT,
}


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


def _call_gemma(text: str, prompt_template: str, course_name: str) -> list[dict]:
    prompt = prompt_template.format(course_name=course_name, text=text[:12000])
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
    objectives: list[dict], system: str, subject: str,
    conn: sqlite3.Connection, seen_ids: set[str],
) -> tuple[int, int]:
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
            (std_id, system, subject, "HS", "9-12",
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

    _keys_env = os.getenv("AP_LANG_KEYS", "")
    _allowed = {k.strip() for k in _keys_env.split(",") if k.strip()} if _keys_env else None

    for course in ALL_COURSES:
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
        subject = course["subject"]
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
                objectives = _call_gemma(chunk_text, PROMPTS[course["prompt"]], course["name"])
            except Exception as e:
                print(f" ERROR: {e}")
                continue
            with conn:
                s, k = _ingest(objectives, system, subject, conn, seen_ids)
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
