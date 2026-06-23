"""Fetch and ingest Peru MINEDU CNEB 2016 math standards (Grades 1-11).

System: pe-minedu
Source: Currículo Nacional de la Educación Básica (CNEB) 2016
  PDF: Ministerio de Educación del Perú (minedu.gob.pe)

4 mathematical competencies, each with 8 learning standard levels (Niveles):
  Level D  → Nivel Destacado (above grade)
  Level 7  → End of Ciclo VII (grades 9-11)
  Level 6  → End of Ciclo VI (grades 7-8)
  Level 5  → End of Ciclo V (grades 5-6)
  Level 4  → End of Ciclo IV (grades 3-4)
  Level 3  → End of Ciclo III (grades 1-2)
  Level 2  → End of Ciclo II (preschool)
  Level 1  → End of Ciclo I (early childhood)

Competency codes:
  CNT = Resuelve problemas de cantidad (Numbers/Quantity)
  REG = Resuelve problemas de regularidad, equivalencia y cambio (Algebra/Patterns)
  GDI = Resuelve problemas de gestión de datos e incertidumbre (Data/Statistics)
  FML = Resuelve problemas de forma, movimiento y localización (Geometry)

ID format: PE_MINEDU.MATH.{comp}.L{level:02d}
  e.g. PE_MINEDU.MATH.CNT.L05  (Quantity, Nivel 5 = end of grades 5-6)
  Nivel Destacado → L08, Nivel 7 → L07, ..., Nivel 1 → L01
"""
import json
import re
import sqlite3
from datetime import date
from pathlib import Path

import fitz  # PyMuPDF
import httpx

from shared.config import DB_PATH, OLLAMA_BASE_URL, OLLAMA_MODEL

SYSTEM = "pe-minedu"
VERIFIED_DATE = date.today().isoformat()
RAW_DIR = DB_PATH.parent / "raw" / "pe"
PDF_URL = "https://www.minedu.gob.pe/curriculo/pdf/curriculo-nacional-de-la-educacion-basica.pdf"
PDF_FILE = "cneb_2016.pdf"

# Competency definitions: (code, name_es, name_en, 0-indexed page of standards text)
COMPETENCIES = [
    ("CNT", "Resuelve problemas de cantidad",
     "Solves quantity problems (Numbers & Operations)", 136),
    ("REG", "Resuelve problemas de regularidad, equivalencia y cambio",
     "Solves regularity, equivalence and change problems (Algebra & Patterns)", 140),
    ("GDI", "Resuelve problemas de gestión de datos e incertidumbre",
     "Solves data management and uncertainty problems (Statistics & Probability)", 144),
    ("FML", "Resuelve problemas de forma, movimiento y localización",
     "Solves shape, movement and location problems (Geometry)", 148),
]

# Nivel → (level_int, grade_band, grade_repr)
LEVEL_MAP = {
    8: ("L08", "above",  "above"),   # Destacado
    7: ("L07", "9-11",   "9"),
    6: ("L06", "7-8",    "7"),
    5: ("L05", "5-6",    "5"),
    4: ("L04", "3-4",    "3"),
    3: ("L03", "1-2",    "1"),
    2: ("L02", "preschool", "0"),
    1: ("L01", "preschool", "0"),
}

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each",
    "such", "both", "also", "into", "more", "most", "some", "other",
    "these", "those", "about", "able", "after", "where", "while", "make",
    "used", "given", "find", "show", "know", "understand", "apply",
    "students", "student", "numbers", "values", "different", "problems",
}

EXTRACT_PROMPT = """\
Below is the learning standards text from Peru's official mathematics curriculum
(Currículo Nacional de la Educación Básica, MINEDU 2016) for the competency:
"{comp_name_es}"

The text contains exactly 8 standards, one per "nivel" (learning level), ordered
from HIGHEST (Nivel Destacado, above grade level) to LOWEST (Nivel 1, early childhood).

Level mapping (highest to lowest):
  Nivel D (Destacado) → level 8  (above grade level)
  Nivel 7 → level 7  (grades 9-11)
  Nivel 6 → level 6  (grades 7-8)
  Nivel 5 → level 5  (grades 5-6)
  Nivel 4 → level 4  (grades 3-4)
  Nivel 3 → level 3  (grades 1-2)
  Nivel 2 → level 2  (preschool)
  Nivel 1 → level 1  (early childhood)

Some lower levels (1, 2) may just say "Este nivel tiene como base..." — include them as-is.
Ignore the diagram legend at the end (lines like "1 D D 4 7 3 2 5 6 DESCRIPCIÓN...").

Return ONLY a JSON array (no markdown). Each element:
  "level"  : integer 1-8 (8=Destacado, 7=highest grade, 1=lowest)
  "text_es": Spanish text verbatim (the full paragraph, trimmed)
  "text_en": accurate English translation (keep mathematical terminology)

STANDARDS TEXT:
{text}
"""


def _download(url: str, path: Path) -> None:
    import urllib.request
    print(f"  Downloading {path.name} …")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=180) as r, open(path, "wb") as f:
        f.write(r.read())
    print(f"  Saved {path.stat().st_size:,} bytes")


def _extract_page_text(pdf_path: Path, page_idx: int) -> str:
    doc = fitz.open(str(pdf_path))
    t = doc[page_idx].get_text()
    doc.close()
    # Remove the header "Currículo Nacional cn" / "Ministerio de Educación"
    t = re.sub(r'^Curr[ií]culo Nacional cn\s*', '', t.strip())
    t = re.sub(r'Ministerio de Educaci[óo]n\s*', '', t)
    return t.strip()


def _call_model(comp_name_es: str, text: str) -> list[dict]:
    prompt = EXTRACT_PROMPT.format(comp_name_es=comp_name_es, text=text[:10000])
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

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")

    print(f"Clearing existing {SYSTEM} data …")
    with conn:
        conn.execute("DELETE FROM keywords WHERE standard_id LIKE 'PE_MINEDU.%'")
        conn.execute("DELETE FROM standards WHERE system = ?", (SYSTEM,))

    seen_ids: set[str] = set()
    grand_std = grand_kw = 0

    for comp_code, comp_name_es, comp_name_en, page_idx in COMPETENCIES:
        text = _extract_page_text(pdf_path, page_idx)
        print(f"  {comp_code} ({len(text)} chars) → model …", end="", flush=True)
        try:
            standards = _call_model(comp_name_es, text)
        except Exception as e:
            print(f" ERROR: {e}")
            continue

        comp_std = comp_kw = 0
        with conn:
            for std in standards:
                level = std.get("level")
                text_es = (std.get("text_es") or "").strip()
                text_en = (std.get("text_en") or "").strip()
                if not level or not text_en or len(text_en) < 15:
                    continue
                try:
                    level_int = int(level)
                except (TypeError, ValueError):
                    continue
                if level_int not in LEVEL_MAP:
                    continue

                level_code, grade_band, grade_repr = LEVEL_MAP[level_int]
                std_id = f"PE_MINEDU.MATH.{comp_code}.{level_code}"
                if std_id in seen_ids:
                    continue
                seen_ids.add(std_id)

                conn.execute(
                    """INSERT OR REPLACE INTO standards
                       (id, system, subject, grade, grade_band, domain, cluster,
                        standard_text, last_verified_date, source_url)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        std_id, SYSTEM, "mathematics", grade_repr, grade_band,
                        comp_name_en,
                        text_es,
                        text_en,
                        VERIFIED_DATE,
                        PDF_URL,
                    ),
                )
                comp_std += 1
                for kw in _extract_keywords(text_en + " " + text_es):
                    conn.execute(
                        "INSERT OR IGNORE INTO keywords (standard_id, keyword) VALUES (?,?)",
                        (std_id, kw),
                    )
                    comp_kw += 1

        grand_std += comp_std
        grand_kw += comp_kw
        print(f" {len(standards)} extracted, {comp_std} ingested")

    conn.close()
    print(f"\nTotal: {grand_std} standards, {grand_kw} keywords")
    print("Done.")


if __name__ == "__main__":
    main()
