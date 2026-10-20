"""Extract Norway LK20 competence aims (kompetansemaal) for grade 1-10 core subjects from the Udir Grep API.

Licence: NLOD (Norwegian Licence for Open Government Data), stated at https://www.udir.no/om-udir/data/ (fetched 2026-10-20):
"Dataene er lagt ut for viderebruk under Norsk lisens for offentlig data (NLOD) ... kopiere og tilgjengeliggjore, endre ...
og a benytte datasettet kommersielt." Attribution required.  API root: https://data.udir.no/kl06/v201906/
Output data/norway_lk20_raw.json: [{plan, subject, trinn, kode, nb, en|None}]; translation of `nb` (where en is None) is a later step.

    uv run python scripts/norway/extract_grep.py
"""
import json
import re
import urllib.request
from pathlib import Path

BASE = "https://data.udir.no/kl06/v201906/"
PLANS = {  # current (publisert) grunnskole plans -> subject
    "MAT01-06": "mathematics", "NAT01-05": "science", "SAF01-05": "social-studies", "NOR01-08": "ela", "ENG01-06": "world-languages",
    "FSP01-04": "world-languages", "KHV01-03": "arts", "MUS01-03": "arts",
}


def get(path):
    return json.load(urllib.request.urlopen(urllib.request.Request(BASE + path, headers={"Accept": "application/json"}), timeout=60))


def title(t, lang):
    return next((x["verdi"] for x in t if x["spraak"] == lang), None)


def nb(t):
    return title(t, "nob") or title(t, "default") or (t[0]["verdi"] if t else None)


def main():
    en = {k["kode"]: title(k["tittel"], "eng") for k in get("kompetansemaal-lk20") if isinstance(k["tittel"], list)}
    out = []
    for plan, subject in PLANS.items():
        lp = get(f"laereplaner-lk20/{plan}")
        name = title(lp["kortform"], "eng") or nb(lp["kortform"])
        for s in lp["kompetansemaal-kapittel"]["kompetansemaalsett"]:
            ks = get(f"kompetansemaalsett-lk20/{s['kode']}")
            t = nb(ks["kortform"])
            m = re.match(r"(\d+)\. trinn", t or "")
            lvl = {"Nivå I": 8, "Nivå II": 9}.get(t)  # foreign-language levels (I from year 8)
            if not m and lvl is None:
                continue
            trinn = int(m.group(1)) if m else lvl
            for km in ks["kompetansemaal"]:
                out.append({"plan": plan, "subject": subject, "area": name, "trinn": trinn, "kode": km["kode"],
                            "nb": km["tittel"], "en": en.get(km["kode"]), "url": km["url-data"]})
    Path(__file__).parents[2].joinpath("data", "norway_lk20_raw.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    from collections import Counter
    print(len(out), Counter((o["plan"], o["en"] is not None) for o in out))


if __name__ == "__main__":
    main()
