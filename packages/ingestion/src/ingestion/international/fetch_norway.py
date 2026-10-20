"""Load Norway LK20 competence aims (Kunnskapsloftet 2020, year 1-10 core subjects) into the DB.

System: no-udir.  IDs: NO_UDIR.{KM code}.  standard_text = Udir's official English text (all 444 aims below carry one);
cluster = Norwegian (bokmal) original.
Source: Utdanningsdirektoratet Grep API https://data.udir.no/kl06/v201906/ ; licence NLOD (Norsk lisens for offentlig data),
stated at https://www.udir.no/om-udir/data/ (fetched 2026-10-20); attribution "Utdanningsdirektoratet".
Extraction: scripts/norway/extract_grep.py -> data/norway_lk20_raw.json (committed; no network here).
"""
import json

from ingestion.international.loader_common import load
from shared.config import PROJECT_ROOT

SYSTEM = "no-udir"
DATA = PROJECT_ROOT / "data" / "norway_lk20_raw.json"
SUBJECTS = ("mathematics", "science", "social-studies", "ela", "world-languages", "arts")


def main() -> None:
    raw = json.loads(DATA.read_text())
    levels = {}
    for r in raw:
        levels.setdefault(r["plan"], set()).add(r["trinn"])
    rows = []
    for r in raw:
        ls = sorted(levels[r["plan"]]); i = ls.index(r["trinn"]); lo = ls[i - 1] + 1 if i and r["plan"] != "FSP01-04" else r["trinn"]
        rows.append({"id": f"NO_UDIR.{r['kode']}", "subject": r["subject"], "grade": str(r["trinn"]),
                     "grade_band": f"{lo}-{r['trinn']}" if lo < r["trinn"] else None, "domain": r["area"], "cluster": r["nb"],
                     "text": r["en"], "url": r["url"]})
    load(SYSTEM, SUBJECTS, rows)


if __name__ == "__main__":
    main()
