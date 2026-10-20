"""Load Japan's Courses of Study (MEXT) for science (elementary + lower secondary) and English (foreign language activities, elementary,
lower secondary, upper secondary objectives) into jp-mext, from MEXT's own English translation (labelled tentative translation, 仮訳).

standard_text = MEXT English; cluster = the pdf/section the row came from (no translation step here).
IDs: JP_MEXT.{SCI|ENG}.{level}.{code}.  Licence: https://www.mext.go.jp/b_menu/1351168.htm (fetched 2026-10-20): "どなたでも以下の1）～6）に従って、
複製、公衆送信、翻訳・変形等の翻案等、自由に利用できます。商用利用も可能です。" and "本利用ルールは、クリエイティブ・コモンズ・ライセンスの表示4.0国際（…CC BY）と
互換性があり…"; also Copyright Act Art. 13 (notices of state organs).  Conditions: credit MEXT, mark edits, do not imply government authorship.
Extraction: scripts/japan/parse_mext_science.py, parse_mext_lang.py -> data/japan_mext_other.json."""
import json
import re

from ingestion.international.loader_common import load
from shared.config import PROJECT_ROOT

SYSTEM = "jp-mext"
DATA = PROJECT_ROOT / "data" / "japan_mext_other.json"
INDEX = "https://www.mext.go.jp/a_menu/shotou/new-cs/1384661.htm"
SUBJECTS = ("science", "world-languages")


def main() -> None:
    rows, seen = [], {}
    for r in json.loads(DATA.read_text()):
        lvl = {"elementary": "EL", "lower-secondary": "LS"}.get(r["level"], re.sub(r"[^A-Z]+", "", r["level"].upper())[:6])
        base = f"JP_MEXT.{'SCI' if r['subject'] == 'science' else 'ENG'}.{lvl}.{r['grade']}.{r['code']}"
        if r["subject"] != "science":
            base += "." + re.sub(r"[^A-Za-z0-9]+", "", r["area"])[:12]
        seen[base] = seen.get(base, 0) + 1
        rows.append({"id": base if seen[base] == 1 else f"{base}.{seen[base]}", "subject": r["subject"], "grade": r["grade"], "grade_band": r["band"],
                     "domain": f"{r['subject_en']} ({r['level']}): {r['area']}" + (f", {r['topic']}" if r["topic"] else ""),
                     "cluster": f"MEXT English translation (tentative): {r['src']}", "text": r["text_en"], "url": INDEX})
    load(SYSTEM, SUBJECTS, rows)


if __name__ == "__main__":
    main()
