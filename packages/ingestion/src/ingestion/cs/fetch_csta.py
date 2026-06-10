"""Fetch and ingest CSTA K-12 Computer Science Standards (2017).

System: csta
Subject: cs
Source: Computer Science Teachers Association via commonstandardsproject.com

CSTA 2017 is the crosswalk hub for all computer science systems.
Organized into five grade bands:
  K-2  (Level 1A)
  3-5  (Level 1B)
  6-8  (Level 2)
  9-10 (Level 3A)
  11-12 (Level 3B)

Core concept areas: Algorithms & Programming, Computing Systems,
Data & Analysis, Impacts of Computing, Networks & the Internet.

IDs: csta.{notation}  e.g. csta.1A-AP-08
"""
import json
import re
import sqlite3
from datetime import date
from pathlib import Path

import httpx

from shared.config import DB_PATH

SYSTEM        = "csta"
SOURCE_URL    = "https://www.csteachers.org/page/standards"
VERIFIED_DATE = date.today().isoformat()
RAW_DIR       = DB_PATH.parent / "raw" / "csta"
CSP_BASE      = "https://commonstandardsproject.com/api/v1"

# CSTA 2017 grade-band sets
GRADE_SETS: dict[str, tuple[str, str]] = {
    "K":  ("K-2",   "EB63269BC6F545038C609C817ABA9FEC"),
    "3":  ("3-5",   "02A29FC9B23A4218AA6F322CBC744F40"),
    "6":  ("6-8",   "A74EC9117E49457B8C48011F24396D8C"),
    "HS": ("9-12",  "733D517E31A44D1EBFFA113AC394C64A"),
}

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each",
    "such", "both", "also", "into", "more", "most", "some", "other",
    "these", "those", "about", "able", "after", "where", "while", "make",
    "used", "given", "find", "show", "know", "understand", "apply",
    "students", "student",
}


def _fetch_set(set_id: str, client: httpx.Client) -> list[dict]:
    cache = RAW_DIR / f"{set_id}.json"
    if cache.exists():
        data = json.loads(cache.read_text())
    else:
        resp = client.get(f"{CSP_BASE}/standard_sets/{set_id}", timeout=30)
        resp.raise_for_status()
        data = resp.json()
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(resp.text)
    payload = data.get("data", data)
    stds = payload.get("standards", {})
    return list(stds.values()) if isinstance(stds, dict) else stds


def _extract_keywords(text: str) -> list[str]:
    words = re.findall(r'\b[a-zA-Z][a-zA-Z-]{3,}\b', text.lower())
    seen: set[str] = set()
    result = []
    for w in words:
        if w not in STOP_WORDS and w not in seen:
            seen.add(w)
            result.append(w)
    return result[:20]


def _ingest_grade_band(
    grade: str,
    grade_band: str,
    all_stds: list[dict],
    conn: sqlite3.Connection,
    seen_notations: set[str],
) -> tuple[int, int]:
    depth_counts: dict[int, int] = {}
    for s in all_stds:
        if (s.get("statementNotation") or "").strip():
            d = s.get("depth", 0)
            depth_counts[d] = depth_counts.get(d, 0) + 1
    if not depth_counts:
        return 0, 0
    leaf_depth = max(depth_counts, key=lambda d: depth_counts[d])

    parent_ids_at_leaf = {
        s["parentId"]
        for s in all_stds
        if s.get("depth") == leaf_depth
        and (s.get("statementNotation") or "").strip()
        and s.get("parentId")
    }

    domains: dict[str, str] = {}
    clusters: dict[str, str] = {}
    for s in all_stds:
        d    = s.get("depth", -1)
        desc = (s.get("description") or "").strip()
        if d == 0:
            domains[s["id"]] = desc
        elif d == leaf_depth - 1 and (s.get("statementNotation") or "").strip():
            clusters[s["id"]] = desc
        elif d == leaf_depth and s["id"] in parent_ids_at_leaf:
            clusters[s["id"]] = desc

    std_count = kw_count = 0

    for s in all_stds:
        if s.get("depth") != leaf_depth or s["id"] in parent_ids_at_leaf:
            continue
        notation = (s.get("statementNotation") or "").strip()
        desc     = (s.get("description") or "").strip()
        if not notation or not desc or notation in seen_notations:
            continue
        seen_notations.add(notation)

        domain_text = cluster_text = ""
        pid = s.get("parentId", "")
        for anc_id in [pid] + list(s.get("ancestorIds", [])):
            if not domain_text and anc_id in domains:
                domain_text = domains[anc_id]
            if not cluster_text and anc_id in clusters:
                cluster_text = clusters[anc_id]

        std_id = f"{SYSTEM}.{notation}"
        conn.execute(
            """INSERT OR REPLACE INTO standards
               (id, system, subject, grade, grade_band, domain, cluster,
                standard_text, last_verified_date, source_url)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (std_id, SYSTEM, "cs", grade, grade_band,
             domain_text, cluster_text, desc, VERIFIED_DATE, SOURCE_URL),
        )
        std_count += 1
        for kw in _extract_keywords(desc):
            conn.execute("INSERT OR IGNORE INTO keywords (standard_id, keyword) VALUES (?,?)",
                         (std_id, kw))
            kw_count += 1

    return std_count, kw_count


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    with conn:
        conn.execute("DELETE FROM keywords WHERE standard_id LIKE 'csta.%'")
        conn.execute("DELETE FROM standards WHERE system = ?", (SYSTEM,))

    print("Fetching CSTA K-12 CS Standards (2017) from commonstandardsproject.com...")

    total_std = total_kw = 0
    seen_notations: set[str] = set()

    with httpx.Client() as client:
        for grade, (band, set_id) in GRADE_SETS.items():
            print(f"  Grades {band}...", end="", flush=True)
            try:
                items = _fetch_set(set_id, client)
                with conn:
                    s, k = _ingest_grade_band(grade, band, items, conn, seen_notations)
                total_std += s
                total_kw  += k
                print(f" {s} standards, {k} keywords")
            except Exception as e:
                print(f" ERROR: {e}")

    conn.close()
    print(f"\nTotal: {total_std} standards, {total_kw} keywords")
    print("Done.")


if __name__ == "__main__":
    main()
