"""Fetch and ingest IB PYP Mathematics Scope and Sequence.

System: ib-pyp
Source: IB PYP Mathematics scope and sequence (2009)
  Mirrored from International College Lebanon (faithful copy of official IBO document)

Covers Primary Years Programme (ages 3–12, approx. grades K–6):
  5 mathematical strands × 6 phases of learning continuums

Strands:
  DH = Data Handling
  ME = Measurement
  SS = Shape and Space
  PF = Pattern and Function
  NU = Number

Phases (not strictly tied to grade levels; IBO approximate mapping):
  Phase 1: ages ~3–5  → grade K,  grade_band K-1
  Phase 2: ages ~5–7  → grade 1,  grade_band K-2
  Phase 3: ages ~7–9  → grade 3,  grade_band 2-4
  Phase 4: ages ~8–10 → grade 4,  grade_band 3-5
  Phase 5: ages ~9–11 → grade 5,  grade_band 4-6
  Phase 6: ages ~11–12→ grade 6,  grade_band 5-6

Learning stages within each phase (used as cluster):
  Constructing meaning          (CM)
  Transferring meaning          (TM)
  Applying with understanding   (AU)

ID format: IB_PYP.MATH.{strand}.P{phase}.{seq:03d}
  e.g. IB_PYP.MATH.DH.P1.001
       IB_PYP.MATH.NU.P6.005
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

SYSTEM = "ib-pyp"
VERIFIED_DATE = date.today().isoformat()
RAW_DIR = DB_PATH.parent / "raw" / "ib_pyp"
PDF_URL = "https://www.ic.edu.lb/uploaded/programs/IB_PYP_Program/PYP_math_scope_and_sequence.pdf"
PDF_FILE = "ib_pyp_math_scope_sequence.pdf"

# (strand_code, strand_name, page_start_idx, page_end_idx_exclusive)
STRANDS = [
    ("DH", "Data Handling",       13, 17),
    ("ME", "Measurement",         17, 21),
    ("SS", "Shape and Space",     21, 25),
    ("PF", "Pattern and Function",25, 28),
    ("NU", "Number",              28, 33),
]

PHASE_MAP = {
    "1": ("K",  "K-1"),
    "2": ("1",  "K-2"),
    "3": ("3",  "2-4"),
    "4": ("4",  "3-5"),
    "5": ("5",  "4-6"),
    "6": ("6",  "5-6"),
}

DOMAIN_MAP = {
    "DH": "Data Handling",
    "ME": "Measurement",
    "SS": "Shape and Space",
    "PF": "Pattern and Function",
    "NU": "Number",
}

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each",
    "such", "both", "also", "into", "more", "most", "some", "other",
    "these", "those", "about", "able", "after", "where", "while", "make",
    "used", "given", "find", "show", "know", "understand", "apply",
    "students", "student", "learners", "primary", "years", "programme",
    "mathematics", "mathematical", "objects", "real", "different",
}

EXTRACT_PROMPT = """\
Below is the "{strand_name}" strand from the IB Primary Years Programme (PYP)
Mathematics Scope and Sequence document (IBO, 2009).

The document describes learning objectives organized into 6 phases (Phase 1–6).
Within each phase, objectives are grouped under three learning stages:
  1. "When constructing meaning learners:" → stage: "CM"
  2. "When transferring meaning into symbols learners:" → stage: "TM"
  3. "When applying with understanding learners:" → stage: "AU"

Each bullet point under these headings is a distinct learning objective.

Also extract the "Conceptual understandings" for each phase — these are short
declarative statements (not bullet points) that describe the big ideas.
Treat these with stage: "CU" (Conceptual Understanding).

Extract ALL objectives and conceptual understandings for ALL phases (1–6).
Do NOT include:
- Section headers or strand descriptions
- "Overall expectations" paragraphs (narrative prose about the phase)
- "Notes" sections (teacher guidance)

Return ONLY a JSON array (no markdown). Each element:
  "phase"  : integer 1–6
  "stage"  : "CU", "CM", "TM", or "AU"
  "text"   : the full objective or understanding statement (trimmed, no bullet character)

STRAND TEXT — {strand_name}:
{text}
"""


def _download(url: str, path: Path) -> None:
    print(f"  Downloading {path.name} …")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(path, "wb") as f:
        f.write(r.read())
    print(f"  Saved {path.stat().st_size:,} bytes")


def _extract_strand_text(pdf_path: Path, start_idx: int, end_idx: int) -> str:
    doc = fitz.open(str(pdf_path))
    parts = []
    for i in range(start_idx, min(end_idx, doc.page_count)):
        t = doc[i].get_text().strip()
        # Remove running header/footer lines
        t = re.sub(r'^Mathematics scope and sequence\s*\n', '', t, flags=re.MULTILINE)
        t = re.sub(r'^Learning continuums\s*\n', '', t, flags=re.MULTILINE)
        t = re.sub(r'^\d+\s*\n', '', t, flags=re.MULTILINE)
        if t.strip():
            parts.append(t.strip())
    doc.close()
    return "\n\n".join(parts)


def _call_model(strand_name: str, text: str) -> list[dict]:
    prompt = EXTRACT_PROMPT.format(strand_name=strand_name, text=text[:12000])
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
        conn.execute("DELETE FROM keywords WHERE standard_id LIKE 'IB_PYP.%'")
        conn.execute("DELETE FROM standards WHERE system = ?", (SYSTEM,))

    seen_ids: set[str] = set()
    grand_std = grand_kw = 0

    for strand_code, strand_name, pg_start, pg_end in STRANDS:
        text = _extract_strand_text(pdf_path, pg_start, pg_end)
        print(f"  {strand_code} / {strand_name} ({len(text)} chars) → model …", end="", flush=True)
        try:
            items = _call_model(strand_name, text)
        except Exception as e:
            print(f" ERROR: {e}")
            continue

        # Track seq per (strand, phase)
        phase_seq: dict[str, int] = {}
        strand_std = strand_kw = 0

        with conn:
            for item in items:
                phase_raw = item.get("phase")
                stage = (item.get("stage") or "").strip().upper()
                text_obj = (item.get("text") or "").strip()

                if not text_obj or len(text_obj) < 8:
                    continue
                if stage not in ("CU", "CM", "TM", "AU"):
                    stage = "CM"
                try:
                    phase = int(phase_raw)
                except (TypeError, ValueError):
                    continue
                if phase not in range(1, 7):
                    continue

                grade, grade_band = PHASE_MAP[str(phase)]
                key = f"{strand_code}.P{phase}"
                phase_seq[key] = phase_seq.get(key, 0) + 1
                seq = phase_seq[key]

                std_id = f"IB_PYP.MATH.{strand_code}.P{phase}.{seq:03d}"
                if std_id in seen_ids:
                    continue
                seen_ids.add(std_id)

                stage_labels = {
                    "CU": "Conceptual Understanding",
                    "CM": "Constructing Meaning",
                    "TM": "Transferring Meaning into Symbols",
                    "AU": "Applying with Understanding",
                }

                conn.execute(
                    """INSERT OR REPLACE INTO standards
                       (id, system, subject, grade, grade_band, domain, cluster,
                        standard_text, last_verified_date, source_url)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        std_id, SYSTEM, "mathematics",
                        grade, grade_band,
                        DOMAIN_MAP[strand_code],
                        stage_labels.get(stage, stage),
                        text_obj,
                        VERIFIED_DATE,
                        PDF_URL,
                    ),
                )
                strand_std += 1
                for kw in _extract_keywords(text_obj):
                    conn.execute(
                        "INSERT OR IGNORE INTO keywords (standard_id, keyword) VALUES (?,?)",
                        (std_id, kw),
                    )
                    strand_kw += 1

        grand_std += strand_std
        grand_kw += strand_kw
        print(f" {len(items)} extracted, {strand_std} ingested")

    conn.close()
    print(f"\nTotal: {grand_std} standards, {grand_kw} keywords")
    print("Done.")


if __name__ == "__main__":
    main()
