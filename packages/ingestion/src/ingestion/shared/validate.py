"""Stage 7: Validate DB integrity after ingestion."""
import sqlite3
import sys

from shared.config import DB_PATH

GRADE_ORDER = ["K", "1", "2", "3", "4", "5", "6", "7", "8", "HS"]


def validate() -> bool:
    conn = sqlite3.connect(DB_PATH)
    errors: list[str] = []
    warnings: list[str] = []

    def check(label: str, query: str, min_val: int, max_val: int | None = None) -> None:
        count = conn.execute(query).fetchone()[0]
        if count < min_val:
            errors.append(f"{label}: {count} (expected >= {min_val})")
        elif max_val and count > max_val:
            warnings.append(f"{label}: {count} (expected <= {max_val})")
        else:
            print(f"  OK  {label}: {count}")

    print("Validating database...")

    check("CCSS standards",  "SELECT COUNT(*) FROM standards WHERE system='ccss'", 300, 450)
    check("sub_standards",   "SELECT COUNT(*) FROM sub_standards", 80)
    check("keywords",        "SELECT COUNT(*) FROM keywords", 1000)
    check("relationships",   "SELECT COUNT(*) FROM standard_relationships", 500)
    check("embeddings",      "SELECT COUNT(*) FROM embeddings", 300)

    # Embedding dimensions
    row = conn.execute("SELECT dimensions, length(vector) FROM embeddings LIMIT 1").fetchone()
    if row:
        dims, blob_len = row
        expected_blob = dims * 4
        if dims == 768 and blob_len == expected_blob:
            print(f"  OK  embedding dimensions: {dims} ({blob_len} bytes)")
        else:
            errors.append(f"embedding: dims={dims}, blob={blob_len} bytes (expected dims=768, blob=3072)")

    # Embedding coverage
    std_n = conn.execute("SELECT COUNT(*) FROM standards").fetchone()[0]
    emb_n = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
    if std_n == emb_n:
        print(f"  OK  embedding coverage: {emb_n}/{std_n}")
    else:
        warnings.append(f"embedding coverage: {emb_n}/{std_n} standards embedded")

    # No missing standard_text
    missing = conn.execute(
        "SELECT COUNT(*) FROM standards WHERE standard_text = '' OR standard_text IS NULL"
    ).fetchone()[0]
    if missing == 0:
        print("  OK  all standards have standard_text")
    else:
        errors.append(f"{missing} standards missing standard_text")

    # Every grade K-8 + HS has at least 5 standards
    for grade in GRADE_ORDER:
        n = conn.execute(
            "SELECT COUNT(*) FROM standards WHERE system='ccss' AND grade=?", (grade,)
        ).fetchone()[0]
        if n < 5:
            errors.append(f"Grade {grade}: only {n} standards (expected >= 5)")
        else:
            print(f"  OK  grade {grade}: {n} standards")

    # sub_standards FK integrity
    orphans = conn.execute(
        "SELECT COUNT(*) FROM sub_standards WHERE parent_id NOT IN (SELECT id FROM standards)"
    ).fetchone()[0]
    if orphans == 0:
        print("  OK  sub_standards FK integrity")
    else:
        errors.append(f"{orphans} sub_standards with missing parent_id")

    # Spot check
    # Note: commonstandardsproject API uses 6.RP.3 notation (no cluster letter)
    spot = conn.execute(
        "SELECT id, grade, domain, standard_text FROM standards WHERE id='CCSS.MATH.6.RP.3'"
    ).fetchone()
    if spot:
        has_ratio = "ratio" in spot[3].lower()
        print(f"  OK  spot check 6.RP.3: grade={spot[1]}, domain={spot[2][:30]}…, 'ratio' in text={has_ratio}")
        if not has_ratio:
            warnings.append("6.RP.3 text does not contain 'ratio'")
    else:
        warnings.append("CCSS.MATH.6.RP.3 not found")

    # Relationship check for 6.RP.3
    rel_check = conn.execute(
        "SELECT relationship FROM standard_relationships WHERE source_id='CCSS.MATH.6.RP.3'"
    ).fetchall()
    rel_types = {r[0] for r in rel_check}
    if "successor" in rel_types or "prerequisite" in rel_types:
        print(f"  OK  6.RP.3 relationships: {rel_types}")
    else:
        warnings.append(f"6.RP.3 has no prerequisite/successor relationships: {rel_types}")

    conn.close()

    if errors:
        print(f"\n  ERRORS ({len(errors)}):")
        for e in errors:
            print(f"    ERROR: {e}")
    if warnings:
        print(f"\n  WARNINGS ({len(warnings)}):")
        for w in warnings:
            print(f"    WARN:  {w}")
    if not errors and not warnings:
        print("\n  All checks passed.")

    return len(errors) == 0


def main() -> None:
    print("Stage 7: Validating ingestion...")
    ok = validate()
    if not ok:
        sys.exit(1)
    print("Done.")


if __name__ == "__main__":
    main()
