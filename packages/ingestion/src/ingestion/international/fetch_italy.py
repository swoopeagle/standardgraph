"""Fetch and ingest Italy MIUR mathematics standards (Grades 1-13).

System: it-miur
Sources:
  Primo ciclo (grades 1-8):
    Indicazioni Nazionali per il Curricolo della Scuola dell'Infanzia e del Primo Ciclo d'Istruzione
    D.M. 16 novembre 2012, n. 254
    https://www.miur.gov.it/documents/20182/51310/DM+254_2012.pdf

  Liceo (grades 9-12):
    Indicazioni Nazionali riguardanti gli obiettivi specifici di apprendimento — Licei
    D.P.R. 15 marzo 2010, n. 89
    https://www.miur.gov.it/documents/20182/0/indicazioni_nazionali_per_i_licei.pdf

Cycle structure:
  Primaria: Classe prima–seconda (gr 1-2), Terza–quarta–quinta (gr 3-5)
  Secondaria I grado: Scuola secondaria di primo grado (gr 6-8)
  Secondaria II grado (Liceo scientifico/classico): gr 9-13

Math domains (Indicazioni Nazionali):
  NUM  = Numeri (Numbers)
  SPA  = Spazio e figure (Space and Geometry)
  REL  = Relazioni e funzioni (Relations and Functions)
  DAT  = Dati e previsioni (Data and Probability)
  ALG  = Algebra [liceo]
  ANAL = Analisi matematica (Analysis) [liceo]
  GEO  = Geometria (Geometry) [liceo]
  PROB = Probabilità e Statistica (Probability and Statistics) [liceo]

The objectives are called:
  "Traguardi per lo sviluppo della competenza" (milestones) — end-of-cycle
  "Obiettivi di apprendimento" (learning objectives) — per period

ID format: IT_MIUR.MATH.{level}.{domain}.{seq:03d}
  e.g. IT_MIUR.MATH.PRIM.NUM.001
       IT_MIUR.MATH.SEC1.REL.003
       IT_MIUR.MATH.LIC.ANAL.002
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

SYSTEM = "it-miur"
VERIFIED_DATE = date.today().isoformat()
RAW_DIR = DB_PATH.parent / "raw" / "it"
SOURCE_URL = "https://www.miur.gov.it/indicazioni-nazionali"

LEVELS = [
    (
        "PRIM", "Scuola Primaria (grades 1–5)",
        "3", "1-5",
        "it_miur_indicazioni_primo_ciclo.pdf",
        "https://www.minori.it/sites/default/files/dm_254_2012_-_allegato_indicazioni_nazionali.pdf",
        0, 999,
    ),
    (
        "SEC1", "Scuola Secondaria di Primo Grado (grades 6–8)",
        "6", "6-8",
        "it_miur_indicazioni_primo_ciclo.pdf",  # same PDF, different section
        "https://www.minori.it/sites/default/files/dm_254_2012_-_allegato_indicazioni_nazionali.pdf",
        0, 999,
    ),
    (
        "LIC", "Liceo — Secondaria di Secondo Grado (grades 9–12)",
        "9", "9-12",
        "it_miur_indicazioni_licei.pdf",
        "https://www.istruzione.it/alternanza/allegati/NORMATIVA%20ASL/INDICAZIONI%20NAZIONALI%20PER%20I%20LICEI.pdf",
        0, 999,
    ),
]

DOMAIN_MAP = {
    "NUM":  "Numbers",
    "SPA":  "Space and Geometry",
    "REL":  "Relations and Functions",
    "DAT":  "Data and Probability",
    "ALG":  "Algebra",
    "ANAL": "Mathematical Analysis",
    "GEO":  "Geometry",
    "PROB": "Probability and Statistics",
    "OTHER": "Other",
}

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each",
    "such", "both", "also", "into", "more", "most", "some", "other",
    "these", "those", "about", "able", "after", "where", "while", "make",
    "used", "given", "find", "show", "know", "understand", "apply",
    "students", "student", "numbers", "values", "different",
}

EXTRACT_PROMPT_PRIMO_CICLO = """\
Below is text from Italy's Indicazioni Nazionali per il Curricolo (D.M. 254/2012),
which defines the national mathematics curriculum for the {level_label}.

The document contains two types of objectives for mathematics:
1. "Traguardi per lo sviluppo della competenza" — end-of-cycle competency milestones
   (bold statements describing what students can do by the end of the cycle)
2. "Obiettivi di apprendimento al termine della classe quinta / terza" — specific
   learning objectives for particular grade periods

Mathematics is organized into 4 nuclei tematici:
  NUM  = Numeri (Numbers and arithmetic operations)
  SPA  = Spazio e figure (Space, geometry, measurement)
  REL  = Relazioni e funzioni (Relations, patterns, functions)
  DAT  = Dati e previsioni (Data handling, probability)

Focus on the {level_label} section of the document.
Extract ALL individual traguardi and obiettivi from that section.

Return ONLY a JSON array (no markdown). Each element:
  "domain_code" : 3-letter code (NUM, SPA, REL, DAT, OTHER)
  "type"        : "traguardo" or "obiettivo"
  "subtopic"    : Italian sub-section heading if present (e.g. "Numeri naturali")
  "text_it"     : Italian text verbatim (trimmed)
  "text_en"     : accurate English translation (preserve mathematical terminology)

If no objectives appear in this text for {level_label}, return [].

TEXT:
{text}
"""

EXTRACT_PROMPT_LICEO = """\
Below is text from Italy's Indicazioni Nazionali riguardanti gli obiettivi specifici
di apprendimento per i Licei (D.P.R. 89/2010), Liceo Scientifico section.

This document defines mathematics objectives for the {level_label}
organized into:
  ALG  = Aritmetica e Algebra (Arithmetic and Algebra)
  GEO  = Geometria (Geometry)
  REL  = Relazioni e funzioni (Relations and Functions)
  DAT  = Dati e previsioni (Data and Statistics)
  ANAL = Analisi matematica (Mathematical Analysis) [second two-year period]
  PROB = Probabilità (Probability)

The objectives are grouped by the "primo biennio" (grades 9-10) and
"secondo biennio e quinto anno" (grades 11-12).

Extract ALL individual objectives (obiettivi specifici di apprendimento).
These appear as bullet points or numbered items within each thematic section.

Return ONLY a JSON array (no markdown). Each element:
  "domain_code" : 4-5 letter code (ALG, GEO, REL, DAT, ANAL, PROB, OTHER)
  "subtopic"    : Italian sub-heading (e.g. "Equazioni e disequazioni", "Calcolo integrale")
  "text_it"     : Italian text verbatim (trimmed)
  "text_en"     : accurate English translation (preserve mathematical terminology)

If no objectives appear in this text, return [].

TEXT ({level_label}):
{text}
"""


def _download(url: str, path: Path) -> bool:
    if path.exists():
        print(f"  Using cached {path.name} ({path.stat().st_size:,} bytes)")
        return True
    print(f"  Downloading {path.name} …")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/pdf,*/*",
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=120) as r, open(path, "wb") as f:
            f.write(r.read())
        print(f"  Saved {path.stat().st_size:,} bytes")
        return True
    except Exception as e:
        print(f"  Download failed: {e}")
        print(f"  → Check URL: {url}")
        return False


def _extract_text(pdf_path: Path) -> str:
    doc = fitz.open(str(pdf_path))
    parts = []
    for i in range(doc.page_count):
        t = doc[i].get_text().strip()
        t = re.sub(r'Ministero dell.Istruzione.*?\n', '', t, flags=re.IGNORECASE)
        t = re.sub(r'^\d+\s*$', '', t, flags=re.MULTILINE)
        if t.strip():
            parts.append(t.strip())
    doc.close()
    return "\n\n".join(parts)


def _call_model(level_label: str, text: str, is_liceo: bool = False) -> list[dict]:
    if is_liceo:
        prompt = EXTRACT_PROMPT_LICEO.format(level_label=level_label, text=text[:14000])
    else:
        prompt = EXTRACT_PROMPT_PRIMO_CICLO.format(level_label=level_label, text=text[:14000])
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "keep_alive": "4h",
        "options": {"temperature": 0.0, "num_ctx": 16384},
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

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")

    print(f"Clearing existing {SYSTEM} data …")
    with conn:
        conn.execute("DELETE FROM keywords WHERE standard_id LIKE 'IT_MIUR.%'")
        conn.execute("DELETE FROM standards WHERE system = ?", (SYSTEM,))

    # Pre-download PDFs
    pdf_files: dict[str, Path] = {}
    for level_code, _, _, _, pdf_file, pdf_url, _, _ in LEVELS:
        path = RAW_DIR / pdf_file
        if path not in pdf_files.values():
            if not _download(pdf_url, path):
                print(f"  WARNING: could not download {pdf_file}")
            pdf_files[pdf_file] = path

    seen_ids: set[str] = set()
    grand_std = grand_kw = 0

    for level_code, level_label, grade, grade_band, pdf_file, _, start_page, end_page in LEVELS:
        pdf_path = RAW_DIR / pdf_file
        if not pdf_path.exists():
            print(f"  SKIP {level_code} — PDF not available")
            continue

        text = _extract_text(pdf_path)
        if not text.strip():
            print(f"  {level_code}: no text extracted — skipping")
            continue

        is_liceo = (level_code == "LIC")
        chunk_size = 14000
        overlap = 500
        chunks = []
        pos = 0
        while pos < len(text):
            chunks.append(text[pos:pos + chunk_size])
            pos += chunk_size - overlap

        print(f"  {level_code} / {level_label} ({len(text)} chars, {len(chunks)} chunk(s))")
        level_std = level_kw = 0

        for ci, chunk in enumerate(chunks):
            print(f"    chunk {ci+1}/{len(chunks)} → model …", end="", flush=True)
            try:
                standards = _call_model(level_label, chunk, is_liceo=is_liceo)
            except Exception as e:
                print(f" ERROR: {e}")
                continue

            with conn:
                for std in standards:
                    domain_code = (std.get("domain_code") or "OTHER").strip().upper()
                    if domain_code not in DOMAIN_MAP:
                        domain_code = "OTHER"
                    subtopic = (std.get("subtopic") or "").strip()
                    text_it = (std.get("text_it") or "").strip()
                    text_en = (std.get("text_en") or "").strip()
                    if not text_en or len(text_en) < 10:
                        continue

                    existing = sum(
                        1 for sid in seen_ids
                        if sid.startswith(f"IT_MIUR.MATH.{level_code}.{domain_code}.")
                    )
                    seq = existing + 1
                    std_id = f"IT_MIUR.MATH.{level_code}.{domain_code}.{seq:03d}"
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
                            DOMAIN_MAP.get(domain_code, domain_code),
                            subtopic,
                            text_en,
                            VERIFIED_DATE,
                            SOURCE_URL,
                        ),
                    )
                    level_std += 1
                    for kw in _extract_keywords(text_en + " " + text_it):
                        conn.execute(
                            "INSERT OR IGNORE INTO keywords (standard_id, keyword) VALUES (?,?)",
                            (std_id, kw),
                        )
                        level_kw += 1

            print(f" {len(standards)} extracted, {level_std} ingested so far")

        grand_std += level_std
        grand_kw += level_kw

    conn.close()
    print(f"\nTotal: {grand_std} standards, {grand_kw} keywords")
    print("Done.")


if __name__ == "__main__":
    main()
