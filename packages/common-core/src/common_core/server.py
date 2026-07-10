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


# Quality scores come from two sources: LLM rubric scoring ("[LLM score N/5]") and
# deterministic exact-match scoring ("[exact-match N/5]", assigned when source and
# target standard text are byte-identical). Both are surfaced as quality_score.
_SCORE_RE = re.compile(r"\[(?:LLM score|exact-match) (\d)/5\]")


def _parse_quality(notes: str | None) -> int | None:
    if not notes:
        return None
    m = _SCORE_RE.search(notes)
    return int(m.group(1)) if m else None


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


# Separator between the two ends of a grade range ('3-6', '3–6', '6 to 8').
_RANGE_SEP = re.compile(r"\s*(?:-|–|—|\.\.|to|through)\s*", re.I)


def _coerce_grade(v) -> str | None:
    """Map an int/str grade to a canonical GRADE_ORDER code, else None.

    Accepts ints, numeric strings ('5', '5.0'), grade codes ('K', 'HS',
    case-insensitive) and high-school year numbers (9–12 → 'HS').
    """
    if v is None:
        return None
    s = str(v).strip().upper()
    s = re.sub(r"^(?:GRADES?|GR)\.?\s*", "", s)  # 'Grade 3' / 'Gr. 3' → '3'
    if s in GRADE_ORDER:
        return s
    if s in ("K", "KG", "KINDERGARTEN"):
        return "K"
    if s in ("HS", "HIGH SCHOOL"):
        return "HS"
    try:
        n = int(float(s))
    except (ValueError, TypeError):
        return None
    if str(n) in GRADE_ORDER:
        return str(n)
    return "HS" if n >= 9 else "K" if n < 0 else None


def _norm_grade_bounds(grade_start, grade_end) -> tuple[str | None, str | None]:
    """Coerce loose grade_start/grade_end args into canonical grade-code bounds.

    Tolerates a range string passed in either slot — LLM callers frequently send
    grade_start='3-6' despite the integer signature, which previously slipped past
    _grade_key as 99 and silently filtered out every grade. Split it into two ends.
    """
    for val in (grade_start, grade_end):
        if isinstance(val, str) and _RANGE_SEP.search(val.strip()):
            parts = _RANGE_SEP.split(val.strip(), maxsplit=1)
            if len(parts) == 2 and parts[0] and parts[1]:
                return _coerce_grade(parts[0]), _coerce_grade(parts[1])
    return _coerce_grade(grade_start), _coerce_grade(grade_end)


# A single-letter CCSS cluster segment sitting directly before the final numeric
# ordinal (e.g. the 'A' in '6.RP.A.3'). The DB is inconsistent about retaining it
# — most IDs keep it ('5.NF.A.2') but some dropped it on ingest ('6.RP.3') — so
# lookups normalise it away to match either form.
_CLUSTER_LETTER = re.compile(r"\.[A-Z](?=\.\d)")


def _loose_id(sid: str) -> str:
    # Upper-case so the compare is case-insensitive and lowercase cluster
    # letters ('6.rp.a.3') still match the [A-Z] cluster pattern.
    return _CLUSTER_LETTER.sub("", sid.upper())


def _resolve_id(conn: sqlite3.Connection, sid: str, system: str) -> str | None:
    """Return the canonical stored ID matching sid, or None.

    Tries, in order: exact match, case-insensitive exact match, then a
    cluster-letter-tolerant loose match (so '6.RP.A.3' finds a stored
    '6.RP.3' and vice versa, regardless of case). Each tier is retried with
    trailing punctuation stripped ('6.RP.A.3.' pasted from prose) — but the
    raw ID is always tried first, so IDs that legitimately end in punctuation
    (e.g. Alberta 'CA-AB.MATH.K.MAT.5.1.3.a.') still match exactly. Shared by
    lookup_standard and map_standard so both tolerate the same ID drift.
    """
    candidates = [sid]
    stripped = sid.rstrip(" .,;:")
    if stripped and stripped != sid:
        candidates.append(stripped)

    for cand in candidates:
        row = conn.execute("SELECT id FROM standards WHERE id = ?", (cand,)).fetchone()
        if row:
            return row[0]
        row = conn.execute(
            "SELECT id FROM standards WHERE id = ? COLLATE NOCASE", (cand,)
        ).fetchone()
        if row:
            return row[0]

    for cand in candidates:
        target = _loose_id(cand)
        match = next(
            (cid for (cid,) in conn.execute(
                "SELECT id FROM standards WHERE system = ?", (system,))
             if _loose_id(cid) == target),
            None,
        )
        if match:
            return match
    return None


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


def _cosine_scores(
    query_vec: np.ndarray,
    conn: sqlite3.Connection,
    system: str | None = None,
) -> list[tuple[float, str]]:
    if system:
        rows = conn.execute(
            "SELECT e.standard_id, e.vector, e.dimensions FROM embeddings e "
            "JOIN standards s ON s.id = e.standard_id WHERE s.system = ?",
            (system,),
        ).fetchall()
    else:
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


# ── Relationship helpers (shared by lookup_standard + get_learning_path) ──────

# Minimum confidence_score for an LLM-validated edge to count as a HARD (default)
# prerequisite. SOFT edges are stored at 0.5 and only surfaced with include_soft.
_HARD_CONF = 0.9
_SOFT_CONF = 0.5


def _related(conn, sid: str, relationship: str, prefer_validated: bool):
    """Return (ids, source) for a standard's prerequisite/successor edges.

    When prefer_validated is True and any method='llm_validated' edges exist for
    this standard, return those (source='llm_validated'); otherwise fall back to
    the grade-heuristic edges (source='grade_heuristic'). Falling back preserves
    non-empty prerequisite lists for standards the pilot never re-validated.
    """
    if prefer_validated:
        val = [r[0] for r in conn.execute(
            "SELECT target_id FROM standard_relationships "
            "WHERE source_id=? AND relationship=? AND method='llm_validated' "
            "ORDER BY confidence_score DESC, target_id",
            (sid, relationship)).fetchall()]
        if val:
            return val, "llm_validated"
    allrows = [r[0] for r in conn.execute(
        "SELECT target_id FROM standard_relationships "
        "WHERE source_id=? AND relationship=? ORDER BY target_id",
        (sid, relationship)).fetchall()]
    return allrows, "grade_heuristic"


def _parse_prereq_note(notes: str | None) -> tuple[str | None, str | None]:
    """Split a validated-edge note into (strength, rationale).

    Stored form: 'llm_prereq cosine=0.83 hard: <why>' — surfaced so callers can
    show *why* a prerequisite was included (the provenance/trust story).
    """
    if not notes:
        return None, None
    m = re.search(r"\b(hard|soft):\s*(.*)$", notes, re.S)
    if m:
        return m.group(1), m.group(2).strip() or None
    return None, notes.strip() or None


# ── Tool 1: lookup_standard ───────────────────────────────────────────────────

@mcp.tool()
def lookup_standard(
    standard_id: str,
    system: str = "ccss",
    include_elaborations: bool = False,
    prefer_validated: bool = True,
) -> str:
    """Fetch the full text, domain, cluster, prerequisites, and successors for a single standard.

    Use this when the user provides a specific standard ID they want to read or understand.

    standard_id: full ID like 'CCSS.MATH.6.RP.A.3' or shortform '6.RP.A.3' (for CCSS).
                 For other systems use the full ID, e.g. 'TX.MATH.5.3.K' or 'CA_BC.MATH.3.a'.
    system: curriculum system code (default 'ccss'). See server instructions for all codes.
    prefer_validated: when True (default), return the LLM-validated prerequisite/successor
                 edges if any exist for this standard (higher precision, may be cross-domain);
                 otherwise fall back to the grade-heuristic edges. The response reports which
                 source was used via `prerequisites_method`.

    Returns the standard text, grade, domain, cluster, sub-standards (if any),
    prerequisite standard IDs from the prior grade, and successor IDs for the next grade.
    """
    sid = _expand_id(standard_id, system)
    conn = _db()

    # Resolve to the canonical stored ID (tolerating cluster-letter/case drift),
    # then use it for every downstream lookup so sub-standards, prerequisites and
    # successors are keyed off the real ID rather than the drifted input.
    canonical = _resolve_id(conn, sid, system)
    row = (
        conn.execute("SELECT * FROM standards WHERE id = ?", (canonical,)).fetchone()
        if canonical
        else None
    )
    if row:
        sid = canonical
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

    prerequisites, prereq_method = _related(conn, sid, "prerequisite", prefer_validated)
    successors, _ = _related(conn, sid, "successor", prefer_validated)

    # Provenance: when the prerequisites are LLM-validated, surface *why* each was
    # included (rationale + hard/soft strength) so callers can show/trust the edge.
    prereq_rationales = None
    if prereq_method == "llm_validated":
        prereq_rationales = {}
        for r in conn.execute(
            "SELECT target_id, confidence_score, notes FROM standard_relationships "
            "WHERE source_id=? AND relationship='prerequisite' AND method='llm_validated'",
            (sid,)).fetchall():
            strength, why = _parse_prereq_note(r[2])
            prereq_rationales[r[0]] = {
                "strength": strength or ("hard" if (r[1] or 0) >= _HARD_CONF else "soft"),
                "why": why,
            }
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
        "prerequisites_method": prereq_method,
        "prerequisite_rationales": prereq_rationales,
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
    scored = _cosine_scores(query_vec, conn, system=system)

    results = []
    for score, sid in scored:
        if len(results) >= limit:
            break
        row = conn.execute(
            "SELECT * FROM standards WHERE id=?", (sid,)
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
    grade_start: int | str | None = None,
    grade_end: int | str | None = None,
) -> str:
    """Show how a math concept is introduced and built upon across grade levels.

    Use this when the user asks questions like "how does fractions develop from grade 3 to 6?"
    or "what's the full progression for proportional reasoning?" or "when is X introduced?"

    concept: plain English name of the math concept (e.g. 'fractions', 'linear equations',
             'place value', 'geometric transformations').
    system: curriculum to trace (default 'ccss'). Try 'cambridge' or 'ib-myp' for comparison.
    grade_start / grade_end: optional bounds to narrow the range (e.g. 3 and 8). Accepts
             ints, grade codes ('K', 'HS'), or a single range string like '3-6' / '6 to 8'.

    Returns the top matching standards per grade, ordered K through HS, showing how the
    concept deepens over time.
    """
    g_start, g_end = _norm_grade_bounds(grade_start, grade_end)
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

        gr_start = g_start or "K"
        gr_end   = g_end   or "HS"

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
    scored = _cosine_scores(query_vec, conn, system=system)

    # Collect top standards per grade, filtered by grade range
    by_grade: dict[str, list[dict]] = {}
    for score, sid in scored:
        if score < 0.5:
            break
        row = conn.execute(
            "SELECT * FROM standards WHERE id=?", (sid,)
        ).fetchone()
        if not row:
            continue
        std = dict(row)
        g = std["grade"]

        if g_start is not None and _grade_key(g) < _grade_key(g_start):
            continue
        if g_end is not None and _grade_key(g) > _grade_key(g_end):
            continue

        by_grade.setdefault(g, []).append({
            "id":   std["id"],
            "text": std["standard_text"],
            "score": round(score, 4),
        })

    conn.close()

    gr_start = g_start or "K"
    gr_end   = g_end   or "HS"

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


# ── Tool 4: get_learning_path ─────────────────────────────────────────────────

@mcp.tool()
def get_learning_path(
    target: str,
    system: str = "ccss",
    from_standard: str | None = None,
    max_depth: int = 20,
    include_soft: bool = False,
) -> str:
    """Build an ordered, grade-increasing sequence of standards to learn to reach a target.

    Walks the LLM-validated prerequisite graph backward from the target standard and
    returns every prerequisite (transitively) as a topologically ordered study plan —
    the substrate for self-paced acceleration ("what do I need before calculus?").
    Only method='llm_validated' edges are traversed, so the path is far cleaner than the
    raw grade-adjacency graph and includes genuine cross-domain dependencies.

    target: the standard to work toward — full ID 'CCSS.MATH.HSF.LE.A.1.b' or shortform.
    system: curriculum system code (default 'ccss'; validated edges currently exist for CCSS math).
    from_standard: optional — the standard the learner has already mastered. When given, the
                   path is pruned to the sub-sequence between that standard and the target.
    max_depth: max prerequisite levels to walk back (default 20; guards pathological depth).
    include_soft: when False (default) only HARD prerequisites (direct building blocks) are
                  followed; when True, SOFT (helpful-background) edges are included too.

    Returns the resolved target, an ordered `path` (each node with id/grade/domain/text and its
    immediate in-path prerequisites), plus counts. If the target has no validated prerequisites
    the path is just the target with an explanatory note.
    """
    conn = _db()
    tgt = _resolve_id(conn, _expand_id(target, system), system)
    if not tgt:
        conn.close()
        return json.dumps({"error": "standard_not_found", "queried_id": _expand_id(target, system)})

    min_conf = _SOFT_CONF if include_soft else _HARD_CONF
    # (learner, prereq) -> {strength, why, confidence} for provenance in the output.
    edge_meta: dict[tuple[str, str], dict] = {}

    def prereqs_of(node: str) -> list[str]:
        rows = conn.execute(
            "SELECT target_id, confidence_score, notes FROM standard_relationships "
            "WHERE source_id=? AND relationship='prerequisite' "
            "AND method='llm_validated' AND confidence_score >= ?",
            (node, min_conf)).fetchall()
        out = []
        for p, conf, notes in rows:
            strength, why = _parse_prereq_note(notes)
            edge_meta[(node, p)] = {
                "strength": strength or ("hard" if (conf or 0) >= _HARD_CONF else "soft"),
                "why": why,
                "confidence": conf,
            }
            out.append(p)
        return out

    # Reverse-BFS the prerequisite closure of the target, bounded by max_depth.
    seen = {tgt}
    edges: dict[str, list[str]] = {}
    frontier = [tgt]
    depth = 0
    while frontier and depth < max_depth:
        nxt: list[str] = []
        for n in frontier:
            ps = prereqs_of(n)
            edges[n] = ps
            for p in ps:
                if p not in seen:
                    seen.add(p)
                    nxt.append(p)
        frontier = nxt
        depth += 1

    # Optional from_standard pruning: keep only nodes on a chain from_standard → target.
    from_resolved = None
    from_reachable = None
    if from_standard:
        src = _resolve_id(conn, _expand_id(from_standard, system), system)
        from_resolved = src
        from_reachable = bool(src and src in seen)
        if from_reachable:
            # Forward reachability from src via validated successor edges, within the closure.
            fwd = {src}
            fr = [src]
            while fr:
                nx: list[str] = []
                for n in fr:
                    for r in conn.execute(
                        "SELECT target_id FROM standard_relationships "
                        "WHERE source_id=? AND relationship='successor' "
                        "AND method='llm_validated' AND confidence_score >= ?",
                        (n, min_conf)).fetchall():
                        s = r[0]
                        if s in seen and s not in fwd:
                            fwd.add(s)
                            nx.append(s)
                fr = nx
            keep = (fwd & seen) | {tgt}
            seen = {n for n in seen if n in keep}

    # Materialise node rows and order by grade (every validated edge increases grade,
    # so grade order is a valid topological order; ties broken by id for determinism).
    nodes = []
    for n in seen:
        row = conn.execute(
            "SELECT id, grade, domain, standard_text FROM standards WHERE id=?", (n,)
        ).fetchone()
        if row:
            nodes.append(dict(row))
    conn.close()
    nodes.sort(key=lambda d: (_grade_key(d["grade"]), d["id"]))

    setids = {d["id"] for d in nodes}

    def _prereq_entries(learner: str):
        entries = []
        for p in edges.get(learner, []):
            if p not in setids:
                continue
            meta = edge_meta.get((learner, p), {})
            entries.append({
                "id":       p,
                "strength": meta.get("strength"),
                "why":      meta.get("why"),
            })
        return entries

    path = [{
        "id":            d["id"],
        "grade":         d["grade"],
        "domain":        d["domain"],
        "standard_text": d["standard_text"],
        "prerequisites_in_path": _prereq_entries(d["id"]),
    } for d in nodes]

    result = {
        "target":       tgt,
        "system":       system,
        "edge_strength": "hard+soft" if include_soft else "hard_only",
        "path_length":  len(path),
        "path":         path,
    }
    if from_standard:
        result["from_standard"] = from_resolved or _expand_id(from_standard, system)
        result["from_standard_reachable"] = from_reachable
    # Notes, most-specific first.
    if from_standard and from_reachable and len(path) == 1:
        # from_standard prunes everything else away → learner is already at/past the target.
        result["note"] = "from_standard already reaches the target — no intermediate steps needed"
    elif len(path) == 1 and path[0]["id"] == tgt:
        result["note"] = ("no validated prerequisites found for this target"
                          + (" at hard strength — retry with include_soft=True" if not include_soft else ""))
    elif from_standard and from_resolved and not from_reachable:
        result["note"] = "from_standard is not a validated prerequisite of the target; returning the full prerequisite path"
    return json.dumps(result, indent=2)


# ── Tool 5: map_standard ──────────────────────────────────────────────────────

@mcp.tool()
def map_standard(
    standard_id: str,
    from_system: str,
    to_system: str,
    confidence_threshold: float = 0.7,
    include_flagged: bool = False,
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
    include_flagged: if True, include mappings flagged for review (LLM quality score 1-2).
      Default False returns only verified-quality mappings.

    Returns matched standards with confidence score, grade alignment, quality_score (1-5),
    flagged status, and mapping method.
    """
    sid = _expand_id(standard_id, from_system)
    conn = _db()

    # Same cluster-letter/case tolerance as lookup_standard, then pin sid to the
    # canonical ID so the crosswalk/embedding queries below hit the stored rows.
    canonical = _resolve_id(conn, sid, from_system)
    src = (
        conn.execute("SELECT * FROM standards WHERE id=?", (canonical,)).fetchone()
        if canonical
        else None
    )
    if not src:
        conn.close()
        return json.dumps({"error": "standard_not_found", "queried_id": sid})

    sid = canonical
    src_dict = dict(src)

    # ── 1. Precomputed crosswalk above threshold ───────────────────────────────
    flagged_clause = "" if include_flagged else "AND cm.flagged_for_review = 0"
    mappings = conn.execute(
        f"""SELECT cm.*, s.standard_text AS target_text, s.grade AS target_grade,
                  s.domain AS target_domain
           FROM crosswalk_mappings cm
           JOIN standards s ON s.id = cm.target_id
           WHERE cm.source_id = ?
             AND cm.target_system = ?
             AND cm.confidence_score >= ?
             {flagged_clause}
           ORDER BY cm.confidence_score DESC""",
        (sid, to_system, confidence_threshold),
    ).fetchall()

    if mappings:
        conn.close()
        result_list = [
            {
                "target_id":            m["target_id"],
                "target_standard_text": m["target_text"],
                "relationship":         m["relationship"],
                "confidence":           m["confidence_score"],
                "quality_score":        _parse_quality(m["notes"]),
                "flagged":              bool(m["flagged_for_review"]),
                "grade_delta":          m["grade_delta"],
                "grade_alignment":      "exact" if m["grade_delta"] == 0 else (
                    f"{abs(m['grade_delta'])} year{'s' if abs(m['grade_delta']) > 1 else ''} "
                    f"{'later' if m['grade_delta'] > 0 else 'earlier'} in target"
                ),
                "verified_by_human":    bool(m["verified_by_human"]),
                "notes":                m["notes"],
            }
            for m in mappings
        ]
        # Rank by quality then confidence. Unscored rows (quality_score is None) are
        # of *unknown* quality, not zero quality — treat them as a neutral midpoint so
        # a high-cosine unscored match isn't buried beneath a mediocre scored one.
        # (Score-1/2 rows are already filtered out by default via flagged_clause.)
        result_list.sort(
            key=lambda x: (x["quality_score"] if x["quality_score"] is not None else 3, x["confidence"]),
            reverse=True,
        )
        return json.dumps({
            "source_id":         src_dict["id"],
            "target_curriculum": to_system,
            "mapping_method":    "precomputed_crosswalk",
            "mappings":          result_list,
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
        scored = _cosine_scores(qvec, conn, system=to_system)
        for score, candidate_id in scored:
            if len(nearest_by_concept) >= 3:
                break
            if score < 0.35:
                break
            row = conn.execute(
                "SELECT * FROM standards WHERE id=?", (candidate_id,)
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
            "quality_score":        _parse_quality(best_below["notes"]),
            "flagged":              bool(best_below["flagged_for_review"]),
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


# ── Tool 6: list_systems ──────────────────────────────────────────────────────

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

    # Counts split into separate fast queries to avoid expensive 3-way JOIN.
    systems = conn.execute(
        """SELECT system,
                  GROUP_CONCAT(DISTINCT subject) AS subjects,
                  COUNT(id) AS standards
           FROM standards
           GROUP BY system
           ORDER BY system"""
    ).fetchall()
    xwalk_counts = dict(conn.execute(
        "SELECT s.system, COUNT(*) FROM crosswalk_mappings cm "
        "INNER JOIN standards s ON s.id = cm.source_id GROUP BY s.system"
    ).fetchall())

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
            "crosswalked": xwalk_counts.get(r["system"], 0),
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


def serve_http() -> None:
    """Run the server over streamable-HTTP for remote/hosted deployments.

    Reads SG_HTTP_HOST / SG_HTTP_PORT (defaults 0.0.0.0:8010). Intended to sit
    behind a TLS-terminating tunnel (Cloudflare Tunnel / Tailscale Funnel), so
    Host/Origin are wildcarded to let the proxied hostname through FastMCP's
    DNS-rebinding guard. Only expose read-only, non-secret data this way.
    """
    import os

    host = os.getenv("SG_HTTP_HOST", "0.0.0.0")
    port = int(os.getenv("SG_HTTP_PORT", "8010"))
    print(f"StandardGraph HTTP MCP → http://{host}:{port}/mcp  (DB={DB_PATH})")
    mcp.run(
        transport="http",
        host=host,
        port=port,
        allowed_hosts=["*"],
        allowed_origins=["*"],
    )


if __name__ == "__main__":
    main()
