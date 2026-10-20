"""Parse MEXT's official English (tentative) translation of the Courses of Study: science, elementary + lower secondary.

Sources (MEXT, fetched 2026-10-20), PDFs linked from https://www.mext.go.jp/a_menu/shotou/new-cs/1384661.htm:
  elementary  https://www.mext.go.jp/content/20230120-mxt_kyoiku02-100002604_05.pdf  (see data file for the exact URLs)
Terms: https://www.mext.go.jp/b_menu/1351168.htm (CC BY 4.0-compatible, commercial use allowed). No translation step: the text is MEXT's English.

    pdftotext -layout el_science.pdf el.txt ; pdftotext -layout ls_science.pdf ls.txt
    python3 scripts/japan/parse_mext_science.py el el.txt > el.json ; python3 scripts/japan/parse_mext_science.py ls ls.txt > ls.json

elementary (el): one row per knowledge sub-item "(a)/(b)/(c)" under "a." and one row per "b." (abilities) clause, per grade 3-6, area A-D, topic (N).
lower secondary (ls): one row per leaf "i./ii./..." (title + description) and per "(b)" integrative clause, per field and topic (N)."""
import json
import re
import sys

HDR = re.compile(r"^(小学校|中学校)学習指導要領|^\s*\d+\s*$|^\s*$")
ROMAN = r"(?:i{1,3}|iv|v|vi{0,3}|ix|x)"


def rows_el(lines):
    rows, grade, area, topic, mode, clause, cur = [], "", "", "", False, "", None

    def flush():
        nonlocal cur
        if cur:
            rows.append({**cur, "text_en": re.sub(r"\s+", " ", cur["text_en"]).strip()}); cur = None

    for l in lines:
        if HDR.match(l):
            continue
        s = l.strip()
        m = re.match(r"^\[Grade (\d)\]", s)
        if m:
            flush(); grade, mode = m.group(1), False; continue
        if re.match(r"^2\. Content", s):
            flush(); mode = True; continue
        if re.match(r"^3\. ", s) or re.match(r"^1\. Objectives", s):
            flush(); mode = False; continue
        if not mode:
            continue
        m = re.match(r"^([A-D])\. (.+)$", s)
        if m and len(m.group(2)) < 60:
            flush(); area = f"{m.group(1)}. {m.group(2)}"; continue
        m = re.match(r"^\((\d+)\) (.+)$", s)
        if m and len(l) - len(l.lstrip()) <= 6 and len(m.group(2)) < 90:
            flush(); topic = f"({m.group(1)}) {m.group(2)}"; clause = ""; continue
        m = re.match(r"^([ab])\. (.+)$", s)
        if m:
            flush(); clause = m.group(1)
            if clause == "b":
                cur = {"grade": grade, "area": area, "topic": topic, "code": f"{topic[:3]}b".replace(" ", ""), "text_en": m.group(2)}
            continue
        m = re.match(r"^\(([a-z])\)\s*(.+)$", s)
        if m and clause == "a":
            flush(); cur = {"grade": grade, "area": area, "topic": topic, "code": f"{topic[:3]}a{m.group(1)}".replace(" ", ""), "text_en": m.group(2)}; continue
        if cur:
            cur["text_en"] += " " + s
    flush()
    return rows


def rows_ls(lines):
    rows, field, topic, group, mode, cur = [], "", "", "", False, None

    def flush():
        nonlocal cur
        if cur:
            rows.append({**cur, "text_en": re.sub(r"\s+", " ", cur["text_en"]).strip()}); cur = None

    for l in lines:
        if HDR.match(l):
            continue
        s = l.strip()
        m = re.match(r"^\[Field (One|Two) \((.+)\)\]", s)
        if m:
            flush(); field = f"Field {m.group(1)} ({m.group(2)})"; mode = False; continue
        if re.match(r"^2\. Contents", s):
            flush(); mode = True; continue
        if re.match(r"^3\. ", s) or re.match(r"^1\. Objectives", s):
            flush(); mode = False; continue
        if not mode:
            continue
        m = re.match(r"^\((\d+)\) (.+)$", s)
        if m and len(l) - len(l.lstrip()) <= 6 and len(m.group(2)) < 80:
            flush(); topic = f"({m.group(1)}) {m.group(2)}"; group = ""; continue
        m = re.match(r"^([a-h])\. (.+)$", s)
        if m and len(m.group(2)) < 80:
            flush(); group = f"{m.group(1)}. {m.group(2)}"; continue
        m = re.match(rf"^({ROMAN})\. (.+)$", s)
        if m:
            flush(); cur = {"grade": "7", "field": field, "area": field, "topic": topic, "group": group, "code": f"{topic[:3]}{group[:1]}{m.group(1)}".replace(" ", ""),
                            "text_en": f"{m.group(2)}: "}; continue
        m = re.match(r"^\(b\)\s*(.+)$", s)
        if m:
            flush(); cur = {"grade": "7", "field": field, "area": field, "topic": topic, "group": "", "code": f"{topic[:3]}b".replace(" ", ""), "text_en": m.group(1)}; continue
        if re.match(r"^\([a-z]\)", s):
            flush(); continue
        if cur:
            cur["text_en"] += " " + s
    flush()
    return rows


if __name__ == "__main__":
    lines = open(sys.argv[2], encoding="utf-8").read().split("\n")
    json.dump((rows_el if sys.argv[1] == "el" else rows_ls)(lines), sys.stdout, ensure_ascii=False, indent=1)
