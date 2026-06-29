"""Fetch and ingest Argentina NAP mathematics standards (Grades 1-9).

System: ar-nap
Source: Núcleos de Aprendizajes Prioritarios (NAP) — Ministerio de Educación
  Approved 2004-2007, updated through Resolución CFE n°174/12.
  http://nap.educ.ar/

Covers:
  Primer Ciclo EGB/Primaria: grades 1-3
  Segundo Ciclo EGB/Primaria: grades 4-6
  Tercer Ciclo EGB/ESB: grades 7-9

Math axes (ejes):
  NUM  = Números y operaciones (Numbers and Operations)
  ALG  = Álgebra y funciones (Algebra and Functions) [grades 7-9]
  GEO  = Geometría (Geometry)
  MED  = Magnitudes y medidas (Measurement)
  PROB = Estadística y probabilidad (Statistics and Probability)
  PROC = Procesos matemáticos (Mathematical Processes)

ID format: AR_NAP.MATH.{level}.{axis}.{seq:03d}
  e.g. AR_NAP.MATH.C1.NUM.001  (Primer ciclo, Numbers)
       AR_NAP.MATH.C3.ALG.002  (Tercer ciclo, Algebra)
"""
import json
import re
import sqlite3
import urllib.request
from datetime import date
from pathlib import Path

import ssl

import fitz  # PyMuPDF
import httpx

from shared.config import DB_PATH, OLLAMA_BASE_URL, OLLAMA_MODEL

SYSTEM = "ar-nap"
VERIFIED_DATE = date.today().isoformat()
RAW_DIR = DB_PATH.parent / "raw" / "ar"
SOURCE_URL = "http://nap.educ.ar/matematica"

LEVELS = [
    (
        "C1", "Primer Ciclo — grades 1–3",
        "1", "1-3",
        "ar_nap_math_ciclo1.pdf",
        # Moved from argentina.gob.ar; now hosted at Biblioteca Nacional del Maestro
        "https://www.bnm.me.gov.ar/giga1/documentos/EL000977.pdf",
    ),
    (
        "C2", "Segundo Ciclo — grades 4–6",
        "4", "4-6",
        "ar_nap_math_ciclo2.pdf",
        # Moved from argentina.gob.ar; now hosted at Biblioteca Nacional del Maestro
        "https://www.bnm.me.gov.ar/giga1/documentos/EL000972.pdf",
    ),
    (
        "C3", "Tercer Ciclo/ESB — grades 7–9",
        "7", "7-9",
        "ar_nap_math_ciclo3.pdf",
        # Moved from argentina.gob.ar; now hosted at Biblioteca Nacional del Maestro
        "https://www.bnm.me.gov.ar/giga1/documentos/EL000973.pdf",
    ),
]

AXIS_MAP = {
    "NUM":  "Numbers and Operations",
    "ALG":  "Algebra and Functions",
    "GEO":  "Geometry",
    "MED":  "Measurement",
    "PROB": "Statistics and Probability",
    "PROC": "Mathematical Processes",
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

EXTRACT_PROMPT = """\
Below is text from Argentina's national mathematics curriculum document:
Núcleos de Aprendizajes Prioritarios (NAP), {level_label}.
Published by the Argentine Ministerio de Educación.

These documents define the "núcleos" (priority learning objectives) for mathematics
organized by mathematical axis (eje). The objectives describe what students should
learn during this school cycle.

Argentina NAP math axes (ejes):
  NUM  = Números y operaciones / El número y las operaciones (Numbers and Operations)
  ALG  = Álgebra y funciones (Algebra and Functions)
  GEO  = Geometría / El espacio, las formas (Geometry/Space)
  MED  = Magnitudes y medidas / La medida (Measurement)
  PROB = Estadística y probabilidad (Statistics and Probability)
  PROC = Procesos matemáticos / Razonamiento matemático (Mathematical Processes)

Learning objectives appear as:
  - Bullet points describing what students will learn ("... que los alumnos...")
  - Numbered items under each eje section
  - Phrases starting with verbs: "Reconocer", "Calcular", "Resolver", "Comparar",
    "Construir", "Representar", "Identificar", "Analizar", "Utilizar", etc.

Return ONLY a JSON array (no markdown). Each element:
  "axis_code" : 3-5 letter code (NUM, ALG, GEO, MED, PROB, PROC, OTHER)
  "subtopic"  : sub-section heading in Spanish (e.g. "Números naturales", "Fracciones")
  "text_es"   : Spanish text verbatim (the full learning objective, trimmed)
  "text_en"   : accurate English translation (preserve mathematical terminology)

If no learning objectives appear in this text, return [].

TEXT ({level_label}):
{text}
"""


def _download(url: str, path: Path) -> bool:
    print(f"  Downloading {path.name} …")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/pdf,*/*",
    }
    # bnm.me.gov.ar has a TLS hostname mismatch (government cert covers a different subdomain)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=120, context=ctx) as r, open(path, "wb") as f:
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
        t = re.sub(r'Ministerio de Educaci[oó]n.*?\n', '', t, flags=re.IGNORECASE)
        t = re.sub(r'N[úu]cleos de Aprendizajes Prioritarios.*?\n', '', t, flags=re.IGNORECASE)
        t = re.sub(r'^\d+\s*$', '', t, flags=re.MULTILINE)
        if t.strip():
            parts.append(t.strip())
    doc.close()
    return "\n\n".join(parts)


def _call_model(level_label: str, text: str) -> list[dict]:
    prompt = EXTRACT_PROMPT.format(level_label=level_label, text=text[:14000])
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
        conn.execute("DELETE FROM keywords WHERE standard_id LIKE 'AR_NAP.%'")
        conn.execute("DELETE FROM standards WHERE system = ?", (SYSTEM,))

    seen_ids: set[str] = set()
    grand_std = grand_kw = 0

    for level_code, level_label, grade, grade_band, pdf_file, pdf_url in LEVELS:
        pdf_path = RAW_DIR / pdf_file
        if not pdf_path.exists():
            if not _download(pdf_url, pdf_path):
                print(f"  SKIP {level_code} — download failed")
                continue

        text = _extract_text(pdf_path)
        if not text.strip():
            print(f"  {level_code}: no text extracted — skipping")
            continue

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
                standards = _call_model(level_label, chunk)
            except Exception as e:
                print(f" ERROR: {e}")
                continue

            with conn:
                for std in standards:
                    axis_code = (std.get("axis_code") or "OTHER").strip().upper()
                    if axis_code not in AXIS_MAP:
                        axis_code = "OTHER"
                    subtopic = (std.get("subtopic") or "").strip()
                    text_es = (std.get("text_es") or "").strip()
                    text_en = (std.get("text_en") or "").strip()
                    if not text_en or len(text_en) < 10:
                        continue

                    existing = sum(
                        1 for sid in seen_ids
                        if sid.startswith(f"AR_NAP.MATH.{level_code}.{axis_code}.")
                    )
                    seq = existing + 1
                    std_id = f"AR_NAP.MATH.{level_code}.{axis_code}.{seq:03d}"
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
                            AXIS_MAP.get(axis_code, axis_code),
                            subtopic,
                            text_en,
                            VERIFIED_DATE,
                            SOURCE_URL,
                        ),
                    )
                    level_std += 1
                    for kw in _extract_keywords(text_en + " " + text_es):
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
