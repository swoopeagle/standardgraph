"""Load Spain's state minimum curriculum (LOMLOE: RD 157/2022, 217/2022, 243/2022) for science, Spanish language and literature,
social studies, digital technology, arts and languages into es-lomloe (the held es-lomloe maths is separate).

One standard = one 'criterio de evaluacion'. standard_text = English translation (Claude; the reviewed result is committed),
cluster = Spanish original.  IDs: ES_LOMLOE.{PRI|ESO|BAC}.{SUBJECT-SLUG}.{grade}.{criterion}[.n].
Licence: BOE reuse conditions (https://www.boe.es/informacion/aviso_legal/index.php, condition 3, fetched 2026-10-20):
reuse for commercial and non-commercial purposes incl. copy, distribution, adaptation; attribution "Fuente de los datos:
Agencia Estatal Boletin Oficial del Estado"; the meaning of the information must not be distorted (translation is labelled).
Extraction: scripts/spain/parse_boe.py + build_rows.py -> data/spain_lomloe_other.json (no network here).
"""
import json
import re

from ingestion.international.loader_common import load
from shared.config import PROJECT_ROOT

SYSTEM = "es-lomloe"
DATA = PROJECT_ROOT / "data" / "spain_lomloe_other.json"
BOE = {"PRI": "BOE-A-2022-3296", "ESO": "BOE-A-2022-4975", "BAC": "BOE-A-2022-5521"}
SUBJECTS = ("science", "ela", "social-studies", "cs", "arts", "world-languages")


def main() -> None:
    seen, rows = {}, []
    for r in json.loads(DATA.read_text()):
        slug = re.sub(r"[^A-Z0-9]+", "-", r["materia_en"].upper()).strip("-")[:28]
        base = f"ES_LOMLOE.{r['etapa']}.{slug}.{r['grade']}.{r['code']}"
        seen[base] = seen.get(base, 0) + 1
        rows.append({"id": base if seen[base] == 1 else f"{base}.{seen[base]}", "subject": r["subject"], "grade": r["grade"],
                     "grade_band": r["grade_band"], "domain": r["materia_en"] + f", specific competence {r['ce']}", "cluster": r["text_es"],
                     "text": r["text_en"], "url": f"https://www.boe.es/diario_boe/xml.php?id={BOE[r['etapa']]}"})
    load(SYSTEM, SUBJECTS, rows)


if __name__ == "__main__":
    main()
