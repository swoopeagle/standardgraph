"""Fetch and ingest math standards for Canadian provinces from commonstandardsproject.com.

Covered provinces:
  ca-bc   British Columbia
  ca-ab   Alberta
  ca-on   Ontario
  ca-mb   Manitoba
  ca-sk   Saskatchewan
  ca-nb   New Brunswick
"""
import sqlite3
import sys
from pathlib import Path

import httpx

from shared.config import DB_PATH
from ingestion.states.fetch_states import (
    fetch_json,
    fetch_set_standards,
    ingest_set,
    select_grade_sets,
    GRADE_ORDER,
)

RAW_DIR = DB_PATH.parent / "raw" / "canada"
CSP_BASE = "https://commonstandardsproject.com/api/v1"

PROVINCES: dict[str, str] = {
    # title → system_id
    "British Columbia": "ca-bc",
    "Alberta":          "ca-ab",
    "Ontario":          "ca-on",
    "Manitoba":         "ca-mb",
    "Saskatchewan":     "ca-sk",
    "New Brunswick":    "ca-nb",
}


def ingest_province(
    prov_name: str,
    jur_id: str,
    system: str,
    conn: sqlite3.Connection,
    client: httpx.Client,
) -> tuple[int, int]:
    cache_path = RAW_DIR / f"jur_{jur_id}.json"
    jur_data = fetch_json(f"{CSP_BASE}/jurisdictions/{jur_id}", cache_path, client)
    all_sets = jur_data.get("data", {}).get("standardSets", [])

    grade_to_sets = select_grade_sets(all_sets)
    if not grade_to_sets:
        print(f"  {prov_name}: no grade sets found — skipping")
        return 0, 0

    set_source: dict[str, str] = {
        s["id"]: s.get("document", {}).get("sourceURL", "")
        for s in all_sets
    }

    total_std = total_kw = 0

    for grade in sorted(grade_to_sets.keys(), key=lambda g: GRADE_ORDER.index(g) if g in GRADE_ORDER else 99):
        set_ids = grade_to_sets[grade]
        grade_stds: list[dict] = []
        source_url = set_source.get(set_ids[0], "") if set_ids else ""
        for sid in set_ids:
            try:
                # Use states RAW_DIR for caching (set IDs are globally unique)
                grade_stds.extend(fetch_set_standards(sid, client))
            except httpx.HTTPError as e:
                print(f"    WARN: {system} grade {grade}: {e}")

        seen_ids: set[str] = set()  # fresh per grade — notation codes repeat across grades
        with conn:
            s, k = ingest_set(set_ids[0] if set_ids else "", grade, system, source_url, grade_stds, conn, seen_ids,
                              force_grade_prefix=True)
        total_std += s
        total_kw  += k

    return total_std, total_kw


def main(provinces_filter: list[str] | None = None) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    # Resolve jurisdiction IDs from CSP
    jur_cache = RAW_DIR / "jurisdictions.json"
    with httpx.Client() as client:
        jur_data = fetch_json(f"{CSP_BASE}/jurisdictions", jur_cache, client)
    jurisdictions = jur_data.get("data", [])

    targets = {
        j["title"]: (PROVINCES[j["title"]], j["id"])
        for j in jurisdictions
        if j["title"] in PROVINCES
    }

    if provinces_filter:
        targets = {k: v for k, v in targets.items() if k in provinces_filter or v[0] in provinces_filter}

    print(f"Fetching Canadian province math standards ({len(targets)} provinces)...")

    grand_std = grand_kw = 0
    with httpx.Client() as client:
        for prov_name in sorted(targets):
            system, jid = targets[prov_name]
            try:
                n, k = ingest_province(prov_name, jid, system, conn, client)
                grand_std += n
                grand_kw  += k
                if n:
                    print(f"  {prov_name} ({system}): {n} standards, {k} keywords")
                else:
                    print(f"  {prov_name}: 0 standards")
            except Exception as e:
                print(f"  {prov_name}: ERROR — {e}")

    conn.close()
    print(f"\nTotal: {grand_std} standards, {grand_kw} keywords")
    print("Done.")


if __name__ == "__main__":
    filter_args = sys.argv[1:] if len(sys.argv) > 1 else None
    if filter_args:
        print(f"Filtering to: {filter_args}")
    main(filter_args)
