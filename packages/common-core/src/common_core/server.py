"""StandardGraph MCP server — education standards across 7 subjects."""
import json
import re
import sqlite3

import numpy as np
from fastmcp import FastMCP

from common_core.config import DB_PATH, OLLAMA_BASE_URL, EMBED_MODEL

def _build_instructions() -> str:
    try:
        _c = sqlite3.connect(DB_PATH)
        _std_count = _c.execute("SELECT COUNT(*) FROM standards").fetchone()[0]
        _sys_count = _c.execute("SELECT COUNT(DISTINCT system) FROM standards").fetchone()[0]
        _c.close()
    except Exception:
        _std_count, _sys_count = 0, 0
    return f"""\
You have access to a database of {_std_count:,} education standards across {_sys_count} \
curriculum systems covering 7 subjects: Mathematics, Science, ELA, Social Studies, \
Computer Science, Arts, and World Languages.

## Subject hubs (crosswalk anchors)
- **Mathematics** → ccss (Common Core State Standards)
- **Science** → ngss (Next Generation Science Standards)
- **ELA** → ccss-ela (Common Core ELA)
- **Social Studies** → c3 (C3 Framework)
- **CS** → csta (CSTA K–12 Framework)

## Naming conventions

**Mathematics** — hub: `ccss`
  US states: two-letter code (`al ak az ar ca co ct dc de fl ga hi ia id il in ks ky
    la ma md me mi mn mo ms mt nc nd ne nh nj nm nv ny oh ok or pa ri sc sd tn tx
    ut va vt wa wi wv wy`)
  ⚠️  `de` = Delaware (US state), NOT Germany. Germany = `de-kmk`.
  Canada: `ca-ab ca-bc ca-mb ca-nb ca-on ca-qc ca-sk`
  International: `sg-moe jp-mext nz-moe au-acara au-vic hk-edb ph-deped uk-nc uk-aqa
    gb-sco ie-ncca in-ncert gh-nacca rw-reb za-caps cambridge ib-myp ib-dp de-kmk`
  AP Math: `ap-calc-ab ap-calc-bc ap-stats ap-precalc`

**Science** — hub: `ngss`
  US states: `{{state}}-sci` (e.g. `ca-sci tx-sci ny-sci`)
  AP Science: `ap-bio ap-chem ap-phys-1 ap-phys-2 ap-phys-c-mech ap-phys-c-em ap-env`

**ELA** — hub: `ccss-ela`
  US states: `{{state}}-ela` (e.g. `ca-ela tx-ela ny-ela`)
  AP English: `ap-english-lang ap-english-lit`

**Social Studies** — hub: `c3`
  US states: `{{state}}-ss` (e.g. `ca-ss tx-ss ny-ss`)
  AP Social Studies: `ap-us-history ap-world-history ap-euro-history ap-us-gov
    ap-comp-gov ap-human-geo ap-macro-econ ap-micro-econ ap-psych
    ap-african-american-stud ap-research ap-seminar`

**Computer Science** — hub: `csta`
  Select US states: `fl-cs ga-cs id-cs in-cs nc-cs ne-cs nh-cs sc-cs ut-cs wi-cs wv-cs`
  AP CS: `ap-cs-a ap-cs-principles`

**Arts:** `ap-2d-art ap-3d-art ap-drawing ap-music-theory`

**World Languages:** `ap-chinese ap-french ap-german ap-italian ap-japanese ap-latin
  ap-spanish-lang ap-spanish-lit`

## Grade codes
K, 1, 2, 3, 4, 5, 6, 7, 8, HS

## When to use each tool
- **lookup_standard**: user provides a specific standard ID
- **search_standards**: user describes a concept and wants matching standards
- **get_progression**: user asks how a topic develops across grade levels
- **map_standard**: user wants to find the equivalent standard in another system
- **list_systems**: get live counts; filter by subject or region to keep response small

## Tips
- Crosswalk mappings are NLP-generated (cosine similarity), not human-verified.
  Confidence ≥ 0.85 is a strong match; 0.70–0.80 is plausible.
  grade_delta ≠ 0 means systems introduce the concept at different grade levels.
- map_standard tries: (1) precomputed crosswalk; (2) two-hop hub bridge; (3) semantic
  embedding fallback. Below-threshold precomputed results are included with "below_threshold": true.
- search_standards falls back to keyword FTS if Ollama is unavailable — install Ollama
  for richer semantic search.
- search_standards queries one system at a time; call multiple times to compare curricula.
"""


GRADE_ORDER = ["K", "1", "2", "3", "4", "5", "6", "7", "8", "HS"]

# ── System metadata ────────────────────────────────────────────────────────────
# country_code: ISO 3166-1 alpha-2
# region: broad geographic grouping used for display and filtering
# language: primary language of instruction
# level: national | state | provincial | international | exam_board

SYSTEM_META: dict[str, dict] = {
    # ── Subject hubs ─────────────────────────────────────────────────────────
    "ccss":      {"country": "United States", "country_code": "US", "region": "North America",     "language": "English",            "level": "national"},
    "ccss-ela":  {"country": "United States", "country_code": "US", "region": "North America",     "language": "English",            "level": "national"},
    "ngss":      {"country": "United States", "country_code": "US", "region": "North America",     "language": "English",            "level": "national"},
    "c3":        {"country": "United States", "country_code": "US", "region": "North America",     "language": "English",            "level": "national"},
    "csta":      {"country": "United States", "country_code": "US", "region": "North America",     "language": "English",            "level": "national"},
    "aero":      {"country": "International", "country_code": None, "region": "International",     "language": "English",            "level": "international"},
    # ── Canada ───────────────────────────────────────────────────────────────
    "ca-ab":     {"country": "Canada",        "country_code": "CA", "region": "North America",     "language": "English",            "level": "provincial"},
    "ca-bc":     {"country": "Canada",        "country_code": "CA", "region": "North America",     "language": "English",            "level": "provincial"},
    "ca-mb":     {"country": "Canada",        "country_code": "CA", "region": "North America",     "language": "English",            "level": "provincial"},
    "ca-nb":     {"country": "Canada",        "country_code": "CA", "region": "North America",     "language": "English/French",     "level": "provincial"},
    "ca-on":     {"country": "Canada",        "country_code": "CA", "region": "North America",     "language": "English",            "level": "provincial"},
    "ca-qc":     {"country": "Canada",        "country_code": "CA", "region": "North America",     "language": "French",             "level": "provincial"},
    "ca-sk":     {"country": "Canada",        "country_code": "CA", "region": "North America",     "language": "English",            "level": "provincial"},
    # ── Asia-Pacific ─────────────────────────────────────────────────────────
    "au-acara":  {"country": "Australia",     "country_code": "AU", "region": "Asia-Pacific",      "language": "English",            "level": "national"},
    "au-vic":    {"country": "Australia",     "country_code": "AU", "region": "Asia-Pacific",      "language": "English",            "level": "state"},
    "hk-edb":   {"country": "Hong Kong",     "country_code": "HK", "region": "Asia-Pacific",      "language": "English/Chinese",    "level": "national"},
    "jp-mext":   {"country": "Japan",         "country_code": "JP", "region": "Asia-Pacific",      "language": "Japanese",           "level": "national"},
    "nz-moe":    {"country": "New Zealand",   "country_code": "NZ", "region": "Asia-Pacific",      "language": "English",            "level": "national"},
    "ph-deped":  {"country": "Philippines",   "country_code": "PH", "region": "Asia-Pacific",      "language": "English/Filipino",   "level": "national"},
    "sg-moe":    {"country": "Singapore",     "country_code": "SG", "region": "Asia-Pacific",      "language": "English",            "level": "national"},
    # ── Europe ───────────────────────────────────────────────────────────────
    "de-kmk":    {"country": "Germany",       "country_code": "DE", "region": "Europe",             "language": "German",             "level": "national"},
    "gb-sco":    {"country": "Scotland",      "country_code": "GB", "region": "Europe",             "language": "English",            "level": "national"},
    "ie-ncca":   {"country": "Ireland",       "country_code": "IE", "region": "Europe",             "language": "English/Irish",      "level": "national"},
    "uk-aqa":    {"country": "England",       "country_code": "GB", "region": "Europe",             "language": "English",            "level": "exam_board"},
    "uk-nc":     {"country": "England",       "country_code": "GB", "region": "Europe",             "language": "English",            "level": "national"},
    # ── South Asia ───────────────────────────────────────────────────────────
    "in-ncert":  {"country": "India",         "country_code": "IN", "region": "South Asia",         "language": "English",            "level": "national"},
    # ── Sub-Saharan Africa ───────────────────────────────────────────────────
    "gh-nacca":  {"country": "Ghana",         "country_code": "GH", "region": "Sub-Saharan Africa", "language": "English",            "level": "national"},
    "rw-reb":    {"country": "Rwanda",        "country_code": "RW", "region": "Sub-Saharan Africa", "language": "English/French",     "level": "national"},
    "za-caps":   {"country": "South Africa",  "country_code": "ZA", "region": "Sub-Saharan Africa", "language": "English/Afrikaans",  "level": "national"},
    # ── International ────────────────────────────────────────────────────────
    "cambridge": {"country": "International", "country_code": None, "region": "International",      "language": "English",            "level": "international"},
    "ib-dp":     {"country": "International", "country_code": None, "region": "International",      "language": "English",            "level": "international"},
    "ib-myp":    {"country": "International", "country_code": None, "region": "International",      "language": "English",            "level": "international"},
    # AP courses are handled by the ap-* prefix rule in _meta(); no entries needed here.
}

_US_STATE_CODES = {
    "ak","al","ar","az","ca","co","ct","dc","de","fl","ga","hi","ia","id","il",
    "in","ks","ky","la","ma","md","me","mi","mn","mo","ms","mt","nc","nd","ne",
    "nh","nj","nm","nv","ny","oh","ok","or","pa","ri","sc","sd","tn","tx","ut",
    "va","vt","wa","wi","wv","wy",
}

_US_STATE_META = {"country": "United States", "country_code": "US", "region": "North America", "language": "English", "level": "state"}
_AP_META       = {"country": "United States", "country_code": "US", "region": "North America", "language": "English", "level": "national"}

_US_STATE_SUFFIXES = {"-sci", "-ela", "-ss", "-cs"}


def _meta(system: str) -> dict:
    if system in SYSTEM_META:
        return SYSTEM_META[system]
    if system in _US_STATE_CODES:
        return _US_STATE_META
    for suffix in _US_STATE_SUFFIXES:
        if system.endswith(suffix) and system[: -len(suffix)] in _US_STATE_CODES:
            return _US_STATE_META
    if system.startswith("ap-"):
        return _AP_META
    return {}


mcp = FastMCP(
    "standardgraph",
    instructions=_build_instructions(),
)


# ── DB helpers ────────────────────────────────────────────────────────────────

def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _expand_id(standard_id: str, system: str = "ccss") -> str:
    """Accept shortform '6.RP.A.3' and expand to 'CCSS.MATH.6.RP.A.3'.

    Already-qualified IDs (containing '.MATH.' or starting with a
    two-letter state/system prefix like 'TX.') are returned unchanged.
    """
    sid = standard_id.strip()
    upper = sid.upper()
    if upper.startswith("CCSS."):
        return sid
    # Already a qualified non-CCSS ID (e.g. 'TX.MATH.5.3.K', 'FL.MATH.MA.5.NSO.2.5')
    if ".MATH." in upper:
        return sid
    if system == "ccss":
        return f"CCSS.MATH.{sid}"
    return sid


def _grade_key(g: str) -> int:
    try:
        return GRADE_ORDER.index(g)
    except ValueError:
        return 99


# ── Embedding ─────────────────────────────────────────────────────────────────

def _embed_query(text: str) -> np.ndarray:
    import httpx
    resp = httpx.post(
        f"{OLLAMA_BASE_URL}/api/embed",
        json={"model": EMBED_MODEL, "input": [text]},
        timeout=30,
    )
    resp.raise_for_status()
    return np.array(resp.json()["embeddings"][0], dtype=np.float32)


def _cosine_scores(query_vec: np.ndarray, conn: sqlite3.Connection) -> list[tuple[float, str]]:
    rows = conn.execute("SELECT standard_id, vector, dimensions FROM embeddings").fetchall()
    if not rows:
        return []
    dim = rows[0]["dimensions"]
    matrix = np.frombuffer(b"".join(r["vector"] for r in rows), dtype=np.float32).reshape(len(rows), dim)
    ids = [r["standard_id"] for r in rows]

    q = query_vec / (np.linalg.norm(query_vec) + 1e-9)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-9
    scores = (matrix / norms) @ q

    return sorted(zip(scores.tolist(), ids), reverse=True)


# ── FTS keyword fallback (used when Ollama is unavailable) ────────────────────

def _fts_query(text: str) -> str:
    """Return an OR expression of prefix wildcards for words of 5+ chars.

    5-char minimum excludes stop-word-like tokens ("with", "that", "from").
    Prefix wildcards bridge gerund/imperative gap: "addin*" matches "adding"
    but not "add"; "fract*" matches "fraction", "fractions", "fractional".
    """
    words = re.findall(r'[a-zA-Z]{5,}', text)
    return " OR ".join(w[:6] + "*" for w in words) if words else ""


def _ensure_fts(conn: sqlite3.Connection) -> bool:
    """Create and populate FTS5 index on standards if not present. One-time cost.

    COUNT(*) on an FTS5 content table reads from the base table, always equals
    len(standards) even when the index is empty. Use the shadow data table
    instead: it has >1 row only after a real rebuild.
    """
    try:
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS standards_fts
            USING fts5(standard_text, domain, cluster,
                       content='standards', content_rowid='rowid')
        """)
        data_rows = conn.execute("SELECT COUNT(*) FROM standards_fts_data").fetchone()[0]
        if data_rows <= 1:
            conn.execute("INSERT INTO standards_fts(standards_fts) VALUES('rebuild')")
            conn.commit()
        return True
    except Exception:
        return False


def _fts_search(
    query: str,
    conn: sqlite3.Connection,
    system: str,
    grade_filter: set[str] | None = None,
    domain_filter: str | None = None,
    limit: int = 5,
) -> list[dict]:
    """BM25-ranked FTS5 keyword search, filtered to a single curriculum system."""
    if not _ensure_fts(conn):
        return []
    fts_q = _fts_query(query)
    if not fts_q:
        return []

    # Pull top global BM25 results then filter by system in Python.
    # 1000 rows at ~6ms; catches tail-ranked systems (first CCSS result for niche
    # queries like "data analysis statistics" can appear at global rank ~238).
    try:
        ranked = conn.execute(
            "SELECT rowid FROM standards_fts WHERE standards_fts MATCH ? ORDER BY rank LIMIT 1000",
            (fts_q,),
        ).fetchall()
    except Exception:
        return []

    if not ranked:
        return []

    rowids = [r[0] for r in ranked]
    placeholders = ",".join("?" * len(rowids))
    try:
        rows_by_id = {
            r["rowid"]: r
            for r in conn.execute(
                f"SELECT rowid, id, grade, domain, standard_text"
                f" FROM standards WHERE rowid IN ({placeholders}) AND system = ?",
                rowids + [system],
            ).fetchall()
        }
    except Exception:
        return []

    results = []
    for rowid in rowids:
        if len(results) >= limit:
            break
        row = rows_by_id.get(rowid)
        if row is None:
            continue
        if grade_filter and row["grade"] not in grade_filter:
            continue
        if domain_filter and domain_filter.lower() not in (row["domain"] or "").lower():
            continue
        results.append({
            "id":            row["id"],
            "grade":         row["grade"],
            "domain":        row["domain"],
            "standard_text": row["standard_text"],
        })
    return results


# ── Tool 1: lookup_standard ───────────────────────────────────────────────────

@mcp.tool()
def lookup_standard(
    standard_id: str,
    system: str = "ccss",
    include_elaborations: bool = False,
) -> str:
    """Fetch the full text, domain, cluster, prerequisites, and successors for a single standard.

    Use this when the user provides a specific standard ID they want to read or understand.

    standard_id: full ID like 'CCSS.MATH.6.RP.A.3' or shortform '6.RP.A.3' (for CCSS).
                 For other systems use the full ID, e.g. 'TX.MATH.5.3.K' or 'CA_BC.MATH.3.a'.
    system: curriculum system code (default 'ccss'). See server instructions for all codes.

    Returns the standard text, grade, domain, cluster, sub-standards (if any),
    prerequisite standard IDs from the prior grade, and successor IDs for the next grade.
    """
    sid = _expand_id(standard_id, system)
    conn = _db()

    row = conn.execute("SELECT * FROM standards WHERE id = ?", (sid,)).fetchone()
    if not row:
        # Suggest nearby IDs
        suggestions = [
            r[0] for r in conn.execute(
                "SELECT id FROM standards WHERE system=? AND grade=? LIMIT 5",
                (system, sid.split(".")[2] if "." in sid else ""),
            ).fetchall()
        ]
        conn.close()
        return json.dumps({"error": "standard_not_found", "queried_id": sid, "suggestions": suggestions})

    std = dict(row)

    sub_stds = conn.execute(
        "SELECT id, text FROM sub_standards WHERE parent_id=? ORDER BY position",
        (sid,),
    ).fetchall()

    prerequisites = [
        r[0] for r in conn.execute(
            "SELECT target_id FROM standard_relationships WHERE source_id=? AND relationship='prerequisite'",
            (sid,),
        ).fetchall()
    ]
    successors = [
        r[0] for r in conn.execute(
            "SELECT target_id FROM standard_relationships WHERE source_id=? AND relationship='successor'",
            (sid,),
        ).fetchall()
    ]
    conn.close()

    return json.dumps({
        "id":           std["id"],
        "system":       std["system"],
        "grade":        std["grade"],
        "domain":       std["domain"],
        "cluster":      std["cluster"],
        "standard_text": std["standard_text"],
        "sub_standards": [f"{r['id']} — {r['text']}" for r in sub_stds],
        "prerequisites": prerequisites,
        "successors":    successors,
        "source_url":   std["source_url"],
        "elaborations":  None,
    }, indent=2)


# ── Tool 2: search_standards ──────────────────────────────────────────────────

@mcp.tool()
def search_standards(
    query: str,
    system: str = "ccss",
    grade: str | None = None,
    domain: str | None = None,
    limit: int = 5,
) -> str:
    """Find standards that match a natural language description of a concept or skill.

    Use this when the user describes what they're looking for rather than citing a standard ID.
    Works across all subjects: mathematics, science, ELA, social studies, CS, arts, world-languages.
    Examples: "adding fractions with unlike denominators", "photosynthesis", "argumentative writing grade 8".

    query: plain English description of the concept or skill.
    system: which curriculum to search (default 'ccss'). Call multiple times to compare systems.
    grade: optional filter — single grade '5', range '6-8', or 'HS'. Grade codes: K 1 2 3 4 5 6 7 8 HS.
    domain: optional keyword to restrict by domain name (e.g. 'geometry', 'algebra').
    limit: number of results (default 5, max sensible ~10).

    Uses semantic similarity (requires Ollama) with automatic keyword FTS fallback when Ollama is unavailable.
    Returns standards ranked by relevance with scores (0–1).
    """
    try:
        query_vec = _embed_query(query)
    except Exception:
        conn = _db()
        results = _fts_search(
            query, conn, system,
            grade_filter=_parse_grade_filter(grade) if grade else None,
            domain_filter=domain,
            limit=limit,
        )
        conn.close()
        return json.dumps({
            "search_method": "keyword_fts_fallback",
            "note": "Ollama is unavailable — results are keyword-based, not semantic. Install Ollama for richer search.",
            "results": results,
        }, indent=2)
    conn = _db()
    scored = _cosine_scores(query_vec, conn)

    results = []
    for score, sid in scored:
        if len(results) >= limit:
            break
        row = conn.execute(
            "SELECT * FROM standards WHERE id=? AND system=?", (sid, system)
        ).fetchone()
        if not row:
            continue
        std = dict(row)

        if grade is not None:
            # Accept "6", "6-8", or ["5","6","7"]
            grades_wanted = _parse_grade_filter(grade)
            if std["grade"] not in grades_wanted:
                continue

        if domain is not None and domain.lower() not in std["domain"].lower():
            continue

        results.append({
            "id":            std["id"],
            "grade":         std["grade"],
            "domain":        std["domain"],
            "standard_text": std["standard_text"],
            "relevance_score": round(score, 4),
        })

    conn.close()
    return json.dumps(results, indent=2)


def _parse_grade_filter(grade: str | list) -> set[str]:
    if isinstance(grade, list):
        return set(grade)
    if "-" in grade and not grade.startswith("K"):
        # range like "6-8"
        parts = grade.split("-")
        try:
            lo, hi = int(parts[0]), int(parts[1])
            return {str(g) for g in range(lo, hi + 1)}
        except ValueError:
            pass
    return {grade}


# ── Tool 3: get_progression ───────────────────────────────────────────────────

@mcp.tool()
def get_progression(
    concept: str,
    system: str = "ccss",
    grade_start: int | None = None,
    grade_end: int | None = None,
) -> str:
    """Show how a math concept is introduced and built upon across grade levels.

    Use this when the user asks questions like "how does fractions develop from grade 3 to 6?"
    or "what's the full progression for proportional reasoning?" or "when is X introduced?"

    concept: plain English name of the math concept (e.g. 'fractions', 'linear equations',
             'place value', 'geometric transformations').
    system: curriculum to trace (default 'ccss'). Try 'cambridge' or 'ib-myp' for comparison.
    grade_start / grade_end: optional integer bounds to narrow the range (e.g. 3 and 8).

    Returns the top matching standards per grade, ordered K through HS, showing how the
    concept deepens over time.
    """
    try:
        query_vec = _embed_query(concept)
    except Exception:
        conn = _db()
        raw = _fts_search(concept, conn, system, limit=60)
        conn.close()

        by_grade: dict[str, list[dict]] = {}
        for r in raw:
            g = r["grade"]
            if grade_start is not None and _grade_key(g) < _grade_key(str(grade_start)):
                continue
            if grade_end is not None and _grade_key(g) > _grade_key(str(grade_end)):
                continue
            by_grade.setdefault(g, []).append({"id": r["id"], "text": r["standard_text"]})

        gr_start = str(grade_start) if grade_start is not None else "K"
        gr_end   = str(grade_end)   if grade_end   is not None else "HS"

        return json.dumps({
            "concept":       concept,
            "system":        system,
            "grade_range":   f"{gr_start}–{gr_end}",
            "search_method": "keyword_fts_fallback",
            "note": "Ollama is unavailable — results are keyword-based, not semantic. Install Ollama for richer search.",
            "stages": [
                {"grade": g, "standards": by_grade[g][:3]}
                for g in sorted(by_grade.keys(), key=_grade_key)
            ],
        }, indent=2)
    conn = _db()
    scored = _cosine_scores(query_vec, conn)

    # Collect top standards per grade, filtered by grade range
    by_grade: dict[str, list[dict]] = {}
    for score, sid in scored:
        if score < 0.5:
            break
        row = conn.execute(
            "SELECT * FROM standards WHERE id=? AND system=?", (sid, system)
        ).fetchone()
        if not row:
            continue
        std = dict(row)
        g = std["grade"]

        if grade_start is not None and _grade_key(g) < _grade_key(str(grade_start)):
            continue
        if grade_end is not None and _grade_key(g) > _grade_key(str(grade_end)):
            continue

        by_grade.setdefault(g, []).append({
            "id":   std["id"],
            "text": std["standard_text"],
            "score": round(score, 4),
        })

    conn.close()

    gr_start = str(grade_start) if grade_start is not None else "K"
    gr_end   = str(grade_end)   if grade_end   is not None else "HS"

    stages = []
    for g in sorted(by_grade.keys(), key=_grade_key):
        stds = sorted(by_grade[g], key=lambda x: -x["score"])[:3]
        stages.append({
            "grade":     g,
            "standards": [{"id": s["id"], "text": s["text"]} for s in stds],
        })

    return json.dumps({
        "concept":     concept,
        "system":      system,
        "grade_range": f"{gr_start}–{gr_end}",
        "stages":      stages,
    }, indent=2)


# ── Tool 4: map_standard ──────────────────────────────────────────────────────

@mcp.tool()
def map_standard(
    standard_id: str,
    from_system: str,
    to_system: str,
    confidence_threshold: float = 0.7,
) -> str:
    """Find the closest equivalent to a standard in a different curriculum system.

    Use this when the user wants to compare curricula — e.g. "what is the CCSS equivalent
    of this Texas standard?", "how does Singapore cover this?", or
    "I'm moving from Ontario to the UK — what's the equivalent?"

    Three strategies are tried in order:
      1. Precomputed NLP crosswalk (direct or reverse through CCSS hub).
      2. Two-hop CCSS bridge: source→CCSS→target (enables any-to-any comparison).
      3. Semantic embedding fallback: embed source text, find nearest in target system.
    Below-threshold precomputed results are always returned, flagged with below_threshold.

    standard_id: the source standard ID (full form, e.g. 'TX.MATH.5.3.K').
    from_system: system code of the source standard (e.g. 'tx', 'ca-on', 'sg-moe').
    to_system: target system code (any indexed system).
    confidence_threshold: minimum cosine similarity for primary results (default 0.7).

    Returns matched standards with confidence score, grade alignment, and mapping method.
    """
    sid = _expand_id(standard_id, from_system)
    conn = _db()

    src = conn.execute("SELECT * FROM standards WHERE id=?", (sid,)).fetchone()
    if not src:
        conn.close()
        return json.dumps({"error": "standard_not_found", "queried_id": sid})

    src_dict = dict(src)

    # ── 1. Precomputed crosswalk above threshold ───────────────────────────────
    mappings = conn.execute(
        """SELECT cm.*, s.standard_text AS target_text, s.grade AS target_grade,
                  s.domain AS target_domain
           FROM crosswalk_mappings cm
           JOIN standards s ON s.id = cm.target_id
           WHERE cm.source_id = ?
             AND cm.target_system = ?
             AND cm.confidence_score >= ?
           ORDER BY cm.confidence_score DESC""",
        (sid, to_system, confidence_threshold),
    ).fetchall()

    if mappings:
        conn.close()
        return json.dumps({
            "source_id":         src_dict["id"],
            "target_curriculum": to_system,
            "mapping_method":    "precomputed_crosswalk",
            "mappings": [
                {
                    "target_id":            m["target_id"],
                    "target_standard_text": m["target_text"],
                    "relationship":         m["relationship"],
                    "confidence":           m["confidence_score"],
                    "grade_delta":          m["grade_delta"],
                    "grade_alignment":      "exact" if m["grade_delta"] == 0 else (
                        f"{abs(m['grade_delta'])} year{'s' if abs(m['grade_delta']) > 1 else ''} "
                        f"{'later' if m['grade_delta'] > 0 else 'earlier'} in target"
                    ),
                    "verified_by_human":    bool(m["verified_by_human"]),
                    "notes":                m["notes"],
                }
                for m in mappings
            ],
        }, indent=2)

    # ── 2. Best precomputed result below threshold ─────────────────────────────
    best_below = conn.execute(
        """SELECT cm.*, s.standard_text AS target_text, s.grade AS target_grade,
                  s.domain AS target_domain
           FROM crosswalk_mappings cm
           JOIN standards s ON s.id = cm.target_id
           WHERE cm.source_id = ?
             AND cm.target_system = ?
           ORDER BY cm.confidence_score DESC
           LIMIT 1""",
        (sid, to_system),
    ).fetchone()

    # ── 3. Two-hop: source → CCSS → target (or reverse for CCSS sources) ──────
    two_hop: list[dict] = []
    if from_system == "ccss":
        # Source IS the CCSS hub — find target-system standards pointing to it
        rows = conn.execute(
            """SELECT cm.source_id, cm.confidence_score,
                      s.standard_text, s.grade, s.domain
               FROM crosswalk_mappings cm
               JOIN standards s ON s.id = cm.source_id
               WHERE cm.target_id = ?
                 AND s.system = ?
               ORDER BY cm.confidence_score DESC
               LIMIT 5""",
            (sid, to_system),
        ).fetchall()
        for r in rows:
            two_hop.append({
                "target_id":            r["source_id"],
                "target_standard_text": r["standard_text"],
                "via_ccss":             sid,
                "hop1_confidence":      1.0,
                "hop2_confidence":      round(r["confidence_score"], 4),
                "combined_confidence":  round(r["confidence_score"], 4),
                "grade":                r["grade"],
            })
    elif to_system != "ccss":
        # Forward two-hop: source → CCSS intermediary → target
        ccss_rows = conn.execute(
            """SELECT target_id, confidence_score
               FROM crosswalk_mappings
               WHERE source_id = ? AND target_system = 'ccss'
               ORDER BY confidence_score DESC
               LIMIT 3""",
            (sid,),
        ).fetchall()
        raw: list[dict] = []
        for cr in ccss_rows:
            ccss_id, ccss_conf = cr["target_id"], cr["confidence_score"]
            target_rows = conn.execute(
                """SELECT cm.source_id, cm.confidence_score,
                          s.standard_text, s.grade, s.domain
                   FROM crosswalk_mappings cm
                   JOIN standards s ON s.id = cm.source_id
                   WHERE cm.target_id = ?
                     AND s.system = ?
                   ORDER BY cm.confidence_score DESC
                   LIMIT 3""",
                (ccss_id, to_system),
            ).fetchall()
            for tr in target_rows:
                raw.append({
                    "target_id":            tr["source_id"],
                    "target_standard_text": tr["standard_text"],
                    "via_ccss":             ccss_id,
                    "hop1_confidence":      round(ccss_conf, 4),
                    "hop2_confidence":      round(tr["confidence_score"], 4),
                    "combined_confidence":  round(ccss_conf * tr["confidence_score"], 4),
                    "grade":                tr["grade"],
                })
        seen: set[str] = set()
        for r in sorted(raw, key=lambda x: -x["combined_confidence"]):
            if r["target_id"] not in seen:
                seen.add(r["target_id"])
                two_hop.append(r)
                if len(two_hop) >= 5:
                    break

    # ── 4. Semantic embedding fallback ────────────────────────────────────────
    nearest_by_concept: list[dict] = []
    embedding_error: str | None = None
    try:
        qvec = _embed_query(src_dict["standard_text"])
        scored = _cosine_scores(qvec, conn)
        for score, candidate_id in scored:
            if len(nearest_by_concept) >= 3:
                break
            if score < 0.35:
                break
            row = conn.execute(
                "SELECT * FROM standards WHERE id=? AND system=?", (candidate_id, to_system)
            ).fetchone()
            if row:
                nearest_by_concept.append({
                    "target_id":            row["id"],
                    "target_standard_text": row["standard_text"],
                    "grade":                row["grade"],
                    "semantic_similarity":  round(score, 4),
                })
    except Exception as exc:
        embedding_error = str(exc)

    conn.close()

    # ── Build no-match response ────────────────────────────────────────────────
    response: dict = {
        "source_id":         src_dict["id"],
        "source_text":       src_dict["standard_text"],
        "target_curriculum": to_system,
        "result":            "no_precomputed_mapping_above_threshold",
    }

    if best_below:
        response["best_precomputed_below_threshold"] = {
            "target_id":            best_below["target_id"],
            "target_standard_text": best_below["target_text"],
            "confidence":           round(best_below["confidence_score"], 4),
            "below_threshold":      True,
            "threshold_used":       confidence_threshold,
        }

    if two_hop:
        response["two_hop_via_ccss"] = two_hop

    if nearest_by_concept:
        response["nearest_by_concept"] = nearest_by_concept

    if embedding_error:
        response["embedding_fallback_error"] = embedding_error
        response["embedding_hint"] = (
            f"Start Ollama with `ollama serve` and pull the model with `ollama pull {EMBED_MODEL}`. "
            "Retry once it is running to get a semantic-similarity result."
        )

    if not best_below and not two_hop and not nearest_by_concept:
        response["result"] = "no_precomputed_or_bridge_mapping_found" if embedding_error else "no_mapping_found"
        try:
            _c = sqlite3.connect(DB_PATH)
            response["available_systems"] = [
                r[0] for r in _c.execute(
                    "SELECT DISTINCT system FROM standards ORDER BY system"
                ).fetchall()
            ]
            _c.close()
        except Exception:
            pass

    return json.dumps(response, indent=2)


# ── Tool 5: list_systems ──────────────────────────────────────────────────────

@mcp.tool()
def list_systems(
    subject: str | None = None,
    region: str | None = None,
) -> str:
    """Return curriculum systems in the database with standard counts and crosswalk coverage.

    Without filters returns all systems (~300 rows — large). Use filters to narrow results.

    subject: restrict to one subject — 'mathematics', 'science', 'ela', 'social-studies',
             'cs', 'arts', 'world-languages'
    region: restrict to one region — 'North America', 'Europe', 'Asia-Pacific',
            'South Asia', 'Sub-Saharan Africa', 'International'

    Returns: system code, subjects covered, standard count, crosswalk coverage, country, region.
    """
    conn = _db()

    # Build subject-filtered system list from the standards table
    if subject:
        subject_systems = {
            r[0] for r in conn.execute(
                "SELECT DISTINCT system FROM standards WHERE subject = ?", (subject,)
            ).fetchall()
        }
    else:
        subject_systems = None

    systems = conn.execute(
        """SELECT s.system,
                  GROUP_CONCAT(DISTINCT s.subject) AS subjects,
                  COUNT(s.id) AS standards,
                  COUNT(e.standard_id) AS embedded,
                  COUNT(cm.source_id) AS crosswalked
           FROM standards s
           LEFT JOIN embeddings e ON e.standard_id = s.id
           LEFT JOIN crosswalk_mappings cm ON cm.source_id = s.id
           GROUP BY s.system
           ORDER BY s.system"""
    ).fetchall()

    total_std = conn.execute("SELECT COUNT(*) FROM standards").fetchone()[0]
    total_emb = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
    total_xwalk = conn.execute("SELECT COUNT(*) FROM crosswalk_mappings").fetchone()[0]
    total_rel = conn.execute("SELECT COUNT(*) FROM standard_relationships").fetchone()[0]
    conn.close()

    system_rows = []
    for r in systems:
        if subject_systems is not None and r["system"] not in subject_systems:
            continue
        m = _meta(r["system"])
        sys_region = m.get("region", "")
        if region and region.lower() not in sys_region.lower():
            continue
        system_rows.append({
            "system":      r["system"],
            "subjects":    r["subjects"],
            "standards":   r["standards"],
            "crosswalked": r["crosswalked"],
            "country":     m.get("country"),
            "region":      sys_region or None,
        })

    return json.dumps({
        "totals": {
            "systems":            len(systems),
            "standards":          total_std,
            "embeddings":         total_emb,
            "crosswalk_mappings": total_xwalk,
            "relationships":      total_rel,
        },
        "filters_applied": {k: v for k, v in {"subject": subject, "region": region}.items() if v},
        "matched_systems":  len(system_rows),
        "systems": system_rows,
    }, indent=2)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
