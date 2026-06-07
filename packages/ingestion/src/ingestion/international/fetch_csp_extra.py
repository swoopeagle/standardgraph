"""Fetch AERO and DoDEA math standards from commonstandardsproject.com.

Covered systems:
  aero   American Education Reaches Out (international schools)
  dodea  Department of Defense Education Activity
"""
import re
import sqlite3
from collections import defaultdict
from datetime import date
from pathlib import Path

import httpx

from shared.config import DB_PATH

RAW_DIR = DB_PATH.parent / "raw" / "international"
CSP_BASE = "https://commonstandardsproject.com/api/v1"
VERIFIED_DATE = date.today().isoformat()

GRADE_ORDER = ["K", "1", "2", "3", "4", "5", "6", "7", "8", "HS"]

EDLEVEL_TO_GRADE: dict[str, str] = {
    "KG": "K", "00": "K", "0": "K", "K": "K",
    "01": "1", "1": "1", "02": "2", "2": "2",
    "03": "3", "3": "3", "04": "4", "4": "4",
    "05": "5", "5": "5", "06": "6", "6": "6",
    "07": "7", "7": "7", "08": "8", "8": "8",
    "09": "HS", "9": "HS", "10": "HS", "11": "HS", "12": "HS",
}

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each",
    "such", "both", "also", "into", "more", "most", "some", "other",
    "these", "those", "about", "able", "after", "where", "while", "make",
    "used", "given", "find", "show", "know", "understand", "apply",
}

JURISDICTIONS = {
    "aero":  "526CDC474EBA461EB6C3D75014FCD8D9",
    "dodea": "522A383527B04F40AFB79FB5EB073FB7",
}


def _cache_get(path: Path) -> dict | None:
    if path.exists():
        import json
        return json.loads(path.read_text())
    return None


def _cache_set(path: Path, data: dict) -> None:
    import json
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def _fetch_json(url: str, cache_path: Path, client: httpx.Client) -> dict:
    cached = _cache_get(cache_path)
    if cached is not None:
        return cached
    resp = client.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    _cache_set(cache_path, data)
    return data


def _extract_keywords(text: str) -> list[str]:
    words = re.findall(r'\b[a-zA-Z][a-zA-Z-]{3,}\b', text.lower())
    seen: set[str] = set()
    result = []
    for w in words:
        if w not in STOP_WORDS and w not in seen:
            seen.add(w)
            result.append(w)
    return result[:20]


def _edlevels_to_grade(levels: list[str]) -> str:
    grades = {EDLEVEL_TO_GRADE.get(lv, "") for lv in levels if lv in EDLEVEL_TO_GRADE}
    grades.discard("")
    if not grades:
        return ""
    if "HS" in grades:
        return "HS"
    return min(grades, key=lambda g: GRADE_ORDER.index(g) if g in GRADE_ORDER else 99)


def _is_core_math(s: dict) -> bool:
    subj = (s.get("subject") or "").lower()
    title = (s.get("title") or "").lower()
    if "math" not in subj:
        return False
    if s.get("document", {}).get("publicationStatus", "") == "Deprecated":
        return False
    for skip in ("spanish", "français", "vaap", "alternate", "modified", "access"):
        if skip in subj or skip in title:
            return False
    return True


def _select_grade_sets(sets: list[dict]) -> dict[str, list[str]]:
    math_sets = [s for s in sets if _is_core_math(s)]
    by_doc: dict[str, list[dict]] = defaultdict(list)
    for s in math_sets:
        doc_id = (s.get("document") or {}).get("id") or "unknown"
        by_doc[doc_id].append(s)

    best_coverage = max((len(v) for v in by_doc.values()), default=0)
    dominant_doc = None
    if best_coverage >= 5:
        dominant_doc = max(by_doc.keys(), key=lambda d: (len(by_doc[d]), d != "unknown"))

    candidate_sets = by_doc[dominant_doc] if dominant_doc else math_sets

    grade_best: dict[str, tuple[int, str]] = {}
    for s in candidate_sets:
        grade = _edlevels_to_grade(s.get("educationLevels", []))
        if not grade:
            continue
        year = int((s.get("document") or {}).get("valid", 0) or 0)
        if grade not in grade_best or year > grade_best[grade][0]:
            grade_best[grade] = (year, s["id"])

    grade_to_sets: dict[str, list[str]] = {g: [info[1]] for g, info in grade_best.items()}

    if dominant_doc and "HS" in grade_to_sets:
        hs_sets = [s["id"] for s in by_doc[dominant_doc]
                   if _edlevels_to_grade(s.get("educationLevels", [])) == "HS"]
        grade_to_sets["HS"] = list(dict.fromkeys(hs_sets))

    return grade_to_sets


def _ingest_set(
    set_id: str,
    grade: str,
    system: str,
    source_url: str,
    client: httpx.Client,
    conn: sqlite3.Connection,
    seen_ids: set[str],
    force_grade_prefix: bool = False,
) -> tuple[int, int]:
    cache = RAW_DIR / f"{set_id}.json"
    data = _fetch_json(f"{CSP_BASE}/standard_sets/{set_id}", cache, client)
    payload = data.get("data", data)
    stds_raw = payload.get("standards", {})
    all_stds = list(stds_raw.values()) if isinstance(stds_raw, dict) else stds_raw
    if not all_stds:
        return 0, 0

    by_id = {s["id"]: s for s in all_stds}

    depth_counts: dict[int, int] = {}
    for s in all_stds:
        if (s.get("statementNotation") or "").strip():
            d = s.get("depth", 0)
            depth_counts[d] = depth_counts.get(d, 0) + 1
    if not depth_counts:
        return 0, 0
    leaf_depth = max(depth_counts, key=lambda d: depth_counts[d])

    parent_ids_at_leaf = {
        s["parentId"] for s in all_stds
        if s.get("depth") == leaf_depth
        and (s.get("statementNotation") or "").strip()
        and s.get("parentId")
    }

    domains: dict[str, str] = {}
    clusters: dict[str, str] = {}
    for s in all_stds:
        d = s.get("depth", -1)
        desc = (s.get("description") or "").strip()
        if d == 0:
            domains[s["id"]] = desc
        elif d == leaf_depth - 1 and (s.get("statementNotation") or "").strip():
            clusters[s["id"]] = desc
        elif d == leaf_depth and s["id"] in parent_ids_at_leaf:
            clusters[s["id"]] = desc

    system_upper = system.upper().replace("-", "_")
    grade_band = "9-12" if grade == "HS" else None
    std_count = kw_count = 0

    for s in all_stds:
        if s.get("depth") != leaf_depth:
            continue
        if s["id"] in parent_ids_at_leaf:
            continue
        notation = (s.get("statementNotation") or "").strip()
        desc = (s.get("description") or "").strip()
        if not notation or not desc:
            continue

        if force_grade_prefix:
            std_id = f"{system_upper}.MATH.{grade}.{notation}"
        else:
            std_id = f"{system_upper}.MATH.{notation}"
        if std_id in seen_ids:
            continue
        seen_ids.add(std_id)

        domain = domains.get(s.get("parentId", ""), "")
        parent = by_id.get(s.get("parentId", ""))
        cluster = clusters.get(s.get("parentId", ""), "")

        conn.execute(
            """INSERT OR REPLACE INTO standards
               (id, system, subject, grade, grade_band, domain, cluster,
                standard_text, last_verified_date, source_url)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (std_id, system, "mathematics", grade, grade_band,
             domain, cluster, desc, VERIFIED_DATE, source_url),
        )
        std_count += 1

        for kw in _extract_keywords(desc):
            conn.execute(
                "INSERT OR IGNORE INTO keywords (standard_id, keyword) VALUES (?,?)",
                (std_id, kw),
            )
            kw_count += 1

    return std_count, kw_count


def _ingest_jurisdiction(org_id: str, system: str, client: httpx.Client, conn: sqlite3.Connection) -> tuple[int, int]:
    cache = RAW_DIR / f"jx_{org_id}.json"
    data = _fetch_json(f"{CSP_BASE}/jurisdictions/{org_id}", cache, client)
    payload = data.get("data", data)
    jx = payload if isinstance(payload, dict) else {}
    sets = jx.get("standardSets", [])
    source_url = jx.get("website", f"https://commonstandardsproject.com")

    grade_to_sets = _select_grade_sets(sets)
    if not grade_to_sets:
        print(f"  {system}: no math grade sets found")
        return 0, 0

    total_std = total_kw = 0
    seen_ids: set[str] = set()
    for grade in sorted(grade_to_sets.keys(), key=lambda g: GRADE_ORDER.index(g) if g in GRADE_ORDER else 99):
        for set_id in grade_to_sets[grade]:
            with conn:
                s, k = _ingest_set(set_id, grade, system, source_url, client, conn, seen_ids)
            total_std += s
            total_kw += k
        print(f"  {system} grade {grade}: done")

    return total_std, total_kw


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    grand_std = grand_kw = 0
    with httpx.Client() as client:
        for system, org_id in JURISDICTIONS.items():
            print(f"Fetching {system} ({org_id})...")
            s, k = _ingest_jurisdiction(org_id, system, client, conn)
            grand_std += s
            grand_kw += k
            print(f"  → {s} standards, {k} keywords")

    conn.close()
    print(f"\nTotal: {grand_std} standards, {grand_kw} keywords")
    print("Done.")


if __name__ == "__main__":
    main()
