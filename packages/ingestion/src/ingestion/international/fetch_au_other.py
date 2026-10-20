"""Load Australian Curriculum v9 humanities/social sciences, digital technologies, arts and languages into the DB.

System: au-acara (adds subjects social-studies, cs, arts, world-languages beside the existing math/ELA/science).
IDs: AU_ACARA.{AC9 code}.  Source: ACARA curriculum workbook (CC BY 4.0; attribution "(c) ACARA"):
  https://www.australiancurriculum.edu.au/content/dam/en/curriculum/ac-version-9/downloads/curriculum-workbook.xlsx
Licence page (fetched 2026-10-20): https://www.australiancurriculum.edu.au/content/acara-curriculum/au/en/copyright-and-terms-of-use.html
  "copyright material available on this website is licensed under a Creative Commons Attribution 4.0 International (CC BY) licence"
Extraction is deterministic: scripts/au_acara/extract_other_subjects.py -> data/au_acara_v9_other.json (committed, no network here).
Excluded: Aboriginal/Classical language frameworks, HPE, Design and Technologies (no subject bucket).
"""
import json

from ingestion.international.loader_common import load
from shared.config import PROJECT_ROOT

SYSTEM = "au-acara"
DATA = PROJECT_ROOT / "data" / "au_acara_v9_other.json"
URL = "https://www.australiancurriculum.edu.au/content/dam/en/curriculum/ac-version-9/downloads/curriculum-workbook.xlsx"
SUBJECTS = ("social-studies", "cs", "arts", "world-languages")


def main() -> None:
    rows = [{"id": f"AU_ACARA.{r['code']}", "subject": r["subject"], "grade": r["grade"], "grade_band": r["grade_band"],
             "domain": r["domain"], "cluster": r["learning_area"], "text": r["text"], "url": URL}
            for r in json.loads(DATA.read_text())]
    load(SYSTEM, SUBJECTS, rows)


if __name__ == "__main__":
    main()
