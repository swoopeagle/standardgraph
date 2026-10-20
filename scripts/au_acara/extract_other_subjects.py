"""Extract Australian Curriculum v9 content descriptions for subjects not yet in the DB.

Source (CC BY 4.0, ACARA; terms page https://www.australiancurriculum.edu.au/content/acara-curriculum/au/en/copyright-and-terms-of-use.html):
  https://www.australiancurriculum.edu.au/content/dam/en/curriculum/ac-version-9/downloads/curriculum-workbook.xlsx
Output: data/au_acara_v9_other.json (committed; the loader needs no network).

    uv run --with openpyxl python scripts/au_acara/extract_other_subjects.py curriculum-workbook.xlsx
"""
import json
import re
import sys
import warnings
from pathlib import Path

import openpyxl

warnings.simplefilter("ignore")
# workbook Subject -> (our subject, id tag)
KEEP = {
    **{s: ("social-studies", t) for s, t in {
        "HASS F-6": "HASS", "Civics and Citizenship 7-10": "CIV", "Economics and Business 7-10": "ECO",
        "Geography 7-10": "GEO", "History 7-10": "HIS"}.items()},
    "Digital Technologies": ("cs", "DIG"),
    **{s: ("arts", t) for s, t in {"Dance": "DAN", "Drama": "DRA", "Media Arts": "MED", "Music": "MUS", "Visual Arts": "VIS"}.items()},
}
LANGS = ["Arabic", "Auslan", "Chinese", "French", "German", "Hindi", "Indonesian", "Italian", "Japanese", "Korean",
         "Modern Greek", "Spanish", "Turkish", "Vietnamese", "Classical Greek 7-10", "Latin 7-10"]
for l in LANGS:
    KEEP[l] = ("world-languages", re.sub(r"[^A-Z]", "", l.upper())[:6])
# frameworks (Aboriginal / Classical) are design frameworks, not outcome sets: excluded


def grade_of(level: str):
    m = re.match(r"Years? (\d+)(?: and (\d+))?$", level)
    if level == "Foundation Year":
        return "K", None
    if not m:
        return None, None
    return m.group(1), (f"{m.group(1)}-{m.group(2)}" if m.group(2) else None)


def clean(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(s))).strip()


def main(path):
    rows = list(openpyxl.load_workbook(path, read_only=True)["Learning areas"].iter_rows(values_only=True))[1:]
    out, strand, sub = [], "", ""
    for r in rows:
        area, subj, level, _, code, pathway, seq, st, sst, cd = r[:10]
        if subj not in KEEP:
            continue
        if st:
            strand, sub = clean(st), ""
        if sst:
            sub = clean(sst)
        if not cd:
            continue
        g, band = grade_of(level or "")
        if g is None:
            continue
        subject, tag = KEEP[subj]
        dom = " / ".join(x for x in (clean(pathway or ""), strand, sub) if x) or subj
        out.append({"subject": subject, "tag": tag, "learning_area": area, "ac_subject": subj, "code": code,
                    "grade": g, "grade_band": band, "level": level, "domain": f"{subj}: {dom}", "text": clean(cd)})
    Path(__file__).parents[2].joinpath("data", "au_acara_v9_other.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    from collections import Counter
    print(len(out), Counter(o["subject"] for o in out))


if __name__ == "__main__":
    main(sys.argv[1])
