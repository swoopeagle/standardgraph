"""Load Sweden's Lgr22 compulsory-school syllabuses (Skolverket Syllabus API) into se-skolverket: central content bullets, grades 1-9,
mathematics, science (biology/physics/chemistry), technology, Swedish, English and other languages, history/geography/civics/religion, art/music/crafts.

standard_text = English translation (Claude; reviewed result committed), cluster = Swedish original.  IDs: SE_SKOLV.{SUBJ}.{band}.{area}.{n}.
Licence: Skolverket API page https://www.skolverket.se/om-skolverket/oppna-data/api-for-laroplaner-kurs--och-amnesplaner , "Villkor for anvandning":
"Villkoren i Skolverkets kallicens (Creative Commons)", linking https://creativecommons.org/publicdomain/zero/1.0/deed.sv (CC0 1.0). Fetched 2026-10-20.
Extraction: scripts/sweden/extract_skolverket.py + translation -> data/sweden_lgr22.json (no network here)."""
import json

from ingestion.international.loader_common import load
from shared.config import PROJECT_ROOT

SYSTEM = "se-skolverket"
DATA = PROJECT_ROOT / "data" / "sweden_lgr22.json"
SUBJECTS = ("mathematics", "science", "cs", "ela", "world-languages", "social-studies", "arts")


def main() -> None:
    rows, seen = [], {}
    for r in json.loads(DATA.read_text()):
        base = f"SE_SKOLV.{r['abbr']}.{r['band']}.{r['area_no']}.{r['seq']}"
        seen[base] = seen.get(base, 0) + 1  # the same area heading can recur inside one subject; suffix keeps ids unique
        rows.append({"id": base if seen[base] == 1 else f"{base}.{seen[base]}", "subject": r["subject"], "grade": r["grade"],
                     "grade_band": r["band"], "domain": f"{r['subject_en']}: {r['area_en']}", "cluster": r["text_sv"], "text": r["text_en"],
                     "url": f"https://api.skolverket.se/syllabus/v1/subjects/{r['api_code']}?schooltype=GR"})
    load(SYSTEM, SUBJECTS, rows)


if __name__ == "__main__":
    main()
