"""Parse the France MEN maths programmes (cycles 2-4) into one row per "Objectifs d'apprentissage" item.

Input: pdftotext -layout text of the three BO annex PDFs (see docs/world-coverage-candidates.md for URLs).
Output: JSON list of {level, grade, theme, section, text_fr}.  Translation + DB load: ingestion.international.fetch_france.

Cycle 2 is a two-column table (objectives | examples), so it is parsed from word coordinates with PyMuPDF
(`uv run --with pymupdf python scripts/france/parse_programmes.py ...`); cycles 3-4 are single-column text.
"""
import json
import re
import sys
from pathlib import Path

GRADES = {
    "Cours préparatoire": "1", "Cours élémentaire première année": "2", "Cours élémentaire deuxième année": "3",
    "Cours moyen première année": "4", "Cours moyen deuxième année": "5", "Sixième": "6",
    "Cinquième": "7", "Quatrième": "8", "Troisième": "9",
}
THEMES = {
    "Nombres, calcul et résolution de problèmes", "Grandeurs et mesures", "Espace et géométrie",
    "Organisation et gestion de données", "Organisation et gestion de données et probabilités",
    "Nombres et calculs", "Proportionnalité, fonctions", "La pensée informatique",
}
FURNITURE = re.compile(r"©|^\s*\d+\s*$|^Enseignements primaire|^Programme de mathématiques|^Annexe")
HDR = "Objectifs d’apprentissage"
END = re.compile(r"[.;:,)»]$")


def heading_like(s: str) -> bool:
    s = s.strip()
    return bool(s) and len(s) < 70 and not END.search(s) and s[0].isupper() and s not in (HDR, "Automatismes")


def parse(path: str, level: str):
    lines = Path(path).read_text().splitlines()
    # program body starts at the 2nd occurrence of the first theme heading (1st is the table of contents)
    firsts = [i for i, l in enumerate(lines) if l.strip() in THEMES]
    first = lines[firsts[0]].strip()
    start = [i for i in firsts if lines[i].strip() == first][1]  # 2nd occurrence (1st is the table of contents)
    theme = grade = section = None
    out, i = [], start
    while i < len(lines):
        raw = lines[i]; s = raw.strip()
        if s in THEMES:
            # cycle 3 repeats "Organisation et gestion de données" as a sub-heading inside each grade: keep the grade
            if not (theme and theme.startswith("Organisation et gestion de données") and s.startswith("Organisation et gestion de données")):
                theme, grade = s, None
            theme = s if theme is None else theme
        elif s in GRADES: grade, section = GRADES[s], None
        elif s.startswith(HDR):
            col = raw.find("Exemples de réussite")
            # nearest preceding heading = section
            j = i - 1
            while j > start and not (heading_like(lines[j]) and lines[j].strip() not in THEMES and lines[j].strip() not in GRADES
                                     and not lines[j].lstrip().startswith(("-", "−"))
                                     and (not lines[j-1].strip() or lines[j-1].rstrip()[-1:] in ".:;" or lines[j+1].strip() in ("Automatismes", HDR, ""))):
                j -= 1
            section = lines[j].strip()
            items, cur = [], None
            k = i + 1
            while k < len(lines):
                l = lines[k]
                if FURNITURE.search(l): k += 1; continue
                if col > 0:  # two-column table (cycle 2): objectives are the left column, "- " bullets
                    left = l[:col].rstrip()
                    if not left.strip(): k += 1; continue
                    if left.startswith("- "): cur = [left[2:].strip()]; items.append(cur)
                    elif left.startswith("  ") and cur: cur.append(left.strip())
                    else: break
                else:
                    t = l.strip()
                    if not t: break
                    if t in ("Automatismes", HDR) or t.startswith(("Prolongements", "Exemples")): break
                    if t in THEMES or t in GRADES: break
                    if cur and END.search(" ".join(cur)) and heading_like(t) and not t[0] in "−-": break
                    if cur and t[0].isupper() or not cur: cur = [t]; items.append(cur)
                    elif cur: cur.append(t)
                k += 1
            for it in items:
                out.append({"level": level, "grade": grade, "theme": theme, "text_fr": " ".join(it)})
            i = k; continue
        i += 1
    return out


def parse_c2(pdf: str):
    """Two-column table: left-column words (x0 < 180) after an "Objectifs d'apprentissage" header."""
    import pymupdf
    out, theme, grade, in_tab, cur = [], None, None, False, None
    for page in pymupdf.open(pdf):
        words = page.get_text("words")
        rows = {}
        for w in words:
            rows.setdefault(round(w[1] / 3), []).append(w)
        for _, ws in sorted(rows.items()):
            ws.sort(key=lambda w: w[0])
            full = " ".join(w[4] for w in ws).strip()
            left = [w for w in ws if w[0] < 180]
            ltxt = " ".join(w[4] for w in left).strip()
            if FURNITURE.search(full) or re.fullmatch(r"\d+", full) or full.startswith(("Enseignements primaire", "Programme de mathématiques du")):
                continue
            if full in THEMES: theme, grade, in_tab, cur = full, None, False, None; continue
            if full in GRADES: grade, in_tab, cur = GRADES[full], False, None; continue
            if full.startswith(HDR): in_tab, cur = True, None; continue
            if not in_tab: continue
            if left and left[0][0] < 44.5 and not ltxt.startswith("-"): in_tab, cur = False, None; continue  # prose resumes
            if not ltxt: continue
            if ltxt.startswith("- "): cur = [ltxt[2:]]; out.append(dict(level="C2", grade=grade, theme=theme, parts=cur))
            elif cur is not None: cur.append(ltxt)
    return [dict(level=o["level"], grade=o["grade"], theme=o["theme"], text_fr=" ".join(o["parts"])) for o in out]


if __name__ == "__main__":
    d, outp = sys.argv[1], sys.argv[2]
    rows = []
    for lvl, f in (("C2", "c2.txt"), ("C3", "c3.txt"), ("C4", "c4.txt")):
        r = parse_c2(f"{d}/c2.pdf") if lvl == "C2" else parse(f"{d}/{f}", lvl); print(lvl, len(r)); rows += r
    Path(outp).write_text(json.dumps(rows, ensure_ascii=False, indent=1))
