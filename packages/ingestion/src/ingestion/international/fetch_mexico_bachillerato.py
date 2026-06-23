"""Fetch and ingest Mexico SEP DGB Bachillerato math standards (grades 10–12).

System: mx-dgb-ems
Source: Dirección General del Bachillerato (DGB) — Educación Media Superior
  PDFs auto-downloaded from dgb.sep.gob.mx/storage/recursos

Covers:
  Grade 10, Semester 1: Matemáticas I   (Bloques I–X, arithmetic/algebra)
  Grade 10, Semester 2: Matemáticas II  (Bloques I–X, geometry/trigonometry)
  Grade 11, Semester 3: Matemáticas III (Bloques I–X, analytic geometry/functions)

Each PDF is a full textbook (~350–490 pages). This script extracts only the
bloque intro pages (~6 pages per bloque) where "¿Qué aprenderás?" objectives
and "Competencias disciplinares" are stated, then uses an LLM to normalise
the objectives into English.

ID format: MX_DGB.MATH.G{grade_key}.B{bloque:02d}.{seq:03d}
  e.g.  MX_DGB.MATH.G10S1.B03.002
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

SYSTEM = "mx-dgb-ems"
VERIFIED_DATE = date.today().isoformat()
RAW_DIR = DB_PATH.parent / "raw" / "mx"

# Textbooks to process: (url, filename, grade_key, human_label, grade_num)
PDF_CONFIGS = [
    (
        "https://dgb.sep.gob.mx/storage/recursos/2024/09/grEdFLFLhJ-Matematicas-I.pdf",
        "mx_bac_matematicas_I.pdf",
        "10S1", "Matemáticas I — Grade 10, Semester 1", "10",
    ),
    (
        "https://dgb.sep.gob.mx/storage/recursos/2024/09/YD78drLFT6-Matematicas-II.pdf",
        "mx_bac_matematicas_II.pdf",
        "10S2", "Matemáticas II — Grade 10, Semester 2", "10",
    ),
    (
        "https://dgb.sep.gob.mx/storage/recursos/2024/09/ZohnhZNF6J-Matematicas-III.pdf",
        "mx_bac_matematicas_III.pdf",
        "11S3", "Matemáticas III — Grade 11, Semester 3", "11",
    ),
]

ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5,
         "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10}

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each",
    "such", "both", "also", "into", "more", "most", "some", "other",
    "these", "those", "about", "able", "after", "where", "while", "make",
    "used", "given", "find", "show", "know", "understand", "apply",
    "students", "student", "problems", "problem", "numbers", "values",
    "different", "various", "through", "between", "involving", "represents",
}

BLOQUE_PROMPT = """\
Below is text extracted from Mexico's official DGB Bachillerato mathematics textbook
"{subject_label}", Bloque {bloque_num} ({bloque_title}).

The text comes from the bloque's introduction pages and may contain:
- CID font encoding artifacts like "(cid:135)" (which is a bullet "•"),
  "(cid:44)(cid:71)..." (garbled glyph sequences), etc. — reconstruct meaning from context.
- "¿Qué aprenderás y cómo?" section: lists specific learning objectives by
  Conceptuales / Procedimentales / Actitudinales categories.
- "Competencias disciplinares" section: broader DGB competency statements.
- "Registro del avance" checklists: competency self-assessment lists.

Extract every individual learning objective/competency that a student is expected
to develop in this bloque. Each bullet point or numbered item is one objective.
Include both specific procedural objectives AND competencias disciplinares.
Skip generic administrative instructions ("Utiliza portada…", "Entregar el…", etc.).

Return ONLY a JSON array (no markdown, no preamble). Each element:
  "obj_text_es" : Spanish text of the objective (reconstruct from garbled CID if needed)
  "obj_text_en" : accurate English translation
  "category"    : "conceptual", "procedural", "attitudinal", or "competencia"

Return [] if no objectives can be extracted.

TEXT:
{text}
"""


def _download(url: str, path: Path) -> None:
    print(f"  Downloading {path.name} …", flush=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
    )
    with urllib.request.urlopen(req, timeout=300) as r, open(path, "wb") as f:
        f.write(r.read())
    print(f"  Saved {path.stat().st_size:,} bytes", flush=True)


def _call_model(prompt: str) -> list[dict]:
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
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as e:
        print(f"    WARN: JSON parse error: {e}", flush=True)
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


def _find_bloques(pdf: pdfplumber.PDF) -> list[tuple[int, str, int]]:
    """Return list of (bloque_num, bloque_title, start_page_0idx), sorted by page.

    Skips the first 18 pages (intro + TOC) where bloque headers appear as
    table-of-contents entries rather than actual section starts.
    """
    ROMAN_PAT = r"(I{1,3}|I?V|VI{0,3}|IX|X)\b"
    found: dict[int, tuple[str, int]] = {}  # num → (title, page_0idx)

    for i, page in enumerate(pdf.pages):
        if i < 5:   # skip only cover/copyright pages; scope tables start around page 6
            continue
        t = page.extract_text() or ""
        m = re.search(r"Bloque\s+" + ROMAN_PAT, t)
        if not m:
            continue
        num = ROMAN.get(m.group(1), 0)
        if num == 0 or num in found:
            continue

        # Title is the first non-trivial line after "Bloque X"
        lines = [l.strip() for l in t.split("\n") if l.strip()]
        bl_idx = next(
            (j for j, l in enumerate(lines) if re.search(r"Bloque\s+" + ROMAN_PAT, l)),
            -1,
        )
        title = ""
        for l in lines[bl_idx + 1 : bl_idx + 5]:
            if (l
                    and not re.match(r"^(I{1,3}|I?V|VI{0,3}|IX|X)$", l)
                    and len(l) > 4
                    and ". . " not in l      # skip TOC leader dots
                    and not l[:1].isdigit()  # skip page-number lines
               ):
                title = l
                break

        found[num] = (title, i)

    # Sort by page order (= correct content order)
    bloques = [(num, title, pg) for num, (title, pg) in found.items()]
    bloques.sort(key=lambda x: x[2])
    return bloques


def _extract_bloque_text(pdf: pdfplumber.PDF, start: int, next_start: int) -> str:
    """Extract text from bloque intro pages (first 8 pages or until next bloque)."""
    end = min(start + 8, next_start, len(pdf.pages))
    parts = []
    for i in range(start, end):
        t = (pdf.pages[i].extract_text() or "").strip()
        if t:
            parts.append(t)
    return "\n\n".join(parts)[:12000]


def _ingest_bloque(
    grade_key: str,
    grade_num: str,
    bloque_num: int,
    bloque_title: str,
    objectives: list[dict],
    conn: sqlite3.Connection,
    seen_ids: set[str],
) -> tuple[int, int]:
    std_count = kw_count = 0
    seq = 0
    for obj in objectives:
        obj_en = (obj.get("obj_text_en") or "").strip()
        obj_es = (obj.get("obj_text_es") or "").strip()
        if not obj_en:
            continue
        # Skip very short or obviously generic entries
        if len(obj_en) < 20:
            continue
        seq += 1
        std_id = f"MX_DGB.MATH.G{grade_key}.B{bloque_num:02d}.{seq:03d}"
        if std_id in seen_ids:
            continue
        seen_ids.add(std_id)

        conn.execute(
            """INSERT OR REPLACE INTO standards
               (id, system, subject, grade, grade_band, domain, cluster,
                standard_text, last_verified_date, source_url)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                std_id, SYSTEM, "mathematics", grade_num, None,
                bloque_title,          # domain = bloque title (English when possible)
                obj.get("category", ""),
                obj_en,
                VERIFIED_DATE,
                "https://dgb.sep.gob.mx/informacion-academica/programas-de-estudio",
            ),
        )
        std_count += 1
        for kw in _extract_keywords(obj_en + " " + obj_es):
            conn.execute(
                "INSERT OR IGNORE INTO keywords (standard_id, keyword) VALUES (?,?)",
                (std_id, kw),
            )
            kw_count += 1

    return std_count, kw_count


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")

    print(f"Clearing existing {SYSTEM} data …")
    with conn:
        conn.execute("DELETE FROM keywords WHERE standard_id LIKE 'MX_DGB.%'")
        conn.execute("DELETE FROM standards WHERE system = ?", (SYSTEM,))

    seen_ids: set[str] = set()
    grand_std = grand_kw = 0

    for url, filename, grade_key, label, grade_num in PDF_CONFIGS:
        pdf_path = RAW_DIR / filename

        if pdf_path.exists():
            print(f"\nUsing cached {filename} ({pdf_path.stat().st_size:,} bytes)")
        else:
            try:
                _download(url, pdf_path)
            except Exception as e:
                print(f"  ERROR downloading {filename}: {e}")
                continue

        print(f"\nProcessing {label} …")
        book_std = book_kw = 0

        with pdfplumber.open(pdf_path) as pdf:
            bloques = _find_bloques(pdf)
            print(f"  Found {len(bloques)} bloques")

            for idx, (bloque_num, bloque_title, start_pg) in enumerate(bloques):
                next_start = bloques[idx + 1][2] if idx + 1 < len(bloques) else len(pdf.pages)
                text = _extract_bloque_text(pdf, start_pg, next_start)

                print(
                    f"  Bloque {bloque_num:2d} ({bloque_title[:40]}) "
                    f"p{start_pg+1}–{min(start_pg+8, next_start)} "
                    f"({len(text)} chars) → model …",
                    end="", flush=True,
                )
                if not text.strip():
                    print(" (no text)")
                    continue

                try:
                    prompt = BLOQUE_PROMPT.format(
                        subject_label=label,
                        bloque_num=bloque_num,
                        bloque_title=bloque_title,
                        text=text,
                    )
                    objectives = _call_model(prompt)
                except Exception as e:
                    print(f" ERROR: {e}")
                    continue

                with conn:
                    s, k = _ingest_bloque(
                        grade_key, grade_num, bloque_num, bloque_title,
                        objectives, conn, seen_ids,
                    )
                book_std += s
                book_kw += k
                print(f" {len(objectives)} extracted, {s} ingested")

        print(f"  Subtotal: {book_std} standards, {book_kw} keywords")
        grand_std += book_std
        grand_kw += book_kw

    conn.close()
    print(f"\nTotal: {grand_std} standards, {grand_kw} keywords")
    print("Done.")


if __name__ == "__main__":
    main()
