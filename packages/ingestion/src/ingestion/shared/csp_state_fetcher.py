"""Shared CSP state standard fetcher — parameterized by subject.

Handles the full lifecycle:
  1. Fetch /jurisdictions to get US state IDs
  2. For each state, fetch /jurisdictions/{id} → filter sets by subject keywords
  3. For each matching set, fetch /standard_sets/{id} → ingest leaf standards

Usage (from a subject module):
    from ingestion.shared.csp_state_fetcher import SubjectConfig, fetch_all_states
    CONFIG = SubjectConfig(
        include_kw=("english language arts", "literacy"),
        exclude_kw=("spanish", "alternate"),
        system_suffix="-ela",
        subject_value="ela",
    )
    fetch_all_states(CONFIG)
"""
import json
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Sequence

import httpx

from shared.config import DB_PATH

CSP_BASE      = "https://commonstandardsproject.com/api/v1"
VERIFIED_DATE = date.today().isoformat()

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

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each",
    "such", "both", "also", "into", "more", "most", "some", "other",
    "these", "those", "about", "able", "after", "where", "while", "make",
    "used", "given", "find", "show", "know", "understand", "apply",
    "students", "student",
}


@dataclass
class SubjectConfig:
    include_kw:    tuple[str, ...]
    exclude_kw:    tuple[str, ...]
    system_suffix: str    # e.g. "-ela"
    subject_value: str    # stored in DB subject column, e.g. "ela"
    raw_subdir:    str    # subdirectory under data/raw/
    source_label:  str    # human-readable, used in source_url fallback


def _cache_get(path: Path) -> dict | None:
    return json.loads(path.read_text()) if path.exists() else None


def _cache_set(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


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


def _is_target_subject(s: dict, cfg: SubjectConfig) -> bool:
    if s.get("document", {}).get("publicationStatus", "") == "Deprecated":
        return False
    txt = ((s.get("subject") or "") + " " + (s.get("title") or "")).lower()
    if any(k in txt for k in cfg.exclude_kw):
        return False
    return any(k in txt for k in cfg.include_kw)


def _fetch_set_standards(set_id: str, raw_dir: Path, client: httpx.Client) -> list[dict]:
    cache = raw_dir / f"{set_id}.json"
    data = _fetch_json(f"{CSP_BASE}/standard_sets/{set_id}", cache, client)
    payload = data.get("data", data)
    stds = payload.get("standards", {})
    return list(stds.values()) if isinstance(stds, dict) else stds


def _ingest_set(
    set_id: str,
    grade: str,
    system: str,
    subject_value: str,
    source_url: str,
    all_stds: list[dict],
    conn: sqlite3.Connection,
    seen_ids: set[str],
) -> tuple[int, int]:
    if not all_stds:
        return 0, 0

    depth_notation_counts: dict[int, int] = defaultdict(int)
    for s in all_stds:
        if (s.get("statementNotation") or "").strip():
            depth_notation_counts[s.get("depth", 0)] += 1
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
        if s.get("depth") != leaf_depth:
            continue
        if s["id"] in parent_ids_at_leaf:
            continue
        notation = (s.get("statementNotation") or "").strip()
        desc     = (s.get("description") or "").strip()
        if not notation or not desc:
            continue

        std_id = f"{system}.{notation}"
        if std_id in seen_ids:
            continue
        seen_ids.add(std_id)

        domain_text  = ""
        cluster_text = ""
        pid = s.get("parentId", "")
        anc = s.get("ancestorIds", [])
        if pid in domains:
            domain_text = domains[pid]
        elif pid in clusters:
            cluster_text = clusters[pid]
        for anc_id in anc:
            if not domain_text and anc_id in domains:
                domain_text = domains[anc_id]
            if not cluster_text and anc_id in clusters:
                cluster_text = clusters[anc_id]

        conn.execute(
            """INSERT OR REPLACE INTO standards
               (id, system, subject, grade, grade_band, domain, cluster,
                standard_text, last_verified_date, source_url)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (std_id, system, subject_value, grade, grade_band,
             domain_text, cluster_text, desc, VERIFIED_DATE, source_url),
        )
        std_count += 1
        for kw in _extract_keywords(desc):
            conn.execute(
                "INSERT OR IGNORE INTO keywords (standard_id, keyword) VALUES (?,?)",
                (std_id, kw),
            )
            kw_count += 1

    return std_count, kw_count


def fetch_all_states(cfg: SubjectConfig, states_filter: Sequence[str] | None = None) -> None:
    raw_dir = DB_PATH.parent / "raw" / cfg.raw_subdir
    raw_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    print(f"Fetching US state {cfg.subject_value.upper()} standards from commonstandardsproject.com...")

    with httpx.Client() as client:
        jur_cache = raw_dir / "jurisdictions.json"
        jur_data  = _fetch_json(f"{CSP_BASE}/jurisdictions", jur_cache, client)
        jurisdictions = jur_data.get("data", [])

    state_jurs = [
        j for j in jurisdictions
        if j.get("type") == "state" and j.get("title") in US_STATES
    ]
    if states_filter:
        state_jurs = [j for j in state_jurs if j["title"] in states_filter]

    print(f"Processing {len(state_jurs)} states...")
    grand_std = grand_kw = 0
    skipped: list[str] = []

    with httpx.Client() as client:
        for jur in sorted(state_jurs, key=lambda j: j["title"]):
            name   = jur["title"]
            jid    = jur["id"]
            abbrev = STATE_ABBREV.get(name, name[:2].lower())
            system = f"{abbrev}{cfg.system_suffix}"

            cache_path = raw_dir / f"jur_{jid}.json"
            try:
                jur_data = _fetch_json(f"{CSP_BASE}/jurisdictions/{jid}", cache_path, client)
            except Exception as e:
                print(f"  {name}: ERROR fetching jurisdiction — {e}")
                continue

            all_sets      = jur_data.get("data", {}).get("standardSets", [])
            subject_sets  = [s for s in all_sets if _is_target_subject(s, cfg)]
            if not subject_sets:
                skipped.append(name)
                continue

            set_source = {s["id"]: s.get("document", {}).get("sourceURL", "") for s in all_sets}

            with conn:
                suffix_upper = cfg.system_suffix.lstrip("-").replace("-", "_").upper()
                conn.execute("DELETE FROM keywords WHERE standard_id LIKE ?",
                             (f"{abbrev}{cfg.system_suffix}.%",))
                conn.execute("DELETE FROM standards WHERE system = ?", (system,))

            total_std = total_kw = 0
            seen_ids: set[str] = set()

            for sset in subject_sets:
                set_id = sset["id"]
                grade  = _edlevels_to_grade(sset.get("educationLevels", []))
                if not grade:
                    grade = "HS"
                source_url = set_source.get(set_id, "")
                try:
                    stds = _fetch_set_standards(set_id, raw_dir, client)
                except httpx.HTTPError as e:
                    print(f"    WARN: {set_id}: {e}")
                    continue

                with conn:
                    s, k = _ingest_set(
                        set_id, grade, system, cfg.subject_value,
                        source_url, stds, conn, seen_ids,
                    )
                total_std += s
                total_kw  += k

            if total_std:
                print(f"  {name}: {total_std} standards, {total_kw} keywords")
                grand_std += total_std
                grand_kw  += total_kw
            else:
                skipped.append(name)

    conn.close()

    if skipped:
        print(f"\nNo {cfg.subject_value} standards found for: {', '.join(skipped)}")
    print(f"\nTotal: {grand_std} standards, {grand_kw} keywords")
    print("Done.")
