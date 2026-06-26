"""Fetch and ingest Mexico SEP Aprendizajes Clave 2017 math standards.

Covered system: mx-sep-2017
Source (auto-downloaded from IPMP — Mexico government digital library):
  https://www.ipmp.gob.mx/web/acervo_digital/documentos/Libros%20Digitales%20Coleccion%20AC/Sec-Matematicas.pdf

This is the official "Aprendizajes Clave para la Educación Integral - Matemáticas. Educación
Secundaria" book (SEP 2017). Despite its name, the book contains a complete scope-and-sequence
dosificación table covering ALL basic education levels (Preescolar, Primaria 1–6, Secundaria 1–3).

Two extraction passes:
  1. Dosificación tables (pages 172–177): wide multi-column tables covering all grade cycles.
     Parsed directly via pdfplumber.extract_tables(). Yields cycle-level objectives for:
       grade_band "1-2"  (Primaria Primer Ciclo)
       grade_band "3-4"  (Primaria Segundo Ciclo)
       grade_band "5-6"  (Primaria Tercer Ciclo)
  2. Per-grade secondary pages (178–180): compact tables with grade-specific objectives for
     grades 7, 8, 9 (Secundaria 1°, 2°, 3°). Extracted via text + LLM.

Framework: "Aprendizajes Clave para la Educación Integral" (SEP 2017)
Ejes (Axes):
  NAV — Número, Álgebra y Variación  (Number, Algebra, and Variation)
  FEM — Forma, Espacio y Medida      (Form, Space, and Measurement)
  AD  — Análisis de Datos            (Data Analysis)

ID format: MX_SEP_2017.MATH.G{grade_key}.{eje}.{seq:03d}
  Cycle examples:  MX_SEP_2017.MATH.G1-2.NAV.001
  Single examples: MX_SEP_2017.MATH.G7.NAV.001
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

SYSTEM = "mx-sep-2017"
VERIFIED_DATE = date.today().isoformat()
RAW_DIR = DB_PATH.parent / "raw" / "mx"

PDF_URL = (
    "https://www.ipmp.gob.mx/web/acervo_digital/documentos/"
    "Libros%20Digitales%20Coleccion%20AC/Sec-Matematicas.pdf"
)
PDF_FILENAME = "mx_secundaria_matematicas.pdf"

# Dosificación table spans pages 172–177 (1-based) in 3 left/right pairs.
# Pages 172,174,176 are left halves; pages 173,175,177 are right halves.
# In 0-based indexing:
DOSIFICACION_PAGE_PAIRS = [(171, 172), (173, 174), (175, 176)]

# Per-grade secondary objective pages (0-based) for grades 7 and 8 only.
# Grade 9 (Secundaria 3°) is sourced from the dosificación table instead because
# its per-grade page (p180) is truncated mid-sentence.
PER_GRADE_PAGES = {
    "7": (177, 179),   # pages 178–179 (1-based) → Secundaria 1°
    "8": (178, 180),   # pages 179–180 → Secundaria 2°
}

# Column indices in dosificación tables (0-based)
# Left page (10 columns): 0=EJE, 1=Tema, 2=Pre, [3,4]=merged, 5=Prim1°, 6=Prim2°(merged), 7=Prim3°, 8=Prim4°(merged)
# Right page (6 columns):  0=remnant, 1=Prim5°, 2=Prim6°(merged), 3=Sec1°(G7), 4=Sec2°(G8), 5=Sec3°(G9)
LEFT_GRADE_COLS  = {5: "1-2", 7: "3-4"}           # skip col2=preschool, skip merged cols 6,8
RIGHT_GRADE_COLS = {1: "5-6", 5: "9"}   # grade 9 from dosificación (per-grade page p180 is truncated)

# EJE detection from rotated PDF text artifacts in the EJE column
_NAV_MARKERS = {"OREMÚN", "NÓICAIRAV", "ARBEGLÁ"}
_FEM_MARKERS = {"AMROF", "OICAPSE", "ADIDEM"}
_AD_MARKERS  = {"SISILÁNA", "SOTAD"}

EJE_NAMES_EN = {
    "NAV": "Number, Algebra, and Variation",
    "FEM": "Form, Space, and Measurement",
    "AD":  "Data Analysis",
}

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each",
    "such", "both", "also", "into", "more", "most", "some", "other",
    "these", "those", "about", "able", "after", "where", "while", "make",
    "used", "given", "find", "show", "know", "understand", "apply",
    "students", "student", "problems", "problem", "numbers", "values",
    "different", "various", "through", "between", "involving", "represents",
}

# ── Prompt for secondary per-grade pages ──────────────────────────────────────

PER_GRADE_PROMPT = """\
Below is text extracted from Mexico's official SEP "Aprendizajes Clave 2017" mathematics
curriculum for Secundaria {mx_grade}° (Grade {grade} in the US grade scale).

The text contains PDF layout artifacts such as reversed/rotated words
("NÓICAIRAV", "ARBEGLÁ", "ADIDEM") — ignore those entirely.

Extract each individual aprendizaje esperado (expected learning objective). Each appears
as a bullet point starting with "•". A single bullet may wrap across multiple lines.

Eje (axis) based on the Tema:
  NAV (Número, Álgebra y Variación → "Number, Algebra, and Variation"):
      Temas: Número, Adición y sustracción, Multiplicación y división,
             Proporcionalidad, Ecuaciones, Funciones, Patrones…
  FEM (Forma, Espacio y Medida → "Form, Space, and Measurement"):
      Temas: Ubicación espacial, Figuras y cuerpos geométricos, Magnitudes y medidas
  AD  (Análisis de Datos → "Data Analysis"):
      Temas: Estadística, Probabilidad

Return ONLY a JSON array (no markdown, no preamble). Each element:
  "eje"         : "NAV", "FEM", or "AD"
  "eje_name_en" : English axis name (see above)
  "tema_es"     : Spanish tema name verbatim
  "tema_en"     : English tema name
  "obj_text_es" : full Spanish text of the objective (verbatim from the bullet)
  "obj_text_en" : accurate English translation of the objective

Rules:
- Each bullet (•) → one JSON element.
- Bullets may span multiple lines; concatenate into one string.
- Track the current Tema: once seen, it applies until the next Tema label.
- Skip "Orientaciones didácticas" narrative text — those are not objectives.
- Return [] if no objectives found.

TEXT:
{text}
"""

# ── Prompt for translating dosificación objectives ─────────────────────────────

TRANSLATE_PROMPT = """\
Translate the following Mexican SEP 2017 mathematics curriculum objectives from Spanish to English.
These are from the "Aprendizajes Clave" framework for {grade_label}.

Return ONLY a JSON array with one element per input objective (same order, same count).
Each element:
  "obj_text_es" : the original Spanish text (copy verbatim)
  "obj_text_en" : accurate English translation

Preserve mathematical terminology precisely. Return [] only if the input list is empty.

OBJECTIVES (one per line, prefixed with index):
{objectives_text}
"""


# ── Helpers ────────────────────────────────────────────────────────────────────

def _download(url: str, path: Path) -> None:
    print(f"  Downloading {url} …")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
    )
    with urllib.request.urlopen(req, timeout=120) as r, open(path, "wb") as f:
        f.write(r.read())
    print(f"  Saved {path.stat().st_size:,} bytes → {path.name}")


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
        print(f"    WARN: JSON parse error: {e}")
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


def _detect_eje(raw: str) -> str:
    """Detect eje from the rotated/reversed PDF text in the EJE column."""
    upper = raw.upper()
    if any(m in upper for m in _NAV_MARKERS):
        return "NAV"
    if any(m in upper for m in _FEM_MARKERS):
        return "FEM"
    if any(m in upper for m in _AD_MARKERS):
        return "AD"
    return ""


def _split_bullets(cell: str | None) -> list[str]:
    """Split a table cell containing '• ...' bullets into individual objective strings."""
    if not cell or not cell.strip():
        return []
    # Split on bullet markers (preserve each bullet's full text)
    raw = cell.strip()
    parts = re.split(r'\n?(?=•)', raw)
    results = []
    for p in parts:
        cleaned = p.strip().lstrip('•').strip()
        if cleaned:
            results.append(cleaned)
    return results


# ── Pass 1: Dosificación table extraction ─────────────────────────────────────

def _parse_dosificacion(pdf_path: Path) -> dict[str, list[tuple[str, str, str]]]:
    """Parse the 3 left/right dosificación table pairs.

    Returns {grade_key: [(eje, tema_es, obj_es), ...]}
    grade_key ∈ {"1-2", "3-4", "5-6", "7", "8", "9"}
    """
    grade_objs: dict[str, list[tuple[str, str, str]]] = {
        k: [] for k in ("1-2", "3-4", "5-6", "7", "8", "9")
    }
    current_eje = "NAV"
    current_tema = ""

    with pdfplumber.open(pdf_path) as pdf:
        for left_idx, right_idx in DOSIFICACION_PAGE_PAIRS:
            left_tables  = pdf.pages[left_idx].extract_tables()
            right_tables = pdf.pages[right_idx].extract_tables()
            if not left_tables or not right_tables:
                continue
            left_t  = left_tables[0]
            right_t = right_tables[0]

            for row_idx, left_row in enumerate(left_t):
                if row_idx >= len(right_t):
                    continue
                right_row = right_t[row_idx]

                # Skip table header rows (first 5 rows are column labels)
                if row_idx < 5:
                    continue

                # Update EJE from column 0
                if left_row[0] and left_row[0].strip():
                    detected = _detect_eje(left_row[0])
                    if detected:
                        current_eje = detected

                # Update Tema from column 1
                if left_row[1] and left_row[1].strip():
                    current_tema = left_row[1].strip()

                if not current_tema:
                    continue

                # Harvest left-page grade columns
                for col, gkey in LEFT_GRADE_COLS.items():
                    if col < len(left_row):
                        for obj in _split_bullets(left_row[col]):
                            grade_objs[gkey].append((current_eje, current_tema, obj))

                # Harvest right-page grade columns
                for col, gkey in RIGHT_GRADE_COLS.items():
                    if col < len(right_row):
                        for obj in _split_bullets(right_row[col]):
                            grade_objs[gkey].append((current_eje, current_tema, obj))

    return grade_objs


def _translate_dosificacion(
    grade_key: str, raw_objs: list[tuple[str, str, str]]
) -> list[tuple[str, str, str, str]]:
    """Translate a list of (eje, tema_es, obj_es) → (eje, tema_es, obj_es, obj_en).

    Sends all objectives as a single batch to minimize model round-trips.
    """
    if not raw_objs:
        return []

    band_labels = {"1-2": "Primaria Primer Ciclo (Grades 1–2)",
                   "3-4": "Primaria Segundo Ciclo (Grades 3–4)",
                   "5-6": "Primaria Tercer Ciclo (Grades 5–6)",
                   "7": "Secundaria 1° (Grade 7)",
                   "8": "Secundaria 2° (Grade 8)",
                   "9": "Secundaria 3° (Grade 9)"}
    grade_label = band_labels.get(grade_key, grade_key)

    obj_lines = "\n".join(f"{i+1}. {obj}" for i, (_, _, obj) in enumerate(raw_objs))
    prompt = TRANSLATE_PROMPT.format(grade_label=grade_label, objectives_text=obj_lines)

    translations = _call_model(prompt)

    result = []
    for i, (eje, tema_es, obj_es) in enumerate(raw_objs):
        if i < len(translations):
            obj_en = (translations[i].get("obj_text_en") or "").strip()
        else:
            obj_en = obj_es  # fallback: keep Spanish if translation failed
        result.append((eje, tema_es, obj_es, obj_en))
    return result


# ── Pass 2: Per-grade secondary page extraction ────────────────────────────────

def _extract_secondary_grade(pdf_path: Path, grade: str, start_pg: int, end_pg: int) -> list[dict]:
    """Extract objectives from per-grade secondary pages using LLM."""
    texts = []
    with pdfplumber.open(pdf_path) as pdf:
        for i in range(start_pg, min(end_pg, len(pdf.pages))):
            t = pdf.pages[i].extract_text() or ""
            # Stop at orientaciones section
            if "Orientaciones didácticas" in t and "EjES" not in t:
                break
            if t.strip():
                texts.append(t)
    if not texts:
        return []

    mx_grade = int(grade) - 6   # Grade 7→1°, 8→2°, 9→3°
    prompt = PER_GRADE_PROMPT.format(
        mx_grade=mx_grade,
        grade=grade,
        text="\n\n".join(texts)[:14000],
    )
    return _call_model(prompt)


# ── Ingestion ──────────────────────────────────────────────────────────────────

def _ingest_cycle(
    grade_key: str,
    translated: list[tuple[str, str, str, str]],
    conn: sqlite3.Connection,
    seen_ids: set[str],
) -> tuple[int, int]:
    """Ingest cycle-level dosificación objectives."""
    grade_num   = grade_key.split("-")[0]           # "1-2" → "1"
    grade_band  = grade_key if "-" in grade_key else None

    eje_seqs: dict[str, int] = {"NAV": 0, "FEM": 0, "AD": 0}
    std_count = kw_count = 0

    for eje, tema_es, obj_es, obj_en in translated:
        if not obj_en:
            obj_en = obj_es
        if not obj_en:
            continue
        if eje not in ("NAV", "FEM", "AD"):
            continue

        # Infer English tema name from Spanish (simple lookup)
        tema_en = _tema_en(tema_es)
        eje_seqs[eje] += 1
        std_id = f"MX_SEP_2017.MATH.G{grade_key}.{eje}.{eje_seqs[eje]:03d}"
        if std_id in seen_ids:
            continue
        seen_ids.add(std_id)

        conn.execute(
            """INSERT OR REPLACE INTO standards
               (id, system, subject, grade, grade_band, domain, cluster,
                standard_text, last_verified_date, source_url)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (std_id, SYSTEM, "mathematics", grade_num, grade_band,
             EJE_NAMES_EN.get(eje, eje), tema_en,
             obj_en, VERIFIED_DATE, PDF_URL),
        )
        std_count += 1
        for kw in _extract_keywords(obj_en + " " + obj_es):
            conn.execute(
                "INSERT OR IGNORE INTO keywords (standard_id, keyword) VALUES (?,?)",
                (std_id, kw),
            )
            kw_count += 1

    return std_count, kw_count


def _ingest_secondary(
    grade: str,
    objectives: list[dict],
    conn: sqlite3.Connection,
    seen_ids: set[str],
) -> tuple[int, int]:
    """Ingest per-grade secondary objectives extracted by LLM."""
    eje_seqs: dict[str, int] = {"NAV": 0, "FEM": 0, "AD": 0}
    std_count = kw_count = 0

    for obj in objectives:
        obj_en = (obj.get("obj_text_en") or "").strip()
        obj_es = (obj.get("obj_text_es") or "").strip()
        if not obj_en:
            continue
        eje = (obj.get("eje") or "").strip().upper()
        if eje not in ("NAV", "FEM", "AD"):
            continue
        eje_name = obj.get("eje_name_en") or EJE_NAMES_EN.get(eje, eje)
        tema_en = (obj.get("tema_en") or "").strip()

        eje_seqs[eje] += 1
        std_id = f"MX_SEP_2017.MATH.G{grade}.{eje}.{eje_seqs[eje]:03d}"
        if std_id in seen_ids:
            continue
        seen_ids.add(std_id)

        conn.execute(
            """INSERT OR REPLACE INTO standards
               (id, system, subject, grade, grade_band, domain, cluster,
                standard_text, last_verified_date, source_url)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (std_id, SYSTEM, "mathematics", grade, None,
             eje_name, tema_en,
             obj_en, VERIFIED_DATE, PDF_URL),
        )
        std_count += 1
        for kw in _extract_keywords(obj_en + " " + obj_es):
            conn.execute(
                "INSERT OR IGNORE INTO keywords (standard_id, keyword) VALUES (?,?)",
                (std_id, kw),
            )
            kw_count += 1

    return std_count, kw_count


def _tema_en(tema_es: str) -> str:
    """Map common Spanish tema names to English."""
    _MAP = {
        "número": "Number",
        "adición y sustracción": "Addition and Subtraction",
        "multiplicación y división": "Multiplication and Division",
        "proporcionalidad": "Proportionality",
        "ecuaciones": "Equations",
        "funciones": "Functions",
        "patrones": "Patterns, Geometric Figures, and Equivalent Expressions",
        "ubicación espacial": "Spatial Location",
        "figuras y cuerpos": "Geometric Figures and Solids",
        "figuras y cuerpos geométricos": "Geometric Figures and Solids",
        "magnitudes y medidas": "Magnitudes and Measurement",
        "estadística": "Statistics",
        "probabilidad": "Probability",
    }
    key = tema_es.lower().strip()
    for k, v in _MAP.items():
        if key.startswith(k):
            return v
    return tema_es  # fallback: keep Spanish


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = RAW_DIR / PDF_FILENAME

    if pdf_path.exists():
        print(f"Using cached {pdf_path.name} ({pdf_path.stat().st_size:,} bytes)")
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
        conn.execute("DELETE FROM keywords WHERE standard_id LIKE 'MX_SEP_2017.%'")
        conn.execute("DELETE FROM standards WHERE system = ?", (SYSTEM,))

    seen_ids: set[str] = set()
    grand_std = grand_kw = 0

    # ── Pass 1: Dosificación tables (Grades 1–6 cycle-level + Grade 9) ──────────
    print("\nPass 1: Parsing dosificación tables (Grades 1–6 by cycle + Grade 9)…")
    raw_by_grade = _parse_dosificacion(pdf_path)

    CYCLE_LABELS = {
        "1-2": "Primaria 1°–2°",
        "3-4": "Primaria 3°–4°",
        "5-6": "Primaria 5°–6°",
        "9":   "Secundaria 3° (Grade 9)",
    }
    for grade_key in ("1-2", "3-4", "5-6", "9"):
        raw = raw_by_grade[grade_key]
        label = CYCLE_LABELS[grade_key]
        print(f"  {grade_key} ({label}): {len(raw)} raw objectives → translating …", end="", flush=True)
        if not raw:
            print(" (none found)")
            continue
        try:
            translated = _translate_dosificacion(grade_key, raw)
        except Exception as e:
            print(f" ERROR: {e}")
            continue
        with conn:
            s, k = _ingest_cycle(grade_key, translated, conn, seen_ids)
        grand_std += s
        grand_kw += k
        print(f" {s} ingested, {k} keywords")

    # ── Pass 2: Per-grade secondary pages (Grades 7 and 8 only) ────────────────
    print("\nPass 2: Extracting per-grade secondary objectives (Grades 7–8)…")
    for grade in ("7", "8"):
        start_pg, end_pg = PER_GRADE_PAGES[grade]
        mx_grade = int(grade) - 6
        print(f"  Grade {grade} (Secundaria {mx_grade}°) → model …", end="", flush=True)
        try:
            objectives = _extract_secondary_grade(pdf_path, grade, start_pg, end_pg)
        except Exception as e:
            print(f" ERROR: {e}")
            continue
        with conn:
            s, k = _ingest_secondary(grade, objectives, conn, seen_ids)
        grand_std += s
        grand_kw += k
        print(f" {len(objectives)} extracted, {s} ingested")

    conn.close()
    print(f"\nTotal: {grand_std} standards, {grand_kw} keywords")
    print("Done.")


if __name__ == "__main__":
    main()
