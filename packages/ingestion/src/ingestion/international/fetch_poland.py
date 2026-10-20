"""Load Poland's podstawa programowa for primary school classes IV-VIII (math, physics, chemistry, biology, geography, history,
computer science, nature studies, civic education) into the DB.  System: pl-men.  IDs: PL_MEN.{SUBJ}.{aims|content}.{seq}.
standard_text = English translation (Claude; reviewed result committed), cluster = Polish original.
Source: Rozporzadzenie MEN of 11 March 2026 (Dz.U. 2026 poz. 378), https://api.sejm.gov.pl/eli/acts/DU/2026/378/text.pdf.
Legal basis: Prawo autorskie Art. 4 ("Nie stanowia przedmiotu prawa autorskiego: 1) akty normatywne ... 2) urzedowe dokumenty ..."),
fetched 2026-10-20 from https://api.sejm.gov.pl/eli/acts/DU/1994/83/text.html; the podstawa is an annex of that regulation.
Extraction: scripts/poland/parse_podstawa.py + translation -> data/poland_podstawa_2026.json (committed; no network here)."""
import json

from ingestion.international.loader_common import load
from shared.config import PROJECT_ROOT

SYSTEM = "pl-men"
DATA = PROJECT_ROOT / "data" / "poland_podstawa_2026.json"
URL = "https://api.sejm.gov.pl/eli/acts/DU/2026/378/text.pdf"
SUBJECTS = ("mathematics", "science", "social-studies", "cs")
TAG = {"MATEMATYKA": "MATH", "FIZYKA": "PHYS", "CHEMIA": "CHEM", "BIOLOGIA": "BIOL", "GEOGRAFIA": "GEOG", "HISTORIA": "HIST",
       "INFORMATYKA": "INFO", "PRZYRODA": "NATS", "EDUKACJA OBYWATELSKA": "CIVC"}


def main() -> None:
    seq, rows = {}, []
    for r in json.loads(DATA.read_text()):
        k = (r["heading"], r["mode"]); seq[k] = seq.get(k, 0) + 1
        rows.append({"id": f"PL_MEN.{TAG[r['heading']]}.{r['mode'].upper()}.{seq[k]:03d}", "subject": r["subject"], "grade": r["grade"],
                     "grade_band": r["band"], "domain": f"{r['name']}: {r['domain_en']}", "cluster": r["text_pl"], "text": r["text_en"], "url": URL})
    load(SYSTEM, SUBJECTS, rows)


if __name__ == "__main__":
    main()
