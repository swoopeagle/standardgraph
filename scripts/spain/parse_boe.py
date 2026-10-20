"""Parse Spain's state minimum curriculum (Reales Decretos 157/2022 Primaria, 217/2022 ESO, 243/2022 Bachillerato) from the
BOE XML into one row per 'criterio de evaluación' (n.m), grouped by materia and course level.

Source XML:  https://www.boe.es/diario_boe/xml.php?id=BOE-A-2022-3296 | BOE-A-2022-4975 | BOE-A-2022-5521
Licence (BOE aviso legal, condition 3, fetched 2026-10-20): "Las presentes condiciones permiten la reutilización de los documentos
sometidos a ellas para fines comerciales y no comerciales"; attribution: "Fuente de los datos: Agencia Estatal Boletín Oficial del Estado".
Output: JSON list {etapa, materia, level, ce, ce_text, code, text_es}; translation is a separate step (data/spain_lomloe_other.json).

    python3 scripts/spain/parse_boe.py DIR_WITH_XML  > /tmp/spain_raw.json
"""
import json
import re
import sys
from pathlib import Path

DOCS = {"PRI": "BOE-A-2022-3296", "ESO": "BOE-A-2022-4975", "BAC": "BOE-A-2022-5521"}
LEVEL = re.compile(r"^(Primer|Segundo|Tercer)\s+ciclo$|^Cursos?\b|^Cuarto curso|^Primer curso|^Segundo curso|^(1|2|3|4)\.º", re.I)
CRIT = re.compile(r"^(\d+)\.(\d+)\.?\s+(.*)$", re.S)


def txt(x):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", x)).replace("&amp;", "&").strip()


def parse(etapa, xml):
    ps = [(c, txt(x)) for c, x in re.findall(r'<p class="([^"]+)">(.*?)</p>', xml, flags=re.S)]
    rows, materia, level, state, started, ce_text, ce_n = [], None, None, None, False, {}, None
    for c, t in ps:
        if not t:
            continue
        if c in ("anexo_num",):
            started = False
        if c == "anexo_tit" and re.search(r"Áreas|Materias|MATERIAS", t, re.I) or re.match(r"MATERIAS DE", t):
            started = True
            continue
        if not started:
            continue
        if c in ("centro_negrita", "centro_cursiva", "centro_redonda", "anexo_tit", "cuerpo_tabla_izq") and not CRIT.match(t):
            if t in ("Criterios de evaluación", "Criterios de evaluación.", "Descriptores operativos"):
                state = "crit"
            elif LEVEL.match(t):
                level = t
            elif re.match(r"ANEXO|MATERIAS|Áreas", t):
                pass
            else:
                materia, level, state, ce_text = t, None, None, {}
            continue
        if re.match(r"^(Competencias específicas|Saberes básicos|Criterios de evaluación)\.?$", t):
            state = {"Competencias específicas": "ce", "Saberes básicos": "sab", "Criterios de evaluación": "crit"}[t.rstrip(".")]
            continue
        m = CRIT.match(t)
        if state == "ce" and m and m.group(2) and re.match(r"^\d+\. ", t):  # '1. text' competencia especifica
            mm = re.match(r"^(\d+)\.\s+(.*)$", t)
            ce_text[mm.group(1)] = mm.group(2)
        elif state == "crit" and m and materia:
            rows.append({"etapa": etapa, "materia": materia, "level": level, "ce": m.group(1),
                         "ce_text": ce_text.get(m.group(1), ""), "code": f"{m.group(1)}.{m.group(2)}", "text_es": m.group(3)})
    return rows


if __name__ == "__main__":
    d = Path(sys.argv[1])
    out = []
    for etapa, id_ in DOCS.items():
        out += parse(etapa, (d / f"{id_}.xml").read_text(encoding="utf-8"))
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
