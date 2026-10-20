"""Map parsed BOE materias to StandardGraph subjects/grades and emit rows awaiting translation.

    python3 scripts/spain/build_rows.py /tmp/spain_raw.json /tmp/spain_todo.json
Math, physical education, philosophy, technical drawing, business and orientation are not mapped (math is already es-lomloe)."""
import json
import re
import sys

SUBJ = {  # materia regex -> (subject, English name)
    r"^Conocimiento del Medio": ("science", "Natural, Social and Cultural Environment (integrated area)"),
    r"^Biología y Geología": ("science", "Biology and Geology"), r"^Física y Química": ("science", "Physics and Chemistry"),
    r"^Biología, Geología": ("science", "Biology, Geology and Environmental Sciences"), r"^Biología$": ("science", "Biology"),
    r"^Ciencias Generales": ("science", "General Sciences"), r"^Física$": ("science", "Physics"), r"^Química$": ("science", "Chemistry"),
    r"^Geología y Ciencias": ("science", "Geology and Environmental Sciences"),
    r"^Geografía e Historia": ("social-studies", "Geography and History"), r"^Geografía$": ("social-studies", "Geography"),
    r"^Historia de España": ("social-studies", "History of Spain"), r"^Historia del Mundo": ("social-studies", "History of the Contemporary World"),
    r"^Economía": ("social-studies", "Economics"), r"^Educación en Valores": ("social-studies", "Civic and Ethical Values Education"),
    r"^Digitalización": ("cs", "Digitalisation"), r"^Tecnología y Digitalización": ("cs", "Technology and Digitalisation"),
    r"^Tecnología$": ("cs", "Technology"), r"^Tecnología e Ingeniería": ("cs", "Technology and Engineering"),
    r"^Educación Artística": ("arts", "Arts Education"), r"^Educación Plástica": ("arts", "Visual and Audiovisual Arts"),
    r"^Expresión Artística": ("arts", "Artistic Expression"), r"^Música": ("arts", "Music"), r"^Análisis Musical": ("arts", "Musical Analysis"),
    r"^Artes [Ee]scénicas": ("arts", "Performing Arts"), r"^Coro": ("arts", "Choir and Vocal Technique"),
    r"^Cultura Audiovisual": ("arts", "Audiovisual Culture"), r"^Dibujo Artístico": ("arts", "Artistic Drawing"),
    r"^Diseño$": ("arts", "Design"), r"^Fundamentos Artísticos": ("arts", "Artistic Foundations"),
    r"^Historia de la Música": ("arts", "History of Music and Dance"), r"^Lenguaje y Práctica Musical": ("arts", "Musical Language and Practice"),
    r"^Movimientos Culturales": ("arts", "Cultural and Artistic Movements"), r"^Proyectos Artísticos": ("arts", "Artistic Projects"),
    r"^Técnicas de Expresión": ("arts", "Graphic-Plastic Expression Techniques"), r"^Volumen": ("arts", "Volume"),
    r"^Historia del Arte": ("arts", "History of Art"),
    r"^Lengua Castellana": ("ela", "Spanish Language and Literature"), r"^Literatura Universal": ("ela", "World Literature"),
    r"^Literatura Dramática": ("ela", "Dramatic Literature"),
    r"^Lengua Extranjera": ("world-languages", "Foreign Language"), r"^Latín": ("world-languages", "Latin"),
    r"^Griego": ("world-languages", "Greek"),
}
ROMAN = {"I": ("11", None), "II": ("12", None)}


def grade(etapa, level, materia):
    if etapa == "PRI":
        if level is None:  # Valores Cívicos y Éticos: criteria given once for the whole stage
            return ("1", "1-6")
        return {"Primer ciclo": ("1", "1-2"), "Segundo ciclo": ("3", "3-4"), "Tercer ciclo": ("5", "5-6")}[level]
    if etapa == "ESO":
        return {None: ("7", "7-10"), "Cursos de primero a tercero": ("7", "7-9"), "Cuarto curso": ("10", None),
                "Cursos primero y segundo": ("7", "7-8"), "Cursos tercero y cuarto": ("9", "9-10")}[level]
    m = re.search(r" (I{1,2})$", materia)
    return ("11", None) if m and m.group(1) == "I" else ("12", None) if m else ("11", "11-12")


rows = json.load(open(sys.argv[1]))
out, n = [], 0
for r in rows:
    for rx, (subj, en) in SUBJ.items():
        if re.search(rx, r["materia"]):
            break
    else:
        continue
    g, band = grade(r["etapa"], r["level"], r["materia"])
    suffix = re.search(r" (I{1,2})$", r["materia"])
    out.append({"n": n, **r, "subject": subj, "materia_en": en + (f" {suffix.group(1)}" if suffix else ""), "grade": g, "grade_band": band})
    n += 1
json.dump(out, open(sys.argv[2], "w"), ensure_ascii=False, indent=1)
import collections
print(len(out), collections.Counter(o["subject"] for o in out))
