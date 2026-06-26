"""Fetch and ingest Brazil BNCC math skills (Grades 1-9).

System: br-bncc
Source: Base Nacional Comum Curricular (BNCC) 2018 — Ensino Fundamental
  PDF: MEC CDN (basenacionalcomum.mec.gov.br)

Covers Ensino Fundamental (grades 1-9):
  EF I  = grades 1-5 (Ensino Fundamental I, ages 6-10)
  EF II = grades 6-9 (Ensino Fundamental II, ages 11-14)

Each skill has an embedded code: (EF{grade:02d}MA{seq:02d})
  EF = Ensino Fundamental
  grade = 01–09
  MA = Matemática
  seq = skill sequence within grade

Math section: pages 281–321 of the 600-page BNCC PDF.

ID format: BR_BNCC.MATH.G{grade:02d}.{seq:03d}
  e.g. BR_BNCC.MATH.G01.001  (grade 1, skill 1)
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

SYSTEM = "br-bncc"
VERIFIED_DATE = date.today().isoformat()
RAW_DIR = DB_PATH.parent / "raw" / "br"
PDF_URL = (
    "https://cdn.mec.gov.br/basenacionalcomum.mec.gov.br/images/"
    "BNCC_EI_EF_110518_versaofinal_site.pdf"
)
PDF_FILE = "bncc_ef_2018.pdf"

# 0-indexed page range containing math habilidades for grades 1-9
MATH_START = 280   # page 281
MATH_END   = 321   # exclusive (page 321 inclusive)

CODE_RE = re.compile(r'\(EF(\d{2})MA(\d{2})\)')

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each",
    "such", "both", "also", "into", "more", "most", "some", "other",
    "these", "those", "about", "able", "after", "where", "while", "make",
    "used", "given", "find", "show", "know", "understand", "apply",
    "students", "student", "number", "numbers", "values", "different",
}

TRANSLATE_PROMPT = """\
Translate each Brazil BNCC mathematics skill from Portuguese to English.
These are official curriculum learning objectives for Ensino Fundamental (grades 1-9).
Preserve mathematical terminology precisely.

Return ONLY a JSON array (no markdown). Each element:
  "code"    : the skill code, e.g. "EF01MA01"
  "text_pt" : original Portuguese text (verbatim)
  "text_en" : accurate English translation

SKILLS:
{skills_text}
"""


def _download(url: str, path: Path) -> None:
    print(f"  Downloading {path.name} …")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
    )
    with urllib.request.urlopen(req, timeout=120) as r, open(path, "wb") as f:
        f.write(r.read())
    print(f"  Saved {path.stat().st_size:,} bytes")


def _extract_skills(pdf_path: Path) -> list[tuple[str, int, int, str]]:
    """Return list of (code, grade, seq, text_pt) from math section."""
    doc = fitz.open(str(pdf_path))
    # Concatenate all math-section pages
    full_text = ""
    for i in range(MATH_START, min(MATH_END, doc.page_count)):
        full_text += (doc[i].get_text() or "") + "\n"
    doc.close()

    # Split on skill codes: everything from one code to the next is the skill text
    parts = CODE_RE.split(full_text)
    # parts layout: [preamble, grade1, seq1, text1, grade2, seq2, text2, ...]
    skills = []
    i = 1
    while i + 2 < len(parts):
        grade = int(parts[i])
        seq = int(parts[i + 1])
        raw_text = parts[i + 2].strip()
        # Trim at the next non-skill content (e.g., section headers, notes)
        # Take text up to two newlines or certain Portuguese section keywords
        m = re.search(r'\n\s*\n', raw_text)
        if m:
            raw_text = raw_text[:m.start()].strip()
        code = f"EF{grade:02d}MA{seq:02d}"
        if raw_text and len(raw_text) > 10:
            skills.append((code, grade, seq, raw_text))
        i += 3

    return skills


def _call_model(skills_batch: list[tuple[str, int, int, str]]) -> list[dict]:
    skills_text = "\n\n".join(
        f"[{code}] {text}" for code, _g, _s, text in skills_batch
    )
    prompt = TRANSLATE_PROMPT.format(skills_text=skills_text[:10000])
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "keep_alive": "4h",
        "options": {"temperature": 0.0, "num_ctx": 8192},
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
        print(f"Using cached {PDF_FILE} ({pdf_path.stat().st_size:,} bytes)")
    else:
        try:
            _download(PDF_URL, pdf_path)
        except Exception as e:
            print(f"ERROR downloading PDF: {e}")
            return

    print("Extracting BNCC math habilidades …")
    try:
        skills = _extract_skills(pdf_path)
    except Exception as e:
        print(f"ERROR extracting skills: {e}")
        return

    print(f"  Found {len(skills)} skills (grades {min(g for _,g,_,_ in skills)}–{max(g for _,g,_,_ in skills)})")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")

    print(f"Clearing existing {SYSTEM} data …")
    with conn:
        conn.execute("DELETE FROM keywords WHERE standard_id LIKE 'BR_BNCC.%'")
        conn.execute("DELETE FROM standards WHERE system = ?", (SYSTEM,))

    seen_ids: set[str] = set()
    grand_std = grand_kw = 0

    # Process in batches of 20 skills
    batch_size = 20
    for b_start in range(0, len(skills), batch_size):
        batch = skills[b_start:b_start + batch_size]
        codes_in_batch = [code for code, _, _, _ in batch]
        print(
            f"  Batch {b_start//batch_size + 1}: skills {codes_in_batch[0]}–{codes_in_batch[-1]} "
            f"→ model …", end="", flush=True,
        )
        try:
            translations = _call_model(batch)
        except Exception as e:
            print(f" ERROR: {e}")
            continue

        # Build lookup from code → (text_pt, text_en)
        trans_map: dict[str, tuple[str, str]] = {}
        for t in translations:
            code = (t.get("code") or "").strip()
            text_en = (t.get("text_en") or "").strip()
            text_pt = (t.get("text_pt") or "").strip()
            if code and text_en:
                trans_map[code] = (text_pt, text_en)

        batch_std = batch_kw = 0
        with conn:
            for code, grade, seq, text_pt in batch:
                text_pt_tr, text_en = trans_map.get(code, (text_pt, ""))
                if not text_en:
                    text_en = ""  # will skip if empty
                if not text_en or len(text_en) < 15:
                    continue

                std_id = f"BR_BNCC.MATH.G{grade:02d}.{seq:03d}"
                if std_id in seen_ids:
                    continue
                seen_ids.add(std_id)

                grade_band = "1-5" if grade <= 5 else "6-9"

                conn.execute(
                    """INSERT OR REPLACE INTO standards
                       (id, system, subject, grade, grade_band, domain, cluster,
                        standard_text, last_verified_date, source_url)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        std_id, SYSTEM, "mathematics", str(grade), grade_band,
                        "Mathematics",  # all skills fall under the single math area
                        text_pt,        # Portuguese original in cluster field
                        text_en,
                        VERIFIED_DATE,
                        "https://basenacionalcomum.mec.gov.br",
                    ),
                )
                batch_std += 1
                for kw in _extract_keywords(text_en + " " + text_pt):
                    conn.execute(
                        "INSERT OR IGNORE INTO keywords (standard_id, keyword) VALUES (?,?)",
                        (std_id, kw),
                    )
                    batch_kw += 1

        grand_std += batch_std
        grand_kw += batch_kw
        print(f" {len(translations)} translated, {batch_std} ingested")

    conn.close()
    print(f"\nTotal: {grand_std} standards, {grand_kw} keywords")
    print("Done.")


if __name__ == "__main__":
    main()
