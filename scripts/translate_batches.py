"""Split rows into translation batches for Claude subagents and merge the results back (used by the scan-3 systems).

    python3 scripts/translate_batches.py split raw.json outdir --src text_zh --ctx area,topic --size 60
    # each subagent reads outdir/b003.json  -> writes outdir/b003.out.json  ([{"i": 123, "en": "..."}, ...])
    python3 scripts/translate_batches.py merge raw.json outdir merged.json --dst text_en     # fails loudly on a missing/empty row
"""
import argparse
import json
import sys
from pathlib import Path


def split(a):
    rows = json.load(open(a.raw)); out = Path(a.outdir); out.mkdir(parents=True, exist_ok=True)
    ctx = [c for c in a.ctx.split(",") if c]
    for k in range(0, len(rows), a.size):
        (out / f"b{k // a.size:03d}.json").write_text(json.dumps(
            [{"i": i, "ctx": " / ".join(str(rows[i].get(c, "")) for c in ctx if rows[i].get(c)), "src": rows[i][a.src]}
             for i in range(k, min(k + a.size, len(rows)))], ensure_ascii=False, indent=0))
    print(f"{len(rows)} rows -> {(len(rows) + a.size - 1) // a.size} batches in {out}")


def merge(a):
    rows = json.load(open(a.raw)); en = {}
    for f in sorted(Path(a.outdir).glob("b*.out.json")):
        for r in json.load(open(f)):
            en[r["i"]] = r["en"].strip()
    miss = [i for i in range(len(rows)) if not en.get(i)]
    if miss:
        sys.exit(f"missing translations for {len(miss)} rows, e.g. {miss[:10]}")
    for i, r in enumerate(rows):
        r[a.dst] = en[i]
    json.dump(rows, open(a.merged, "w"), ensure_ascii=False, indent=1)
    print(f"merged {len(rows)} rows -> {a.merged}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("split"); s.add_argument("raw"); s.add_argument("outdir"); s.add_argument("--src", default="text_zh"); s.add_argument("--ctx", default=""); s.add_argument("--size", type=int, default=60)
    m = sub.add_parser("merge"); m.add_argument("raw"); m.add_argument("outdir"); m.add_argument("merged"); m.add_argument("--dst", default="text_en")
    a = ap.parse_args(); {"split": split, "merge": merge}[a.cmd](a)
