"""Fetch and ingest Nigeria NERDC Basic Education Curriculum Mathematics.

Covered system: ng-nerdc
Sources (NERDC PDFs from nerdc.gov.ng):
  Primary 1-3:
    https://nerdc.gov.ng/content_manager/primary/pri1-3_nvc.pdf
  Primary 4-6:
    https://nerdc.gov.ng/content_manager/primary/pri4-6_nvc.pdf (inferred)
  Junior Secondary 1-3:
    https://nerdc.gov.ng/content_manager/jss/jss1-3_nvc.pdf (inferred)

Grade mapping: Pr1-3 → 1-3, Pr4-6 → 4-6, JSS1-3 → 7-9
IDs: NG_NERDC.MATH.{grade}.{hash}
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

SYSTEM = "ng-nerdc"
SOURCE_URL = "https://www.nerdc.gov.ng/content_manager/curriculum.html"
VERIFIED_DATE = date.today().isoformat()
RAW_DIR = DB_PATH.parent / "raw" / "nigeria"

PHASES = [
    (
        "pri1-3.pdf",
        "https://nerdc.gov.ng/content_manager/primary/pri1-3_nvc.pdf",
        ["1", "2", "3"],
        "Primary 1-3",
    ),
    (
        "pri4-6.pdf",
        "https://nerdc.gov.ng/content_manager/primary/pri4-6_nvc.pdf",
        ["4", "5", "6"],
        "Primary 4-6",
    ),
    (
        "jss1-3.pdf",
        "https://nerdc.gov.ng/content_manager/jss/jss1-3_nvc.pdf",
        ["7", "8", "9"],
        "Junior Secondary 1-3",
    ),
]

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each",
    "such", "both", "also", "into", "more", "most", "some", "other",
    "these", "those", "about", "able", "after", "where", "while", "make",
    "used", "given", "find", "show", "know", "understand", "apply",
}

EXTRACT_PROMPT = """\
Extract all mathematics learning outcomes and competencies from this Nigeria NERDC curriculum text for {phase_label}.

The curriculum is organized into:
- Topics or content areas (e.g. "Numbers and Numeration", "Basic Operations", "Algebra", "Geometry", "Measurement", "Data Collection")
- Specific learning outcomes, competencies, or skills

Return ONLY a JSON array (no other text, no markdown). Each element must have:
  "topic"        : topic or content area
  "outcome_text" : full text of the learning outcome or competency

Rules:
- Extract every specific learning outcome, competency, or skill listed.
- Do NOT include teaching methods, activities, assessment notes, or resources.
- Preserve exact wording.

NERDC MATHEMATICS TEXT ({phase_label}):
{text}
"""


def _download_pdf(url: str, path: Path) -> None:
    print(f"  Downloading {url} ...")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, path, timeout=30)
    print(f"  Saved: {path.stat().st_size:,} bytes")


def _extract_pages(pdf_path: Path) -> list[tuple[int, str]]:
    results = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            if text.strip():
                results.append((i + 1, text))
    return results


def _call_gemma(text: str, phase_label: str) -> list[dict]:
    prompt = EXTRACT_PROMPT.format(phase_label=phase_label, text=text[:4000])
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "keep_alive": "4h",
        "options": {"temperature": 0.0},
    }
    resp = httpx.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload, timeout=3600)
    resp.raise_for_status()
    content = resp.json()["message"]["content"].strip()
    content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.MULTILINE)
    content = re.sub(r"\s*```$", "", content, flags=re.MULTILINE)
    m = re.search(r"\[.*\]", content, re.DOTALL)
    if not m:
        return []
    return json.loads(m.group(0))


def _extract_keywords(text: str) -> list[str]:
    words = re.findall(r'\b[a-zA-Z][a-zA-Z-]{3,}\b', text.lower())
    seen: set[str] = set()
    result = []
    for w in words:
        if w not in STOP_WORDS and w not in seen:
            seen.add(w)
            result.append(w)
    return result[:20]


def _ingest(objectives: list[dict], grades: list[str], conn: sqlite3.Connection, seen_ids: set[str]) -> tuple[int, int]:
    std_count = kw_count = 0
    for obj in objectives:
        outcome_text = (obj.get("outcome_text") or "").strip()
        if not outcome_text:
            continue
        topic = (obj.get("topic") or "").strip()

        for grade in grades:
            std_id = f"NG_NERDC.MATH.{grade}.{abs(hash(outcome_text[:40])) % 100000}"
            if std_id in seen_ids:
                continue
            seen_ids.add(std_id)

            conn.execute(
                """INSERT OR REPLACE INTO standards
                   (id, system, subject, grade, grade_band, domain, cluster,
                    standard_text, last_verified_date, source_url)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (std_id, SYSTEM, "mathematics", grade, None,
                 topic, "", outcome_text, VERIFIED_DATE, SOURCE_URL),
            )
            std_count += 1
            for kw in _extract_keywords(outcome_text):
                conn.execute("INSERT OR IGNORE INTO keywords (standard_id, keyword) VALUES (?,?)", (std_id, kw))
                kw_count += 1

    return std_count, kw_count


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    print("Extracting Nigeria NERDC Mathematics standards...")
    grand_std = grand_kw = 0
    seen_ids: set[str] = set()

    for fname, url, grades, phase_label in PHASES:
        pdf_path = RAW_DIR / fname
        if not pdf_path.exists():
            try:
                _download_pdf(url, pdf_path)
            except Exception as e:
                print(f"  WARN: failed to download {phase_label}: {e}, trying fallback")
                # Try alternate URL patterns if primary fails
                if "pri4-6" in fname:
                    url = "https://nerdc.gov.ng/content_manager/primary/pri4-6_mathematics.pdf"
                elif "jss1-3" in fname:
                    url = "https://nerdc.gov.ng/content_manager/jss/jss1-3_mathematics.pdf"
                try:
                    _download_pdf(url, pdf_path)
                except Exception as e2:
                    print(f"  ERROR: fallback also failed, skipping {phase_label}")
                    continue

        pages = _extract_pages(pdf_path)
        if not pages:
            print(f"  WARN: no pages extracted from {phase_label}")
            continue

        print(f"\n  {phase_label}: {len(pages)} content pages")
        phase_std = phase_kw = 0

        chunk_size = 4
        for i in range(0, len(pages), chunk_size):
            chunk = pages[i:i + chunk_size]
            chunk_text = "\n\n".join(t for _, t in chunk)
            page_nums = f"{chunk[0][0]}-{chunk[-1][0]}"
            print(f"    pages {page_nums}: {len(chunk_text)} chars → Gemma...", end="", flush=True)
            try:
                objectives = _call_gemma(chunk_text, phase_label)
            except Exception as e:
                print(f" ERROR: {e}")
                continue

            with conn:
                s, k = _ingest(objectives, grades, conn, seen_ids)
            phase_std += s
            phase_kw += k
            print(f" {len(objectives)} extracted, {s} ingested")

        print(f"  {phase_label} total: {phase_std} standards, {phase_kw} keywords")
        grand_std += phase_std
        grand_kw += phase_kw

    conn.close()
    print(f"\nTotal: {grand_std} standards, {grand_kw} keywords")
    print("Done.")


if __name__ == "__main__":
    main()
