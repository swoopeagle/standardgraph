"""Fetch and ingest Korea NCIC 2015 math curriculum standards (Grades 1-9).

System: kr-ncf
Source: Ministry of Education Notice 2015-74 [Appendix 8] Mathematics Curriculum
  PDF mirror at textbook-miraen CDN (공통 교육과정 covers grades 1-9)

Grade bands and code prefixes in the PDF:
  Grades 1-2: codes beginning [2수XX-XX]
  Grades 3-4: codes beginning [4수XX-XX]
  Grades 5-6: codes beginning [6수XX-XX]
  Grades 7-9: codes beginning [9수XX-XX]  (middle school = 중학교)

Strand codes (consistent across grades):
  01 = 수와 연산 / Numbers and Operations
  02 = 도형 / Geometric Figures  (elementary: 도형; MS: also includes 기하)
  03 = 측정 / Measurement        (elementary); 함수 / Functions (MS)
  04 = 규칙성 / Patterns         (elementary); 기하 / Geometry (MS)
  05 = 자료와 가능성 / Data      (elementary); 확률과 통계 / Statistics (MS)
  MS strand 02 = 문자와 식 / Letters and Expressions

ID format: KR_NCF.MATH.{grade_band}.{strand}.{seq:03d}
  grade_band: G12, G34, G56, G79
  e.g. KR_NCF.MATH.G12.01.003
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

SYSTEM = "kr-ncf"
VERIFIED_DATE = date.today().isoformat()
RAW_DIR = DB_PATH.parent / "raw" / "kr"
PDF_URL = (
    "http://textbook-miraen.cdn.x-cdn.com/textbook/newbook/curriculum/"
    "%EB%B3%84%EC%B1%858_%EC%88%98%ED%95%99%EA%B3%BC%20%EA%B5%90%EC%9C%A1%EA%B3%BC%EC%A0%95.pdf"
)
PDF_FILE = "kr_math_2015_byulsaek8.pdf"

# Pages in the PDF that contain 성취기준 (achievement standards) for grades 1-9.
# Pages 7-41 (0-indexed 6-40) = 공통 교육과정 standards section.
# Pages 42+ = pedagogical guidance (not standards), and 47+ = high school.
STANDARDS_START = 6   # 0-indexed
STANDARDS_END   = 41  # exclusive

# Code prefix → grade band label
CODE_TO_BAND = {"2": "G12", "4": "G34", "6": "G56", "9": "G79"}

# Elementary strands by strand number
ELEM_STRANDS = {
    "01": "Numbers and Operations",
    "02": "Geometric Figures",
    "03": "Measurement",
    "04": "Patterns and Correspondence",
    "05": "Data and Probability",
}
# Middle-school strands
MS_STRANDS = {
    "01": "Numbers and Operations",
    "02": "Letters and Algebraic Expressions",
    "03": "Functions",
    "04": "Geometry",
    "05": "Statistics and Probability",
}

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each",
    "such", "both", "also", "into", "more", "most", "some", "other",
    "these", "those", "about", "able", "after", "where", "while", "make",
    "used", "given", "find", "show", "know", "understand", "apply",
    "students", "student", "number", "numbers", "values",
}

EXTRACT_PROMPT = """\
The following is an extract from Korea's official Ministry of Education mathematics curriculum
(2015 revision, 교육부 고시 제2015-74호 [별책 8]).

Each achievement standard (성취기준) starts with a code in square brackets, e.g.:
  [2수01-01]  (grade band 1-2, strand 01, standard 01)
  [9수04-13]  (grade band 7-9, strand 04, standard 13)

Code structure: [{{grade_band}}수{{strand:02d}}-{{seq:02d}}]
  grade_band digit: 2 = grades 1-2, 4 = grades 3-4, 6 = grades 5-6, 9 = grades 7-9
  strand: 01=수와 연산, 02=도형/문자와 식, 03=측정/함수, 04=규칙성/기하, 05=자료/확률과 통계

Extract EVERY standard code and its Korean text in this chunk.
Translate each standard to English.

Return ONLY a JSON array (no markdown, no preamble). Each element:
  "code"        : the full code string, e.g. "9수04-13" (omit brackets)
  "text_ko"     : Korean text of the standard (verbatim from the PDF)
  "text_en"     : accurate English translation

Return [] if no achievement standards appear in this text.

TEXT:
{text}
"""


def _download(url: str, path: Path) -> None:
    print(f"  Downloading {path.name} …")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
    )
    with urllib.request.urlopen(req, timeout=120) as r, open(path, "wb") as f:
        f.write(r.read())
    print(f"  Saved {path.stat().st_size:,} bytes")


def _call_model(text: str) -> list[dict]:
    prompt = EXTRACT_PROMPT.format(text=text[:11000])
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


def _parse_code(code: str) -> tuple[str, str, int] | None:
    """Parse '9수04-13' → (grade_band='G79', strand='04', seq=13). Returns None on error."""
    m = re.match(r"([2469])수(\d{2})-(\d+)", code)
    if not m:
        return None
    gb = CODE_TO_BAND.get(m.group(1))
    if not gb:
        return None
    strand = m.group(2)
    seq = int(m.group(3))
    return gb, strand, seq


def _extract_keywords(text: str) -> list[str]:
    words = re.findall(r'\b[a-zA-Z][a-zA-Z-]{3,}\b', text.lower())
    seen: set[str] = set()
    result = []
    for w in words:
        if w not in STOP_WORDS and w not in seen:
            seen.add(w)
            result.append(w)
    return result[:20]


def _strand_name(grade_band: str, strand: str) -> str:
    if grade_band == "G79":
        return MS_STRANDS.get(strand, f"Strand {strand}")
    return ELEM_STRANDS.get(strand, f"Strand {strand}")


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
        conn.execute("DELETE FROM keywords WHERE standard_id LIKE 'KR_NCF.%'")
        conn.execute("DELETE FROM standards WHERE system = ?", (SYSTEM,))

    seen_ids: set[str] = set()
    grand_std = grand_kw = 0

    print(f"Extracting grades 1-9 achievement standards (pages {STANDARDS_START+1}–{STANDARDS_END}) …")
    with pdfplumber.open(pdf_path) as pdf:
        # Process in chunks of 5 pages so prompt fits in 8192 context
        chunk_pages = 5
        for start in range(STANDARDS_START, STANDARDS_END, chunk_pages):
            end = min(start + chunk_pages, STANDARDS_END)
            parts = []
            for i in range(start, end):
                t = (pdf.pages[i].extract_text() or "").strip()
                if t:
                    parts.append(t)
            chunk_text = "\n\n".join(parts)
            if not chunk_text.strip():
                continue

            print(
                f"  pages {start+1}–{end} ({len(chunk_text)} chars) → model …",
                end="", flush=True,
            )
            try:
                standards = _call_model(chunk_text)
            except Exception as e:
                print(f" ERROR: {e}")
                continue

            chunk_std = chunk_kw = 0
            with conn:
                for std in standards:
                    code = (std.get("code") or "").strip()
                    text_en = (std.get("text_en") or "").strip()
                    text_ko = (std.get("text_ko") or "").strip()
                    if not code or not text_en or len(text_en) < 15:
                        continue
                    parsed = _parse_code(code)
                    if not parsed:
                        continue
                    grade_band, strand, seq = parsed
                    std_id = f"KR_NCF.MATH.{grade_band}.{strand}.{seq:03d}"
                    if std_id in seen_ids:
                        continue
                    seen_ids.add(std_id)

                    # Grade is the last digit of the band (e.g. G12→2, G79→9)
                    grade_num = grade_band[-1]

                    conn.execute(
                        """INSERT OR REPLACE INTO standards
                           (id, system, subject, grade, grade_band, domain, cluster,
                            standard_text, last_verified_date, source_url)
                           VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (
                            std_id, SYSTEM, "mathematics", grade_num,
                            grade_band.replace("G", ""),
                            _strand_name(grade_band, strand),
                            text_ko,
                            text_en,
                            VERIFIED_DATE,
                            "https://ncic.re.kr/mobile.spcbtoedu.renew.do",
                        ),
                    )
                    chunk_std += 1
                    for kw in _extract_keywords(text_en + " " + text_ko):
                        conn.execute(
                            "INSERT OR IGNORE INTO keywords (standard_id, keyword) VALUES (?,?)",
                            (std_id, kw),
                        )
                        chunk_kw += 1

            grand_std += chunk_std
            grand_kw += chunk_kw
            print(f" {len(standards)} extracted, {chunk_std} ingested")

    conn.close()
    print(f"\nTotal: {grand_std} standards, {grand_kw} keywords")
    print("Done.")


if __name__ == "__main__":
    main()
