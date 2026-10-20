"""Extract Curriculum for Excellence social studies experiences & outcomes (SOC) from Education Scotland's single E&O PDF.
(Expressive arts, modern languages and technologies were tried: their columns interleave and do not parse reliably, so they are not ingested.)

Source: https://education.gov.scot/media/wpsnskgv/all-experiencesoutcomes18.pdf (the same file as the held gb-sco science/ELA).
Licence (https://education.gov.scot/terms-of-use/, fetched 2026-10-20): "(c) Crown copyright ... You may use and re-use the information
featured on this website (not including logos) free of charge in any format or medium, under the terms of the Open Government Licence."
Each outcome is a text block followed by its code block ("SOC 2-04a") in the same column; pairing is by column edge and vertical order.
Output: data/scotland_eo_other.json

    uv run --with pymupdf python scripts/scotland/extract_eo.py all-experiencesoutcomes18.pdf
"""
import json
import re
import sys
from pathlib import Path

import fitz

CODE = re.compile(r"^([A-Z]{3,4}) (\d)-(\d\d)([a-z])\s*$")
AREA = {"SOC": ("social-studies", "Social studies")}  # only SOC parses cleanly (EXA/MLAN/TCH columns interleave; dropped, see docs)
PAGES = range(282, 298)  # PDF pages (1-based) of the social studies outcomes tables, before the appendix
LEVEL = {"0": ("K", "Early"), "1": ("2", "First"), "2": ("5", "Second"), "3": ("7", "Third"), "4": ("8", "Fourth")}
TCH_KEEP = ("Digital Literacy", "Computing Science")


COLS = [34, 176, 317, 459, 601]  # left edges of the Early..Fourth columns on the landscape E&O pages
SPLIT = re.compile(r"((?:SOC|EXA|MLAN|TCH|HWB|LIT|MNU|SCN|MTH|RME|RERC|LGL|GAI|ENG|CLAN) \d-\d\d[a-z])")


def main(pdf):
    doc = fitz.open(pdf)
    out, seen = [], set()
    for pn, page in enumerate(doc):
        if pn + 1 not in PAGES:
            continue
        blocks = [b for b in page.get_text("blocks") if b[4].strip()]
        heads = [" ".join(b[4].split()) for b in blocks if 40 < b[1] < 80]
        organiser = re.sub(r" \(continued\)$", "", heads[0]) if heads else ""
        words = [w for w in page.get_text("words") if 100 < w[1] < 545]
        for k, left in enumerate(COLS):
            right = COLS[k + 1] - 2 if k < 4 else 9999
            col = sorted((w for w in words if left - 3 <= w[0] < right), key=lambda w: (round(w[1]), w[0]))
            text = " ".join(w[4] for w in col)
            parts = SPLIT.split(text)
            for i in range(1, len(parts), 2):
                code, body = parts[i], " ".join(parts[i - 1].split())
                body = re.sub(r"^((Early|First|Second|Third|Fourth|a)\s+)+(?=[A-Z])", "", body)  # column-header words leaking into a continued page
                pre = code.split()[0]
                if pre not in AREA or code in seen or len(body) < 15:
                    continue
                if pre == "TCH" and not organiser.startswith(TCH_KEEP):
                    continue
                if int(code.split()[1][0]) != k:
                    continue  # code does not belong to this column: layout anomaly, skip rather than guess
                seen.add(code)
                subject, area = AREA[pre]
                g, band = LEVEL[code.split()[1][0]]
                out.append({"subject": subject, "area": area, "organiser": organiser, "code": code, "grade": g, "level": band,
                            "text": body, "page": pn + 1})
    Path(__file__).parents[2].joinpath("data", "scotland_eo_other.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    from collections import Counter
    print(len(out), Counter(o["subject"] for o in out), Counter(o["code"][:3] for o in out))


if __name__ == "__main__":
    main(sys.argv[1])
