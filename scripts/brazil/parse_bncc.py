"""Extract the Ensino Fundamental habilidades (BNCC) other than mathematics, physical education and religious education.

Source: http://basenacionalcomum.mec.gov.br/images/BNCC_EI_EF_110518_versaofinal_site.pdf (BNCC Educacao Infantil e Ensino Fundamental, final version 2018; 600 pp, text layer).
Statute basis (Lei 9.610/98 art. 8 IV "os textos de tratados ou convencoes, leis, decretos, regulamentos, decisoes judiciais e demais atos oficiais"; the BNCC is the Anexo of
Resolucao CNE/CP 2/2017 art. 1) is a legal-judgement route; the gov.br site also stamps CC BY-ND 3.0 (see docs/world-coverage-scan-3.md). STATUTE-ROUTE, pending counsel.

    pdftotext BNCC_EI_EF.pdf raw.txt && python3 scripts/brazil/parse_bncc.py raw.txt > data/brazil_bncc_other_raw.json
Code grammar: EF + year code (06 = grade 6; 15 = grades 1-5) + component (LP, CI, HI, GE, AR, LI) + number."""
import json
import re
import sys

COMP = {"LP": ("ela", "Portuguese Language"), "CI": ("science", "Science"), "HI": ("social-studies", "History"), "GE": ("social-studies", "Geography"),
        "AR": ("arts", "Arts"), "LI": ("world-languages", "English Language")}


def grades(yy):
    a, b = int(yy[0]), int(yy[1])
    if yy[0] == "0":
        return str(b), str(b)          # single grade, e.g. 06
    return str(a), f"{a}-{b}"          # band, e.g. 35 -> 3-5, 12 -> 1-2, 69 -> 6-9


def parse(text):
    lines = text.split("\n"); out, seen = [], set(); i = 0
    while i < len(lines):
        m = re.match(r"^\s*\((EF(\d{2})([A-Z]{2})(\d{2}))\)\s*(.*)$", lines[i])
        if not m or m.group(3) not in COMP:
            i += 1; continue
        code, yy, comp, n, txt = m.groups(); buf = [txt]; i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r"^\s*\(EF\d{2}[A-Z]{2}\d{2}\)", lines[i]) and not re.match(r"^\d{1,3}$", lines[i].strip()) \
                and not lines[i].strip().isupper():
            buf.append(lines[i].strip()); i += 1
        t = re.sub(r"\s+", " ", " ".join(buf)).replace("- ", "-") if False else re.sub(r"\s+", " ", " ".join(buf)).strip()
        if code in seen:
            continue
        seen.add(code); g, band = grades(yy)
        out.append({"code": code, "subject": COMP[comp][0], "component": COMP[comp][1], "comp": comp, "grade": g, "band": band, "text_pt": t})
    return out


if __name__ == "__main__":
    json.dump(parse(open(sys.argv[1], encoding="utf-8").read()), sys.stdout, ensure_ascii=False, indent=1)
