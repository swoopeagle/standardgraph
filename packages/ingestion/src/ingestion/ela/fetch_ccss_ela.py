"""Fetch and ingest CCSS ELA standards from commonstandardsproject.com.

System: ccss-ela
Subject: ela
Grades: K-12

CCSS ELA is the crosswalk hub for all ELA systems, analogous to CCSS Math
for mathematics. Only the main grade-level ELA sets are ingested; supplementary
literacy-in-content-area sets and Spanish versions are excluded.

IDs: ccss-ela.{notation}  e.g. ccss-ela.CCSS.ELA-Literacy.RL.K.1
"""
import json
import re
import sqlite3
from datetime import date
from pathlib import Path

import httpx

from shared.config import DB_PATH

SYSTEM        = "ccss-ela"
SOURCE_URL    = "https://www.corestandards.org/ELA-Literacy/"
VERIFIED_DATE = date.today().isoformat()
RAW_DIR       = DB_PATH.parent / "raw" / "ccss_ela"
CSP_BASE      = "https://commonstandardsproject.com/api/v1"

# CCSS jurisdiction in CSP; ELA sets use document D10003FC
CCSS_JUR_ID = "67810E9EF6944F9383DCC602A3484C23"

GRADE_SETS: dict[str, str] = {
    "K":  f"{CCSS_JUR_ID}_D10003FC_grade-k",
    "1":  f"{CCSS_JUR_ID}_D10003FC_grade-01",
    "2":  f"{CCSS_JUR_ID}_D10003FC_grade-02",
    "3":  f"{CCSS_JUR_ID}_D10003FC_grade-03",
    "4":  f"{CCSS_JUR_ID}_D10003FC_grade-04",
    "5":  f"{CCSS_JUR_ID}_D10003FC_grade-05",
    "6":  f"{CCSS_JUR_ID}_D10003FC_grade-06",
    "7":  f"{CCSS_JUR_ID}_D10003FC_grade-07",
    "8":  f"{CCSS_JUR_ID}_D10003FC_grade-08",
    "HS": f"{CCSS_JUR_ID}_D10003FC_grades-09-10",  # 9-10 covers the core HS anchors
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


def _ingest_grade(
    grade: str,
    all_stds: list[dict],
    conn: sqlite3.Connection,
    seen_notations: set[str],
) -> tuple[int, int]:
    # Determine leaf depth by most common depth with a notation
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

    grade_band = "9-12" if grade == "HS" else None
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
            (std_id, SYSTEM, "ela", grade, grade_band,
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
        conn.execute("DELETE FROM keywords WHERE standard_id LIKE 'ccss-ela.%'")
        conn.execute("DELETE FROM standards WHERE system = ?", (SYSTEM,))

    print("Fetching CCSS ELA standards from commonstandardsproject.com...")

    total_std = total_kw = 0
    seen_notations: set[str] = set()

    with httpx.Client() as client:
        for grade, set_id in GRADE_SETS.items():
            label = f"Grade {grade}" if grade != "HS" else "Grades 9-10 (HS)"
            print(f"  {label}...", end="", flush=True)
            try:
                items = _fetch_set(set_id, client)
                with conn:
                    s, k = _ingest_grade(grade, items, conn, seen_notations)
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
