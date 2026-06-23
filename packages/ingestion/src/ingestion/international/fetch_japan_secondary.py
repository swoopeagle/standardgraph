"""Fetch and ingest Japan MEXT junior-high school math standards (Grades 7-9).

Covered system: jp-mext  (same system as elementary; adds grades 7/8/9)
Source:
  - Course of Study for Lower Secondary School (2008 revision, Chapter 2 Section 3)
    https://www.mext.go.jp/a_menu/shotou/new-cs/youryou/chu/su.htm
    Japanese-language HTML page; processed with multilingual model

Structure (Japanese): Grades are labeled 第1学年/第2学年/第3学年 (JHS Years 1-3 = Grades 7-9)
Strands: A 数と式, B 図形, C 関数, D 資料の活用

ID format: JP_MEXT.MATH.{grade}.{strand}.{topic}.{obj}
  e.g. JP_MEXT.MATH.7.A.1.a  (grade 7 = JHS Year 1)
"""
import json
import re
import sqlite3
from datetime import date
from pathlib import Path

import httpx

from shared.config import DB_PATH, OLLAMA_BASE_URL, OLLAMA_MODEL

SYSTEM = "jp-mext"
SOURCE_URL = "https://www.mext.go.jp/a_menu/shotou/new-cs/youryou/chu/su.htm"
VERIFIED_DATE = date.today().isoformat()

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each",
    "such", "both", "also", "into", "more", "most", "some", "other",
    "these", "those", "about", "able", "after", "where", "while", "make",
    "used", "given", "find", "show", "know", "understand", "apply",
}

JHS_STRAND_NAMES = {
    "A": "Numbers and Algebraic Expressions",
    "B": "Geometrical Figures",
    "C": "Functions",
    "D": "Making Use of Data",
}

EXTRACT_PROMPT = """\
The following is the Japanese text of the Japan MEXT 2008 Course of Study for Junior High School
Mathematics, {year_label} (Grade {grade}).

Extract all learning objectives (目標 and 内容) from this text. The content is organized into
strands labeled A (数と式 = Numbers and Algebraic Expressions), B (図形 = Geometrical Figures),
C (関数 = Functions), D (資料の活用 = Making Use of Data).

Within each strand, topics are numbered (1), (2), (3)… and sub-objectives are labeled ア, イ, ウ, エ, オ
(which correspond to a, b, c, d, e in English).

For each leaf-level objective (ア/イ/ウ/エ/オ sub-item), return it in English. If a topic has no
sub-items, include the topic itself as a single objective.

Return ONLY a JSON array (no other text, no markdown). Each element must have:
  "strand"      : strand letter (A, B, C, or D)
  "strand_name" : full English strand name (e.g. "Numbers and Algebraic Expressions")
  "topic_num"   : topic number as string (e.g. "1", "2")
  "topic_text"  : English translation of the topic-level description
  "obj_letter"  : objective letter in English (a, b, c, d, e); empty string if no sub-items
  "obj_text"    : English translation of the leaf-level objective text

Rules:
- Translate all content to English.
- If a topic has lettered sub-items (ア/イ/ウ/…), extract each sub-item separately.
- If a topic has no sub-items, include the topic itself with empty obj_letter.
- Do NOT include strand headers, 用語・記号 (vocabulary/symbols) sections, or 数学的活動 sections.
- Preserve mathematical terminology precisely.

JAPANESE TEXT FOR {year_label} (GRADE {grade}):
{text}
"""


def _fetch_and_split() -> dict[str, str]:
    """Fetch the MEXT JHS math HTML page and split by year anchors.

    The page uses named anchors (1gakunen, 2gakunen, 3gakunen) that mark
    the start of each year's content section.
    """
    r = httpx.get(
        SOURCE_URL,
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
        timeout=30,
        follow_redirects=True,
    )
    r.raise_for_status()
    html = r.text

    # Strip script/style before anchor search
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL)

    # Split by anchors: <a name="1gakunen">, <a name="2gakunen">, <a name="3gakunen">
    anchor_map = {"1gakunen": "7", "2gakunen": "8", "3gakunen": "9"}
    anchor_re = re.compile(
        r'<a\s+name\s*=\s*"(1gakunen|2gakunen|3gakunen)"',
        re.IGNORECASE,
    )

    # Find all anchor positions
    positions: list[tuple[int, str]] = []
    for m in anchor_re.finditer(html):
        grade = anchor_map.get(m.group(1).lower(), "")
        if grade:
            positions.append((m.start(), grade))
    positions.sort()

    if not positions:
        # Fallback: strip all tags and return as single block
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        print("  WARN: no anchor tags found — returning full text as single block")
        return {"7": text}

    def _html_to_text(fragment: str) -> str:
        t = re.sub(r"<[^>]+>", " ", fragment)
        return re.sub(r"\s+", " ", t).strip()

    blocks: dict[str, str] = {}
    for i, (pos, grade) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(html)
        blocks[grade] = _html_to_text(html[pos:end])

    return blocks


def _call_model(grade: str, year_label: str, text: str) -> list[dict]:
    prompt = EXTRACT_PROMPT.format(
        grade=grade,
        year_label=year_label,
        text=text[:10000],
    )
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
        print(f"    WARN: no JSON array in model response for grade {grade}")
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


def _ingest_objectives(
    objectives: list[dict],
    grade: str,
    conn: sqlite3.Connection,
    seen_ids: set[str],
) -> tuple[int, int]:
    std_count = kw_count = 0
    for obj in objectives:
        obj_text = (obj.get("obj_text") or "").strip()
        if not obj_text:
            continue
        strand = (obj.get("strand") or "").strip().upper()
        strand_name = (obj.get("strand_name") or JHS_STRAND_NAMES.get(strand, "")).strip()
        topic_num = (obj.get("topic_num") or "").strip()
        obj_letter = (obj.get("obj_letter") or "").strip()
        if not strand or not topic_num:
            continue
        notation = f"{strand}.{topic_num}.{obj_letter}" if obj_letter else f"{strand}.{topic_num}"
        std_id = f"JP_MEXT.MATH.{grade}.{notation}"
        if std_id in seen_ids:
            continue
        seen_ids.add(std_id)
        conn.execute(
            """INSERT OR REPLACE INTO standards
               (id, system, subject, grade, grade_band, domain, cluster,
                standard_text, last_verified_date, source_url)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (std_id, SYSTEM, "mathematics", grade, None,
             strand_name, (obj.get("topic_text") or "").strip(), obj_text,
             VERIFIED_DATE, SOURCE_URL),
        )
        std_count += 1
        for kw in _extract_keywords(obj_text):
            conn.execute(
                "INSERT OR IGNORE INTO keywords (standard_id, keyword) VALUES (?,?)",
                (std_id, kw),
            )
            kw_count += 1
    return std_count, kw_count


def main() -> None:
    print(f"Fetching MEXT JHS Math page: {SOURCE_URL}")
    try:
        year_blocks = _fetch_and_split()
    except Exception as e:
        print(f"  ERROR fetching page: {e}")
        return

    if not year_blocks:
        print("  WARN: no year blocks found")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")

    year_label_map = {"7": "第1学年 (Year 1)", "8": "第2学年 (Year 2)", "9": "第3学年 (Year 3)"}
    grand_std = grand_kw = 0
    seen_ids: set[str] = set()

    for grade in sorted(year_blocks.keys(), key=int):
        year_label = year_label_map.get(grade, f"Grade {grade}")
        block = year_blocks[grade]
        print(f"  Grade {grade} ({year_label}): {len(block)} chars → model...", end="", flush=True)
        try:
            objectives = _call_model(grade, year_label, block)
        except Exception as e:
            print(f" ERROR: {e}")
            continue
        with conn:
            s, k = _ingest_objectives(objectives, grade, conn, seen_ids)
        grand_std += s
        grand_kw += k
        print(f" {len(objectives)} extracted, {s} ingested")

    conn.close()
    print(f"\nTotal: {grand_std} standards, {grand_kw} keywords")
    print("Done.")


if __name__ == "__main__":
    main()
