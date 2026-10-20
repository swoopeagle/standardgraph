"""Load France MEN mathematics programmes (cycles 2-4, CP to 3e = grades 1-9) into the DB.

System: fr-men.  IDs: FR_MEN.MATH.{grade}.{seq:03d}.  standard_text = English translation,
cluster = French original (same convention as br-bncc / mx-sep-2017).

Sources (Bulletin officiel annexes, arretes of the Ministere de l'Education nationale; all fetched 2026-10-19):
  Cycle 2 (CP-CE2, 2024 programme):  https://www.education.gouv.fr/sites/default/files/document/Annexe%204%20%E2%80%93%20Programme%20de%20math%C3%A9matiques%20du%20cycle%202-403821.pdf
  Cycle 3 (CM1-6e, 2025 programme):  https://www.education.gouv.fr/sites/default/files/ensel620_annexe2-v2.pdf
  Cycle 4 (5e-3e, 2020 programme):   https://www.education.gouv.fr/sites/default/files/document/Annexe%202%20%E2%80%93%20Programme%20de%20math%C3%A9matiques%20pour%20le%20cycle%204-480716.pdf
Licence: Etalab Open Licence 2.0 (eduscol legal notice), attribution "Ministere de l'Education nationale".
Not covered: lycee (seconde / specialite maths); education.gouv.fr blocked automated access to those annexes.

Extraction is deterministic: scripts/france/parse_programmes.py (each "Objectifs d'apprentissage" item = one standard),
translation by Claude; the reviewed result is committed in data/france_math_programmes.json, so this loader needs no network.
"""
import json
import sqlite3
from datetime import date
from pathlib import Path

from shared.config import DB_PATH, PROJECT_ROOT

SYSTEM = "fr-men"
DATA = PROJECT_ROOT / "data" / "france_math_programmes.json"
SOURCE_URL = {
    "C2": "https://www.education.gouv.fr/sites/default/files/document/Annexe%204%20%E2%80%93%20Programme%20de%20math%C3%A9matiques%20du%20cycle%202-403821.pdf",
    "C3": "https://www.education.gouv.fr/sites/default/files/ensel620_annexe2-v2.pdf",
    "C4": "https://www.education.gouv.fr/sites/default/files/document/Annexe%202%20%E2%80%93%20Programme%20de%20math%C3%A9matiques%20pour%20le%20cycle%204-480716.pdf",
}
DOMAIN = {
    "Nombres, calcul et résolution de problèmes": "Numbers, calculation and problem solving",
    "Nombres et calculs": "Numbers and calculations",
    "Grandeurs et mesures": "Quantities and measurement",
    "Espace et géométrie": "Space and geometry",
    "Organisation et gestion de données": "Data handling and probability",
    "Organisation et gestion de données et probabilités": "Data handling and probability",
    "Proportionnalité, fonctions": "Proportionality and functions",
    "La pensée informatique": "Computational thinking",
}
STOP = {"that", "with", "this", "from", "their", "which", "using", "each", "such", "into", "more", "other", "these",
        "those", "about", "given", "find", "know", "numbers", "number", "problems", "solve", "use", "using"}


def keywords(text: str) -> set[str]:
    return {w for w in (t.strip(".,;:()'\"").lower() for t in text.split()) if len(w) > 4 and w.isalpha() and w not in STOP}


def main() -> None:
    rows = json.loads(DATA.read_text())
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    today, seq = date.today().isoformat(), {}
    with conn:
        conn.execute("DELETE FROM standards WHERE system = ?", (SYSTEM,))  # idempotent re-run (keywords cascade)
        for r in rows:
            seq[r["grade"]] = seq.get(r["grade"], 0) + 1
            sid = f"FR_MEN.MATH.{r['grade']}.{seq[r['grade']]:03d}"
            conn.execute(
                """INSERT INTO standards (id, system, subject, grade, grade_band, domain, cluster, standard_text,
                                          last_verified_date, source_url) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (sid, SYSTEM, "mathematics", r["grade"], None, DOMAIN[r["theme"]], r["text_fr"], r["text_en"],
                 today, SOURCE_URL[r["level"]]),
            )
            conn.executemany("INSERT OR IGNORE INTO keywords (standard_id, keyword) VALUES (?,?)",
                             [(sid, k) for k in keywords(r["text_en"])])
    n = conn.execute("SELECT COUNT(*) FROM standards WHERE system=?", (SYSTEM,)).fetchone()[0]
    print(f"{SYSTEM}: {n} standards")


if __name__ == "__main__":
    main()
