"""Fetch and ingest College Board AP Mathematics courses.

Covered systems:
  ap-calc-ab  — AP Calculus AB
  ap-calc-bc  — AP Calculus BC (superset of AB; includes Units 9–10)
  ap-stats    — AP Statistics
  ap-precalc  — AP Precalculus

Sources (auto-downloaded from College Board):
  Calculus AB/BC: https://apcentral.collegeboard.org/media/pdf/ap-calculus-ab-and-bc-course-and-exam-description.pdf
  Statistics:     https://apcentral.collegeboard.org/media/pdf/ap-statistics-course-and-exam-description.pdf
  Precalculus:    https://apcentral.collegeboard.org/media/pdf/ap-precalculus-course-and-exam-description.pdf

Objective format: Big Idea Code + number (e.g. LIM-2.A, CHA-3.D, VAR-1.B)
IDs: AP.{COURSE}.{objective_num}  e.g. AP.CALC_AB.LIM-2.A
"""
import json
import re
import sqlite3
import time
import urllib.request
from datetime import date
from pathlib import Path

import httpx
import pdfplumber

from shared.config import DB_PATH, OLLAMA_BASE_URL

VERIFIED_DATE = date.today().isoformat()
RAW_DIR = DB_PATH.parent / "raw" / "ap"
OLLAMA_MODEL = "gemma4:31b-it-q8_0"
SOURCE_URL = "https://apcentral.collegeboard.org"

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each",
    "such", "both", "also", "into", "more", "most", "some", "other",
    "these", "those", "about", "able", "after", "where", "while", "make",
    "used", "given", "find", "show", "know", "understand", "apply",
    "students", "student", "should", "calculus", "statistics",
}

# ── Course definitions ─────────────────────────────────────────────────────────

COURSES = [
    {
        "key":       "calc",
        "pdf_file":  "ap_calc_ab_bc.pdf",
        "url":       "https://apcentral.collegeboard.org/media/pdf/ap-calculus-ab-and-bc-course-and-exam-description.pdf",
        "systems":   ["ap-calc-ab", "ap-calc-bc"],
        "start_page": 35,   # skip intro; Unit 1 begins around p36
        "end_page":   215,  # Units 1-10 end; practice exam follows
        "prompt":    "CALC",
    },
    {
        "key":       "stats",
        "pdf_file":  "ap_stats.pdf",
        "url":       "https://apcentral.collegeboard.org/media/pdf/ap-statistics-course-and-exam-description.pdf",
        "systems":   ["ap-stats"],
        "start_page": 25,
        "end_page":   280,
        "prompt":    "STATS",
    },
    {
        "key":       "precalc",
        "pdf_file":  "ap_precalc.pdf",
        "url":       "https://apcentral.collegeboard.org/media/pdf/ap-precalculus-course-and-exam-description.pdf",
        "systems":   ["ap-precalc"],
        "start_page": 25,
        "end_page":   220,
        "prompt":    "PRECALC",
    },
]

# ── Prompts ────────────────────────────────────────────────────────────────────

CALC_PROMPT = """\
Extract all AP Calculus learning objectives from this College Board Course and Exam Description text.

AP Calculus uses this hierarchy:
  Big Ideas: CHA (Change), LIM (Limits and Continuity), FUN (Analysis of Functions)
  Enduring Understandings: e.g. LIM-1, CHA-3
  Learning Objectives: e.g. LIM-2.A, CHA-3.D  ← extract these
  Essential Knowledge: e.g. LIM-2.A.1 (supporting detail, include in text)

The document covers both AB and BC. Units 1-8 are shared; Units 9-10 are BC only.
Some individual topics in Units 1-8 are also BC only (labeled "BC ONLY").

Return ONLY a JSON array. Each element must have:
  "course"        : "AB", "BC", or "both"
  "objective_num" : the learning objective code (e.g. "LIM-2.A")
  "big_idea"      : big idea name (e.g. "Limits and Continuity")
  "objective_text": full text of the learning objective
  "unit"          : unit number as string (e.g. "1", "9")

If no learning objectives appear in this text, return [].
Do NOT include enduring understandings or essential knowledge as separate items.

TEXT:
{text}
"""

STATS_PROMPT = """\
Extract all AP Statistics learning objectives from this College Board Course and Exam Description text.

AP Statistics uses this hierarchy:
  Big Ideas: VAR (Variation and Distribution), UNC (Patterns and Uncertainty),
             DAT (Data-Based Predictions), PRB (Random Processes and Their Outcomes)
  Enduring Understandings: e.g. VAR-1, DAT-2
  Learning Objectives: e.g. VAR-1.A, DAT-2.C  ← extract these
  Essential Knowledge: supporting detail

Return ONLY a JSON array. Each element must have:
  "objective_num" : the learning objective code (e.g. "VAR-1.A")
  "big_idea"      : big idea name (e.g. "Variation and Distribution")
  "objective_text": full text of the learning objective

If no learning objectives appear in this text, return [].

TEXT:
{text}
"""

PRECALC_PROMPT = """\
Extract all AP Precalculus learning objectives from this College Board Course and Exam Description text.

AP Precalculus uses this hierarchy:
  Units: 1 (Polynomial and Rational Functions), 2 (Exponential and Logarithmic Functions),
         3 (Trigonometric and Polar Functions), 4 (Functions Involving Parameters, Vectors, Matrices)
  Learning Objectives are numbered like PCR-1.A, PCR-2.B, etc.
  (PCR = Precalculus, with Big Idea codes like FUN, LIM, etc.)

Return ONLY a JSON array. Each element must have:
  "objective_num" : the learning objective code (e.g. "FUN-1.A")
  "unit"          : unit number as string ("1", "2", "3", or "4")
  "big_idea"      : big idea name
  "objective_text": full text of the learning objective

If no learning objectives appear in this text, return [].

TEXT:
{text}
"""

PROMPTS = {"CALC": CALC_PROMPT, "STATS": STATS_PROMPT, "PRECALC": PRECALC_PROMPT}

# ── Helpers ────────────────────────────────────────────────────────────────────

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


def _call_gemma(text: str, prompt_template: str) -> list[dict]:
    prompt = prompt_template.format(text=text[:5500])
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


def _ingest_calc(objectives: list[dict], conn: sqlite3.Connection, seen_ids: dict[str, set]) -> tuple[int, int]:
    std_count = kw_count = 0
    for obj in objectives:
        obj_text = (obj.get("objective_text") or "").strip()
        obj_num = (obj.get("objective_num") or "").strip()
        if not obj_text or not obj_num:
            continue

        course = (obj.get("course") or "both").strip().lower()
        big_idea = (obj.get("big_idea") or "").strip()
        unit = str(obj.get("unit") or "").strip()

        targets: list[str] = []
        if course in ("ab", "both"):
            targets.append("ap-calc-ab")
        if course in ("bc", "both"):
            targets.append("ap-calc-bc")
        if not targets:
            targets = ["ap-calc-ab", "ap-calc-bc"]

        for system in targets:
            std_id = f"AP.{system.replace('-','_').upper()}.{obj_num}"
            if std_id in seen_ids[system]:
                continue
            seen_ids[system].add(std_id)
            conn.execute(
                """INSERT OR REPLACE INTO standards
                   (id, system, subject, grade, grade_band, domain, cluster,
                    standard_text, last_verified_date, source_url)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (std_id, system, "mathematics", "HS", "9-12",
                 big_idea, f"Unit {unit}" if unit else "", obj_text,
                 VERIFIED_DATE, SOURCE_URL),
            )
            std_count += 1
            for kw in _extract_keywords(obj_text):
                conn.execute("INSERT OR IGNORE INTO keywords (standard_id, keyword) VALUES (?,?)", (std_id, kw))
                kw_count += 1
    return std_count, kw_count


def _ingest_single(objectives: list[dict], system: str, conn: sqlite3.Connection, seen_ids: set) -> tuple[int, int]:
    std_count = kw_count = 0
    for obj in objectives:
        obj_text = (obj.get("objective_text") or "").strip()
        obj_num = (obj.get("objective_num") or "").strip()
        if not obj_text or not obj_num:
            continue
        big_idea = (obj.get("big_idea") or "").strip()
        unit = str(obj.get("unit") or "").strip()
        std_id = f"AP.{system.replace('-','_').upper()}.{obj_num}"
        if std_id in seen_ids:
            continue
        seen_ids.add(std_id)
        conn.execute(
            """INSERT OR REPLACE INTO standards
               (id, system, subject, grade, grade_band, domain, cluster,
                standard_text, last_verified_date, source_url)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (std_id, system, "mathematics", "HS", "9-12",
             big_idea, f"Unit {unit}" if unit else "", obj_text,
             VERIFIED_DATE, SOURCE_URL),
        )
        std_count += 1
        for kw in _extract_keywords(obj_text):
            conn.execute("INSERT OR IGNORE INTO keywords (standard_id, keyword) VALUES (?,?)", (std_id, kw))
            kw_count += 1
    return std_count, kw_count


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    grand_std = grand_kw = 0

    for course in COURSES:
        pdf_path = RAW_DIR / course["pdf_file"]
        if not pdf_path.exists():
            _download(course["url"], pdf_path)

        systems = course["systems"]
        prompt_template = PROMPTS[course["prompt"]]

        # Clear stale records
        with conn:
            for sys in systems:
                prefix = f"AP.{sys.replace('-','_').upper()}."
                conn.execute("DELETE FROM keywords WHERE standard_id LIKE ?", (prefix + "%",))
                conn.execute("DELETE FROM standards WHERE system = ?", (sys,))

        pages = _extract_pages(pdf_path, course["start_page"], course["end_page"])
        chunk_size = 4
        course_std = course_kw = 0

        # seen_ids per system
        if course["key"] == "calc":
            seen_ids: dict | set = {"ap-calc-ab": set(), "ap-calc-bc": set()}
        else:
            seen_ids = set()

        print(f"\nExtracting {', '.join(systems)} ({len(pages)} content pages)...")

        for i in range(0, len(pages), chunk_size):
            chunk = pages[i:i + chunk_size]
            chunk_text = "\n\n".join(t for _, t in chunk)
            page_nums = f"{chunk[0][0]}-{chunk[-1][0]}"
            print(f"  pages {page_nums}: {len(chunk_text)} chars → Gemma...", end="", flush=True)
            try:
                objectives = _call_gemma(chunk_text, prompt_template)
            except Exception as e:
                print(f" ERROR: {e}")
                continue

            with conn:
                if course["key"] == "calc":
                    s, k = _ingest_calc(objectives, conn, seen_ids)
                else:
                    s, k = _ingest_single(objectives, systems[0], conn, seen_ids)

            course_std += s
            course_kw += k
            if objectives:
                print(f" {len(objectives)} extracted, {s} ingested")
            else:
                print(f" 0 extracted")
            time.sleep(0.3)

        print(f"  Total: {course_std} standards, {course_kw} keywords")
        grand_std += course_std
        grand_kw += course_kw

    conn.close()
    print(f"\nGrand total: {grand_std} standards, {grand_kw} keywords")
    print("Done.")


if __name__ == "__main__":
    main()
