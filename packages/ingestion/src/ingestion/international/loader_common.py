"""Shared loader for committed-JSON systems: idempotent per (system, subjects) replace + keywords."""
import sqlite3
from datetime import date

from shared.config import DB_PATH

STOP = {"that", "with", "this", "from", "their", "which", "using", "each", "such", "into", "more", "other", "these", "those", "about"}


def keywords(text: str) -> set[str]:
    return {w for w in (t.strip(".,;:()'\"").lower() for t in text.split()) if len(w) > 4 and w.isalpha() and w not in STOP}


def load(system: str, subjects: tuple, rows: list[dict]) -> None:
    """rows: dicts with id, subject, grade, grade_band, domain, cluster, text, url."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    today = date.today().isoformat()
    with conn:
        conn.execute(f"DELETE FROM standards WHERE system = ? AND subject IN ({','.join('?' * len(subjects))})", (system, *subjects))
        for r in rows:
            conn.execute(
                """INSERT INTO standards (id, system, subject, grade, grade_band, domain, cluster, standard_text,
                                          last_verified_date, source_url) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (r["id"], system, r["subject"], r["grade"], r["grade_band"], r["domain"], r["cluster"], r["text"], today, r["url"]))
            conn.executemany("INSERT OR IGNORE INTO keywords (standard_id, keyword) VALUES (?,?)", [(r["id"], k) for k in keywords(r["text"])])
    for s in subjects:
        n = conn.execute("SELECT COUNT(*) FROM standards WHERE system=? AND subject=?", (system, s)).fetchone()[0]
        print(f"{system}/{s}: {n}")
