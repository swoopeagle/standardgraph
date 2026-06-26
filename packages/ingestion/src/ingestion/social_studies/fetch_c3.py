"""Fetch and ingest the C3 Framework for Social Studies State Standards.

System: c3
Subject: social-studies
Source: National Council for the Social Studies (NCSS) via CSP

The C3 Framework is the crosswalk hub for all social studies systems,
analogous to CCSS for math. Organized into four Dimensions:
  D1 — Developing Questions and Planning Inquiries
  D2 — Applying Disciplinary Concepts and Tools
  D3 — Evaluating Sources and Using Evidence
  D4 — Communicating Conclusions and Taking Informed Action

Grade bands: K-2, 3-5, 6-8, 9-12

IDs: c3.{notation}  e.g. c3.D2.His.1.K-2
"""
import json
import re
import sqlite3
from datetime import date
from pathlib import Path

import httpx

from shared.config import DB_PATH

SYSTEM        = "c3"
SOURCE_URL    = "https://www.socialstudies.org/standards/c3"
VERIFIED_DATE = date.today().isoformat()
RAW_DIR       = DB_PATH.parent / "raw" / "c3"
CSP_BASE      = "https://commonstandardsproject.com/api/v1"

# NCSS jurisdiction in CSP; C3 grade-band sets
NCSS_JUR_ID = "63B92F2164654D019589410B6CA225EA"

GRADE_SETS: dict[str, str] = {
    "K":  f"{NCSS_JUR_ID}_D2607350_grades-01-02-k",
    "3":  f"{NCSS_JUR_ID}_D2607350_grades-03-04-05",
    "6":  f"{NCSS_JUR_ID}_D2607350_grades-06-07-08",
    "HS": f"{NCSS_JUR_ID}_D2607350_grades-09-10-11-12",
}

GRADE_BAND: dict[str, str] = {"K": "K-2", "3": "3-5", "6": "6-8", "HS": "9-12"}

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

    grade_band = GRADE_BAND.get(grade, "9-12")
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
            (std_id, SYSTEM, "social-studies", grade, grade_band,
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
        conn.execute("DELETE FROM keywords WHERE standard_id LIKE 'c3.%'")
        conn.execute("DELETE FROM standards WHERE system = ?", (SYSTEM,))

    print("Fetching C3 Framework (Social Studies) from commonstandardsproject.com...")

    total_std = total_kw = 0
    seen_notations: set[str] = set()

    with httpx.Client() as client:
        for grade, set_id in GRADE_SETS.items():
            band  = GRADE_BAND.get(grade, "9-12")
            label = f"Grades {band}"
            print(f"  {label}...", end="", flush=True)
            try:
                items = _fetch_set(set_id, client)
                with conn:
                    s, k = _ingest_grade_band(grade, items, conn, seen_notations)
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
