"""Fetch and ingest math standards for all 50 US states from commonstandardsproject.com."""
import json
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from shared.config import DB_PATH

RAW_DIR = DB_PATH.parent / "raw" / "states"
CSP_BASE = "https://commonstandardsproject.com/api/v1"

VERIFIED_DATE = date.today().isoformat()

US_STATES: set[str] = {
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
    "Connecticut", "Delaware", "District of Columbia", "Florida", "Georgia",
    "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky",
    "Louisiana", "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota",
    "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada", "New Hampshire",
    "New Jersey", "New Mexico", "New York", "North Carolina", "North Dakota",
    "Ohio", "Oklahoma", "Oregon", "Pennsylvania", "Rhode Island",
    "South Carolina", "South Dakota", "Tennessee", "Texas", "Utah", "Vermont",
    "Virginia", "Washington", "West Virginia", "Wisconsin", "Wyoming",
}

STATE_ABBREV: dict[str, str] = {
    "Alabama": "al", "Alaska": "ak", "Arizona": "az", "Arkansas": "ar",
    "California": "ca", "Colorado": "co", "Connecticut": "ct", "Delaware": "de",
    "District of Columbia": "dc", "Florida": "fl", "Georgia": "ga",
    "Hawaii": "hi", "Idaho": "id", "Illinois": "il", "Indiana": "in",
    "Iowa": "ia", "Kansas": "ks", "Kentucky": "ky", "Louisiana": "la",
    "Maine": "me", "Maryland": "md", "Massachusetts": "ma", "Michigan": "mi",
    "Minnesota": "mn", "Mississippi": "ms", "Missouri": "mo", "Montana": "mt",
    "Nebraska": "ne", "Nevada": "nv", "New Hampshire": "nh", "New Jersey": "nj",
    "New Mexico": "nm", "New York": "ny", "North Carolina": "nc",
    "North Dakota": "nd", "Ohio": "oh", "Oklahoma": "ok", "Oregon": "or",
    "Pennsylvania": "pa", "Rhode Island": "ri", "South Carolina": "sc",
    "South Dakota": "sd", "Tennessee": "tn", "Texas": "tx", "Utah": "ut",
    "Vermont": "vt", "Virginia": "va", "Washington": "wa",
    "West Virginia": "wv", "Wisconsin": "wi", "Wyoming": "wy",
}

GRADE_ORDER = ["K", "1", "2", "3", "4", "5", "6", "7", "8", "HS"]

EDLEVEL_TO_GRADE: dict[str, str] = {
    "KG": "K", "00": "K", "0": "K", "K": "K",
    "01": "1", "1": "1", "02": "2", "2": "2",
    "03": "3", "3": "3", "04": "4", "4": "4",
    "05": "5", "5": "5", "06": "6", "6": "6",
    "07": "7", "7": "7", "08": "8", "8": "8",
    "09": "HS", "10": "HS", "11": "HS", "12": "HS",
    "9": "HS",
}

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each",
    "such", "both", "also", "into", "more", "most", "some", "other",
    "these", "those", "about", "able", "after", "where", "while", "make",
    "used", "given", "find", "show", "know", "understand", "apply",
}


def _cache_get(path: Path) -> dict | None:
    if path.exists():
        return json.loads(path.read_text())
    return None


def _cache_set(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def fetch_json(url: str, cache_path: Path, client: httpx.Client) -> dict:
    cached = _cache_get(cache_path)
    if cached is not None:
        return cached
    resp = client.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    _cache_set(cache_path, data)
    return data


def extract_keywords(text: str) -> list[str]:
    words = re.findall(r'\b[a-zA-Z][a-zA-Z-]{3,}\b', text.lower())
    seen: set[str] = set()
    result = []
    for w in words:
        if w not in STOP_WORDS and w not in seen:
            seen.add(w)
            result.append(w)
    return result[:20]


def edlevels_to_grade(levels: list[str]) -> str:
    """Map a list of education level codes to K/1-8/HS grade string."""
    grades = {EDLEVEL_TO_GRADE.get(lv, "") for lv in levels if lv in EDLEVEL_TO_GRADE}
    grades.discard("")
    if not grades:
        return ""
    # If any HS level present, mark as HS
    if "HS" in grades:
        return "HS"
    # Return lowest grade in set (pick the set's base grade)
    return min(grades, key=lambda g: GRADE_ORDER.index(g) if g in GRADE_ORDER else 99)


def _doc_year(s: dict) -> int:
    """Return the document's valid year for recency comparison (0 if unknown)."""
    try:
        return int(s.get("document", {}).get("valid", 0) or 0)
    except (ValueError, TypeError):
        return 0


def select_grade_sets(sets: list[dict]) -> dict[str, list[str]]:
    """
    From a jurisdiction's standardSets, return a mapping of grade → list of set IDs.

    Handles two patterns:
    - One document covering all grades (Texas, Florida): picks that doc and
      collects its sets, deduplicating by grade.
    - One document per grade (Arizona, Virginia): collects the most recent
      published set for each grade across all documents.

    Access Points, Spanish/French, and Deprecated sets are excluded.
    """
    def _is_core_math(s: dict) -> bool:
        subj = (s.get("subject") or "").lower()
        title = (s.get("title") or "").lower()
        if "math" not in subj:
            return False
        if s.get("document", {}).get("publicationStatus", "") == "Deprecated":
            return False
        # Exclude language variants and accessibility programs
        for skip in ("spanish", "français", "vaap", "alternate", "modified", "access"):
            if skip in subj or skip in title:
                return False
        return True

    math_sets = [s for s in sets if _is_core_math(s)]

    # Group by document ID to find how many grade-sets each document covers
    by_doc: dict[str, list[dict]] = defaultdict(list)
    for s in math_sets:
        doc_id = s.get("document", {}).get("id") or s.get("document", {}).get("asnIdentifier") or "unknown"
        by_doc[doc_id].append(s)

    # If one document covers 5+ grade sets, treat it as the canonical source.
    # Prefer named document IDs over "unknown" (course sets without a shared doc ID,
    # e.g. Ontario's standalone 2021 HS courses, should not beat a proper K-8 document).
    dominant_doc: str | None = None
    named_docs = {k: v for k, v in by_doc.items() if k != "unknown"}
    best_named_coverage = max((len(v) for v in named_docs.values()), default=0)
    best_coverage = max((len(v) for v in by_doc.values()), default=0)
    if best_named_coverage >= 5:
        dominant_doc = max(named_docs.keys(), key=lambda d: len(named_docs[d]))
    elif best_coverage >= 5:
        dominant_doc = max(by_doc.keys(), key=lambda d: len(by_doc[d]))

    candidate_sets = by_doc[dominant_doc] if dominant_doc else math_sets

    # Build grade → best set-id (most recent document year wins)
    grade_best: dict[str, tuple[int, str]] = {}  # grade → (year, set_id)
    for s in candidate_sets:
        grade = edlevels_to_grade(s.get("educationLevels", []))
        if not grade:
            continue
        year = _doc_year(s)
        sid  = s["id"]
        if grade not in grade_best or year > grade_best[grade][0]:
            grade_best[grade] = (year, sid)

    # For HS, some states split into course sets — collect all of them from
    # the same document (like CCSS does for Algebra I/II/Geometry)
    grade_to_sets: dict[str, list[str]] = {g: [info[1]] for g, info in grade_best.items()}

    # Add extra HS sets when the dominant doc has multiple HS sets
    if dominant_doc and "HS" in grade_to_sets:
        hs_sets_in_doc = [
            s["id"] for s in by_doc[dominant_doc]
            if edlevels_to_grade(s.get("educationLevels", [])) == "HS"
        ]
        grade_to_sets["HS"] = list(dict.fromkeys(hs_sets_in_doc))  # dedup, order-stable

    return grade_to_sets


def fetch_set_standards(set_id: str, client: httpx.Client) -> list[dict]:
    cache = RAW_DIR / f"{set_id}.json"
    data = fetch_json(f"{CSP_BASE}/standard_sets/{set_id}", cache, client)
    payload = data.get("data", data)
    stds = payload.get("standards", {})
    return list(stds.values()) if isinstance(stds, dict) else stds


def ingest_set(
    set_id: str,
    grade: str,
    state_abbrev: str,
    source_url: str,
    all_stds: list[dict],
    conn: sqlite3.Connection,
    seen_ids: set[str],
    force_grade_prefix: bool = False,
) -> tuple[int, int]:
    """
    Ingest one grade set for a state. Returns (standards_inserted, keywords_inserted).

    Depth detection: treats the deepest depth-level that has statementNotation
    items as the leaf (standard) level. Items one level above provide cluster
    context; items at depth-0 provide domain context.
    """
    if not all_stds:
        return 0, 0

    by_id: dict[str, dict] = {s["id"]: s for s in all_stds}

    # Find leaf depth: depth with the most notation items
    depth_notation_counts: dict[int, int] = {}
    for s in all_stds:
        if (s.get("statementNotation") or "").strip():
            d = s.get("depth", 0)
            depth_notation_counts[d] = depth_notation_counts.get(d, 0) + 1
    if not depth_notation_counts:
        return 0, 0
    leaf_depth = max(depth_notation_counts, key=lambda d: depth_notation_counts[d])

    # Among items at leaf_depth, find true leaves (items that are NOT
    # parentId of another notation-bearing item at the same depth).
    parent_ids_at_leaf = {
        s["parentId"]
        for s in all_stds
        if s.get("depth") == leaf_depth
        and (s.get("statementNotation") or "").strip()
        and s.get("parentId")
    }

    # Build domain and cluster lookup by ID
    domains:  dict[str, str]  = {}
    clusters: dict[str, str]  = {}
    for s in all_stds:
        d = s.get("depth", -1)
        desc = (s.get("description") or "").strip()
        if d == 0:
            domains[s["id"]] = desc
        elif d == leaf_depth - 1 and (s.get("statementNotation") or "").strip():
            clusters[s["id"]] = desc
        # Also treat leaf-depth items that have children as cluster-level context
        elif d == leaf_depth and s["id"] in parent_ids_at_leaf:
            clusters[s["id"]] = desc

    system = state_abbrev
    grade_band = "9-12" if grade == "HS" else None
    state_upper = state_abbrev.upper()

    std_count = kw_count = 0

    for s in all_stds:
        if s.get("depth") != leaf_depth:
            continue
        # Skip items that are parents of other notation-bearing items at same depth
        if s["id"] in parent_ids_at_leaf:
            continue
        notation = (s.get("statementNotation") or "").strip()
        desc = (s.get("description") or "").strip()
        if not notation or not desc:
            continue

        if force_grade_prefix:
            std_id = f"{state_upper}.MATH.{grade}.{notation}"
        else:
            std_id = f"{state_upper}.MATH.{notation}"
        if std_id in seen_ids:
            continue
        seen_ids.add(std_id)

        ancestors = s.get("ancestorIds", [])
        parent_id = s.get("parentId")

        domain_text  = ""
        cluster_text = ""

        # Walk ancestors from root to leaf
        for anc_id in ancestors:
            anc = by_id.get(anc_id, {})
            anc_depth = anc.get("depth", -1)
            if anc_depth == 0:
                domain_text = domains.get(anc_id, "")
            elif anc_depth == leaf_depth - 1:
                cluster_text = clusters.get(anc_id, "")

        # Fallback: check direct parent
        if not domain_text and parent_id:
            p = by_id.get(parent_id, {})
            if p.get("depth", -1) == 0:
                domain_text = domains.get(parent_id, "")
            elif p.get("depth", -1) == leaf_depth - 1:
                cluster_text = clusters.get(parent_id, "")
                gp_id = p.get("parentId")
                if gp_id:
                    domain_text = domains.get(gp_id, "")

        conn.execute(
            """INSERT OR REPLACE INTO standards
               (id, system, subject, grade, grade_band, domain, cluster,
                standard_text, last_verified_date, source_url)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                std_id, system, "mathematics", grade, grade_band,
                domain_text, cluster_text,
                desc, VERIFIED_DATE, source_url,
            ),
        )
        std_count += 1

        for kw in extract_keywords(desc):
            conn.execute(
                "INSERT OR IGNORE INTO keywords (standard_id, keyword) VALUES (?,?)",
                (std_id, kw),
            )
            kw_count += 1

    return std_count, kw_count


def ingest_state(
    state_name: str,
    jur_id: str,
    conn: sqlite3.Connection,
    client: httpx.Client,
) -> tuple[int, int]:
    """Fetch and ingest all math standards for one US state."""
    abbrev = STATE_ABBREV.get(state_name, state_name[:2].lower())

    # Fetch jurisdiction detail (cached)
    cache_path = RAW_DIR / f"jur_{jur_id}.json"
    jur_data = fetch_json(f"{CSP_BASE}/jurisdictions/{jur_id}", cache_path, client)
    all_sets = jur_data.get("data", {}).get("standardSets", [])

    grade_to_sets = select_grade_sets(all_sets)
    if not grade_to_sets:
        print(f"  {state_name}: no grade sets found — skipping")
        return 0, 0

    # Build a set_id → source_url lookup from the jurisdiction data
    set_source: dict[str, str] = {
        s["id"]: s.get("document", {}).get("sourceURL", "")
        for s in all_sets
    }

    total_std = total_kw = 0
    seen_ids: set[str] = set()

    for grade in sorted(grade_to_sets.keys(), key=lambda g: GRADE_ORDER.index(g) if g in GRADE_ORDER else 99):
        set_ids = grade_to_sets[grade]
        grade_stds: list[dict] = []
        source_url = set_source.get(set_ids[0], "") if set_ids else ""
        for sid in set_ids:
            try:
                grade_stds.extend(fetch_set_standards(sid, client))
            except httpx.HTTPError as e:
                print(f"    WARN: failed to fetch {sid}: {e}")

        with conn:
            s, k = ingest_set(set_ids[0] if set_ids else "", grade, abbrev, source_url, grade_stds, conn, seen_ids)

        total_std += s
        total_kw  += k

    return total_std, total_kw


def main(states_filter: list[str] | None = None) -> None:
    """
    Ingest math standards for all US states (or a subset).

    Args:
        states_filter: if provided, only ingest these state names.
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    print("Fetching US state math standards from commonstandardsproject.com...")

    with httpx.Client() as client:
        # Load jurisdiction list (cached)
        jur_cache = RAW_DIR / "jurisdictions.json"
        jur_data = fetch_json(f"{CSP_BASE}/jurisdictions", jur_cache, client)
        jurisdictions = jur_data.get("data", [])

    state_jurs = [
        j for j in jurisdictions
        if j.get("type") == "state" and j.get("title") in US_STATES
    ]
    if states_filter:
        state_jurs = [j for j in state_jurs if j["title"] in states_filter]

    print(f"Processing {len(state_jurs)} states...")

    grand_std = grand_kw = 0
    skipped = []

    with httpx.Client() as client:
        for jur in sorted(state_jurs, key=lambda j: j["title"]):
            name = jur["title"]
            jid  = jur["id"]
            try:
                std_n, kw_n = ingest_state(name, jid, conn, client)
                if std_n:
                    print(f"  {name}: {std_n} standards, {kw_n} keywords")
                grand_std += std_n
                grand_kw  += kw_n
                if not std_n:
                    skipped.append(name)
            except Exception as exc:
                print(f"  {name}: ERROR — {exc}")
                skipped.append(name)

    conn.close()
    print(f"\nTotal: {grand_std} standards, {grand_kw} keywords")
    if skipped:
        print(f"Skipped ({len(skipped)}): {', '.join(skipped)}")
    print("Done.")


if __name__ == "__main__":
    # Optional: pass state names as CLI args for partial runs
    filter_states = sys.argv[1:] if len(sys.argv) > 1 else None
    if filter_states:
        print(f"Filtering to: {filter_states}")
    main(filter_states)
