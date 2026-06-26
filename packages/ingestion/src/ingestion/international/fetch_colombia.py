"""Fetch and ingest Colombia MEN math standards (Grade bands 1-3 through 10-11).

System: co-men
Source: Estándares Básicos de Competencias (Guía No. 22, 2006)
  PDF: Ministerio de Educación Nacional (mineducacion.gov.co)

Grade bands:
  G01_03 = grades 1-3   (Primero a tercero)
  G04_05 = grades 4-5   (Cuarto a quinto)
  G06_07 = grades 6-7   (Sexto a séptimo)
  G08_09 = grades 8-9   (Octavo a noveno)
  G10_11 = grades 10-11 (Décimo a undécimo)

Strand codes:
  NUM = Pensamiento numérico y sistemas numéricos
  GEO = Pensamiento espacial y sistemas geométricos
  MET = Pensamiento métrico y sistemas de medidas
  VAR = Pensamiento variacional y sistemas algebraicos y analíticos
  ALE = Pensamiento aleatorio y sistemas de datos

ID format: CO_MEN.MATH.G{lo:02d}_{hi:02d}.{strand}.{seq:03d}
  e.g. CO_MEN.MATH.G01_03.NUM.001
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

SYSTEM = "co-men"
VERIFIED_DATE = date.today().isoformat()
RAW_DIR = DB_PATH.parent / "raw" / "co"
PDF_URL = "https://www.mineducacion.gov.co/1759/articles-340021_recurso_1.pdf"
PDF_FILE = "co_estandares_basicos_matematicas.pdf"

# 0-indexed page ranges for each grade band (math section pages 80-89)
GRADE_BANDS = [
    ("G01_03", "1-3",   "1-3",  79, 81),   # pages 80-81 (0-indexed 79-80)
    ("G04_05", "4-5",   "4-5",  81, 83),
    ("G06_07", "6-7",   "6-7",  83, 85),
    ("G08_09", "8-9",   "8-9",  85, 87),
    ("G10_11", "10-11", "10-11", 87, 89),
]

STRAND_MAP = {
    "NUM": "Numbers and Numerical Systems",
    "GEO": "Spatial Thinking and Geometric Systems",
    "MET": "Metric Thinking and Measurement Systems",
    "VAR": "Variational Thinking and Algebraic Systems",
    "ALE": "Random Thinking and Data Systems",
}

STRAND_PATTERNS = [
    (re.compile(r"PENSAMIENTO\s+NUM[ÉE]RICO", re.I), "NUM"),
    (re.compile(r"PENSAMIENTO\s+ESPACIAL",    re.I), "GEO"),
    (re.compile(r"PENSAMIENTO\s+M[ÉE]TRICO", re.I), "MET"),
    (re.compile(r"PENSAMIENTO\s+VARIACIONAL", re.I), "VAR"),
    (re.compile(r"PENSAMIENTO\s+ALEATORIO",   re.I), "ALE"),
]

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each",
    "such", "both", "also", "into", "more", "most", "some", "other",
    "these", "those", "about", "able", "after", "where", "while", "make",
    "used", "given", "find", "show", "know", "understand", "apply",
    "students", "student", "numbers", "values", "different",
}

EXTRACT_PROMPT = """\
Below is the math standards text from Colombia's official curriculum document
(Estándares Básicos de Competencias en Matemáticas, MEN 2006) for grade band {band_label}.

The standards are organized into 5 "pensamientos" (mathematical thinking areas):
  - PENSAMIENTO NUMÉRICO Y SISTEMAS NUMÉRICOS (strand_code: NUM)
  - PENSAMIENTO ESPACIAL Y SISTEMAS GEOMÉTRICOS (strand_code: GEO)
  - PENSAMIENTO MÉTRICO Y SISTEMAS DE MEDIDAS (strand_code: MET)
  - PENSAMIENTO VARIACIONAL Y SISTEMAS ALGEBRAICOS Y ANALÍTICOS (strand_code: VAR)
  - PENSAMIENTO ALEATORIO Y SISTEMAS DE DATOS (strand_code: ALE)

Each standard is a bullet point (starting with "•") under its thinking area heading.
Number them sequentially within each strand (1, 2, 3...).

Return ONLY a JSON array (no markdown). Each element:
  "strand_code" : 3-letter code (NUM, GEO, MET, VAR, ALE)
  "seq"         : integer — sequence number within this strand
  "text_es"     : Spanish text of the standard (verbatim, trimmed, without the bullet •)
  "text_en"     : accurate English translation

TEXT FOR GRADE BAND {band_label}:
{text}
"""


def _download(url: str, path: Path) -> None:
    print(f"  Downloading {path.name} …")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(path, "wb") as f:
        f.write(r.read())
    print(f"  Saved {path.stat().st_size:,} bytes")


def _extract_band_text(pdf_path: Path, page_start: int, page_end: int) -> str:
    doc = fitz.open(str(pdf_path))
    parts = []
    for i in range(page_start, min(page_end, doc.page_count)):
        parts.append(doc[i].get_text())
    doc.close()
    return "\n\n".join(parts)


def _call_model(band_label: str, text: str) -> list[dict]:
    prompt = EXTRACT_PROMPT.format(band_label=band_label, text=text[:12000])
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
        conn.execute("DELETE FROM keywords WHERE standard_id LIKE 'CO_MEN.%'")
        conn.execute("DELETE FROM standards WHERE system = ?", (SYSTEM,))

    seen_ids: set[str] = set()
    grand_std = grand_kw = 0

    for band_id, grade_band, band_label, pg_start, pg_end in GRADE_BANDS:
        text = _extract_band_text(pdf_path, pg_start, pg_end)
        print(f"  Band {band_label} ({len(text)} chars) → model …", end="", flush=True)
        try:
            standards = _call_model(band_label, text)
        except Exception as e:
            print(f" ERROR: {e}")
            continue

        band_std = band_kw = 0
        with conn:
            for std in standards:
                strand_code = (std.get("strand_code") or "").strip().upper()
                seq = std.get("seq")
                text_es = (std.get("text_es") or "").strip()
                text_en = (std.get("text_en") or "").strip()
                if not strand_code or not seq or not text_en or len(text_en) < 15:
                    continue
                if strand_code not in STRAND_MAP:
                    continue
                try:
                    seq_int = int(seq)
                except (TypeError, ValueError):
                    continue

                std_id = f"CO_MEN.MATH.{band_id}.{strand_code}.{seq_int:03d}"
                if std_id in seen_ids:
                    continue
                seen_ids.add(std_id)

                grade_mid = band_label.split("-")[0]

                conn.execute(
                    """INSERT OR REPLACE INTO standards
                       (id, system, subject, grade, grade_band, domain, cluster,
                        standard_text, last_verified_date, source_url)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        std_id, SYSTEM, "mathematics", grade_mid, grade_band,
                        STRAND_MAP[strand_code],
                        text_es,
                        text_en,
                        VERIFIED_DATE,
                        PDF_URL,
                    ),
                )
                band_std += 1
                for kw in _extract_keywords(text_en + " " + text_es):
                    conn.execute(
                        "INSERT OR IGNORE INTO keywords (standard_id, keyword) VALUES (?,?)",
                        (std_id, kw),
                    )
                    band_kw += 1

        grand_std += band_std
        grand_kw += band_kw
        print(f" {len(standards)} extracted, {band_std} ingested")

    conn.close()
    print(f"\nTotal: {grand_std} standards, {grand_kw} keywords")
    print("Done.")


if __name__ == "__main__":
    main()
