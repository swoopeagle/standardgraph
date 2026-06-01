"""Stage 1-3: Download and ingest CCSS Math standards from Common Standards Project."""
import json
import re
import sqlite3
import sys
from pathlib import Path

import httpx

from shared.config import DB_PATH

RAW_DIR = DB_PATH.parent / "raw"
CSP_BASE = "https://commonstandardsproject.com/api/v1"

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each",
    "such", "both", "also", "into", "more", "most", "some", "other",
    "these", "those", "about", "able", "after", "where", "while", "make",
    "used", "given", "find", "show", "know", "understand", "apply",
}

GRADE_ORDER = ["K", "1", "2", "3", "4", "5", "6", "7", "8", "HS"]


def fetch_ccss_math() -> dict:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cache = RAW_DIR / "ccss_math.json"

    if cache.exists():
        print(f"  Using cached data: {cache}")
        return json.loads(cache.read_text())

    with httpx.Client(timeout=30) as client:
        print("  Fetching document list from commonstandardsproject.com...")
        resp = client.get(f"{CSP_BASE}/standard_documents")
        resp.raise_for_status()
        payload = resp.json()

        docs = payload if isinstance(payload, list) else payload.get("data", payload.get("standard_documents", []))

        ccss_math_id = None
        for doc in docs:
            title = doc.get("title", "") or doc.get("name", "")
            if "Common Core" in title and "Math" in title:
                ccss_math_id = doc.get("id")
                print(f"  Found: {title!r}  id={ccss_math_id}")
                break

        if not ccss_math_id:
            titles = [d.get("title", d.get("name", "?")) for d in docs[:10]]
            print(f"  Available documents: {titles}", file=sys.stderr)
            raise ValueError("CCSS Math document not found. Check stderr for available titles.")

        print(f"  Downloading full document...")
        resp = client.get(f"{CSP_BASE}/standard_documents/{ccss_math_id}")
        resp.raise_for_status()
        data = resp.json()

    cache.write_text(json.dumps(data, indent=2))
    print(f"  Cached to {cache}")
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


def grade_from_notation(notation: str) -> str:
    """'6.RP.A.3' -> '6', 'K.CC.A.1' -> 'K', 'HSN-RN.A.1' -> 'HS'."""
    if notation.startswith("HS"):
        return "HS"
    return notation.split(".")[0]


def domain_code_from_notation(notation: str) -> str:
    """'6.RP.A.3' -> 'RP', 'HSN-RN.A.1' -> 'N-RN'."""
    if notation.startswith("HS"):
        # e.g. HSN-RN -> N-RN
        rest = notation[2:]
        return rest.split(".")[0] if "." in rest else rest
    parts = notation.split(".")
    return parts[1] if len(parts) > 1 else ""


def ingest(data: dict) -> None:
    doc = data.get("data", data)
    raw_standards = doc.get("standards", [])
    print(f"  {len(raw_standards)} raw entries in document")

    by_id: dict[str, dict] = {s["id"]: s for s in raw_standards}

    domains: dict[str, str] = {}
    clusters: dict[str, dict] = {}

    for s in raw_standards:
        depth = s.get("depth", 0)
        desc = s.get("description", s.get("title", "")).strip()
        if depth == 3:
            domains[s["id"]] = desc
        elif depth == 4:
            grade = ""
            for anc_id in reversed(s.get("ancestorIds", [])):
                anc = by_id.get(anc_id, {})
                if anc.get("depth") == 2:
                    grade = anc.get("statementNotation", anc.get("listId", ""))
                    break
            clusters[s["id"]] = {
                "letter": s.get("listId", ""),
                "description": desc,
                "grade": grade,
            }

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    std_count = 0
    kw_count = 0

    with conn:
        for s in raw_standards:
            if s.get("depth") != 5:
                continue

            notation = s.get("statementNotation", "")
            description = s.get("description", s.get("title", "")).strip()
            if not notation or not description:
                continue

            std_id = f"CCSS.MATH.{notation}"
            grade = grade_from_notation(notation)
            domain_code = domain_code_from_notation(notation)

            cluster_id = None
            domain_id = None
            for anc_id in reversed(s.get("ancestorIds", [])):
                anc = by_id.get(anc_id, {})
                d = anc.get("depth")
                if d == 4 and cluster_id is None:
                    cluster_id = anc_id
                elif d == 3 and domain_id is None:
                    domain_id = anc_id

            cluster_info = clusters.get(cluster_id, {}) if cluster_id else {}
            domain_text = domains.get(domain_id, "") if domain_id else ""

            conn.execute(
                """INSERT OR REPLACE INTO standards
                   (id, source, grade, domain_code, domain, cluster_letter, cluster, description)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    std_id, "CCSS", grade, domain_code, domain_text,
                    cluster_info.get("letter", ""),
                    cluster_info.get("description", ""),
                    description,
                ),
            )
            std_count += 1

            for kw in extract_keywords(description):
                conn.execute(
                    "INSERT INTO keywords (standard_id, keyword) VALUES (?, ?)",
                    (std_id, kw),
                )
                kw_count += 1

    conn.close()
    print(f"  Inserted {std_count} standards, {kw_count} keywords")

    conn = sqlite3.connect(DB_PATH)
    s = conn.execute("SELECT COUNT(*) FROM standards WHERE source='CCSS'").fetchone()[0]
    k = conn.execute("SELECT COUNT(*) FROM keywords").fetchone()[0]
    conn.close()
    print(f"  DB: {s} CCSS standards, {k} keywords")


def main() -> None:
    print("Stage 1-3: Fetching CCSS Math standards...")
    data = fetch_ccss_math()
    ingest(data)
    print("Done.")


if __name__ == "__main__":
    main()
