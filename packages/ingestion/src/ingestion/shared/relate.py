"""Stage 4: Build standard_relationships from grade progression within each domain."""
import sqlite3

from shared.config import DB_PATH

GRADE_ORDER = ["K", "1", "2", "3", "4", "5", "6", "7", "8", "HS"]


def grade_key(g: str) -> int:
    try:
        return GRADE_ORDER.index(g)
    except ValueError:
        return 99


def main() -> None:
    print("Stage 4: Building standard relationships...")
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")

    rows = conn.execute(
        "SELECT id, grade, domain, system FROM standards ORDER BY domain, grade"
    ).fetchall()
    print(f"  Processing {len(rows)} standards...")

    # Group by (system, domain)
    by_domain: dict[tuple, list[tuple]] = {}
    for std_id, grade, domain, system in rows:
        key = (system, domain)
        by_domain.setdefault(key, []).append((grade, std_id))

    relationships: list[tuple] = []
    seen: set[tuple] = set()

    def add(src: str, tgt: str, rel: str, system: str) -> None:
        key = (src, tgt, rel)
        if key not in seen:
            seen.add(key)
            relationships.append((src, tgt, rel, system))

    for (system, domain), entries in by_domain.items():
        # Sort by grade within each domain
        grade_map: dict[str, list[str]] = {}
        for grade, std_id in entries:
            grade_map.setdefault(grade, []).append(std_id)

        grades = sorted(grade_map.keys(), key=grade_key)

        for i in range(len(grades) - 1):
            g1, g2 = grades[i], grades[i + 1]
            # Only link adjacent or near-adjacent grades (gap ≤ 2)
            if grade_key(g2) - grade_key(g1) > 2:
                continue
            for id1 in grade_map[g1]:
                for id2 in grade_map[g2]:
                    add(id1, id2, "successor",    system)
                    add(id2, id1, "prerequisite", system)

    with conn:
        conn.execute("DELETE FROM standard_relationships")
        conn.executemany(
            """INSERT OR IGNORE INTO standard_relationships
               (source_id, target_id, relationship, system)
               VALUES (?,?,?,?)""",
            relationships,
        )

    count = conn.execute("SELECT COUNT(*) FROM standard_relationships").fetchone()[0]
    conn.close()
    print(f"  Inserted {count} relationships")
    print("Done.")


if __name__ == "__main__":
    main()
