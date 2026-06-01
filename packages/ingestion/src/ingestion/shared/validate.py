"""Stage 7: Validate DB integrity after ingestion."""
import sqlite3
import sys

from shared.config import DB_PATH


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
    check("CCSS standards",  "SELECT COUNT(*) FROM standards WHERE source='CCSS'", 400, 650)
    check("keywords",        "SELECT COUNT(*) FROM keywords", 1000)
    check("relationships",   "SELECT COUNT(*) FROM standard_relationships", 500)
    check("embeddings",      "SELECT COUNT(*) FROM embeddings", 400)

    vec_row = conn.execute("SELECT length(vector) FROM embeddings LIMIT 1").fetchone()
    if vec_row:
        expected = 768 * 4  # 768 float32s
        if vec_row[0] == expected:
            print(f"  OK  embedding size: {vec_row[0]} bytes (768 × float32)")
        else:
            errors.append(f"embedding size: {vec_row[0]} bytes (expected {expected})")

    std_n = conn.execute("SELECT COUNT(*) FROM standards").fetchone()[0]
    emb_n = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
    if std_n == emb_n:
        print(f"  OK  embedding coverage: {emb_n}/{std_n}")
    else:
        warnings.append(f"embedding coverage: {emb_n}/{std_n} standards embedded")

    missing = conn.execute(
        "SELECT COUNT(*) FROM standards WHERE description = '' OR description IS NULL"
    ).fetchone()[0]
    if missing == 0:
        print("  OK  all standards have descriptions")
    else:
        errors.append(f"{missing} standards missing description")

    spot = conn.execute(
        "SELECT id, grade, domain FROM standards WHERE id='CCSS.MATH.6.RP.A.3'"
    ).fetchone()
    if spot:
        print(f"  OK  spot check 6.RP.A.3: grade={spot[1]}, domain={spot[2]}")
    else:
        warnings.append("CCSS.MATH.6.RP.A.3 not found (ID format may differ)")

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
