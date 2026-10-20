"""Extract subject outcomes ("предметные результаты ... к концу обучения в N классе") from the federal working programmes (ФРП) of the Russian Federal Educational Programmes (ФОП).

Source: per-subject files published by ФГБНУ "Институт содержания и методов обучения имени В.С. Леднева" (edsoo.ru), https://static.edsoo.ru/projects/fop/files/{noo,ooo,soo}/<n>.pdf
(text layer; the programmes are annexes approved by Minprosveshcheniya orders No. 370/371/372 of 18.05.2023, published in the gazette http://publication.pravo.gov.ru/document/0001202307140040).
Statute basis: Civil Code Part IV Art. 1259(6)(1) (official documents of state bodies, incl. normative acts, are not objects of copyright) -> STATUTE-ROUTE, pending counsel.

    pdftotext -layout X.pdf X.txt ; python3 scripts/russia/parse_fop.py X.txt <subject> <abbr> > X.json
One row per outcome paragraph (a ';'-terminated bullet) under a grade lead-in and a numbered topic heading."""
import json
import re
import sys

GRADE = re.compile(r"[Кк] концу(?: обучения)?\s+(?:в |во )?(\d{1,2})(?:[\s-]*(?:м|го)?)?\s*класс")
HEAD = re.compile(r"^(\d+(?:\.\d+)+)\.?\s+(.+?)[:.]?$")
STOP = re.compile(r"^(?:\d+(?:\.\d+)*\.?\s+)?(Тематическое планирование|Поурочное планирование|Планируемые результаты освоения|Пояснительная записка|Содержание обучения)", re.I)


def paragraphs(lines):
    buf = []
    for l in lines + [""]:
        s = l.strip()
        if not s or re.fullmatch(r"\d{1,4}", s) or s.startswith("Код ") or re.match(r"^Проверяемые", s):
            if buf:
                yield re.sub(r"\s+", " ", " ".join(buf)).strip(); buf = []
        else:
            buf.append(s)


def parse(lines, subject, abbr):
    rows, grade, topic, on = [], None, "", False
    for p in paragraphs(lines):
        g = GRADE.search(p)
        if g and (p.endswith(":") or "результаты" in p[:160].lower()):
            grade, topic, on = int(g.group(1)), "", True
            m = HEAD.match(p.split(" К концу")[0].split(" к концу")[0]); topic = ""
            continue
        if STOP.match(p):
            on = False; continue
        if not on:
            continue
        m = HEAD.match(p)
        if m and len(p) < 140 and ";" not in p:
            if m.group(1).count(".") <= 1:
                on = False                    # depth-2 heading (e.g. 162.11.) closes the outcomes
            else:
                topic = m.group(2).strip(" .:")
            continue
        if p.endswith(":") and len(p) < 200:
            continue                           # lead-in ("... должны отражать ... умений:")
        if len(p) >= 15 and p[-1] in ";.":
            rows.append({"subject": subject, "abbr": abbr, "grade": str(grade), "topic_ru": topic, "text_ru": p.rstrip(";").strip()})
    return rows


if __name__ == "__main__":
    json.dump(parse(open(sys.argv[1], encoding="utf-8").read().split("\n"), sys.argv[2], sys.argv[3]), sys.stdout, ensure_ascii=False, indent=1)
