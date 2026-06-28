"""Fetch and ingest Portugal DGE mathematics programs (Grades 1-12).

System: pt-dge
Source: Direção-Geral da Educação (DGE) — Aprendizagens Essenciais (2018)
  These replaced the earlier Metas Curriculares and Programas de Matemática.
  https://www.dge.mec.pt/aprendizagens-essenciais-ensino-basico

Covers:
  1º Ciclo do Ensino Básico: grades 1-4
  2º Ciclo do Ensino Básico: grades 5-6
  3º Ciclo do Ensino Básico: grades 7-9
  Ensino Secundário: grades 10-11 (Matemática A or B)

Math domains:
  NO  = Números e Operações (Numbers and Operations)
  GEO = Geometria e Medida (Geometry and Measurement)
  ALG = Álgebra (Algebra) [2nd cycle+]
  OTD = Organização e Tratamento de Dados (Data Handling/Statistics)
  FUN = Funções e Gráficos (Functions and Graphs) [secondary]
  CAL = Cálculo (Calculus) [secondary]
  OTHER = Other

ID format: PT_DGE.MATH.{level}.{domain}.{seq:03d}
  e.g. PT_DGE.MATH.C1.NO.001  (1st cycle, Numbers)
       PT_DGE.MATH.SEC.ALG.003 (Secondary, Algebra)
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

SYSTEM = "pt-dge"
VERIFIED_DATE = date.today().isoformat()
RAW_DIR = DB_PATH.parent / "raw" / "pt"
SOURCE_URL = "https://www.dge.mec.pt/aprendizagens-essenciais-ensino-basico"

# Aprendizagens Essenciais (2018) — per-grade PDFs on dge.mec.pt
# URL pattern: https://www.dge.mec.pt/sites/default/files/Curriculo/Aprendizagens_Essenciais/
LEVELS = [
    (
        "C1_G1", "1º Ciclo — Grade 1 (1.º ano)",
        "1", "1-4",
        "pt_dge_ae_math_1ano.pdf",
        "https://www.dge.mec.pt/sites/default/files/Curriculo/Aprendizagens_Essenciais/1_ciclo/ae_mat_1.o_ano.pdf",
    ),
    (
        "C1_G2", "1º Ciclo — Grade 2 (2.º ano)",
        "2", "1-4",
        "pt_dge_ae_math_2ano.pdf",
        "https://www.dge.mec.pt/sites/default/files/Curriculo/Aprendizagens_Essenciais/1_ciclo/ae_mat_2.o_ano.pdf",
    ),
    (
        "C1_G3", "1º Ciclo — Grade 3 (3.º ano)",
        "3", "1-4",
        "pt_dge_ae_math_3ano.pdf",
        "https://www.dge.mec.pt/sites/default/files/Curriculo/Aprendizagens_Essenciais/1_ciclo/ae_mat_3.o_ano.pdf",
    ),
    (
        "C1_G4", "1º Ciclo — Grade 4 (4.º ano)",
        "4", "1-4",
        "pt_dge_ae_math_4ano.pdf",
        "https://www.dge.mec.pt/sites/default/files/Curriculo/Aprendizagens_Essenciais/1_ciclo/ae_mat_4.o_ano.pdf",
    ),
    (
        "C2_G5", "2º Ciclo — Grade 5 (5.º ano)",
        "5", "5-6",
        "pt_dge_ae_math_5ano.pdf",
        "https://www.dge.mec.pt/sites/default/files/Curriculo/Aprendizagens_Essenciais/2_ciclo/ae_mat_5.o_ano.pdf",
    ),
    (
        "C2_G6", "2º Ciclo — Grade 6 (6.º ano)",
        "6", "5-6",
        "pt_dge_ae_math_6ano.pdf",
        "https://www.dge.mec.pt/sites/default/files/Curriculo/Aprendizagens_Essenciais/2_ciclo/ae_mat_6.o_ano.pdf",
    ),
    (
        "C3_G7", "3º Ciclo — Grade 7 (7.º ano)",
        "7", "7-9",
        "pt_dge_ae_math_7ano.pdf",
        "https://www.dge.mec.pt/sites/default/files/Curriculo/Aprendizagens_Essenciais/3_ciclo/ae_mat_7.o_ano.pdf",
    ),
    (
        "C3_G8", "3º Ciclo — Grade 8 (8.º ano)",
        "8", "7-9",
        "pt_dge_ae_math_8ano.pdf",
        "https://www.dge.mec.pt/sites/default/files/Curriculo/Aprendizagens_Essenciais/3_ciclo/ae_mat_8.o_ano.pdf",
    ),
    (
        "C3_G9", "3º Ciclo — Grade 9 (9.º ano)",
        "9", "7-9",
        "pt_dge_ae_math_9ano.pdf",
        "https://www.dge.mec.pt/sites/default/files/Curriculo/Aprendizagens_Essenciais/3_ciclo/ae_mat_9.o_ano.pdf",
    ),
    (
        "SEC_G10", "Ensino Secundário — Grade 10 (10.º ano Matemática A)",
        "10", "10-12",
        "pt_dge_ae_math_10ano.pdf",
        "https://www.dge.mec.pt/sites/default/files/Curriculo/Aprendizagens_Essenciais/mat_a_10_-_vf.pdf",
    ),
    (
        "SEC_G11", "Ensino Secundário — Grade 11 (11.º ano Matemática A)",
        "11", "10-12",
        "pt_dge_ae_math_11ano.pdf",
        "https://www.dge.mec.pt/sites/default/files/Curriculo/Aprendizagens_Essenciais/11_matematica_a.pdf",
    ),
    (
        "SEC_G12", "Ensino Secundário — Grade 12 (12.º ano Matemática A)",
        "12", "10-12",
        "pt_dge_ae_math_12ano.pdf",
        "https://www.dge.mec.pt/sites/default/files/Curriculo/Aprendizagens_Essenciais/12_matematica_a.pdf",
    ),
]

DOMAIN_MAP = {
    "NO":  "Numbers and Operations",
    "GEO": "Geometry and Measurement",
    "ALG": "Algebra",
    "OTD": "Data Handling and Statistics",
    "FUN": "Functions and Graphs",
    "CAL": "Calculus",
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
Below is text from Portugal's mathematics curriculum document:
Aprendizagens Essenciais (Essential Learning) for {level_label},
published by the Direção-Geral da Educação (DGE), 2018.

These documents define the essential learning objectives (aprendizagens essenciais)
for mathematics. Learning objectives describe what students should know and be able to do.

Portuguese DGE math domains:
  NO  = Números e Operações (Numbers and Operations)
  GEO = Geometria e Medida (Geometry and Measurement)
  ALG = Álgebra (Algebra)
  OTD = Organização e Tratamento de Dados (Data Handling/Statistics)
  FUN = Funções e Gráficos (Functions and Graphs) [secondary]
  CAL = Cálculo (Calculus/Analysis) [secondary]

Learning objectives appear as:
  - Items under "O aluno deve ser capaz de" (The student must be able to)
  - Bullet points starting with verbs: "Reconhecer", "Calcular", "Resolver",
    "Compreender", "Representar", "Identificar", "Aplicar", "Justificar", etc.
  - Items listed after domain headings (Números e Operações, Geometria...)

Return ONLY a JSON array (no markdown). Each element:
  "domain_code" : 2-3 letter code (NO, GEO, ALG, OTD, FUN, CAL, OTHER)
  "subtopic"    : sub-section heading in Portuguese (e.g. "Números naturais", "Frações")
  "text_pt"     : Portuguese text verbatim (the full learning objective, trimmed)
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
        t = re.sub(r'Dire[çc][aã]o-Geral da Educa[çc][aã]o.*?\n', '', t, flags=re.IGNORECASE)
        t = re.sub(r'^\d+\s*$', '', t, flags=re.MULTILINE)
        if t.strip():
            parts.append(t.strip())
    doc.close()
    return "\n\n".join(parts)


def _call_model(level_label: str, text: str) -> list[dict]:
    prompt = EXTRACT_PROMPT.format(level_label=level_label, text=text)
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
        conn.execute("DELETE FROM keywords WHERE standard_id LIKE 'PT_DGE.%'")
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

        chunk_size = 12000
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
                    domain_code = (std.get("domain_code") or "OTHER").strip().upper()
                    if domain_code not in DOMAIN_MAP:
                        domain_code = "OTHER"
                    subtopic = (std.get("subtopic") or "").strip()
                    text_pt = (std.get("text_pt") or "").strip()
                    text_en = (std.get("text_en") or "").strip()
                    if not text_en or len(text_en) < 10:
                        continue

                    existing = sum(
                        1 for sid in seen_ids
                        if sid.startswith(f"PT_DGE.MATH.{level_code}.{domain_code}.")
                    )
                    seq = existing + 1
                    std_id = f"PT_DGE.MATH.{level_code}.{domain_code}.{seq:03d}"
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
                    for kw in _extract_keywords(text_en + " " + text_pt):
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
