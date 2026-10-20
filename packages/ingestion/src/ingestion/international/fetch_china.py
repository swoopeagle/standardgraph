"""READY, PENDING COUNSEL: do not run against a release DB until the statute-route question in docs/world-coverage-scan-3.md is answered.
(One command once cleared:  DB_PATH=<copy> uv run python -m ingestion.international.fetch_china )

China, compulsory-education curriculum standards 2022 edition (grades 1-9): mathematics, science (+physics/chemistry/biology), Chinese language, history, geography,
information technology, arts, English.  System cn-moe.  standard_text = English translation (Claude), cluster = Chinese original (OCR text).
Source: Ministry of Education notice 教材〔2022〕2号 https://www.moe.gov.cn/srcsite/A26/s8001/202204/t20220420_619921.html (standards attached as image-only PDFs; OCR with
scripts/china/vision_ocr.swift; parse scripts/china/parse_cn.py; assemble scripts/china/assemble.py -> data/china_compulsory_2022.json).
Licence basis: ONLY the Copyright Law (2020) Art. 5 exclusion of "具有立法、行政、司法性质的文件" (documents of a legislative, administrative or judicial nature);
the MOE site statement (网站声明) also forbids commercial verbatim reprint of site content.  Untested for curriculum standards -> counsel."""
import json

from ingestion.international.loader_common import load
from shared.config import PROJECT_ROOT

SYSTEM = "cn-moe"
DATA = PROJECT_ROOT / "data" / "china_compulsory_2022.json"
URL = "https://www.moe.gov.cn/srcsite/A26/s8001/202204/t20220420_619921.html"
SUBJECTS = ("mathematics", "science", "ela", "social-studies", "cs", "arts", "world-languages")


def main() -> None:
    rows = []
    for r in json.loads(DATA.read_text()):
        dom = f"{r['name_en']}: {r['area_en']}" + (f" / {r['topic_en']}" if r["topic_en"] else "") + (f" / {r['subtopic_en']}" if r["subtopic_en"] else "")
        rows.append({"id": f"CN_MOE.{r['abbr']}.{r['grade']}.{r['seq']:03d}", "subject": r["subject"], "grade": r["grade"], "grade_band": r["band"],
                     "domain": dom, "cluster": r["text_zh"], "text": r["text_en"], "url": URL})
    load(SYSTEM, SUBJECTS, rows)


if __name__ == "__main__":
    main()
