"""Eval 4: Search quality — golden query recall evaluation.

Embeds each query with nomic-embed-text (localhost Ollama), then measures
whether the expected standard appears in the top-k results by cosine similarity.
"""
import sqlite3
import sys
from pathlib import Path

import httpx
import numpy as np

DB_PATH = Path(__file__).parent.parent.parent / "data" / "common_core.db"
EMBED_URL = "http://localhost:11434/api/embed"
EMBED_MODEL = "nomic-embed-text"

# (query, expected_id, description)
GOLDEN_QUERIES = [
    # ── Mathematics ──────────────────────────────────────────────────────────
    ("adding fractions with unlike denominators",
     "CCSS.MATH.5.NF.A.2",
     "CCSS Math 5 — add/subtract fractions unlike denominators"),
    ("dividing fractions by whole numbers grade 5",
     "CCSS.MATH.5.NF.B.7",
     "CCSS Math 5 — divide unit fractions"),
    ("slope of a line equation y equals mx plus b",
     "CCSS.MATH.8.EE.6",
     "CCSS Math 8 — derive y=mx+b from similar triangles"),
    ("Pythagorean theorem distance between two points",
     "CCSS.MATH.8.G.8",
     "CCSS Math 8 — Pythagorean theorem applied"),
    ("solving quadratic equations",
     "CCSS.MATH.HSA.REI.B.4",
     "CCSS HS Algebra — solve quadratic equations"),
    ("place value understand hundreds tens ones grade 2",
     "CCSS.MATH.2.NBT.B.9",
     "CCSS Math 2 — place value understanding"),
    ("area and circumference of a circle",
     "CCSS.MATH.7.G.4",
     "CCSS Math 7 — circle area and circumference"),

    # ── ELA ──────────────────────────────────────────────────────────────────
    ("integrate information from two texts on the same topic grade 4",
     "ccss-ela.CCSS.ELA-Literacy.RI.4.9",
     "CCSS ELA 4 — integrate two informational texts"),
    ("write routinely extended time frames range of tasks",
     "ccss-ela.CCSS.ELA-Literacy.W.8.10",
     "CCSS ELA 8 — routine writing"),

    # ── Science ──────────────────────────────────────────────────────────────
    ("what plants and animals need to survive kindergarten",
     "NGSS.K-LS1-1",
     "NGSS K — plants and animals need to survive"),
    ("photosynthesis matter energy ecosystems middle school",
     "NGSS.MS-LS1-6",
     "NGSS MS — photosynthesis"),
    ("engineering design test compare objects solve problem",
     "NGSS.K-2-ETS1-3",
     "NGSS K-2 ETS — compare design solutions"),

    # ── Computer Science ─────────────────────────────────────────────────────
    ("debug identify and fix errors loops programs",
     "csta.1A-AP-14",
     "CSTA 1A — debug loops"),
    ("keep login information private log off devices",
     "csta.1A-IC-18",
     "CSTA 1A — login privacy"),

    # ── Social Studies ────────────────────────────────────────────────────────
    ("civic virtues participation school community",
     "c3.D2.Civ.7.K-2",
     "C3 Civics K-2 — civic virtues"),
]

OK   = "\033[32m OK \033[0m"
FAIL = "\033[31mFAIL\033[0m"
WARN = "\033[33mWARN\033[0m"


def _embed(texts: list[str]) -> np.ndarray:
    resp = httpx.post(
        EMBED_URL,
        json={"model": EMBED_MODEL, "input": texts},
        timeout=60,
    )
    resp.raise_for_status()
    return np.array(resp.json()["embeddings"], dtype=np.float32)


def _search(query_vec: np.ndarray, system_vecs: np.ndarray, system_ids: list[str],
            k: int = 10) -> list[tuple[str, float]]:
    q = query_vec / (np.linalg.norm(query_vec) + 1e-9)
    norms = np.linalg.norm(system_vecs, axis=1, keepdims=True)
    vecs_n = system_vecs / (norms + 1e-9)
    sims = vecs_n @ q
    top = np.argsort(sims)[::-1][:k]
    return [(system_ids[i], float(sims[i])) for i in top]


def main() -> int:
    conn = sqlite3.connect(DB_PATH)

    # Determine which system each expected ID belongs to
    id_to_system = {}
    for _, eid, _ in GOLDEN_QUERIES:
        row = conn.execute("SELECT system FROM standards WHERE id=?", (eid,)).fetchone()
        if row:
            id_to_system[eid] = row[0]
        else:
            id_to_system[eid] = None

    # Pre-load embeddings per system
    systems_needed = set(id_to_system.values()) - {None}
    system_embeddings: dict[str, tuple[list[str], np.ndarray]] = {}
    for system in systems_needed:
        rows = conn.execute(
            "SELECT s.id, e.vector FROM standards s JOIN embeddings e ON e.standard_id=s.id WHERE s.system=?",
            (system,),
        ).fetchall()
        ids = [r[0] for r in rows]
        vecs = np.array([np.frombuffer(r[1], dtype=np.float32) for r in rows])
        system_embeddings[system] = (ids, vecs)

    print("\n── Golden query evaluation ──────────────────────────────────────────")
    print(f"  {'Query':<50} {'R@1':>4} {'R@5':>4} {'R@10':>5}")
    print(f"  {'-'*50} {'----':>4} {'----':>4} {'-----':>5}")

    hits_1 = hits_5 = hits_10 = total = 0

    for query, expected_id, desc in GOLDEN_QUERIES:
        system = id_to_system.get(expected_id)
        if system is None:
            print(f"  [{WARN}] {desc}: expected ID not in DB — skipped")
            continue

        try:
            q_vec = _embed([query])[0]
        except Exception as e:
            print(f"  [{WARN}] Embed failed: {e}")
            continue

        ids, vecs = system_embeddings[system]
        results = _search(q_vec, vecs, ids, k=10)
        result_ids = [r[0] for r in results]

        in_1  = expected_id in result_ids[:1]
        in_5  = expected_id in result_ids[:5]
        in_10 = expected_id in result_ids[:10]

        hits_1  += in_1
        hits_5  += in_5
        hits_10 += in_10
        total   += 1

        tag = OK if in_5 else (WARN if in_10 else FAIL)
        short_q = query[:48] + ".." if len(query) > 48 else query
        print(f"  [{tag}] {short_q:<50} {'✓' if in_1 else '✗':>4} {'✓' if in_5 else '✗':>4} {'✓' if in_10 else '✗':>5}")
        if not in_10:
            top3 = ", ".join(r[0] for r in results[:3])
            print(f"         expected: {expected_id}")
            print(f"         got:      {top3}")

    print(f"\n  Results ({total} queries):")
    print(f"    Recall@1  : {hits_1}/{total}  ({100*hits_1/total:.0f}%)")
    print(f"    Recall@5  : {hits_5}/{total}  ({100*hits_5/total:.0f}%)")
    print(f"    Recall@10 : {hits_10}/{total}  ({100*hits_10/total:.0f}%)")
    print()

    conn.close()
    return 0 if hits_5 / total >= 0.70 else 1


if __name__ == "__main__":
    sys.exit(main())
