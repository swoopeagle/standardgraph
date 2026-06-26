"""Fetch and ingest Finland OPH Perusopetus 2014 math objectives (Grades 1-9).

System: fi-oph
Source: Perusopetuksen opetussuunnitelman perusteet 2014 (POPS 2014)
  National Core Curriculum for Basic Education 2014
  Published by: Opetushallitus (OPH) — Finnish National Agency for Education

Covers basic education (perusopetus):
  Grade band 1-2: Section 13.4.4 Matematiikka (vuosiluokat 1-2)
  Grade band 3-6: Section 14.4.X Matematiikka (vuosiluokat 3-6)
  Grade band 7-9: Section 15.4.4 Matematiikka (vuosiluokat 7-9)

Standards are "Opetuksen tavoitteet" (teaching objectives), coded T1-Tn,
organized into three categories:
  ATT  = Merkitys, arvot ja asenteet (Meaning, values, and attitudes)
  WORK = Työskentelyn taidot (Working skills/mathematical practices)
  CONC = Käsitteelliset ja tiedonalakohtaiset tavoitteet (Conceptual/subject objectives)

Content areas (sisältöalueet) are coded S1-S6:
  S1 = Ajattelun taidot (Thinking skills)
  S2 = Luvut ja laskutoimitukset (Numbers and Operations)
  S3 = Algebra
  S4 = Funktiot (Functions) [grades 3-9]
  S5 = Geometria (Geometry)
  S6 = Tietojen käsittely, tilastot ja todennäköisyys (Data, Statistics, Probability)

ID format: FI_OPH.MATH.G{lo}_{hi}.T{n:02d}
  e.g. FI_OPH.MATH.G1_2.T01
       FI_OPH.MATH.G7_9.T14
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

SYSTEM = "fi-oph"
VERIFIED_DATE = date.today().isoformat()
RAW_DIR = DB_PATH.parent / "raw" / "fi"
PDF_URL = "https://www.oph.fi/sites/default/files/documents/perusopetuksen_opetussuunnitelman_perusteet_2014.pdf"
PDF_FILE = "fi_pops_2014.pdf"

# (section_id, label, grade_str, grade_band, page_start_idx, page_end_idx_exclusive)
GRADE_BANDS = [
    ("G1_2", "Vuosiluokat 1-2 / Grades 1-2", "1", "1-2", 127, 130),
    ("G3_6", "Vuosiluokat 3-6 / Grades 3-6", "3", "3-6", 234, 238),
    ("G7_9", "Vuosiluokat 7-9 / Grades 7-9", "7", "7-9", 373, 376),
]

DOMAIN_MAP = {
    "ATT":  "Mathematical Attitudes and Values",
    "WORK": "Mathematical Working Skills",
    "CONC": "Conceptual and Subject-Specific Objectives",
}

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each",
    "such", "both", "also", "into", "more", "most", "some", "other",
    "these", "those", "about", "able", "after", "where", "while", "make",
    "used", "given", "find", "show", "know", "understand", "apply",
    "students", "student", "numbers", "values", "different",
    "guide", "support", "encourage", "pupils", "pupil", "learning",
}

EXTRACT_PROMPT = """\
Below is text from Finland's National Core Curriculum for Basic Education 2014 (POPS 2014),
the mathematics section for {grade_band_label}.

The mathematics teaching objectives (Opetuksen tavoitteet) are coded T1, T2, T3, etc.
and organized into three categories:

1. Merkitys, arvot ja asenteet (Meaning, values, and attitudes) → category: "ATT"
2. Työskentelyn taidot (Working skills / mathematical practices) → category: "WORK"
3. Käsitteelliset ja tiedonalakohtaiset tavoitteet (Conceptual/subject objectives) → category: "CONC"

Each objective is a statement beginning with a Finnish infinitive verb
(ohjata, tukea, harjaannuttaa, perehdyttää, kannustaa, etc.) describing what
teaching should achieve.

Extract ALL T-numbered objectives (T1, T2, T3, etc.) from the objectives table.
Do NOT include:
- Content area descriptions (S1 Ajattelun taidot: ..., S2 Luvut: ...)
- Assessment criteria sections
- Introductory paragraphs about the subject

Return ONLY a JSON array (no markdown). Each element:
  "t_num"    : integer — the T-number (e.g. 1 for T1, 14 for T14)
  "category" : "ATT", "WORK", or "CONC"
  "text_fi"  : Finnish text verbatim (the full objective statement, trimmed)
  "text_en"  : accurate English translation

MATHEMATICS OBJECTIVES TEXT ({grade_band_label}):
{text}
"""


def _download(url: str, path: Path) -> None:
    print(f"  Downloading {path.name} …")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(path, "wb") as f:
        f.write(r.read())
    print(f"  Saved {path.stat().st_size:,} bytes")


def _extract_pages_text(pdf_path: Path, start_idx: int, end_idx: int) -> str:
    doc = fitz.open(str(pdf_path))
    parts = []
    for i in range(start_idx, min(end_idx, doc.page_count)):
        t = doc[i].get_text().strip()
        # Remove page number line at top
        t = re.sub(r'^\d+\s*\n', '', t)
        # Remove grade band header line
        t = re.sub(r'^VUOSILUOKAT\s+\d[–-]\d+\s*\n', '', t)
        if t.strip():
            parts.append(t.strip())
    doc.close()
    return "\n\n".join(parts)


def _call_model(grade_band_label: str, text: str) -> list[dict]:
    prompt = EXTRACT_PROMPT.format(grade_band_label=grade_band_label, text=text[:10000])
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "keep_alive": "4h",
        "options": {"temperature": 0.0, "num_ctx": 12288},
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

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")

    print(f"Clearing existing {SYSTEM} data …")
    with conn:
        conn.execute("DELETE FROM keywords WHERE standard_id LIKE 'FI_OPH.%'")
        conn.execute("DELETE FROM standards WHERE system = ?", (SYSTEM,))

    seen_ids: set[str] = set()
    grand_std = grand_kw = 0

    for section_id, label, grade, grade_band, pg_start, pg_end in GRADE_BANDS:
        text = _extract_pages_text(pdf_path, pg_start, pg_end)
        print(f"  {section_id} / {label} ({len(text)} chars) → model …", end="", flush=True)
        try:
            objectives = _call_model(label, text)
        except Exception as e:
            print(f" ERROR: {e}")
            continue

        band_std = band_kw = 0
        with conn:
            for obj in objectives:
                t_num = obj.get("t_num")
                category = (obj.get("category") or "").strip().upper()
                text_fi = (obj.get("text_fi") or "").strip()
                text_en = (obj.get("text_en") or "").strip()
                if not t_num or not text_en or len(text_en) < 10:
                    continue
                if category not in ("ATT", "WORK", "CONC"):
                    category = "CONC"
                try:
                    t_int = int(t_num)
                except (TypeError, ValueError):
                    continue

                std_id = f"FI_OPH.MATH.{section_id}.T{t_int:02d}"
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
                        DOMAIN_MAP.get(category, category),
                        text_fi,
                        text_en,
                        VERIFIED_DATE,
                        PDF_URL,
                    ),
                )
                band_std += 1
                for kw in _extract_keywords(text_en + " " + text_fi):
                    conn.execute(
                        "INSERT OR IGNORE INTO keywords (standard_id, keyword) VALUES (?,?)",
                        (std_id, kw),
                    )
                    band_kw += 1

        grand_std += band_std
        grand_kw += band_kw
        print(f" {len(objectives)} extracted, {band_std} ingested")

    conn.close()
    print(f"\nTotal: {grand_std} standards, {grand_kw} keywords")
    print("Done.")


if __name__ == "__main__":
    main()
