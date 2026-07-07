"""Fetch and ingest Ontario elementary math standards (Grades 1–8).

Covered system: ca-on (extends existing HS-only data with grades 1–8)
Source: Ontario Ministry of Education — The Ontario Curriculum, Mathematics, 2020,
  served as structured content from the ministry's public Kentico-backed API
  (the same endpoint the dcp.edu.gov.on.ca site's SSR uses — no key required):
    https://ws.api.dcp.edu.gov.on.ca/content/api

Why the API and not a PDF: Ontario publishes the 2020 curriculum only as an
interactive web app, not a clean PDF. The delivery API returns each specific
expectation as structured JSON with its exact code and verbatim text — far more
reliable than OCR + LLM extraction.

Content model (Kentico types):
  l4___overall_expectation  → codename encodes grade+strand: 'math___grade_5___b_...'
    .specific_expectations   → l5___specific_expectation items
  l5___specific_expectation → title_index (code, e.g. 'B2.5'), content (rich text)

Grade + strand are read from the l4 codename (the l3 strand layer is unreliable
for some grade/strand combinations, so we anchor on l4 instead).
"""
import html
import re
import sqlite3
import sys
from datetime import date

import httpx

from shared.config import DB_PATH

SYSTEM = "ca-on"
API = "https://ws.api.dcp.edu.gov.on.ca/content/api"
SOURCE_URL = "https://www.dcp.edu.gov.on.ca/en/curriculum/elementary-mathematics"
VERIFIED_DATE = date.today().isoformat()
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/125.0 Safari/537.36"

STRAND_NAME = {
    "a": "Social-Emotional Learning", "b": "Number", "c": "Algebra",
    "d": "Data", "e": "Spatial Sense", "f": "Financial Literacy",
}
# Match a math overall-expectation codename and pull grade + strand letter.
L4_RE = re.compile(r"^math___grade_(\d+)___([a-f])")

STOP_WORDS = {
    "that", "with", "this", "from", "they", "have", "been", "were", "will",
    "when", "then", "than", "their", "there", "which", "using", "each", "such",
    "both", "also", "into", "more", "most", "some", "other", "these", "those",
    "about", "able", "after", "where", "while", "make", "used", "given", "find",
    "show", "know", "understand", "apply", "including", "variety", "tools",
}


def _strip_html(s: str) -> str:
    s = re.sub(r"<object\b[^>]*>.*?</object>", "", s, flags=re.DOTALL)  # drop embeds
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def _extract_keywords(text: str) -> list[str]:
    seen: set[str] = set()
    out = []
    for w in re.findall(r"\b[a-zA-Z][a-zA-Z-]{3,}\b", text.lower()):
        if w not in STOP_WORDS and w not in seen:
            seen.add(w)
            out.append(w)
    return out[:20]


def _fetch(client: httpx.Client, params: dict) -> dict:
    r = client.get(f"{API}/items", params=params)
    r.raise_for_status()
    return r.json()


def fetch_expectations() -> list[dict]:
    """Pull all Ontario elementary-math specific expectations as dicts."""
    rows: dict[tuple[str, str], dict] = {}  # (grade, code) → row (dedups CMS copies)
    with httpx.Client(headers={"User-Agent": UA}, timeout=90) as client:
        items: list[dict] = []
        mc: dict = {}
        skip = 0
        while True:
            d = _fetch(client, {
                "system.type": "l4___overall_expectation",
                "depth": "2", "limit": "100", "skip": str(skip), "language": "en-CA",
            })
            items += d["items"]
            mc.update(d.get("modular_content", {}))
            n = len(d["items"])
            skip += n
            if n < 100:
                break

    for ov in items:
        m = L4_RE.match(ov["system"]["codename"])
        if not m:
            continue
        grade, strand = m.group(1), m.group(2)
        for sc in ov["elements"].get("specific_expectations", {}).get("value", []):
            se = mc.get(sc)
            if not se or se["system"]["type"] != "l5___specific_expectation":
                continue
            el = se["elements"]
            code = (el.get("title_index", {}).get("value") or "").strip()
            text = _strip_html(el.get("content", {}).get("value") or "")
            if not code or not text:
                continue
            rows[(grade, code)] = {
                "grade": grade, "strand": strand,
                "domain": STRAND_NAME.get(strand, strand),
                "code": code, "text": text,
            }
    return list(rows.values())


def _ingest(rows: list[dict], conn: sqlite3.Connection) -> tuple[int, int]:
    std_count = kw_count = 0
    for r in rows:
        std_id = f"CA-ON.MATH.{r['grade']}.{r['code']}"
        # Skip if this exact standard is already present (idempotent re-runs).
        if conn.execute(
            "SELECT 1 FROM standards WHERE system=? AND grade=? AND standard_text=?",
            (SYSTEM, r["grade"], r["text"]),
        ).fetchone():
            continue
        conn.execute(
            """INSERT OR REPLACE INTO standards
               (id, system, subject, grade, domain, cluster,
                standard_text, last_verified_date, source_url)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (std_id, SYSTEM, "mathematics", r["grade"], r["domain"], None,
             r["text"], VERIFIED_DATE, SOURCE_URL),
        )
        std_count += 1
        for kw in _extract_keywords(r["text"]):
            conn.execute(
                "INSERT OR IGNORE INTO keywords (standard_id, keyword) VALUES (?,?)",
                (std_id, kw),
            )
            kw_count += 1
    return std_count, kw_count


def main() -> None:
    print("Fetching Ontario elementary math (grades 1–8) from the ministry API...")
    rows = fetch_expectations()
    print(f"  → {len(rows)} specific expectations across grades "
          f"{sorted({r['grade'] for r in rows}, key=int)}")
    if not rows:
        sys.exit("ERROR: no expectations returned — API shape may have changed")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    with conn:
        s, k = _ingest(rows, conn)

    dist = conn.execute(
        "SELECT grade, COUNT(*) FROM standards WHERE system=? GROUP BY grade "
        "ORDER BY CASE grade WHEN 'K' THEN 0 WHEN 'HS' THEN 99 ELSE CAST(grade AS INT) END",
        (SYSTEM,),
    ).fetchall()
    conn.close()
    print(f"  Ingested {s} new standards, {k} keywords")
    print("  ca-on grade distribution now:")
    for grade, count in dist:
        print(f"    Grade {grade:3s}: {count}")


if __name__ == "__main__":
    main()
