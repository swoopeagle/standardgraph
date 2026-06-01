"""Stage 1-3: Fetch CCSS Math standards from commonstandardsproject.com and load into DB."""
import json
import re
import sqlite3
from datetime import date
from pathlib import Path

import httpx

from shared.config import DB_PATH

RAW_DIR = DB_PATH.parent / "raw"

CSP_BASE = "https://commonstandardsproject.com/api/v1"
DOC_ID   = "49FCDFBD2CF04033A9C347BFA0584DF0"

# Confirmed set IDs — D2604890 is CCSS Math K-8; three course sets cover all HS domains.
GRADE_SETS: dict[str, list[str]] = {
    "K":  [f"{DOC_ID}_D2604890_grade-k"],
    "1":  [f"{DOC_ID}_D2604890_grade-01"],
    "2":  [f"{DOC_ID}_D2604890_grade-02"],
    "3":  [f"{DOC_ID}_D2604890_grade-03"],
    "4":  [f"{DOC_ID}_D2604890_grade-04"],
    "5":  [f"{DOC_ID}_D2604890_grade-05"],
    "6":  [f"{DOC_ID}_D2604890_grade-06"],
    "7":  [f"{DOC_ID}_D2604890_grade-07"],
    "8":  [f"{DOC_ID}_D2604890_grade-08"],
    # HS: three course sets — deduplicated by statementNotation
    "HS": [
        f"{DOC_ID}_D21095618_grades-09-10-11-12",  # Algebra I  (HSN, HSA, HSF, HSS)
        f"{DOC_ID}_D21095825_grades-09-10-11-12",  # Geometry   (HSG)
        f"{DOC_ID}_D21095711_grades-09-10-11-12",  # Algebra II (HSN, HSA, HSF, HSG, HSS)
    ],
}

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each",
    "such", "both", "also", "into", "more", "most", "some", "other",
    "these", "those", "about", "able", "after", "where", "while", "make",
    "used", "given", "find", "show", "know", "understand", "apply",
}

SOURCE_URL     = "https://www.corestandards.org/Math/"
VERIFIED_DATE  = date.today().isoformat()


def fetch_set(set_id: str, client: httpx.Client) -> list[dict]:
    """Fetch one standard set, return list of standard dicts."""
    cache = RAW_DIR / f"{set_id}.json"
    if cache.exists():
        data = json.loads(cache.read_text())
    else:
        resp = client.get(f"{CSP_BASE}/standard_sets/{set_id}", timeout=30)
        resp.raise_for_status()
        data = resp.json()
        cache.write_text(json.dumps(data, indent=2))

    payload = data.get("data", data)
    stds = payload.get("standards", {})
    return list(stds.values()) if isinstance(stds, dict) else stds


def extract_keywords(text: str) -> list[str]:
    words = re.findall(r'\b[a-zA-Z][a-zA-Z-]{3,}\b', text.lower())
    seen: set[str] = set()
    result = []
    for w in words:
        if w not in STOP_WORDS and w not in seen:
            seen.add(w)
            result.append(w)
    return result[:20]


def ingest_grade(
    grade: str,
    all_stds: list[dict],
    conn: sqlite3.Connection,
    seen_notations: set[str],
) -> tuple[int, int, int]:
    """
    Parse and insert standards for one grade.

    Depth mapping (confirmed from API inspection):
      0 = domain heading
      1 = cluster
      2 = standard (leaf — the rows we want in `standards`)
      3 = sub-standard (lettered, e.g. 6.RP.A.3a)

    Returns (standards_inserted, sub_standards_inserted, keywords_inserted).
    """
    by_id: dict[str, dict] = {s["id"]: s for s in all_stds}

    domains:  dict[str, str]  = {}  # id -> description
    clusters: dict[str, dict] = {}  # id -> {letter, text}

    for s in all_stds:
        depth = s.get("depth", -1)
        desc  = s.get("description", "").strip()
        if depth == 0:
            domains[s["id"]] = desc
        elif depth == 1:
            clusters[s["id"]] = {
                "letter": s.get("listId", ""),
                "text":   desc,
            }

    std_count = sub_count = kw_count = 0
    grade_band = "9-12" if grade == "HS" else None

    # Pass 1: insert depth-2 standards (must come before sub-standards so
    # seen_notations is populated when we process depth-3 below).
    for s in all_stds:
        depth    = s.get("depth", -1)
        notation = s.get("statementNotation", "").strip()
        desc     = s.get("description", "").strip()

        if not notation or not desc or depth != 2:
            continue

        if True:  # always depth == 2 here
            # Leaf standard — check for duplicates (HS sets overlap)
            if notation in seen_notations:
                continue
            seen_notations.add(notation)

            std_id    = f"CCSS.MATH.{notation}"
            ancestors = s.get("ancestorIds", [])
            parent_id = s.get("parentId")

            domain_id  = None
            cluster_id = None
            for anc_id in reversed(ancestors):
                anc = by_id.get(anc_id, {})
                d   = anc.get("depth", -1)
                if d == 1 and cluster_id is None:
                    cluster_id = anc_id
                elif d == 0 and domain_id is None:
                    domain_id = anc_id

            # Fallback: walk up via parentId
            if cluster_id is None and parent_id:
                p = by_id.get(parent_id, {})
                if p.get("depth") == 1:
                    cluster_id = parent_id
                    if domain_id is None:
                        gp_id = p.get("parentId")
                        if gp_id and by_id.get(gp_id, {}).get("depth") == 0:
                            domain_id = gp_id

            domain_text  = domains.get(domain_id, "")  if domain_id  else ""
            cluster_info = clusters.get(cluster_id, {}) if cluster_id else {}

            conn.execute(
                """INSERT OR REPLACE INTO standards
                   (id, system, subject, grade, grade_band, domain, cluster,
                    standard_text, last_verified_date, source_url)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    std_id, "ccss", "mathematics", grade, grade_band,
                    domain_text, cluster_info.get("text", ""),
                    desc, VERIFIED_DATE, SOURCE_URL,
                ),
            )
            std_count += 1

            for kw in extract_keywords(desc):
                conn.execute(
                    "INSERT OR IGNORE INTO keywords (standard_id, keyword) VALUES (?,?)",
                    (std_id, kw),
                )
                kw_count += 1

    # Pass 2: insert depth-3 sub-standards (parents now guaranteed in seen_notations)
    for s in all_stds:
        depth    = s.get("depth", -1)
        notation = s.get("statementNotation", "").strip()
        desc     = s.get("description", "").strip()

        if not notation or not desc or depth != 3:
            continue

        if True:  # always depth == 3 here
            # Sub-standard — find depth-2 parent
            parent_notation = None
            # Walk ancestorIds looking for a depth-2 ancestor
            ancestors = s.get("ancestorIds", [])
            for anc_id in reversed(ancestors):
                anc = by_id.get(anc_id, {})
                if anc.get("depth") == 2:
                    parent_notation = anc.get("statementNotation", "")
                    break
            # Fallback via parentId
            if not parent_notation:
                pid = s.get("parentId")
                if pid and by_id.get(pid, {}).get("depth") == 2:
                    parent_notation = by_id[pid].get("statementNotation", "")

            if not parent_notation or parent_notation not in seen_notations:
                continue

            parent_std_id = f"CCSS.MATH.{parent_notation}"
            sub_id        = f"CCSS.MATH.{notation}"
            position      = s.get("position", 0)

            conn.execute(
                """INSERT OR REPLACE INTO sub_standards
                   (id, parent_id, system, text, position)
                   VALUES (?,?,?,?,?)""",
                (sub_id, parent_std_id, "ccss", desc, position),
            )
            sub_count += 1

    return std_count, sub_count, kw_count


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    total_std = total_sub = total_kw = 0
    seen_notations: set[str] = set()

    print("Stage 1-3: Fetching CCSS Math standards...")
    with httpx.Client() as client:
        for grade, set_ids in GRADE_SETS.items():
            all_stds: list[dict] = []
            for sid in set_ids:
                all_stds.extend(fetch_set(sid, client))

            with conn:
                s, sub, k = ingest_grade(grade, all_stds, conn, seen_notations)

            total_std += s
            total_sub += sub
            total_kw  += k
            print(f"  Grade {grade:2s}: {s:3d} standards, {sub:3d} sub-standards, {k:4d} keywords")

    conn.close()
    print(f"\nTotal: {total_std} standards, {total_sub} sub-standards, {total_kw} keywords")
    print("Done.")


if __name__ == "__main__":
    main()
