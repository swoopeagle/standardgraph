"""Assemble data/china_compulsory_2022.json from per-subject parsed + translated JSON (scratch dir produced by parse_cn.py + translate_batches.py).

    python3 scripts/china/assemble.py <scratch dir with cn_<key>_merged.json> <headings_en.json> > data/china_compulsory_2022.json
Row = {subject, abbr, name_en, grade, band, area_zh/topic_zh/subtopic_zh, area_en/..., code, page, text_zh, text_en}. text_zh is the OCR text (Apple Vision, zh-Hans; CER ~2-3% on a
hand-checked sample, see docs/world-coverage-scan-3.md); formula-heavy items are the weak spot."""
import json
import re
import sys

CFG = [  # key, subject, abbr, English name
    ("math", "mathematics", "MATH", "Mathematics"), ("science", "science", "SCI", "Science (grades 1-9)"), ("physics", "science", "PHYS", "Physics"),
    ("chem", "science", "CHEM", "Chemistry"), ("bio", "science", "BIOL", "Biology"), ("chinese", "ela", "CHIN", "Chinese Language"),
    ("history", "social-studies", "HIST", "History"), ("geog", "social-studies", "GEOG", "Geography"), ("infotech", "cs", "INFO", "Information Technology"),
    ("art", "arts", "ARTS", "Arts"), ("english", "world-languages", "ENGL", "English"),
]


def main(d, heads):
    he = json.load(open(heads)); out = []
    for key, subj, abbr, name in CFG:
        n = 0
        for r in json.load(open(f"{d}/cn_{key}_merged.json")):
            t = r["text_zh"].strip()
            if len(t) < 8 or re.fullmatch(r"[\d.\s]*\S{0,12}", t):  # blank / bare heading rows the grammar could not attach
                continue
            n += 1
            out.append({"subject": subj, "abbr": abbr, "name_en": name, "grade": r["grade"], "band": r["band"], "seq": n, "code": r["code"], "page": r["page"],
                        "area_zh": r["area"], "topic_zh": r["topic"], "subtopic_zh": r["subtopic"],
                        "area_en": he.get(r["area"], r["area"]), "topic_en": he.get(r["topic"], r["topic"]) if r["topic"] else "",
                        "subtopic_en": he.get(r["subtopic"], r["subtopic"]) if r["subtopic"] else "",
                        "stage_inferred": bool(r.get("stage_inferred")), "text_zh": t, "text_en": r["text_en"]})
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
