"""Eval: Database integrity checks.

Fast deterministic checks that catch silent data failures:
- Empty or suspiciously short standard texts
- Orphaned sub_standards (parent not in standards table)
- Standards missing embeddings
- Crosswalk coverage by system
- Relationship pointers to non-existent standards

All checks are deterministic — no LLM judge needed.

Usage:
  uv run python scripts/eval/db_integrity.py
  uv run python scripts/eval/db_integrity.py --verbose
"""
import argparse
import sqlite3
import sys
from pathlib import Path

ROOT    = Path(__file__).parent.parent.parent
DB_PATH = ROOT / "data" / "common_core.db"

_OK   = "\033[32m OK \033[0m"
_FAIL = "\033[31mFAIL\033[0m"
_WARN = "\033[33mWARN\033[0m"
_INFO = "\033[90mINFO\033[0m"


def _run(label: str, ok: bool, detail: str = "", warn: bool = False) -> bool:
    tag = _OK if ok else (_WARN if warn else _FAIL)
    print(f"  [{tag}] {label}")
    if detail:
        print(f"       {detail}")
    return ok


def main(verbose: bool = False) -> int:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    failures = 0
    warnings = 0

    print(f"\n── DB integrity checks ─────────────────────────────────────────────")
    print(f"  DB: {DB_PATH}")

    # ── Basic counts ──────────────────────────────────────────────────────────
    total_std  = conn.execute("SELECT COUNT(*) FROM standards").fetchone()[0]
    total_emb  = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
    total_xwlk = conn.execute("SELECT COUNT(*) FROM crosswalk_mappings").fetchone()[0]
    total_sub  = conn.execute("SELECT COUNT(*) FROM sub_standards").fetchone()[0]
    total_rel  = conn.execute("SELECT COUNT(*) FROM standard_relationships").fetchone()[0]
    total_sys  = conn.execute("SELECT COUNT(DISTINCT system) FROM standards").fetchone()[0]
    print(f"\n  DB totals: {total_std:,} standards | {total_sys} systems | "
          f"{total_emb:,} embeddings | {total_xwlk:,} crosswalks | "
          f"{total_sub:,} sub_standards | {total_rel:,} relationships\n")

    # ── 1. Empty standard texts ───────────────────────────────────────────────
    empty = conn.execute(
        "SELECT id, system, standard_text FROM standards WHERE standard_text IS NULL OR standard_text=''"
    ).fetchall()
    ok = _run(
        f"No empty standard_text ({len(empty)} found)",
        len(empty) == 0,
        "; ".join(f"{r['id']}" for r in empty[:5]) if empty else "",
    )
    if not ok: failures += 1

    # ── 2. Suspiciously short texts ───────────────────────────────────────────
    MIN_LEN = 10
    short = conn.execute(
        f"SELECT id, system, LENGTH(standard_text) as l FROM standards WHERE LENGTH(standard_text) < {MIN_LEN}"
    ).fetchall()
    # Iowa sub-standards are legitimately short snippets — report as warning not failure
    non_trivial_short = [r for r in short if r["l"] < 5]
    warn_short = [r for r in short if 5 <= r["l"] < MIN_LEN]
    ok = _run(
        f"No critically short standard_text (<5 chars): {len(non_trivial_short)} found",
        len(non_trivial_short) == 0,
        "; ".join(f"{r['id']}(len={r['l']})" for r in non_trivial_short[:5]) if non_trivial_short else "",
    )
    if not ok: failures += 1
    if warn_short:
        _run(
            f"Short standard_text (5–{MIN_LEN-1} chars): {len(warn_short)} found (may be sub-standard snippets)",
            True, warn=True,
            detail="; ".join(f"{r['id']}(len={r['l']})" for r in warn_short[:5]),
        )
        warnings += 1

    # ── 3. Orphaned sub_standards ─────────────────────────────────────────────
    orphaned = conn.execute(
        "SELECT COUNT(*) FROM sub_standards WHERE parent_id NOT IN (SELECT id FROM standards)"
    ).fetchone()[0]
    ok = _run(f"No orphaned sub_standards: {orphaned} found", orphaned == 0)
    if not ok: failures += 1

    # ── 4. Missing embeddings ─────────────────────────────────────────────────
    missing_emb = conn.execute(
        "SELECT COUNT(*) FROM standards WHERE id NOT IN (SELECT standard_id FROM embeddings)"
    ).fetchone()[0]
    pct_missing = 100 * missing_emb / total_std if total_std else 0
    ok = missing_emb == 0
    _run(
        f"All standards have embeddings: {missing_emb} missing ({pct_missing:.1f}%)",
        ok,
        warn=missing_emb > 0 and pct_missing < 2,
    )
    if not ok:
        if pct_missing >= 2:
            failures += 1
        else:
            warnings += 1
        if verbose or missing_emb <= 20:
            rows = conn.execute(
                "SELECT system, COUNT(*) as n FROM standards "
                "WHERE id NOT IN (SELECT standard_id FROM embeddings) "
                "GROUP BY system ORDER BY n DESC LIMIT 10"
            ).fetchall()
            for r in rows:
                print(f"         {r['system']}: {r['n']} missing")

    # ── 5. Duplicate standard IDs ─────────────────────────────────────────────
    dupes = conn.execute(
        "SELECT id, COUNT(*) as n FROM standards GROUP BY id HAVING n > 1"
    ).fetchall()
    ok = _run(f"No duplicate standard IDs: {len(dupes)} found", len(dupes) == 0,
              "; ".join(r["id"] for r in dupes[:5]) if dupes else "")
    if not ok: failures += 1

    # ── 6. Relationship pointers resolve ─────────────────────────────────────
    bad_src = conn.execute(
        "SELECT COUNT(*) FROM standard_relationships WHERE source_id NOT IN (SELECT id FROM standards)"
    ).fetchone()[0]
    bad_tgt = conn.execute(
        "SELECT COUNT(*) FROM standard_relationships WHERE target_id NOT IN (SELECT id FROM standards)"
    ).fetchone()[0]
    ok = bad_src == 0 and bad_tgt == 0
    _run(
        f"All relationship pointers resolve: {bad_src} bad source, {bad_tgt} bad target",
        ok,
        warn=not ok,
    )
    if not ok: warnings += 1

    # ── 7. Crosswalk target IDs resolve ───────────────────────────────────────
    bad_xwlk = conn.execute(
        "SELECT COUNT(*) FROM crosswalk_mappings WHERE target_id NOT IN (SELECT id FROM standards)"
    ).fetchone()[0]
    ok = _run(
        f"All crosswalk target_ids resolve: {bad_xwlk} dangling",
        bad_xwlk == 0,
        warn=bad_xwlk > 0,
    )
    if not ok: warnings += 1

    # ── 8. Embedding dimension consistency ────────────────────────────────────
    dims = conn.execute("SELECT DISTINCT dimensions FROM embeddings").fetchall()
    ok = _run(
        f"All embeddings have same dimension: {[r[0] for r in dims]}",
        len(dims) == 1,
    )
    if not ok: failures += 1

    # ── 9. Crosswalk confidence range ────────────────────────────────────────
    bad_conf = conn.execute(
        "SELECT COUNT(*) FROM crosswalk_mappings WHERE confidence_score < 0 OR confidence_score > 1"
    ).fetchone()[0]
    ok = _run(
        f"All confidence_scores in [0,1]: {bad_conf} out-of-range",
        bad_conf == 0,
    )
    if not ok: failures += 1

    # ── 10. Crosswalk coverage — systems with <50% crosswalked ───────────────
    rows = conn.execute("""
        SELECT s.system,
               COUNT(s.id) as total,
               COUNT(cm.source_id) as crosswalked
        FROM standards s
        LEFT JOIN crosswalk_mappings cm ON cm.source_id = s.id
        GROUP BY s.system
        HAVING total >= 20 AND CAST(crosswalked AS FLOAT)/total < 0.5
        ORDER BY CAST(crosswalked AS FLOAT)/total ASC
        LIMIT 10
    """).fetchall()
    ok = _run(
        f"Systems with <50% crosswalk coverage: {len(rows)} found",
        len(rows) == 0,
        warn=len(rows) > 0,
        detail="; ".join(f"{r['system']}({r['crosswalked']}/{r['total']})" for r in rows[:5]) if rows else "",
    )
    if not ok: warnings += 1

    # ── 11. Grade codes valid ─────────────────────────────────────────────────
    VALID_GRADES = {"K", "1", "2", "3", "4", "5", "6", "7", "8", "HS"}
    bad_grades = conn.execute(
        "SELECT DISTINCT grade FROM standards WHERE grade NOT IN ('K','1','2','3','4','5','6','7','8','HS')"
    ).fetchall()
    ok = _run(
        f"All grade codes valid: {len(bad_grades)} invalid values",
        len(bad_grades) == 0,
        detail=str([r[0] for r in bad_grades[:10]]) if bad_grades else "",
        warn=len(bad_grades) > 0,
    )
    if not ok: warnings += 1

    conn.close()

    print(f"\n  Result: {failures} failure(s), {warnings} warning(s)")
    print()
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()
    sys.exit(main(verbose=args.verbose))
