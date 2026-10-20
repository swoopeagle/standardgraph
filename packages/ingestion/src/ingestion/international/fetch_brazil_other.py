"""READY, PENDING COUNSEL: do not run against a release DB until the statute-route question in docs/world-coverage-scan-3.md is answered.
(One command once cleared:  DB_PATH=<copy> uv run python -m ingestion.international.fetch_brazil_other )

Brazil BNCC (Ensino Fundamental habilidades) for Portuguese, science, history, geography, arts and English, into br-bncc (maths is separate).
standard_text = English translation (Claude), cluster = Portuguese original.  IDs: BR_BNCC.{EFxxYYnn}.
Source: http://basenacionalcomum.mec.gov.br/images/BNCC_EI_EF_110518_versaofinal_site.pdf; extraction scripts/brazil/parse_bncc.py -> data/brazil_bncc_other.json.
Licence basis: Lei 9.610/98 art. 8 IV ("demais atos oficiais"), the BNCC being the Anexo of Resolucao CNE/CP 2/2017.  COUNTER-SIGNAL: gov.br/mec pages are stamped
"Creative Commons Atribuicao-SemDerivacoes 3.0" (CC BY-ND 3.0)."""
import json

from ingestion.international.loader_common import load
from shared.config import PROJECT_ROOT

SYSTEM = "br-bncc"
DATA = PROJECT_ROOT / "data" / "brazil_bncc_other.json"
URL = "http://basenacionalcomum.mec.gov.br/images/BNCC_EI_EF_110518_versaofinal_site.pdf"
SUBJECTS = ("ela", "science", "social-studies", "arts", "world-languages")


def main() -> None:
    rows = [{"id": f"BR_BNCC.{r['code']}", "subject": r["subject"], "grade": r["grade"], "grade_band": r["band"] if r["band"] != r["grade"] else None,
             "domain": r["component"], "cluster": r["text_pt"], "text": r["text_en"], "url": URL} for r in json.loads(DATA.read_text())]
    load(SYSTEM, SUBJECTS, rows)


if __name__ == "__main__":
    main()
