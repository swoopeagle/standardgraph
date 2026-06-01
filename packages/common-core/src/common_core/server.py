"""Common Core Math Standards MCP server — 4 tools."""
import json
import sqlite3
import struct

import httpx
from fastmcp import FastMCP

from shared.config import DB_PATH, OLLAMA_BASE_URL, EMBED_MODEL

mcp = FastMCP("intl-math-standards")

GRADE_ORDER = ["K", "1", "2", "3", "4", "5", "6", "7", "8", "HS"]


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _unpack(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def _embed(text: str) -> list[float]:
    resp = httpx.post(
        f"{OLLAMA_BASE_URL}/api/embed",
        json={"model": EMBED_MODEL, "input": [text]},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["embeddings"][0]


@mcp.tool()
def lookup_standard(standard_id: str) -> str:
    """Look up a math standard by ID (e.g. CCSS.MATH.6.RP.A.3)."""
    conn = _db()
    row = conn.execute("SELECT * FROM standards WHERE id = ?", (standard_id,)).fetchone()
    conn.close()
    if not row:
        return json.dumps({"error": f"Standard '{standard_id}' not found."})
    return json.dumps(dict(row), indent=2)


@mcp.tool()
def search_standards(query: str, limit: int = 5) -> str:
    """Search math standards semantically using a natural language query."""
    query_vec = _embed(query)

    conn = _db()
    rows = conn.execute("SELECT standard_id, vector FROM embeddings").fetchall()

    scored = sorted(
        ((float(_cosine(query_vec, _unpack(r["vector"]))), r["standard_id"]) for r in rows),
        reverse=True,
    )

    results = []
    for _, sid in scored[:limit]:
        std = conn.execute("SELECT * FROM standards WHERE id = ?", (sid,)).fetchone()
        if std:
            results.append(dict(std))

    conn.close()
    return json.dumps(results, indent=2)


@mcp.tool()
def get_progression(standard_id: str) -> str:
    """Return the full grade progression for the domain of a given standard."""
    conn = _db()
    std = conn.execute("SELECT * FROM standards WHERE id = ?", (standard_id,)).fetchone()
    if not std:
        conn.close()
        return json.dumps({"error": f"Standard '{standard_id}' not found."})

    std = dict(std)
    related = conn.execute(
        "SELECT * FROM standards WHERE domain_code = ? AND source = ?",
        (std["domain_code"], std["source"]),
    ).fetchall()
    conn.close()

    by_grade: dict[str, list] = {}
    for r in related:
        r = dict(r)
        by_grade.setdefault(r["grade"], []).append(r)

    def grade_key(g: str) -> int:
        try:
            return GRADE_ORDER.index(g)
        except ValueError:
            return 99

    progression = [
        {"grade": g, "standards": by_grade[g]}
        for g in sorted(by_grade, key=grade_key)
    ]

    return json.dumps({"current": std, "domain": std["domain_code"], "progression": progression}, indent=2)


@mcp.tool()
def map_standard(standard_id: str, target_curriculum: str = "Singapore-MOE") -> str:
    """Map a standard to another curriculum. Returns pre-computed crosswalks or a Phase 1 stub."""
    conn = _db()
    std = conn.execute("SELECT * FROM standards WHERE id = ?", (standard_id,)).fetchone()
    if not std:
        conn.close()
        return json.dumps({"error": f"Standard '{standard_id}' not found."})

    std = dict(std)
    mappings = conn.execute(
        """SELECT cm.*, s.description, s.grade, s.domain
           FROM crosswalk_mappings cm
           JOIN standards s ON s.id = cm.to_id
           WHERE cm.from_id = ? AND s.source = ?""",
        (standard_id, target_curriculum),
    ).fetchall()
    conn.close()

    if mappings:
        return json.dumps({"from": std, "target_curriculum": target_curriculum,
                           "mappings": [dict(m) for m in mappings]}, indent=2)

    return json.dumps({
        "from": std,
        "target_curriculum": target_curriculum,
        "mappings": [],
        "note": f"No crosswalk data for {target_curriculum} yet — coming in Phase 2.",
    }, indent=2)


if __name__ == "__main__":
    mcp.run()
