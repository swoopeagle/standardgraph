"""Eval 1: Coverage accuracy — known standard ID existence and count validation."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / "data" / "common_core.db"

# Known standard IDs that must exist in the DB
REQUIRED_IDS = [
    # CCSS Math
    "CCSS.MATH.5.NF.A.2",
    "CCSS.MATH.5.NF.B.7",
    "CCSS.MATH.8.EE.6",
    "CCSS.MATH.8.G.8",
    "CCSS.MATH.HSA.REI.B.4",
    "CCSS.MATH.2.NBT.B.9",
    "CCSS.MATH.7.G.4",
    # CCSS ELA
    "ccss-ela.CCSS.ELA-Literacy.W.8.10",
    "ccss-ela.CCSS.ELA-Literacy.RI.4.9",
    # NGSS
    "NGSS.K-LS1-1",
    "NGSS.MS-LS1-6",
    "NGSS.K-2-ETS1-1",
    # CSTA
    "csta.1A-AP-14",
    "csta.1A-IC-18",
    # C3
    "c3.D2.Civ.7.K-2",
]

# Official counts from authoritative sources
# Format: (system, min, max, source_note)
OFFICIAL_COUNTS = [
    ("ccss",     343, 343, "CCSS Math — 343 standards exactly"),
    ("ccss-ela", 480, 530, "CCSS ELA — ~504 including grade-specific"),
    ("ngss",     195, 220, "NGSS — 103 PEs but includes DCIs/SEPs/CCCs in our schema"),
    ("csta",      88, 110, "CSTA K-12 2017 — 101 practice concepts"),
    ("c3",       200, 250, "C3 Framework — ~220 indicators"),
]

OK   = "\033[32m OK \033[0m"
FAIL = "\033[31mFAIL\033[0m"
WARN = "\033[33mWARN\033[0m"


def main() -> int:
    conn = sqlite3.connect(DB_PATH)
    failures = 0

    print("\n── Required standard IDs ────────────────────────────────────────────")
    for sid in REQUIRED_IDS:
        row = conn.execute("SELECT standard_text FROM standards WHERE id=?", (sid,)).fetchone()
        if row:
            print(f"  [{OK}] {sid}")
        else:
            print(f"  [{FAIL}] {sid}  ← NOT FOUND")
            failures += 1

    print("\n── Official count validation ────────────────────────────────────────")
    for system, lo, hi, note in OFFICIAL_COUNTS:
        count = conn.execute(
            "SELECT COUNT(*) FROM standards WHERE system=?", (system,)
        ).fetchone()[0]
        if lo <= count <= hi:
            tag = OK
        else:
            tag = WARN
        print(f"  [{tag}] {system:12s}  {count:>5}  (expected {lo}–{hi})  {note}")

    print("\n── Systems with suspiciously low counts (<10) ──────────────────────")
    low = conn.execute(
        "SELECT system, COUNT(*) n FROM standards GROUP BY system HAVING n < 10 ORDER BY n"
    ).fetchall()
    for system, n in low:
        print(f"  [{WARN}] {system}: {n} standards")
    if not low:
        print(f"  [{OK}]  None")

    conn.close()
    print(f"\n  {'FAIL' if failures else 'OK'}  {failures} required-ID check(s) failed\n")
    return 1 if failures else 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
