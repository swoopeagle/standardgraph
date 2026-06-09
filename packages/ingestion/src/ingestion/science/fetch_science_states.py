"""Fetch and ingest science standards for all 50 US states via CSP API.

System IDs: {abbrev}-sci  e.g. tx-sci, ca-sci
Subject: science
Crosswalk hub: ngss

Captures all science discipline documents (Biology, Chemistry, Physics,
Earth Science, Environmental Science, unified K-12 Science, etc.).
Deprecated, alternate, and non-science sets are excluded.
"""
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

RAW_DIR = DB_PATH.parent / "raw" / "science_states"
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

_SCIENCE_KEYWORDS = ("science", "biology", "chemistry", "physics", "environmental",
                     "earth", "geology", "astronomy", "ecology")
_EXCLUDE_KEYWORDS = ("computer", "health", "consumer", "family", "agriculture",
                     "español", "spanish", "alternate", "modified", "access", "vaap")


def _is_core_science(s: dict) -> bool:
    subj  = (s.get("subject") or "").lower()
    title = (s.get("title") or "").lower()
    if s.get("document", {}).get("publicationStatus", "") == "Deprecated":
        return False
    if any(kw in subj or kw in title for kw in _EXCLUDE_KEYWORDS):
        return False
    return any(kw in subj or kw in title for kw in _SCIENCE_KEYWORDS)


def _cache_get(path: Path) -> dict | None:
    return json.loads(path.read_text()) if path.exists() else None


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
    grades = {EDLEVEL_TO_GRADE.get(lv, "") for lv in levels if lv in EDLEVEL_TO_GRADE}
    grades.discard("")
    if not grades:
        return ""
    if "HS" in grades:
        return "HS"
    return min(grades, key=lambda g: GRADE_ORDER.index(g) if g in GRADE_ORDER else 99)


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
) -> tuple[int, int]:
    if not all_stds:
        return 0, 0

    by_id: dict[str, dict] = {s["id"]: s for s in all_stds}

    depth_notation_counts: dict[int, int] = {}
    for s in all_stds:
        if (s.get("statementNotation") or "").strip():
            d = s.get("depth", 0)
            depth_notation_counts[d] = depth_notation_counts.get(d, 0) + 1
    if not depth_notation_counts:
        return 0, 0
    leaf_depth = max(depth_notation_counts, key=lambda d: depth_notation_counts[d])

    parent_ids_at_leaf = {
        s["parentId"]
        for s in all_stds
        if s.get("depth") == leaf_depth
        and (s.get("statementNotation") or "").strip()
        and s.get("parentId")
    }

    domains:  dict[str, str] = {}
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

    system = f"{state_abbrev}-sci"
    grade_band = "9-12" if grade == "HS" else None
    state_upper = state_abbrev.upper()

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

        std_id = f"{state_upper}.SCI.{notation}"
        if std_id in seen_ids:
            continue
        seen_ids.add(std_id)

        ancestors = s.get("ancestorIds", [])
        parent_id = s.get("parentId")
        domain_text = cluster_text = ""

        for anc_id in ancestors:
            anc = by_id.get(anc_id, {})
            anc_depth = anc.get("depth", -1)
            if anc_depth == 0:
                domain_text = domains.get(anc_id, "")
            elif anc_depth == leaf_depth - 1:
                cluster_text = clusters.get(anc_id, "")

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
            (std_id, system, "science", grade, grade_band,
             domain_text, cluster_text, desc, VERIFIED_DATE, source_url),
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
    abbrev = STATE_ABBREV.get(state_name, state_name[:2].lower())
    system = f"{abbrev}-sci"

    cache_path = RAW_DIR / f"jur_{jur_id}.json"
    jur_data = fetch_json(f"{CSP_BASE}/jurisdictions/{jur_id}", cache_path, client)
    all_sets = jur_data.get("data", {}).get("standardSets", [])

    science_sets = [s for s in all_sets if _is_core_science(s)]
    if not science_sets:
        return 0, 0

    set_source: dict[str, str] = {
        s["id"]: s.get("document", {}).get("sourceURL", "")
        for s in all_sets
    }

    total_std = total_kw = 0
    seen_ids: set[str] = set()

    for sci_set in science_sets:
        set_id = sci_set["id"]
        grade = edlevels_to_grade(sci_set.get("educationLevels", []))
        if not grade:
            grade = "HS"
        source_url = set_source.get(set_id, "")
        try:
            stds = fetch_set_standards(set_id, client)
        except httpx.HTTPError as e:
            print(f"    WARN: failed to fetch {set_id}: {e}")
            continue

        with conn:
            s, k = ingest_set(set_id, grade, abbrev, source_url, stds, conn, seen_ids)
        total_std += s
        total_kw += k

    return total_std, total_kw


def main(states_filter: list[str] | None = None) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    print("Fetching US state science standards from commonstandardsproject.com...")

    with httpx.Client() as client:
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
    filter_states = sys.argv[1:] if len(sys.argv) > 1 else None
    if filter_states:
        print(f"Filtering to: {filter_states}")
    main(filter_states)
