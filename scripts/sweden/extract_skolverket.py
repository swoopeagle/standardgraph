"""Extract Lgr22 central content (centralt innehåll) from the Skolverket Syllabus API into one row per bullet.

Source: https://api.skolverket.se/syllabus/v1/subjects/{code}?schooltype=GR  (JSON, no key; docs https://www.skolverket.se/om-skolverket/oppna-data/api-for-laroplaner-kurs--och-amnesplaner).
Terms: that docs page, "Villkor för användning": "Villkoren i Skolverkets källicens (Creative Commons)", linked to https://creativecommons.org/publicdomain/zero/1.0/deed.sv (CC0 1.0).

    python3 scripts/sweden/extract_skolverket.py <dir with subj_GRGR*.json> > data/sweden_lgr22_raw.json
Swedish only; the translation step adds text_en / area_en."""
import glob
import html
import json
import re
import sys

SUBJ = {  # API code -> (our subject, English name, short id)
    "GRGRMAT01": ("mathematics", "Mathematics", "MAT"), "GRGRBIO01": ("science", "Biology", "BIO"), "GRGRFYS01": ("science", "Physics", "FYS"),
    "GRGRKEM01": ("science", "Chemistry", "KEM"), "GRGRTEK01": ("cs", "Technology", "TEK"),
    "GRGRSVE01": ("ela", "Swedish", "SVE"), "GRGRSVA01": ("ela", "Swedish as a second language", "SVA"),
    "GRGRENG01": ("world-languages", "English", "ENG"), "GRGRMSP01": ("world-languages", "Modern languages", "MSP"),
    "GRGRMOD01": ("world-languages", "Mother tongue tuition", "MOD"), "GRGRTSP01": ("world-languages", "Swedish Sign Language for the deaf", "TSP"),
    "GRGRHIS01": ("social-studies", "History", "HIS"), "GRGRGEO01": ("social-studies", "Geography", "GEO"),
    "GRGRSAM01": ("social-studies", "Civics", "SAM"), "GRGRREL01": ("social-studies", "Religious studies", "REL"),
    "GRGRBIL01": ("arts", "Visual arts", "BIL"), "GRGRMUS01": ("arts", "Music", "MUS"), "GRGRSLJ01": ("arts", "Crafts", "SLJ"),
}


def parse(d):
    s = d["subject"]; rows = []
    for blk in s["centralContents"]:
        band, area, n = None, "", 0
        for m in re.finditer(r"<h3>(.*?)</h3>|<h4>(.*?)</h4>|<li>(.*?)</li>", blk["text"], flags=re.S):
            clean = lambda x: re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", x or ""))).replace("­", "").strip()
            if m.group(1) is not None:
                g = re.search(r"(\d)\D{1,3}(\d)", clean(m.group(1))); band = (g.group(1), f"{g.group(1)}-{g.group(2)}") if g else ("1", "1-9"); area, n = "", 0
            elif m.group(2) is not None:
                area, n = clean(m.group(2)), 0
            elif band:
                n += 1; rows.append({"band": band[1], "grade": band[0], "area_sv": area, "seq": n, "text_sv": clean(m.group(3))})
    return rows


if __name__ == "__main__":
    out, seen = [], {}
    for code, (subj, name, abbr) in SUBJ.items():
        f = glob.glob(f"{sys.argv[1]}/subj_{code}.json")
        if not f:
            continue
        for r in parse(json.load(open(f[0]))):
            k = (abbr, r["band"], r["area_sv"]); seen.setdefault(k, len(seen) + 1)
            out.append({"subject": subj, "subject_en": name, "abbr": abbr, "api_code": code, **r, "area_no": seen[k]})
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
