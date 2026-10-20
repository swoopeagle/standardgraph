"""Parse the objectives (five skill areas) of MEXT's official English translation of the Courses of Study for English:
elementary foreign language activities (grades 3-4), elementary English (5-6), lower secondary (7-9), upper secondary English (10-12).
One row per skill clause (a./b./c.) under "(N) Listening / Reading / Speaking [Interaction] / Speaking [Production] / Writing".

    pdftotext -layout X.pdf X.txt ; python3 scripts/japan/parse_mext_lang.py <el_fla|el_fl|ls_fl|hs_en> X.txt > X.json
Source/terms: see scripts/japan/parse_mext_science.py (MEXT terms https://www.mext.go.jp/b_menu/1351168.htm)."""
import json
import re
import sys

GRADE = {"el_fla": ("3", "3-4"), "el_fl": ("5", "5-6"), "ls_fl": ("7", "7-9"), "hs_en": ("10", "10-12")}
HDR = re.compile(r"^(小学校|中学校|高等学校)学習指導要領|^\s*\d+\s*$|^\s*$|^\s*[１-９]\s*$")


def parse(kind, lines):
    g, band = GRADE[kind]; rows, course, skill, mode, cur = [], "English", "", False, None

    def flush():
        nonlocal cur
        if cur:
            cur["text_en"] = re.sub(r"\s+", " ", cur["text_en"]).strip(); rows.append(cur)
        cur = None

    for l in lines:
        if HDR.match(l):
            continue
        s = l.strip()
        m = re.match(r"^[IVX]+\.\s+([A-Z][A-Z &/,\-]+(?: [IVX]+)?)$", s)
        if m and kind == "hs_en":
            flush(); course = m.group(1).title().replace(" I", " I"); mode = False; continue
        if re.match(r"^1\.\s+Objectives", s):
            flush(); mode = True; skill = ""; continue
        if re.match(r"^2\.\s+Contents?", s):
            flush(); mode = False; continue
        if not mode:
            continue
        m = re.match(r"^\((\d)\)\s+(Listening|Reading|Speaking \[Interaction\]|Speaking \[Production\]|Writing)$", s)
        if m:
            flush(); skill = m.group(2); continue
        m = re.match(r"^([a-d])\.\s+(.*)$", s)
        if m and skill:
            flush(); cur = {"grade": g, "band": band, "course": course, "skill": skill, "code": f"{skill.split()[0][:4]}{m.group(1)}".lower(), "text_en": m.group(2)}; continue
        if cur and not re.match(r"^\(\d\)", s):
            cur["text_en"] += " " + s
    flush()
    return rows


if __name__ == "__main__":
    json.dump(parse(sys.argv[1], open(sys.argv[2], encoding="utf-8").read().split("\n")), sys.stdout, ensure_ascii=False, indent=1)
