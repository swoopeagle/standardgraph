"""Load Italy's Indicazioni nazionali per il curricolo (primo ciclo, DM 9 dicembre 2025 n. 221) for Italian, English/second language, history, geography,
science, technology, music and art into it-miur (maths is the existing it-miur ingest).  One row per learning objective ("Obiettivi specifici di apprendimento")
or expected competence ("Competenze attese") at the end of grade 3 / 5 (primary) and grade 3 of lower secondary (school grade 8).

standard_text = English translation (Claude), cluster = Italian original.  IDs: IT_MIUR25.{SUBJ}.{level}.{class}.{kind}.{n}.
Licence: https://www.mim.gov.it/note-legali (fetched 2026-10-20): "Salvo ove diversamente indicato, i testi pubblicati sul presente sito sono messi a disposizione
con licenza CC-BY 3.0" (+ Legge 633/1941 art. 5, official acts).  Source PDF: https://www.mim.gov.it/documents/20182/10554370/curricolo_web.pdf
Extraction: scripts/italy/parse_curricolo.py + translation -> data/italy_curricolo_2025.json (no network here)."""
import json
import re

from ingestion.international.loader_common import load
from shared.config import PROJECT_ROOT

SYSTEM = "it-miur"
DATA = PROJECT_ROOT / "data" / "italy_curricolo_2025.json"
URL = "https://www.mim.gov.it/documents/20182/10554370/curricolo_web.pdf"
SUBJECTS = ("ela", "world-languages", "social-studies", "science", "cs", "arts")


def main() -> None:
    rows = []
    for r in json.loads(DATA.read_text()):
        slug = re.sub(r"[^A-Z]+", "", r["subject_en"].upper())[:6]
        rows.append({"id": f"IT_MIUR25.{slug}.{r['level'][:3].upper()}.{r['class'][:3].upper()}.{r['kind'][:3].upper()}.{r['seq']}", "subject": r["subject"],
                     "grade": r["grade"], "grade_band": r["band"],
                     "domain": f"{r['subject_en']} ({'primary' if r['level'] == 'primaria' else 'lower secondary'}, {'learning objectives' if r['kind'] == 'objective' else 'expected competences'})"
                               + (f": {r['area_en']}" if r.get("area_en") else ""),
                     "cluster": r["text_it"], "text": r["text_en"], "url": URL})
    load(SYSTEM, SUBJECTS, rows)


if __name__ == "__main__":
    main()
