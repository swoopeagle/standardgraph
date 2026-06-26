"""Fetch and ingest Germany KMK Bildungsstandards Mathematik.

System: de-kmk
Sources: KMK Bildungsstandards for Mathematics at 4 exit levels:
  Primary   (grade 4):  2022 update — Primarbereich
  Hauptschule (grade 9):  2004 — Hauptschulabschluss (ESA)
  MSA       (grade 10): 2003 — Mittlerer Schulabschluss
  Abitur    (grade 12): 2012 — Allgemeine Hochschulreife (AHR)

Each document describes competencies expected at the END of the respective level.
Standards are expressed as bullet-point statements under "Die Schülerinnen und Schüler"
(The students).

Organization:
  Process competencies (K1-K6): cross-cutting mathematical practices
  Content domains (Leitideen): topical content standards

Leitideen (Primary, 2022):
  ZO  = Zahl und Operation (Number and Operations)
  GM  = Größen und Messen (Measurement)
  MSF = Muster, Strukturen und funktionaler Zusammenhang (Patterns/Functions)
  RF  = Raum und Form (Space and Shape)
  DZ  = Daten und Zufall (Data and Probability)

Leitideen (Secondary, 2003/2004/2012):
  ZO  = Zahl (Number)
  MO  = Messen (Measurement)
  RF  = Raum und Form (Space and Shape)
  FU  = Funktionaler Zusammenhang (Functional Relationships)
  DZ  = Daten und Zufall (Data and Probability)

Process competencies (K1-K6, all levels):
  K1 = Mathematisch argumentieren (Argumentation)
  K2 = Probleme mathematisch lösen (Problem Solving)
  K3 = Mathematisch modellieren (Modeling)
  K4 = Mathematische Darstellungen verwenden (Representation)
  K5 = Mit symbolischen/formalen Elementen umgehen (Symbolic/Formal)
  K6 = Kommunizieren (Communication)

ID format: DE_KMK.MATH.{level}.{domain}.{seq:03d}
  e.g. DE_KMK.MATH.PRIM.ZO.001
       DE_KMK.MATH.MSA.K2.003
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

SYSTEM = "de-kmk"
VERIFIED_DATE = date.today().isoformat()
RAW_DIR = DB_PATH.parent / "raw" / "de"

LEVELS = [
    (
        "PRIM", "Primary (grades 1-4, Jahrgangsstufe 4 exit)",
        "4", "1-4",
        "de_kmk_bista_primarbereich_mathe.pdf",
        "https://www.kmk.org/fileadmin/Dateien/veroeffentlichungen_beschluesse/2022/2022_06_23-Bista-Primarbereich-Mathe.pdf",
        9,   # start page (0-indexed)
    ),
    (
        "HSA", "Hauptschulabschluss (grade 9 exit)",
        "9", "5-9",
        "de_kmk_bista_haupt_mathe.pdf",
        "https://www.kmk.org/fileadmin/Dateien/veroeffentlichungen_beschluesse/2004/2004_10_15-Bildungsstandards-Mathe-Haupt.pdf",
        7,
    ),
    (
        "MSA", "Mittlerer Schulabschluss (grade 10 exit)",
        "10", "5-10",
        "de_kmk_bista_msa_mathe.pdf",
        "https://www.kmk.org/fileadmin/Dateien/veroeffentlichungen_beschluesse/2003/2003_12_04-Bildungsstandards-Mathe-Mittleren-SA.pdf",
        7,
    ),
    (
        "AHR", "Allgemeine Hochschulreife / Abitur (grade 12 exit)",
        "12", "11-12",
        "de_kmk_bista_abi_mathe.pdf",
        "https://www.kmk.org/fileadmin/Dateien/veroeffentlichungen_beschluesse/2012/2012_10_18-Bildungsstandards-Mathe-Abi.pdf",
        10,
    ),
]

DOMAIN_MAP = {
    "ZO": "Number and Operations",
    "GM": "Measurement",
    "MSF": "Patterns, Structures, and Functional Relationships",
    "RF": "Space and Shape",
    "DZ": "Data and Probability",
    "MO": "Measurement",
    "FU": "Functional Relationships",
    "K1": "Mathematical Argumentation",
    "K2": "Mathematical Problem Solving",
    "K3": "Mathematical Modeling",
    "K4": "Mathematical Representation",
    "K5": "Symbolic and Formal Mathematics",
    "K6": "Mathematical Communication",
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
Below is text from the German KMK Bildungsstandards (National Education Standards) for
Mathematics, {level_label}.

The document describes competencies expected of students at this education level.
Standards appear as bullet-point items under "Die Schülerinnen und Schüler" (The students).

The standards are organized into:

A) PROCESS COMPETENCIES (Prozessbezogene Kompetenzen), coded K1-K6:
  K1 = Mathematisch argumentieren (Mathematical argumentation/reasoning)
  K2 = Probleme mathematisch lösen (Mathematical problem solving)
  K3 = Mathematisch modellieren (Mathematical modeling)
  K4 = Mathematische Darstellungen verwenden (Mathematical representation)
  K5 = Mit symbolischen/formalen Elementen der Mathematik umgehen (Symbolic/formal math)
  K6 = Kommunizieren (Mathematical communication)

B) CONTENT DOMAIN STANDARDS (Inhaltsbezogene Kompetenzen) organized by Leitideen:
  ZO  = Zahl und Operation / Zahl (Number and Operations)
  GM  = Größen und Messen (Measurement) [Primary only, secondary uses MO]
  MO  = Messen (Measurement) [Secondary]
  MSF = Muster, Strukturen und funktionaler Zusammenhang (Patterns/Functions) [Primary]
  FU  = Funktionaler Zusammenhang (Functional Relationships) [Secondary]
  RF  = Raum und Form (Space and Shape/Geometry)
  DZ  = Daten und Zufall (Data and Probability)

Extract ALL individual bullet-point statements (•, –, or −) from both process and
content domain sections. Each statement describes something students can do.
Do NOT include section headers or introductory paragraphs.

Return ONLY a JSON array (no markdown). Each element:
  "domain_code": 2-3 letter code (K1-K6, ZO, GM, MSF, RF, DZ, MO, FU)
  "subdomain"  : German name of the sub-section within the domain (e.g. "Zahldarstellungen und Zahlbeziehungen verstehen")
  "text_de"    : German text verbatim (the full bullet point, trimmed)
  "text_en"    : accurate English translation

STANDARDS TEXT ({level_label}):
{text}
"""


def _download(url: str, path: Path) -> None:
    print(f"  Downloading {path.name} …")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(path, "wb") as f:
        f.write(r.read())
    print(f"  Saved {path.stat().st_size:,} bytes")


def _extract_text(pdf_path: Path, start_page: int) -> str:
    doc = fitz.open(str(pdf_path))
    parts = []
    for i in range(start_page, doc.page_count):
        t = doc[i].get_text().strip()
        # Remove page number lines like "Seite 14" at top
        t = re.sub(r'^Seite \d+\s*\n', '', t)
        # Remove running header lines with BOE/legislation formatting
        t = re.sub(r'^\d{6}\.\d+\s*\n', '', t)
        if t.strip():
            parts.append(t.strip())
    doc.close()
    return "\n\n".join(parts)


def _call_model(level_label: str, text: str) -> list[dict]:
    prompt = EXTRACT_PROMPT.format(level_label=level_label, text=text[:12000])
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
        conn.execute("DELETE FROM keywords WHERE standard_id LIKE 'DE_KMK.%'")
        conn.execute("DELETE FROM standards WHERE system = ?", (SYSTEM,))

    seen_ids: set[str] = set()
    grand_std = grand_kw = 0

    for level_code, level_label, grade, grade_band, pdf_file, pdf_url, start_page in LEVELS:
        pdf_path = RAW_DIR / pdf_file
        if not pdf_path.exists():
            try:
                _download(pdf_url, pdf_path)
            except Exception as e:
                print(f"ERROR downloading {pdf_file}: {e}")
                continue

        text = _extract_text(pdf_path, start_page)
        print(f"  {level_code} / {level_label} ({len(text)} chars) → model …", end="", flush=True)
        try:
            standards = _call_model(level_label, text)
        except Exception as e:
            print(f" ERROR: {e}")
            continue

        level_std = level_kw = 0
        with conn:
            for std in standards:
                domain_code = (std.get("domain_code") or "").strip().upper()
                subdomain = (std.get("subdomain") or "").strip()
                text_de = (std.get("text_de") or "").strip()
                text_en = (std.get("text_en") or "").strip()
                if not domain_code or not text_en or len(text_en) < 10:
                    continue
                # Accept K1-K6, ZO, GM, MSF, RF, DZ, MO, FU
                if not re.match(r'^(K[1-6]|ZO|GM|MSF|RF|DZ|MO|FU)$', domain_code):
                    continue

                # Assign sequence number per domain
                existing = sum(1 for sid in seen_ids
                               if sid.startswith(f"DE_KMK.MATH.{level_code}.{domain_code}."))
                seq = existing + 1
                std_id = f"DE_KMK.MATH.{level_code}.{domain_code}.{seq:03d}"
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
                        pdf_url,
                    ),
                )
                level_std += 1
                for kw in _extract_keywords(text_en + " " + text_de):
                    conn.execute(
                        "INSERT OR IGNORE INTO keywords (standard_id, keyword) VALUES (?,?)",
                        (std_id, kw),
                    )
                    level_kw += 1

        grand_std += level_std
        grand_kw += level_kw
        print(f" {len(standards)} extracted, {level_std} ingested")

    conn.close()
    print(f"\nTotal: {grand_std} standards, {grand_kw} keywords")
    print("Done.")


if __name__ == "__main__":
    main()
