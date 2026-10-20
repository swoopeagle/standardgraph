"""Load Curriculum for Excellence social studies experiences & outcomes (SOC) as extra subject of gb-sco.
IDs follow the held gb-sco pattern: GB_SCO.SOC.{grade}.{code}.1 (Early=K, First=2, Second=5, Third=7, Fourth=8).
Source: https://education.gov.scot/media/wpsnskgv/all-experiencesoutcomes18.pdf ; licence: Open Government Licence via
https://education.gov.scot/terms-of-use/ ("(c) Crown copyright ... under the terms of the Open Government Licence").
Extraction: scripts/scotland/extract_eo.py -> data/scotland_eo_other.json (committed; no network here)."""
import json

from ingestion.international.loader_common import load
from shared.config import PROJECT_ROOT

SYSTEM = "gb-sco"
DATA = PROJECT_ROOT / "data" / "scotland_eo_other.json"
URL = "https://education.gov.scot/media/wpsnskgv/all-experiencesoutcomes18.pdf"


def main() -> None:
    rows = [{"id": f"GB_SCO.SOC.{r['grade']}.{r['code'].replace(' ', '')}.1", "subject": r["subject"], "grade": r["grade"],
             "grade_band": r["level"], "domain": r["organiser"] or "Social studies", "cluster": None, "text": r["text"], "url": URL}
            for r in json.loads(DATA.read_text())]
    load(SYSTEM, ("social-studies",), rows)


if __name__ == "__main__":
    main()
