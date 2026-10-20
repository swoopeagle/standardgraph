"""Extract learning objectives and expected competences from the Italian Indicazioni nazionali per il curricolo (primo ciclo, DM 9 dicembre 2025 n. 221).

Source: https://www.mim.gov.it/documents/20182/10554370/curricolo_web.pdf (text layer).  Terms: https://www.mim.gov.it/note-legali , "i testi pubblicati sul presente sito sono messi
a disposizione con licenza CC-BY 3.0" (fetched 2026-10-20); also Legge 633/1941 art. 5 (official acts).  Mathematics is not extracted (it-miur maths is already in the DB).

    pdftotext curricolo_web.pdf raw.txt && python3 scripts/italy/parse_curricolo.py raw.txt > data/italy_curricolo_2025_raw.json
One row per "–" bullet under "Obiettivi specifici di apprendimento al termine della classe X" / "Competenze attese al termine della classe X",
subject from the PDF page range of each discipline (table of contents, printed page + 1)."""
import json
import re
import sys

SUBJ = [(69, 83, "ela", "Italian"), (84, 96, "world-languages", "English and second community language"), (97, 105, "social-studies", "History"),
        (106, 113, "social-studies", "Geography"), (131, 140, "science", "Science"), (141, 147, "cs", "Technology"), (148, 158, "arts", "Music"),
        (159, 168, "arts", "Art and image")]
GRADE = {("primaria", "terza"): ("3", "1-3"), ("primaria", "quinta"): ("5", "4-5"), ("secondaria", "terza"): ("8", "6-8")}
NOISE = re.compile(r"^(\d{1,3}|Indicazioni nazionali per il curricolo.*|Indicazioni nazionali per le scuole.*|Le discipline)$")


def parse(text):
    out = []; seq = {}
    for pno, page in enumerate(text.split("\f"), 1):
        subj = next((s for a, b, *s in SUBJ if a <= pno <= b), None)
        if not subj:
            continue
        for ln in page.split("\n"):
            s = ln.strip()
            if not s or NOISE.match(s):
                continue
            state = parse.state
            if state.get("subj") != subj[1]:
                state.clear(); state["subj"] = subj[1]; state["level"] = "primaria"
            if s.startswith("Scuola primaria"):
                state["level"] = "primaria"; state["cur"] = None; continue
            if s.startswith("Scuola secondaria di primo grado"):
                state["level"] = "secondaria"; state["cur"] = None; continue
            m = re.match(r"^(Competenze attese|Obiettivi specifici di apprendimento)(?: al termine della classe (terza|quinta))?", s, re.I)
            if m:
                state["cur"] = None; state["kind"] = "competence" if m.group(1).lower().startswith("comp") else "objective"
                if m.group(2):
                    state["class"] = m.group(2)
                state["area"] = ""; continue
            if state.get("kind") is None or state.get("class") is None and state["level"] == "primaria":
                continue
            if re.match(r"^[–-]\s+", s):
                cur = state.get("cur")
                if cur:
                    out.append(cur)
                state["cur"] = {"subject": subj[0], "subject_en": subj[1], "level": state["level"], "class": state.get("class", "terza"),
                                "kind": state["kind"], "area_it": state.get("area", ""), "pdf_page": pno, "text_it": re.sub(r"^[–-]\s+", "", s)}
                continue
            cur = state.get("cur")
            if cur and not re.search(r"[.;:]$", cur["text_it"]):
                cur["text_it"] += " " + s                      # wrapped line of the current bullet
            elif len(s) < 90 and not s.endswith((".", ";", ",")):
                if cur:
                    out.append(cur); state["cur"] = None
                state["area"] = s                              # area heading line
            elif cur:
                cur["text_it"] += " " + s
        # keep bullet open across pages
    if parse.state.get("cur"):
        out.append(parse.state["cur"])
    for r in out:
        g, band = GRADE[(r["level"], r["class"])]
        k = (r["subject_en"], r["level"], r["class"], r["kind"]); seq[k] = seq.get(k, 0) + 1
        r.update({"grade": g, "band": band, "seq": seq[k], "text_it": re.sub(r"\s+", " ", r["text_it"]).strip()})
    return out


parse.state = {}

if __name__ == "__main__":
    json.dump(parse(open(sys.argv[1], encoding="utf-8").read()), sys.stdout, ensure_ascii=False, indent=1)
