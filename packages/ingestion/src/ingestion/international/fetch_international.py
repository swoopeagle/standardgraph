"""Fetch and ingest international math standards from commonstandardsproject.com.

Covered systems:
  au-acara    Australian Curriculum (ACARA)
  au-vic      Victorian Curriculum (Australia)
  cambridge   Cambridge International Education (Primary + Lower Secondary + IGCSE)
  ib-myp      IB Middle Years Programme Mathematics
  ib-dp       IB Diploma Programme Mathematics
  uk-aqa      AQA GCSE Mathematics (England/Wales)
  uk-nc       England National Curriculum Mathematics (KS1-KS2, Years 1-6)
"""
import json
import re
import sqlite3
import sys
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

# ── Curriculum registry ──────────────────────────────────────────────────────
# Each entry: (csp_org_id, system_id, set_filter_fn, grade_override_fn)
#   set_filter_fn(set_dict) -> bool  — True to include the set
#   grade_override_fn(set_dict) -> str|None  — override edlevel-derived grade

def _is_math(s: dict) -> bool:
    subj = s.get("subject", "").lower()
    return "math" in subj and "access" not in s.get("title", "").lower()


def _not_deprecated(s: dict) -> bool:
    return s.get("document", {}).get("publicationStatus", "") != "Deprecated"


def _au_acara_filter(s: dict) -> bool:
    return _is_math(s) and _not_deprecated(s) and "Mathematics" == s.get("subject", "")


def _au_vic_filter(s: dict) -> bool:
    if not (_is_math(s) and _not_deprecated(s)):
        return False
    levels = s.get("educationLevels", [])
    # Skip the multi-level "Level 6" framework set (K-10 all at once)
    if len(levels) > 3:
        return False
    title = s.get("title", "")
    # Prefer "Year X" titles over "Level X" when both exist; de-dup handled later
    return True


def _cambridge_filter(s: dict) -> bool:
    return _is_math(s) and _not_deprecated(s)


def _ib_myp_filter(s: dict) -> bool:
    subj = s.get("subject", "")
    title = s.get("title", "")
    return "MYP: Mathematics" in subj or (
        "Mathematics" in title and ("Year" in title or "Framework" in title)
        and "MYP" not in subj and "Analysis" not in title and "Applications" not in title
    )


def _ib_dp_filter(s: dict) -> bool:
    title = s.get("title", "")
    return any(kw in title for kw in ("Analysis and Approaches", "Applications and Interpretation"))


def _uk_aqa_filter(s: dict) -> bool:
    return "math" in s.get("subject", "").lower() and _not_deprecated(s)


def _uk_nc_filter(s: dict) -> bool:
    if "math" not in s.get("subject", "").lower():
        return False
    if not _not_deprecated(s):
        return False
    # Skip the assessment framework set (multi-level, not curriculum statements)
    return "assessment framework" not in s.get("title", "").lower()


# IB MYP has empty educationLevels for Year 1 / Year 3; derive from title
_IB_MYP_TITLE_GRADE: dict[str, str] = {
    "Mathematics Year 1": "6",
    "Mathematics Year 3": "8",
}


def _ib_myp_grade_override(s: dict) -> str | None:
    return _IB_MYP_TITLE_GRADE.get(s.get("title", "").strip())


CURRICULA: list[dict] = [
    {
        "csp_id":       "CCF00D6D47C149B78B2339F8A137836D",
        "system":       "au-acara",
        "set_filter":   _au_acara_filter,
        "grade_override": None,
        "source_url":   "https://www.australiancurriculum.edu.au/f-10-curriculum/mathematics/",
    },
    {
        "csp_id":       "46B2191930FE47AC93A2BD710924AC4B",
        "system":       "au-vic",
        "set_filter":   _au_vic_filter,
        "grade_override": None,
        "source_url":   "https://victoriancurriculum.vcaa.vic.edu.au/mathematics/",
    },
    {
        "csp_id":       "4CD66FA670574787B151B04578670F6F",
        "system":       "cambridge",
        "set_filter":   _cambridge_filter,
        "grade_override": None,
        "source_url":   "https://www.cambridgeinternational.org/programmes-and-qualifications/cambridge-primary-and-lower-secondary/",
    },
    {
        "csp_id":       "6C108E8EC1944844B15FEFE71337CFB6",
        "system":       "ib-myp",
        "set_filter":   _ib_myp_filter,
        "grade_override": _ib_myp_grade_override,
        "source_url":   "https://www.ibo.org/programmes/middle-years-programme/curriculum/mathematics/",
    },
    {
        "csp_id":       "6C108E8EC1944844B15FEFE71337CFB6",
        "system":       "ib-dp",
        "set_filter":   _ib_dp_filter,
        "grade_override": None,
        "source_url":   "https://www.ibo.org/programmes/diploma-programme/curriculum/mathematics/",
    },
    {
        "csp_id":       "3A4F64A6B79845888BADD3F0EC2CFF66",
        "system":       "uk-aqa",
        "set_filter":   _uk_aqa_filter,
        "grade_override": None,
        "source_url":   "https://www.aqa.org.uk/subjects/mathematics/gcse/mathematics-8300",
    },
    {
        "csp_id":            "AA5150D37ACE44B1B365366AB7869005",
        "system":            "uk-nc",
        "set_filter":        _uk_nc_filter,
        "grade_override":    None,
        "force_grade_prefix": True,
        "source_url":        "https://www.gov.uk/government/publications/national-curriculum-in-england-mathematics-programmes-of-study",
    },
]

# ── Helpers ──────────────────────────────────────────────────────────────────

def _cache_get(path: Path) -> dict | None:
    return json.loads(path.read_text()) if path.exists() else None


def fetch_json(url: str, cache_path: Path, client: httpx.Client) -> dict:
    if cache_path.exists():
        return json.loads(cache_path.read_text())
    resp = client.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(data, indent=2))
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


def edlevels_to_grade(levels: list[str], override_fn=None, set_dict: dict | None = None) -> str:
    if override_fn and set_dict:
        g = override_fn(set_dict)
        if g:
            return g
    grades = {EDLEVEL_TO_GRADE.get(lv, "") for lv in levels if lv in EDLEVEL_TO_GRADE}
    grades.discard("")
    if not grades:
        return ""
    if "HS" in grades:
        return "HS"
    return min(grades, key=lambda g: GRADE_ORDER.index(g) if g in GRADE_ORDER else 99)


def ingest_set(
    all_stds: list[dict],
    grade: str,
    system: str,
    source_url: str,
    conn: sqlite3.Connection,
    seen_ids: set[str],
    force_grade_prefix: bool = False,
) -> tuple[int, int]:
    """Ingest standards from one set. Leaf-depth detection handles any structure."""
    if not all_stds:
        return 0, 0

    by_id = {s["id"]: s for s in all_stds}

    # Count notation items per depth; pick the depth with the most items
    # (avoids picking sparse depth-3 sub-points over dense depth-2 standards)
    depth_notation_counts: dict[int, int] = {}
    for s in all_stds:
        if (s.get("statementNotation") or "").strip():
            d = s.get("depth", 0)
            depth_notation_counts[d] = depth_notation_counts.get(d, 0) + 1
    if not depth_notation_counts:
        return 0, 0
    leaf_depth = max(depth_notation_counts, key=lambda d: depth_notation_counts[d])

    # Items that are parents of other notation-bearing items at the same depth
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

        # Include grade in ID when: (a) force_grade_prefix is set for the curriculum
        # (e.g. UK NC where Year 3 and Year 6 both use "S.1"), or (b) notation has no
        # dots and is short (e.g. IB MYP "D5") so same code appears in multiple years.
        if force_grade_prefix or ("." not in notation and len(notation) <= 8):
            std_id = f"{system_upper}.MATH.{grade}.{notation}"
        else:
            std_id = f"{system_upper}.MATH.{notation}"
        if std_id in seen_ids:
            continue
        seen_ids.add(std_id)

        ancestors = s.get("ancestorIds", [])
        parent_id = s.get("parentId")
        domain_text = cluster_text = ""

        for anc_id in ancestors:
            anc = by_id.get(anc_id, {})
            anc_d = anc.get("depth", -1)
            if anc_d == 0:
                domain_text = domains.get(anc_id, "")
            elif anc_d == leaf_depth - 1:
                cluster_text = clusters.get(anc_id, "")

        if not domain_text and parent_id:
            p = by_id.get(parent_id, {})
            if p.get("depth") == 0:
                domain_text = domains.get(parent_id, "")
            elif p.get("depth") == leaf_depth - 1:
                cluster_text = clusters.get(parent_id, "")
                gp = by_id.get(p.get("parentId", ""), {})
                if gp.get("depth") == 0:
                    domain_text = domains.get(p.get("parentId", ""), "")

        conn.execute(
            """INSERT OR REPLACE INTO standards
               (id, system, subject, grade, grade_band, domain, cluster,
                standard_text, last_verified_date, source_url)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (std_id, system, "mathematics", grade, grade_band,
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


def ingest_curriculum(curriculum: dict, conn: sqlite3.Connection, client: httpx.Client) -> tuple[int, int]:
    """Fetch and ingest all math sets for one international curriculum."""
    csp_id  = curriculum["csp_id"]
    system  = curriculum["system"]
    source_url   = curriculum["source_url"]
    set_filter   = curriculum["set_filter"]
    grade_override = curriculum["grade_override"]

    cache_path = RAW_DIR / f"jur_{csp_id}.json"
    jur_data = fetch_json(f"{CSP_BASE}/jurisdictions/{csp_id}", cache_path, client)
    all_sets = jur_data.get("data", {}).get("standardSets", [])

    math_sets = [s for s in all_sets if set_filter(s)]

    # Deduplicate: for each grade, prefer "Year X" title over "Level X";
    # otherwise keep set with more standards (fetched lazily below).
    grade_candidates: dict[str, list[dict]] = defaultdict(list)
    for s in math_sets:
        grade = edlevels_to_grade(
            s.get("educationLevels", []),
            override_fn=grade_override,
            set_dict=s,
        )
        if grade:
            grade_candidates[grade].append(s)

    if not grade_candidates:
        print(f"  {system}: no grade sets found — skipping")
        return 0, 0

    total_std = total_kw = 0

    for grade in sorted(grade_candidates.keys(), key=lambda g: GRADE_ORDER.index(g) if g in GRADE_ORDER else 99):
        candidates = grade_candidates[grade]

        # Fetch ALL sets for this grade and combine; prefer "Year X" titles first.
        # Using a fresh seen_ids per grade prevents collision when different years
        # share the same notation codes (e.g. IB MYP Year 1 and Year 3 both use D1-D5).
        grade_stds: list[dict] = []
        sorted_candidates = sorted(
            candidates,
            key=lambda s: (0 if s.get("title", "").startswith("Year") else 1),
        )
        source_url_for_grade = source_url
        for candidate in sorted_candidates:
            cache = RAW_DIR / f"{candidate['id']}.json"
            try:
                set_data = fetch_json(f"{CSP_BASE}/standard_sets/{candidate['id']}", cache, client)
            except httpx.HTTPError as e:
                print(f"    WARN: {system} grade {grade}: {e}")
                continue
            payload  = set_data.get("data", set_data)
            stds_raw = payload.get("standards", {})
            grade_stds.extend(list(stds_raw.values()) if isinstance(stds_raw, dict) else stds_raw)

        if not grade_stds:
            continue

        seen_ids: set[str] = set()  # fresh per grade — avoids cross-year notation collision
        with conn:
            s, k = ingest_set(
                grade_stds, grade, system, source_url_for_grade, conn, seen_ids,
                force_grade_prefix=curriculum.get("force_grade_prefix", False),
            )
        total_std += s
        total_kw  += k

    return total_std, total_kw


def main(systems_filter: list[str] | None = None) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    curricula = CURRICULA
    if systems_filter:
        curricula = [c for c in curricula if c["system"] in systems_filter]

    print(f"Fetching international math standards ({len(curricula)} curricula)...")

    grand_std = grand_kw = 0
    with httpx.Client() as client:
        for curriculum in curricula:
            system = curriculum["system"]
            try:
                std_n, kw_n = ingest_curriculum(curriculum, conn, client)
                grand_std += std_n
                grand_kw  += kw_n
                if std_n:
                    print(f"  {system}: {std_n} standards, {kw_n} keywords")
                else:
                    print(f"  {system}: 0 standards (check filter)")
            except Exception as exc:
                print(f"  {system}: ERROR — {exc}")

    conn.close()
    print(f"\nTotal: {grand_std} standards, {grand_kw} keywords")
    print("Done.")


if __name__ == "__main__":
    filter_systems = sys.argv[1:] if len(sys.argv) > 1 else None
    if filter_systems:
        print(f"Filtering to: {filter_systems}")
    main(filter_systems)
