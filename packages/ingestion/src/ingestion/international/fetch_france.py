"""Fetch and ingest France MEN mathematics programs (Grades 1-12).

System: fr-men
Sources:
  Cycles 2+3+4 (grades 1-9): Programmes de mathématiques, BO spécial n°11
    du 26 novembre 2015 (updated July 2018 for cycle 4 algebra)
    https://eduscol.education.fr/document/8398/download  (cycles 2+3+4 combined)
  Lycée (grades 10-12): Programme de mathématiques — Bac général 2019
    https://www.education.gouv.fr/sites/default/files/2019-07/programme-mathematiques-lycee-general-108944.pdf

Cycle structure:
  Cycle 2: CP, CE1, CE2 → grades 1-3
  Cycle 3: CM1, CM2, 6e → grades 4-6 (spans primary to collège)
  Cycle 4: 5e, 4e, 3e  → grades 7-9  (collège)
  Lycée Spécialité: 2nde, 1ère, Terminale → grades 10-12

Math domains (cycles 2+3+4):
  NC  = Nombres et calculs (Numbers and Operations)
  GM  = Grandeurs et mesures (Measurement)
  EG  = Espace et géométrie (Space and Geometry)
  RF  = Relations et fonctions (Relations and Functions) [cycle 3+]
  ALG = Algèbre (Algebra) [cycle 4 addition 2018]

Lycée topics: Analyse (Analysis), Algèbre/Géométrie, Probabilités et Statistiques

ID format: FR_MEN.MATH.{level}.{domain}.{seq:03d}
  e.g. FR_MEN.MATH.C2.NC.001   (Cycle 2, Numbers and Operations)
       FR_MEN.MATH.LYC.PROBA.003
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

SYSTEM = "fr-men"
VERIFIED_DATE = date.today().isoformat()
RAW_DIR = DB_PATH.parent / "raw" / "fr"
SOURCE_URL = "https://eduscol.education.fr/729/programmes-et-ressources-en-mathematiques"

# (level_code, label, grade, grade_band, pdf_file, pdf_url, start_page, end_page)
LEVELS = [
    (
        "C2", "Cycle 2 — CP, CE1, CE2 (grades 1–3)",
        "1", "1-3",
        "fr_men_maths_cycle2.pdf",
        "https://cache.media.education.gouv.fr/file/MEN_SPE_11/75/6/Programme_cycle_2_pour_B.O._1424756.pdf",
        0, 999,
    ),
    (
        "C3", "Cycle 3 — CM1, CM2, 6e (grades 4–6)",
        "4", "4-6",
        "fr_men_maths_cycle3.pdf",
        "https://eduscol.education.fr/document/8399/download",
        0, 999,
    ),
    (
        "C4", "Cycle 4 — 5e, 4e, 3e (grades 7–9)",
        "7", "7-9",
        "fr_men_maths_cycle4.pdf",
        "https://pedagogie.ac-strasbourg.fr/fileadmin/pedagogie/mathematiques/College/Programmes_Documents_officiels/Maths_cycle4_BO_SPE_11_26-11-2015.pdf",
        0, 999,
    ),
    (
        "LYC", "Lycée Spécialité Mathématiques (grades 10–12)",
        "10", "10-12",
        "fr_men_maths_lycee.pdf",
        "https://cache.media.education.gouv.fr/file/SPE8_MENJ_25_7_2019/90/7/spe246_annexe_1158907.pdf",
        0, 999,
    ),
]

DOMAIN_MAP = {
    "NC":    "Numbers and Operations",
    "GM":    "Measurement",
    "EG":    "Space and Geometry",
    "RF":    "Relations and Functions",
    "ALG":   "Algebra",
    "ANAL":  "Analysis",
    "PROBA": "Probability and Statistics",
    "GEO":   "Geometry",
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
Below is text from the French national mathematics curriculum (Programmes de mathématiques),
{level_label}, published by the Ministère de l'Éducation Nationale (MEN).

The document contains learning objectives (attendus de fin de cycle / compétences attendues)
organized by mathematical domain. These are the expected outcomes for students at this level.

French mathematics domains in this program:
  NC   = Nombres et calculs (Numbers and Operations)
  GM   = Grandeurs et mesures (Measurement)
  EG   = Espace et géométrie (Space and Geometry)
  RF   = Relations et fonctions (Relations and Functions)  [cycles 3+]
  ALG  = Algèbre (Algebra)  [cycle 4+]
  ANAL = Analyse (Analysis) [lycée only]
  PROBA= Probabilités et statistiques (Probability and Statistics) [cycle 4+]
  GEO  = Géométrie (Geometry) [lycée only]

Extract ALL individual learning objectives/outcomes from the text. These appear as:
  - Bullet points (•, –, −) or numbered items under "Attendus de fin de cycle" or "Les élèves apprennent à..."
  - Descriptions starting with "Connaître", "Calculer", "Résoudre", "Reconnaître",
    "Comparer", "Utiliser", "Représenter", "Maîtriser", etc.
  - In lycée: objectives under each theme (Analyse, Algèbre, Probabilités, Géométrie)

Return ONLY a JSON array (no markdown). Each element:
  "domain_code" : 2-5 letter code (NC, GM, EG, RF, ALG, ANAL, PROBA, GEO, OTHER)
  "subdomain"   : sub-section heading in French (e.g. "Addition et soustraction", "Fractions")
  "text_fr"     : French text verbatim (the full learning objective, trimmed)
  "text_en"     : accurate English translation (preserve mathematical terminology)

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
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=120) as r, open(path, "wb") as f:
            data = r.read()
            f.write(data)
        print(f"  Saved {path.stat().st_size:,} bytes")
        return True
    except Exception as e:
        print(f"  Download failed: {e}")
        print(f"  → Check URL: {url}")
        return False


def _extract_text(pdf_path: Path, start_page: int, end_page: int) -> str:
    doc = fitz.open(str(pdf_path))
    parts = []
    for i in range(start_page, min(end_page, doc.page_count)):
        t = doc[i].get_text().strip()
        # Remove common French BO header/footer patterns
        t = re.sub(r'Bulletin officiel.*?\n', '', t, flags=re.IGNORECASE)
        t = re.sub(r'Ministère de l.éducation.*?\n', '', t, flags=re.IGNORECASE)
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
        conn.execute("DELETE FROM keywords WHERE standard_id LIKE 'FR_MEN.%'")
        conn.execute("DELETE FROM standards WHERE system = ?", (SYSTEM,))

    seen_ids: set[str] = set()
    grand_std = grand_kw = 0

    for level_code, level_label, grade, grade_band, pdf_file, pdf_url, start_page, end_page in LEVELS:
        pdf_path = RAW_DIR / pdf_file
        if not pdf_path.exists():
            if not _download(pdf_url, pdf_path):
                print(f"  SKIP {level_code} — download failed")
                continue

        text = _extract_text(pdf_path, start_page, end_page)
        if not text.strip():
            print(f"  {level_code}: no text extracted from PDF — skipping")
            continue

        # Process in chunks of ~14k chars to stay within context window
        chunk_size = 14000
        overlap = 500
        level_std = level_kw = 0
        chunks = []
        pos = 0
        while pos < len(text):
            chunks.append(text[pos:pos + chunk_size])
            pos += chunk_size - overlap

        print(f"  {level_code} / {level_label} ({len(text)} chars, {len(chunks)} chunk(s))")
        for ci, chunk in enumerate(chunks):
            print(f"    chunk {ci+1}/{len(chunks)} → model …", end="", flush=True)
            try:
                standards = _call_model(level_label, chunk)
            except Exception as e:
                print(f" ERROR: {e}")
                continue

            with conn:
                for std in standards:
                    domain_code = (std.get("domain_code") or "OTHER").strip().upper()
                    if domain_code not in DOMAIN_MAP:
                        domain_code = "OTHER"
                    subdomain = (std.get("subdomain") or "").strip()
                    text_fr = (std.get("text_fr") or "").strip()
                    text_en = (std.get("text_en") or "").strip()
                    if not text_en or len(text_en) < 10:
                        continue

                    existing = sum(
                        1 for sid in seen_ids
                        if sid.startswith(f"FR_MEN.MATH.{level_code}.{domain_code}.")
                    )
                    seq = existing + 1
                    std_id = f"FR_MEN.MATH.{level_code}.{domain_code}.{seq:03d}"
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
                            subdomain,
                            text_en,
                            VERIFIED_DATE,
                            SOURCE_URL,
                        ),
                    )
                    level_std += 1
                    for kw in _extract_keywords(text_en + " " + text_fr):
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
