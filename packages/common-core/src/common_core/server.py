"""International Math Standards MCP server."""
import json
import sqlite3

import numpy as np
from fastmcp import FastMCP

from shared.config import DB_PATH, OLLAMA_BASE_URL, EMBED_MODEL

mcp = FastMCP(
    "intl-math-standards",
    instructions="""
You have access to a database of 17,743 math standards across 64 curriculum systems, all
cross-referenced to the US Common Core State Standards (CCSS) as the hub.

## Available systems

**US:** ccss (343 standards, the hub), plus all 50 states + DC by two-letter code
  (al ak az ar ca co ct dc de fl ga hi id il in ia ks ky la me md ma mi mn ms mo
   mt ne nv nh nj nm ny nc nd oh ok or pa ri sc sd tn tx ut vt va wa wv wi wy)

**Canada:** ca-ab (Alberta) ca-bc (British Columbia) ca-mb (Manitoba)
           ca-nb (New Brunswick) ca-on (Ontario) ca-sk (Saskatchewan)

**International:** au-acara (Australian Curriculum) au-vic (Victorian Curriculum)
  cambridge (Cambridge International) ib-myp (IB Middle Years) ib-dp (IB Diploma)
  uk-aqa (AQA GCSE) uk-nc (England National Curriculum, Years 1-6)

## Grade codes
K, 1, 2, 3, 4, 5, 6, 7, 8, HS

## When to use each tool

- **lookup_standard**: user provides a specific standard ID they want to read
- **search_standards**: user describes a concept and wants to find matching standards
- **get_progression**: user asks how a topic develops across grade levels
- **map_standard**: user wants to compare a standard across systems (e.g. "how does Texas
  cover this vs CCSS?" or "what does the IB equivalent look like?")

## Tips
- Crosswalk mappings are NLP-generated (cosine similarity), not human-verified.
  A confidence ≥ 0.85 is a strong match; 0.70–0.80 is plausible but worth checking.
  A grade_delta ≠ 0 means the systems introduce the concept at different grade levels.
- map_standard only maps to/from CCSS as the intermediate — direct system-to-system
  mapping goes source → CCSS → target.
- search_standards queries one system at a time; call it multiple times to compare
  how different curricula cover the same concept.
""",
)

GRADE_ORDER = ["K", "1", "2", "3", "4", "5", "6", "7", "8", "HS"]


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
    """Find math standards that match a natural language description of a concept or skill.

    Use this when the user describes what they're looking for rather than citing a standard ID.
    Examples: "adding fractions with unlike denominators", "geometric transformations grade 8",
    "solving quadratic equations".

    query: plain English description of the math concept or skill.
    system: which curriculum to search (default 'ccss'). Call multiple times to compare systems.
    grade: optional filter — single grade '5', range '6-8', or 'HS'. Grade codes: K 1 2 3 4 5 6 7 8 HS.
    domain: optional keyword to restrict by domain name (e.g. 'geometry', 'algebra').
    limit: number of results (default 5, max sensible ~10).

    Returns standards ranked by semantic similarity with relevance scores (0–1).
    """
    query_vec = _embed_query(query)
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
    query_vec = _embed_query(concept)
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
    of this Texas standard?", "how does Cambridge cover this CCSS standard?", or
    "I'm moving from Ontario to the UK — what's the equivalent?"

    Note: all mappings go through CCSS as the hub. For direct system-to-system comparison
    (e.g. tx → cambridge), call this twice: tx → ccss, then search_standards in cambridge
    using the CCSS standard text.

    standard_id: the source standard ID (full form, e.g. 'TX.MATH.5.3.K').
    from_system: system code of the source standard (e.g. 'tx', 'ca-on', 'cambridge').
    to_system: target system code — currently only 'ccss' mappings are precomputed.
               For other targets, use search_standards instead.
    confidence_threshold: minimum cosine similarity to return (default 0.7; raise to 0.85
                          for high-confidence matches only).

    Returns matched standards with confidence score, grade alignment, and whether
    the mapping has been human-verified.
    """
    sid = _expand_id(standard_id, from_system)
    conn = _db()

    src = conn.execute("SELECT * FROM standards WHERE id=?", (sid,)).fetchone()
    if not src:
        conn.close()
        return json.dumps({"error": "standard_not_found", "queried_id": sid})

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
    conn.close()

    if mappings:
        return json.dumps({
            "source_id":         dict(src)["id"],
            "target_curriculum": to_system,
            "mappings": [
                {
                    "target_id":          m["target_id"],
                    "target_standard_text": m["target_text"],
                    "relationship":       m["relationship"],
                    "confidence":         m["confidence_score"],
                    "grade_delta":        m["grade_delta"],
                    "grade_alignment":    "exact" if m["grade_delta"] == 0 else f"{abs(m['grade_delta'])} year{'s' if abs(m['grade_delta'])>1 else ''} {'later' if m['grade_delta']>0 else 'earlier'} in target",
                    "verified_by_human":  bool(m["verified_by_human"]),
                    "notes":              m["notes"],
                }
                for m in mappings
            ],
        }, indent=2)

    available = ["sg-moe", "ib-myp", "ncert"]
    return json.dumps({
        "source_id":   sid,
        "to_system":   to_system,
        "result":      "no_mapping",
        "reason":      f"{to_system} not yet indexed." if to_system not in available else f"No mapping found for {sid} → {to_system} above confidence {confidence_threshold}.",
        "available_systems": available,
    }, indent=2)


if __name__ == "__main__":
    mcp.run()
