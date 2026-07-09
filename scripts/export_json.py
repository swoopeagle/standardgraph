#!/usr/bin/env python3
"""Export the StandardGraph SQLite DB to a Marble-compatible JSON layer.

Produces a `data/` directory of UTF-8 JSON/JSONL files plus a checksummed
manifest, mirroring the shape of withmarbleapp/os-taxonomy so our corpus can be
consumed as plain files (no SQLite, no MCP runtime) and compared like-for-like.

Design choices (and how they map to Marble):
  * Big tables (standards, crosswalks, relationships) are written as **JSONL**
    — one record per line — because at 154k / 95k / 1.58M rows a single JSON
    array is neither streamable nor git-friendly. Marble's files are tiny
    enough to be arrays; ours are not.
  * `standard_relationships` stores both `prerequisite` and `successor` as exact
    inverses. We export only `prerequisite` edges (reverse an edge to get
    "unlocks"), exactly as Marble stores one direction.
  * Crosswalk quality scores are embedded in `notes` as "[LLM score N/5]".
    We parse them into a first-class `quality_score` field (1-5, or null).
  * Embeddings are intentionally NOT exported (derived, recomputable) — same
    call Marble made.

LICENSING GATE (read before publishing):
  Some source systems are proprietary (AP = College Board, IB = IBO, plus
  NGSS/Cambridge restrictions). For a public release, pass --codes-only with
  those slugs so verbatim `standard_text` is dropped and only the id/code
  ships. Default is FULL TEXT for internal inspection. The script prints a
  warning listing systems that look encumbered.

Usage:
  uv run python scripts/export_json.py --out /path/to/export
  uv run python scripts/export_json.py --out ./export --codes-only ib-dp,ib-myp,ap-calc-ab,...
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

SCORE_RE = re.compile(r"\[LLM score (\d)/5\]")

# Grade codes are TEXT and do not sort lexically (K, HS break digit ordering).
GRADE_ORDER = {"K": 0, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6,
               "7": 7, "8": 8, "9": 9, "10": 10, "11": 11, "12": 12, "HS": 13}

# Slugs whose upstream license likely forbids redistributing verbatim text.
# Not applied by default — surfaced as a warning and available via --codes-only.
LIKELY_ENCUMBERED_PREFIXES = ("ap-", "ib-")
LIKELY_ENCUMBERED_EXACT = {"cambridge", "ib-dp", "ib-myp"}


class HashingWriter:
    """Write text to a file while accumulating a sha256 and a line count."""

    def __init__(self, path: Path):
        self.path = path
        self._fh = path.open("w", encoding="utf-8")
        self._h = hashlib.sha256()
        self.lines = 0

    def write_record(self, obj: dict) -> None:
        line = json.dumps(obj, ensure_ascii=False)
        self._fh.write(line)
        self._fh.write("\n")
        self._h.update(line.encode("utf-8"))
        self._h.update(b"\n")
        self.lines += 1

    def write_raw(self, text: str) -> None:
        self._fh.write(text)
        self._h.update(text.encode("utf-8"))

    def close(self) -> tuple[str, int]:
        self._fh.close()
        return self._h.hexdigest(), self.path.stat().st_size


def parse_quality(notes: str | None) -> int | None:
    if not notes:
        return None
    m = SCORE_RE.search(notes)
    return int(m.group(1)) if m else None


def export_standards(conn, out_dir: Path, codes_only: set[str]) -> dict:
    # Preload sub-standards and keywords to avoid per-row queries.
    subs: dict[str, list] = defaultdict(list)
    for pid, sid, text, pos in conn.execute(
        "SELECT parent_id, id, text, position FROM sub_standards ORDER BY parent_id, position"
    ):
        subs[pid].append({"id": sid, "text": text, "position": pos})

    kws: dict[str, list] = defaultdict(list)
    for sid, kw in conn.execute(
        "SELECT standard_id, keyword FROM keywords ORDER BY standard_id"
    ):
        kws[sid].append(kw)

    w = HashingWriter(out_dir / "standards.jsonl")
    cur = conn.execute(
        "SELECT id, system, subject, grade, grade_band, domain, cluster, "
        "standard_text, last_verified_date, source_url FROM standards ORDER BY system, id"
    )
    for (sid, system, subject, grade, grade_band, domain, cluster,
         text, verified, url) in cur:
        rec = {
            "id": sid,
            "system": system,
            "subject": subject,
            "grade": grade,
            "grade_band": grade_band,
            "domain": domain,
            "cluster": cluster,
            "last_verified_date": verified,
            "source_url": url,
        }
        if system in codes_only:
            rec["text_included"] = False
        else:
            rec["standard_text"] = text
            rec["text_included"] = True
        if subs.get(sid):
            rec["sub_standards"] = subs[sid]
        if kws.get(sid):
            rec["keywords"] = kws[sid]
        w.write_record(rec)
    sha, size = w.close()
    return {"bytes": size, "sha256": sha, "records": w.lines}


def export_crosswalks(conn, out_dir: Path) -> dict:
    w = HashingWriter(out_dir / "crosswalks.jsonl")
    cur = conn.execute(
        "SELECT source_id, target_id, source_system, target_system, relationship, "
        "confidence_score, grade_delta, notes, verified_by_human "
        "FROM crosswalk_mappings ORDER BY source_system, source_id"
    )
    for (src, tgt, ss, ts, rel, conf, gd, notes, vh) in cur:
        w.write_record({
            "source_id": src,
            "target_id": tgt,
            "source_system": ss,
            "target_system": ts,
            "relationship": rel,
            "confidence_score": conf,
            "quality_score": parse_quality(notes),
            "grade_delta": gd,
            "verified_by_human": bool(vh),
            "notes": notes,
        })
    sha, size = w.close()
    return {"bytes": size, "sha256": sha, "records": w.lines}


def export_relationships(conn, out_dir: Path) -> dict:
    # Only prerequisite edges; successor is the exact inverse.
    w = HashingWriter(out_dir / "relationships.jsonl")
    cur = conn.execute(
        "SELECT source_id, target_id, system FROM standard_relationships "
        "WHERE relationship = 'prerequisite' ORDER BY source_id"
    )
    for (src, tgt, system) in cur:
        # source_id depends on target_id (target is the prerequisite).
        w.write_record({"topic_id": src, "prerequisite_id": tgt, "system": system})
    sha, size = w.close()
    return {"bytes": size, "sha256": sha, "records": w.lines}


def export_systems(conn, out_dir: Path, codes_only: set[str]) -> dict:
    rows = conn.execute(
        "SELECT system, subject, COUNT(*) AS n, "
        "GROUP_CONCAT(DISTINCT grade) AS grades "
        "FROM standards GROUP BY system, subject ORDER BY system"
    ).fetchall()
    systems = []
    for system, subject, n, grades in rows:
        codes = [g for g in (grades or "").split(",") if g]
        codes.sort(key=lambda g: GRADE_ORDER.get(g, 99))
        systems.append({
            "slug": system,
            "subject": subject,
            "standard_count": n,
            "grade_min": codes[0] if codes else None,
            "grade_max": codes[-1] if codes else None,
            "text_included": system not in codes_only,
        })
    payload = {
        "version": "v1",
        "systemCount": len(systems),
        "systems": systems,
    }
    path = out_dir / "systems.json"
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    path.write_text(text, encoding="utf-8")
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return {"bytes": path.stat().st_size, "sha256": sha, "records": len(systems)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(Path.home() / ".standardgraph" / "common_core.db"))
    ap.add_argument("--out", required=True, help="output directory (a data/ dir is created inside)")
    ap.add_argument("--codes-only", default="",
                    help="comma-separated system slugs to ship codes-only (no verbatim text)")
    args = ap.parse_args()

    codes_only = {s.strip() for s in args.codes_only.split(",") if s.strip()}
    out_dir = Path(args.out) / "data"
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(args.db)

    print(f"Exporting from {args.db}")
    print(f"  -> {out_dir}")
    if codes_only:
        print(f"  codes-only systems: {sorted(codes_only)}")
    else:
        print("  codes-only systems: NONE (full text — internal use only)")

    files = {}
    print("standards ...", flush=True)
    files["standards.jsonl"] = export_standards(conn, out_dir, codes_only)
    print("crosswalks ...", flush=True)
    files["crosswalks.jsonl"] = export_crosswalks(conn, out_dir)
    print("relationships ...", flush=True)
    files["relationships.jsonl"] = export_relationships(conn, out_dir)
    print("systems ...", flush=True)
    files["systems.json"] = export_systems(conn, out_dir, codes_only)

    # Warn about encumbered systems still shipping full text.
    encumbered = []
    for (system,) in conn.execute("SELECT DISTINCT system FROM standards"):
        looks_enc = system in LIKELY_ENCUMBERED_EXACT or system.startswith(LIKELY_ENCUMBERED_PREFIXES)
        if looks_enc and system not in codes_only:
            encumbered.append(system)

    manifest = {
        "dataset": "StandardGraph JSON layer",
        "version": "v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "note": "Marble-compatible file shape. Relationships are prerequisite-only "
                "(reverse an edge for 'unlocks'). Embeddings intentionally omitted "
                "(derived, recomputable).",
        "codesOnlySystems": sorted(codes_only),
        "counts": {
            "standards": files["standards.jsonl"]["records"],
            "crosswalks": files["crosswalks.jsonl"]["records"],
            "relationships_prerequisite": files["relationships.jsonl"]["records"],
            "systems": files["systems.json"]["records"],
        },
        "files": files,
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    conn.close()

    print("\nDone. Files written:")
    for name, meta in files.items():
        mb = meta["bytes"] / 1e6
        print(f"  {name:<24} {meta['records']:>10,} recs   {mb:>8.1f} MB")
    print(f"  {'manifest.json':<24} {'':>10}        {manifest_path.stat().st_size/1e3:>8.1f} KB")

    if encumbered:
        print("\n⚠️  LICENSING: these systems ship FULL TEXT but look proprietary.")
        print("   For a public release, re-run with --codes-only including:")
        print("   " + ",".join(sorted(encumbered)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
