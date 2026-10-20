"""Parse Poland's podstawa programowa for szkola podstawowa classes IV-VIII (Rozporzadzenie MEN of 11 March 2026, Dz.U. 2026 poz. 378).

Source PDF: https://api.sejm.gov.pl/eli/acts/DU/2026/378/text.pdf  (official Sejm ELI API; annex of a ministerial regulation)
Legal basis (fetched 2026-10-20 from https://api.sejm.gov.pl/eli/acts/DU/1994/83/text.html), Prawo autorskie Art. 4:
"Nie stanowia przedmiotu prawa autorskiego: 1) akty normatywne lub ich urzedowe projekty, 2) urzedowe dokumenty, materialy, znaki i symbole".
Output: one row per numbered requirement ("N)" item, lettered sub-items folded in) of the chosen subjects.

    pdftotext -layout text.pdf pl378.txt && python3 scripts/poland/parse_podstawa.py pl378.txt > /tmp/pl_raw.json
"""
import json
import re
import sys

SUBJECTS = {  # heading in the annex -> (our subject, English name, grade, band)
    "MATEMATYKA": ("mathematics", "Mathematics"), "FIZYKA": ("science", "Physics"), "CHEMIA": ("science", "Chemistry"),
    "BIOLOGIA": ("science", "Biology"), "GEOGRAFIA": ("social-studies", "Geography"), "HISTORIA": ("social-studies", "History"),
    "INFORMATYKA": ("cs", "Computer science"), "PRZYRODA": ("science", "Nature studies (grades 4-6)"),
    "EDUKACJA OBYWATELSKA": ("social-studies", "Civic education"),
}
HEADINGS = ["JĘZYK POLSKI", "JĘZYK OBCY NOWOŻYTNY", "JĘZYK ŁACIŃSKI", "PLASTYKA", "MUZYKA", "HISTORIA", "EDUKACJA OBYWATELSKA",
            "PRZYRODA", "GEOGRAFIA", "BIOLOGIA", "CHEMIA", "FIZYKA", "MATEMATYKA", "INFORMATYKA", "ZAJĘCIA PRAKTYCZNO-TECHNICZNE",
            "WYCHOWANIE FIZYCZNE", "EDUKACJA DLA BEZPIECZEŃSTWA", "EDUKACJA ZDROWOTNA", "JĘZYK MNIEJSZOŚCI NARODOWEJ LUB ETNICZNEJ"]
JUNK = re.compile(r"^\s*(Dziennik Ustaw.*|.*Poz\. 378|[–\-\s\d]*)\s*$")
BANDS = {"IV–VI": ("4", "4-6"), "VII–VIII": ("7", "7-8"), "VII i VIII": ("7", "7-8"), "IV–VIII": ("4", "4-8")}
DEFAULT = {"MATEMATYKA": None, "FIZYKA": ("7", "7-8"), "CHEMIA": ("7", "7-8"), "BIOLOGIA": ("5", "5-8"), "GEOGRAFIA": ("5", "5-8"),
           "HISTORIA": ("4", "4-8"), "INFORMATYKA": ("4", "4-8"), "PRZYRODA": ("4", "4-6"), "EDUKACJA OBYWATELSKA": ("8", "8")}


def sections(lines):
    start = next(i for i, l in enumerate(lines) if "II ETAP EDUKACYJNY (KLASY IV–VIII)" in l)
    pos = []
    for i in range(start, len(lines)):
        t = lines[i].strip()
        if t in HEADINGS and lines[i].startswith(" " * 10):
            pos.append((i, t))
    return [(h, pos[k][0] + 1, pos[k + 1][0] if k + 1 < len(pos) else len(lines)) for k, (i, h) in enumerate(pos) for h in [h]]


def parse(lines):
    rows = []
    for name, a, b in sections(lines):
        if name not in SUBJECTS:
            continue
        kind, band, domain, item, mode = None, DEFAULT.get(name), "General aims", None, "pre"
        def flush():
            nonlocal item
            if item:
                rows.append({"heading": name, "subject": SUBJECTS[name][0], "name": SUBJECTS[name][1], "grade": (band or ("4", "4-8"))[0],
                             "band": (band or ("4", "4-8"))[1], "domain": domain, "mode": mode, "code": item[0],
                             "text_pl": re.sub(r"\s+", " ", item[1]).strip()})
            item = None
        for l in lines[a:b]:
            if JUNK.match(l):
                continue
            s = l.strip()
            if s.startswith("Cele kształcenia"):
                flush(); mode, domain = "aims", "General aims"; continue
            if s.startswith(("Warunki i sposób realizacji", "Warunki i sposoby realizacji")):
                flush(); mode = "end"; continue
            if mode in ("pre", "end"):
                continue
            if s.startswith("Treści nauczania"):
                flush(); mode, domain = "content", ""; continue
            m = re.match(r"^Klasy\s+([IVX]+(?:[–-]| i )[IVX]+)\s*$", s)
            if m:
                flush(); band = BANDS.get(m.group(1).replace("-", "–"), band); continue
            m = re.match(r"^(\d+)\.\s+(.*?)(?:\.\s*)?Uczeń:?\s*$", s) if mode == "content" else None
            if m and not l.startswith(" " * 14):
                flush(); domain = re.sub(r"\s+", " ", m.group(2)).strip(); continue
            m = re.match(r"^(\d+)[).]\s+(.*)$", s)
            indent = len(l) - len(l.lstrip())
            if m and indent <= 12 and not (mode == "content" and not domain and False):
                # section heading wrapped over two lines ("2. Miary.\n Uczeń:") is handled by the Uczeń-less fallback below
                flush(); item = (m.group(1), m.group(2)); continue
            if re.match(r"^Uczeń:?$", s):
                continue
            if item and s:
                if indent >= 8:
                    item = (item[0], item[1] + " " + s)
                else:
                    flush()
        flush()
    return rows


if __name__ == "__main__":
    lines = open(sys.argv[1], encoding="utf-8").read().replace("﻿", "").split("\n")
    json.dump(parse(lines), sys.stdout, ensure_ascii=False, indent=1)
