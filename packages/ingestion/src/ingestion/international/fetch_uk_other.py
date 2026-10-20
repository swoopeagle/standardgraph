"""Load England National Curriculum programmes of study (computing, history, geography, citizenship, art and design,
music, languages) into the DB as extra subjects of uk-nc.  IDs: UK_NC.{SUBJ}.{ks}.{seq}.
Licence: Open Government Licence v3.0 (gov.uk national-curriculum collection; attribution "Crown copyright, Department for Education").
Extraction: scripts/uk_nc/extract_other_subjects.py -> data/uk_nc_other.json (committed; no network here).
"""
import json

from ingestion.international.loader_common import load
from shared.config import PROJECT_ROOT

SYSTEM = "uk-nc"
DATA = PROJECT_ROOT / "data" / "uk_nc_other.json"
SUBJECTS = ("social-studies", "cs", "arts", "world-languages")
TAG = {"Computing": "COMP", "History": "HIST", "Geography": "GEOG", "Citizenship": "CIT", "Art and design": "ART",
       "Music": "MUS", "Languages": "LANG"}


def main() -> None:
    seq, rows = {}, []
    for r in json.loads(DATA.read_text()):
        k = (r["label"], r["ks"]); seq[k] = seq.get(k, 0) + 1
        rows.append({"id": f"UK_NC.{TAG[r['label']]}.KS{r['ks']}.{seq[k]:02d}", "subject": r["subject"], "grade": r["grade"],
                     "grade_band": r["grade_band"], "domain": r["domain"], "cluster": None, "text": r["text"], "url": r["url"]})
    load(SYSTEM, SUBJECTS, rows)


if __name__ == "__main__":
    main()
