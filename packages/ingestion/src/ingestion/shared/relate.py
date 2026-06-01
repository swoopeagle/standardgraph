"""Stage 4: Build standard_relationships from grade progression and cluster groupings."""
import sqlite3

from shared.config import DB_PATH

GRADE_ORDER = ["K", "1", "2", "3", "4", "5", "6", "7", "8", "HS"]


def grade_key(g: str) -> int:
    try:
        return GRADE_ORDER.index(g)
    except ValueError:
        return 99


def build_relationships() -> None:
    conn = sqlite3.connect(DB_PATH)
    standards = conn.execute(
        "SELECT id, grade, domain_code, cluster_letter FROM standards"
    ).fetchall()
    print(f"  Processing {len(standards)} standards...")

    by_cluster: dict[tuple, list[tuple]] = {}
    by_domain: dict[str, list[tuple]] = {}

    for std_id, grade, domain_code, cluster_letter in standards:
        cluster_key = (domain_code, cluster_letter)
        by_cluster.setdefault(cluster_key, []).append((grade, std_id))
        by_domain.setdefault(domain_code, []).append((grade, std_id))

    relationships: list[tuple] = []
    seen: set[tuple] = set()

    def add(from_id: str, to_id: str, rel_type: str, weight: float = 1.0) -> None:
        key = (from_id, to_id, rel_type)
        if key not in seen:
            seen.add(key)
            relationships.append((from_id, to_id, rel_type, weight))

    # Within-cluster: all standards in the same cluster are "related"
    for entries in by_cluster.values():
        if len(entries) < 2:
            continue
        for i, (_, id1) in enumerate(entries):
            for j, (_, id2) in enumerate(entries):
                if i != j:
                    add(id1, id2, "related", 0.8)

    # Cross-grade: standards in the same domain, adjacent grades, build_on each other
    for domain_code, entries in by_domain.items():
        grade_map: dict[str, list[str]] = {}
        for grade, std_id in entries:
            grade_map.setdefault(grade, []).append(std_id)

        grades = sorted(grade_map.keys(), key=grade_key)
        for i in range(len(grades) - 1):
            g1, g2 = grades[i], grades[i + 1]
            if grade_key(g2) - grade_key(g1) <= 2:
                for id1 in grade_map[g1]:
                    for id2 in grade_map[g2]:
                        add(id1, id2, "builds_on", 0.7)

    with conn:
        conn.execute("DELETE FROM standard_relationships")
        conn.executemany(
            "INSERT INTO standard_relationships (from_id, to_id, relationship_type, weight) VALUES (?,?,?,?)",
            relationships,
        )

    count = conn.execute("SELECT COUNT(*) FROM standard_relationships").fetchone()[0]
    conn.close()
    print(f"  Inserted {count} relationships")


def main() -> None:
    print("Stage 4: Building standard relationships...")
    build_relationships()
    print("Done.")


if __name__ == "__main__":
    main()
