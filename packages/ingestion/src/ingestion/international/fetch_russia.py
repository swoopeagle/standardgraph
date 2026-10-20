"""READY, PENDING COUNSEL: do not run against a release DB until the statute-route question in docs/world-coverage-scan-3.md is answered.
(One command once cleared:  DB_PATH=<copy> uv run python -m ingestion.international.fetch_russia )

Russia, federal working programmes (ФРП) of the federal educational programmes (ФОП НОО/ООО/СОО): subject outcomes by grade for mathematics, the world around us, physics,
chemistry, biology, informatics, geography, Russian language, literature.  System ru-fop.  standard_text = English translation (Claude), cluster = Russian original.
Source: per-subject files from ФГБНУ ИСМО (edsoo.ru, https://static.edsoo.ru/projects/fop/files/{noo,ooo,soo}/<n>.pdf), the programmes being annexes approved by Minprosveshcheniya orders
No. 370/371/372 of 18.05.2023 (gazette: http://publication.pravo.gov.ru/document/0001202307140040).  Licence basis: Civil Code Art. 1259(6)(1) only; edsoo.ru footer says
"Все права защищены".  Extraction: scripts/russia/parse_fop.py -> data/russia_fop_2023.json."""
import json

from ingestion.international.loader_common import load
from shared.config import PROJECT_ROOT

SYSTEM = "ru-fop"
DATA = PROJECT_ROOT / "data" / "russia_fop_2023.json"
URL = "http://publication.pravo.gov.ru/document/0001202307140040"
SUBJECTS = ("mathematics", "science", "ela", "social-studies", "cs")


def main() -> None:
    rows = [{"id": f"RU_FOP.{r['file'].upper()}.{r['grade']}.{r['seq']:03d}", "subject": r["subject"], "grade": r["grade"], "grade_band": None,
             "domain": r["name_en"] + (f": {r['topic_ru']}" if r["topic_ru"] else ""), "cluster": r["text_ru"], "text": r["text_en"], "url": URL}
            for r in json.loads(DATA.read_text())]
    load(SYSTEM, SUBJECTS, rows)


if __name__ == "__main__":
    main()
