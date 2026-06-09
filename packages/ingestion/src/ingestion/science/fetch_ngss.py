"""Fetch and ingest NGSS (Next Generation Science Standards) via CSP API.

Covered system: ngss
Source: commonstandardsproject.com (Next Generation Science Standards org)
Grades: K-12

Performance Expectations (PEs) like K-PS2-1, MS-LS1-1, HS-ESS1-1 are the
leaf-level standards and serve as the crosswalk hub for all science systems
(analogous to how CCSS is the hub for mathematics).

DCI, CCC, and SEP component items are intentionally skipped — PEs are the
testable, curriculum-facing standards.

IDs: NGSS.{pe_code}  e.g. NGSS.K-PS2-1, NGSS.MS-LS1-1, NGSS.HS-ESS1-1
"""
import json
import re
import sqlite3
from datetime import date
from pathlib import Path

import httpx

from shared.config import DB_PATH

SYSTEM = "ngss"
CSP_BASE = "https://commonstandardsproject.com/api/v1"
SOURCE_URL = "https://www.nextgenscience.org"
VERIFIED_DATE = date.today().isoformat()
RAW_DIR = DB_PATH.parent / "raw" / "ngss"

# CSP jurisdiction ID for Next Generation Science Standards
NGSS_JUR_ID = "71E5AA409D894EB0B43A8CD82F727BFE"

# Hardcoded grade set IDs from the NGSS CSP jurisdiction
GRADE_SETS = [
    ("K",  "71E5AA409D894EB0B43A8CD82F727BFE_D2454348_grade-k"),
    ("1",  "71E5AA409D894EB0B43A8CD82F727BFE_D2454348_grade-01"),
    ("2",  "71E5AA409D894EB0B43A8CD82F727BFE_D2454348_grade-02"),
    ("3",  "71E5AA409D894EB0B43A8CD82F727BFE_D2454348_grade-03"),
    ("4",  "71E5AA409D894EB0B43A8CD82F727BFE_D2454348_grade-04"),
    ("5",  "71E5AA409D894EB0B43A8CD82F727BFE_D2454348_grade-05"),
    ("6",  "71E5AA409D894EB0B43A8CD82F727BFE_D2454348_grades-06-07-08"),
    ("HS", "71E5AA409D894EB0B43A8CD82F727BFE_D2454348_grades-09-10-11-12"),
]

GRADE_BAND: dict[str, str] = {"6": "6-8", "HS": "9-12"}

# Matches PE codes: K-PS2-1, MS-LS1-1, HS-ESS1-1, K-2-ETS1-1, 1-LS1-1
# Discipline codes contain letters+digits (PS2, LS1, ESS1, ETS1) — [A-Z]+ alone misses them.
# Excludes DCI (DCI.PS2.A.K-2.1), CCC (CCC.9.K-2.1), SEP items (all have dots).
# Also excludes topic headers like K-PS2 or K-2-ETS1 (no trailing -\d+).
PE_RE = re.compile(r'^[A-Z0-9]+-(?:\d+-)?[A-Z]+\d+-\d+$')

DOMAIN_MAP = {
    "PS":  "Physical Science",
    "LS":  "Life Science",
    "ESS": "Earth and Space Science",
    "ETS": "Engineering, Technology, and Applications of Science",
}

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each",
    "such", "both", "also", "into", "more", "most", "some", "other",
    "these", "those", "about", "able", "after", "where", "while", "make",
    "used", "given", "find", "show", "know", "understand", "apply",
    "students", "student", "science",
}


def _domain_from_notation(notation: str) -> str:
    for part in notation.split("-"):
        for code, name in DOMAIN_MAP.items():
            if part.startswith(code) and len(part) > len(code):
                return name
        for code, name in DOMAIN_MAP.items():
            if part == code:
                return name
    return "Science"


def _extract_keywords(text: str) -> list[str]:
    words = re.findall(r'\b[a-zA-Z][a-zA-Z-]{3,}\b', text.lower())
    seen: set[str] = set()
    result = []
    for w in words:
        if w not in STOP_WORDS and w not in seen:
            seen.add(w)
            result.append(w)
    return result[:20]


def _fetch_set(set_id: str, client: httpx.Client) -> list[dict]:
    cache = RAW_DIR / f"{set_id}.json"
    if cache.exists():
        stds = json.loads(cache.read_text()).get("data", {}).get("standards", {})
        return list(stds.values()) if isinstance(stds, dict) else stds
    resp = client.get(f"{CSP_BASE}/standard_sets/{set_id}", timeout=30)
    resp.raise_for_status()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(resp.text)
    stds = resp.json().get("data", {}).get("standards", {})
    return list(stds.values()) if isinstance(stds, dict) else stds


def _ingest_set(grade: str, items: list[dict], conn: sqlite3.Connection, seen_ids: set[str]) -> tuple[int, int]:
    # Build topic (depth=0) cluster lookup
    clusters: dict[str, str] = {}
    for s in items:
        if s.get("depth") == 0:
            clusters[s["id"]] = s.get("description", "")

    grade_band = GRADE_BAND.get(grade)
    std_count = kw_count = 0

    for s in items:
        nota = (s.get("statementNotation") or "").strip()
        desc = (s.get("description") or "").strip()
        if not nota or not desc or not PE_RE.match(nota):
            continue

        std_id = f"NGSS.{nota}"
        if std_id in seen_ids:
            continue
        seen_ids.add(std_id)

        domain = _domain_from_notation(nota)

        cluster = ""
        parent_id = s.get("parentId")
        if parent_id and parent_id in clusters:
            cluster = clusters[parent_id]
        if not cluster:
            for anc_id in s.get("ancestorIds", []):
                if anc_id in clusters:
                    cluster = clusters[anc_id]
                    break

        conn.execute(
            """INSERT OR REPLACE INTO standards
               (id, system, subject, grade, grade_band, domain, cluster,
                standard_text, last_verified_date, source_url)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (std_id, SYSTEM, "science", grade, grade_band,
             domain, cluster, desc, VERIFIED_DATE, SOURCE_URL),
        )
        std_count += 1
        for kw in _extract_keywords(desc):
            conn.execute("INSERT OR IGNORE INTO keywords (standard_id, keyword) VALUES (?,?)", (std_id, kw))
            kw_count += 1

    return std_count, kw_count


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    with conn:
        conn.execute("DELETE FROM keywords WHERE standard_id LIKE 'NGSS.%'")
        conn.execute("DELETE FROM standards WHERE system = ?", (SYSTEM,))

    print("Fetching NGSS standards from commonstandardsproject.com...")

    total_std = total_kw = 0
    seen_ids: set[str] = set()

    with httpx.Client() as client:
        for grade, set_id in GRADE_SETS:
            label = f"Grades {grade}" if grade != "HS" else "Grades 9-12"
            print(f"  {label}...", end="", flush=True)
            try:
                items = _fetch_set(set_id, client)
                with conn:
                    s, k = _ingest_set(grade, items, conn, seen_ids)
                total_std += s
                total_kw += k
                print(f" {s} standards, {k} keywords")
            except Exception as e:
                print(f" ERROR: {e}")

    conn.close()
    print(f"\nTotal: {total_std} standards, {total_kw} keywords")
    print("Done.")


if __name__ == "__main__":
    main()
