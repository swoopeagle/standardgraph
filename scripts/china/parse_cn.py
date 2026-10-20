"""Parse OCR'd PRC compulsory-education curriculum standards (2022 edition) into one row per content requirement.

Source: https://www.moe.gov.cn/srcsite/A26/s8001/202204/t20220420_619921.html (Ministry of Education notice  教材〔2022〕2号,
standards attached as image-only PDFs).  OCR: scripts/china/vision_ocr.swift (Apple Vision, zh-Hans) on 200 dpi page renders.

    pdftoppm -r 200 -png X.pdf p/p && ls p/*.png | sort | xargs vision_ocr > ocr_X.jsonl
    python3 scripts/china/parse_cn.py ocr_X.jsonl <subject-key> > raw.json

Grammar (shared by the 2022 standards): 第N学段（a~b年级） > 【内容要求】 > "1. 主题" > "（1）子主题" > item "（n）..." or "①..."
Items end at 【学业要求】/【教学提示】. Subject keys are parsed with the same state machine; per-subject quirks live in CFG."""
import json
import re
import sys

STAGE = {"一": ("1", "1-2"), "二": ("3", "3-4"), "三": ("5", "5-6"), "四": ("7", "7-9")}
HDR = re.compile(r"^\s*[I1l|丨]*\s*义务教育.*课程标准|^[一二三四五六七八九十]+、课程内容\S{0,3}$|^[\d\s|丨I']+$|^\s*[|丨I]\s*[一二三四五六七八九十]+、")
FOOT = re.compile(r"^[［\[]\d+[］\]]")
BEGIN = re.compile(r"^(【内容要求】|1[.．]\s*内容要求$)")
END = re.compile(r"^(【学业要求】|【教学提示】|【说明】|2[.．]\s*学业要求|3[.．]\s*教学提示)")
NUM = {c: i for i, c in enumerate("①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳", 1)}


NOISE = re.compile(r"[A-Za-z|丨I1l0']{0,3}义务教育\S{1,6}课程标准[（(]2022年版[）)]|[四五六三二]、课程内容\s*[|丨I\d』']*")


def clean(t):
    return NOISE.sub("", re.sub(r"\s+", "", t))


def page_lines(path):
    for pno, l in enumerate(open(path, encoding="utf-8"), 1):
        out, foot = [], False
        for x in json.loads(l)["lines"]:
            t = x["t"].strip()
            if not t or HDR.match(t):
                continue
            if FOOT.match(t):
                foot = True
            if not foot:
                out.append((pno, t))
        yield from out


def parse(path, subj_name):
    rows, area, stage, topic, sub, item, mode, started = [], "", None, "", "", None, False, False

    def flush():
        nonlocal item
        if item:
            rows.append({"subject_name": subj_name, "area": area, "stage": stage[0], "grade": stage[0], "band": stage[1], "topic": topic,
                         "subtopic": sub, "code": item[0], "page": item[2], "text_zh": clean(item[1])})
        item = None

    for pno, t in page_lines(path):
        m = re.match(r"^[（(]?第([一二三四])学段", t)
        if m and len(t) < 16:
            flush(); stage = STAGE[m.group(1)]; mode = False; topic = sub = ""; continue
        m = re.match(r"^[（(]([一二三四五六七八])[）)]\s*(\S{2,12})$", t)
        if m and not t.endswith("。") :
            flush(); area = m.group(2); mode = False; stage = None if started and False else stage; continue
        if BEGIN.match(t):
            flush(); mode = True; started = True; topic = sub = ""; continue
        if END.match(t) or t.startswith("【学业质量"):
            flush(); mode = False; continue
        if started and re.match(r"^五、学业质量$", t):
            break
        if not mode or stage is None:
            continue
        m = re.match(r"^(\d+)[.．、]\s*(\S.*)$", t)
        if m and len(m.group(2)) <= 16 and not re.search(r"[，。；]", m.group(2)):
            flush(); topic = m.group(2); sub = ""; continue
        m = re.match(r"^[（(]([\d①-⑳]+)[）)]\s*(.*)$", t)
        if m:
            body = m.group(2)
            if len(body) <= 12 and not re.search(r"[，。；]", body) and body:
                flush(); sub = body; continue  # subtopic heading, e.g. （1）有理数
            flush(); item = (str(NUM.get(m.group(1), m.group(1))), body, pno); continue
        m = re.match(r"^([①-⑳])\s*(.*)$", t)
        if m:
            flush(); item = (f"{sub or 'x'}.{NUM[m.group(1)]}" if False else str(NUM[m.group(1)]), m.group(2), pno); continue
        m = re.match(r"^(主题活动|项目学习)\s*(\d+)\s*[：:]\s*(.*)$", t)
        if m:
            flush(); item = (f"{m.group(1)}{m.group(2)}", m.group(3), pno); continue
        if item:
            item = (item[0], item[1] + t, item[2])
    flush()
    return rows




def parse_table(path, subj_name, concept_re=r"^[（(][一二三四五六七八九十]+[）)]\s*(\S{3,16})$"):
    """Science-style standards: 内容要求 is a 3-column table (学习内容 | circled-digit requirements | 学段 'a~b 年级').
    A group (= one stage) starts whenever the circled numbering restarts at ①; the stage label sits inside its group's cell."""
    rows, area, mode, groups = [], "", False, []  # groups: [{"labels": [(a,b)], "items": [[n, text, page]]}]

    def close():
        order = ["1", "3", "5", "7"]  # an unlabelled group (OCR missed the label) takes the unique stage between its neighbours, else the next one
        known = [g["labels"][0][0] if g["labels"] else None for g in groups]
        for k, g in enumerate(groups):
            if known[k] is None:
                prev = max((order.index(v) for v in known[:k] if v), default=-1)
                nxt = min((order.index(v) for v in known[k + 1:] if v), default=4)
                known[k] = order[min(prev + 1, 3)] if nxt - prev >= 1 and prev + 1 < 4 else order[3]
                g["inferred"] = True
        for k, g in enumerate(groups):
            lab = (known[k], None)
            st = {"1": ("1", "1-2"), "3": ("3", "3-4"), "5": ("5", "5-6"), "7": ("7", "7-9")}.get(lab[0]) if lab else None
            for n, text, pg in g["items"]:
                rows.append({"subject_name": subj_name, "area": area, "stage": st[0] if st else None, "grade": st[0] if st else None,
                             "band": st[1] if st else None, "topic": "", "subtopic": "", "code": f"s{lab[0] if lab else '?'}.{n}", "page": pg, "stage_inferred": bool(g.get("inferred")),
                             "text_zh": clean(text)})
        groups.clear()

    for pno, l in enumerate(open(path, encoding="utf-8"), 1):
        lines = sorted(json.loads(l)["lines"], key=lambda x: x["y"])
        xs = sorted(x["x"] for x in lines if re.match(r"^[①-⑳]", x["t"].strip()))
        ix = xs[len(xs) // 2] if xs else None
        for x in lines:
            t = x["t"].strip()
            if not t or HDR.match(t) or t in ("续表", "学段", "学习内容", "内容要求", "年级"):
                continue
            if FOOT.match(t):
                break
            m = re.match(concept_re, t)
            if m and not t.endswith("。") and x["x"] < 0.3:
                close(); area = m.group(1); mode = False; continue
            if t.startswith("【内容要求】"):
                close(); mode = True; continue
            if t.startswith(("【学业要求】", "【教学提示】")):
                close(); mode = False; continue
            if not mode:
                continue
            m = re.match(r"^([1-9])\s*[~～—-]\s*([1-9])$", t)
            if m and groups:
                groups[-1]["labels"].append((m.group(1), m.group(2))); continue
            m = re.match(r"^([①-⑳])\s*(.*)$", t)
            if m:
                n = NUM[m.group(1)]
                if n == 1 or not groups:
                    groups.append({"labels": [], "items": []})
                groups[-1]["items"].append([str(n), m.group(2), pno]); continue
            if groups and groups[-1]["items"] and ix is not None and abs(x["x"] - ix) < 0.02:
                groups[-1]["items"][-1][1] += t
    close()
    return rows


def parse_coded(path, subj_name, stage=("7", "7-9"), item_re=r"^(\d+\.\d+\.\d+)\s*(.*)$", topic_re=r"^(\d+\.\d+)\s*(\S{2,24})$",
                area_re=r"^[（(]([一二三四五六七八九十]+)[）)]\s*(\S{2,16})$", head_sep=""):
    """Single-stage subjects (physics, chemistry, biology, ...) whose 内容要求 are coded 1.1.1 / 1.1.2 under topic 1.1 under area （一）."""
    rows, area, topic, item, mode = [], "", "", None, False

    def flush():
        nonlocal item
        if item:
            rows.append({"subject_name": subj_name, "area": area, "stage": stage[0], "grade": stage[0], "band": stage[1], "topic": topic,
                         "subtopic": "", "code": item[0], "page": item[2], "text_zh": clean(item[1])})
        item = None

    for pno, t in page_lines(path):
        if re.match(r"^五、学业质量$", t) and rows:
            break
        m = re.match(area_re, t)
        if m and not t.endswith("。") and not mode:
            area = m.group(2); continue
        if BEGIN.match(t):
            flush(); mode = True; continue
        if END.match(t):
            flush(); mode = False; continue
        if not mode:
            continue
        m = re.match(item_re, t)
        if m:
            flush(); item = (m.group(1), m.group(2) + head_sep, pno); continue
        if re.match(r"^概念\d", t):
            flush(); area = area.split("|")[0] + "|" + clean(t)[:60]; continue
        m = re.match(topic_re, t)
        if m:
            flush(); topic = m.group(2); continue
        if item:
            item = (item[0], item[1] + t, item[2])
    flush()
    return rows


def parse_para(path, subj_name, stage=("7", "7-9"), topic_re=r"^(\d+\.\d+(?:\.\d+)?)\s*(\S{2,30})$", area_re=r"^[（(]([一二三四五六七八九十]+)[）)]\s*(\S{2,20})$"):
    """Prose-style 内容要求 (chemistry, biology, ...): one row per paragraph or （n） item under a numbered topic.
    A paragraph starts on an indented first line (OCR x offset) or a （n） marker."""
    rows, area, topic, tcode, cur, mode, seq = [], "", "", "", None, False, {}

    def flush():
        nonlocal cur
        if cur and len(cur[0]) > 8:
            seq[tcode] = seq.get(tcode, 0) + 1
            rows.append({"subject_name": subj_name, "area": area, "stage": stage[0], "grade": stage[0], "band": stage[1], "topic": f"{tcode} {topic}",
                         "subtopic": "", "code": f"{tcode}.{seq[tcode]}", "page": cur[1], "text_zh": clean(cur[0])})
        cur = None

    for pno, l in enumerate(open(path, encoding="utf-8"), 1):
        lines = sorted(json.loads(l)["lines"], key=lambda x: x["y"])
        body = sorted(x["x"] for x in lines if len(x["t"]) > 14)
        margin = body[len(body) // 4] if body else 0.15
        foot = False
        for x in lines:
            t = x["t"].strip()
            if not t or HDR.match(t):
                continue
            if FOOT.match(t):
                break
            if re.match(r"^五、学业质量$", t) and rows:
                flush(); return rows
            m = re.match(area_re, t)
            if m and not t.endswith("。") and not mode:
                area = m.group(2); continue
            if t.startswith("【内容要求】"):
                flush(); mode = True; continue
            if t.startswith(("【学业要求】", "【教学提示】", "【说明】")):
                flush(); mode = False; continue
            if not mode:
                continue
            m = re.match(topic_re, t)
            if m and not re.search(r"[，。；]", m.group(2)):
                flush(); tcode, topic = m.group(1), m.group(2); continue
            starts = re.match(r"^[（(][\d]+[）)]", t) or x["x"] > margin + 0.018
            if starts:
                flush(); cur = (t, pno)
            elif cur:
                cur = (cur[0] + t, cur[1])
    flush()
    return rows


def parse_strand(path, subj_name, start=r"^（三）学段要求", end=r"^四、课程内容$", strand_re=r"^【(.{2,12})】$"):
    """语文-style 学段要求: 第N学段 > 【strand】 > numbered items 1. 2. ... (items wrap across lines)."""
    rows, stage, strand, item, on = [], None, "", None, False

    def flush():
        nonlocal item
        if item:
            rows.append({"subject_name": subj_name, "area": strand, "stage": stage[0], "grade": stage[0], "band": stage[1], "topic": "", "subtopic": "",
                         "code": f"s{stage[0]}.{item[0]}", "page": item[2], "text_zh": clean(item[1])})
        item = None

    seen_start = 0
    for pno, t in page_lines(path):
        if re.match(start, t):
            seen_start += 1
            if seen_start >= 1 and rows == [] and not on:
                on = True
            continue
        if not on:
            continue
        if re.match(end, t) and rows:
            flush(); break
        if rows and re.match(r"^(基础型|发展型|拓展型)学习任务群", t):
            flush(); break
        m = re.match(r"^第([一二三四])学段", t)
        if m and len(t) < 16:
            flush(); stage = STAGE[m.group(1)]; continue
        m = re.match(strand_re, t)
        if m:
            flush()
            if rows and m.group(1) not in ("识字与写字", "阅读与鉴赏", "表达与交流", "梳理与探究"):
                break  # past the 学段要求 (e.g. 【教学提示】 of 课程内容)
            strand = m.group(1); continue
        if stage is None:
            continue
        m = re.match(r"^(\d+)[.．、]\s*(.+)$", t)
        if m and strand:
            flush(); item = (m.group(1), m.group(2), pno); continue
        if item:
            item = (item[0], item[1] + t, item[2])
    flush()
    return rows


def parse_bullets(path, subj_name, stage=("7", "7-9")):
    """Geography-style: （一）area > 主题N theme > 【内容要求】 > "1. topic" > bullet items starting with •."""
    rows, area, theme, topic, item, mode = [], "", "", "", None, False

    def flush():
        nonlocal item
        if item and len(item[0]) > 8:
            rows.append({"subject_name": subj_name, "area": area, "stage": stage[0], "grade": stage[0], "band": stage[1], "topic": topic,
                         "subtopic": theme, "code": "", "page": item[1], "text_zh": clean(item[0])})
        item = None

    for pno, t in page_lines(path):
        if re.match(r"^五、学业质量$", t) and rows:
            flush(); break
        m = re.match(r"^[（(]([一二三四五六七八九十]+)[）)]\s*(\S{2,16})$", t)
        if m and not mode and not t.endswith("。"):
            area = m.group(2); continue
        m = re.match(r"^(主题[一二三四五六七八九十]+)\s*(\S.*)$", t)
        if m and len(t) < 30:
            flush(); theme = f"{m.group(1)} {m.group(2)}"; mode = False; continue
        if BEGIN.match(t):
            flush(); mode = True; continue
        if END.match(t):
            flush(); mode = False; continue
        if not mode:
            continue
        m = re.match(r"^(\d+)[.．]\s*(\S.{1,24})$", t)
        if m and not re.search(r"[，。；]", t):
            flush(); topic = m.group(2); continue
        if re.match(r"^[•·●▪]", t):
            flush(); item = (t[1:], pno); continue
        if item:
            item = (item[0] + t, item[1])
    flush()
    for k, r in enumerate(rows, 1):
        r["code"] = str(k)
    return rows


ART_STAGE = {"一": ("1", "1-2"), "二": ("3", "3-5"), "三": ("6", "6-7"), "四": ("8", "8-9")}  # 艺术 uses a 2-3-2-2 stage split


def parse_blocks(path, subj_name, stage_map=ART_STAGE):
    """One row per 【内容要求】 block (arts, music-style: the requirement is a single paragraph per learning task and stage)."""
    rows, area, stage, topic, buf, mode = [], "", None, "", [], False

    def flush(pno):
        nonlocal buf
        if buf and stage:
            rows.append({"subject_name": subj_name, "area": area, "stage": stage[0], "grade": stage[0], "band": stage[1], "topic": topic, "subtopic": "",
                         "code": str(len(rows) + 1), "page": pno, "text_zh": clean("".join(buf))})
        buf = []

    for pno, t in page_lines(path):
        m = re.match(r"^[（(]([一二三四五六七八])[）)]\s*(\S{2,16})$", t)
        if m and not mode and not t.endswith("。"):
            area = m.group(2); stage = None; continue
        m = re.match(r"^[（(]?第([一二三四])学段", t)
        if m and len(t) < 16:
            flush(pno); stage = stage_map[m.group(1)]; mode = False; continue
        if re.match(r"^学习任务\d+[：:]", t) and not mode:
            topic = t; continue
        if BEGIN.match(t):
            flush(pno); mode = True; continue
        if END.match(t):
            flush(pno); mode = False; continue
        if re.match(r"^六、学业质量", t) and rows:
            break
        if mode:
            buf.append(t)
    flush(0)
    return rows


EN_LEVEL = {"一": ("3", "3-4"), "二": ("5", "5-6"), "三": ("7", "7-9")}  # 英语 一/二/三级 = grades 3-4 / 5-6 / 7-9


def parse_levels(path, subj_name, start=r"^3\. 语言知识$", end=r"^（二）教学提示$"):
    """英语: 语言知识 / 语言技能 tables whose numbered items (1. 2. ...) restart per 级 (一级/二级/三级/三级+); the label sits inside its group."""
    rows, area, table, on, groups, last_area = [], "", "", False, [], ""

    def close():
        for g in groups:
            lab = g["labels"][0] if g["labels"] else None
            if lab is None:
                continue
            st = EN_LEVEL[lab[0]]
            for n, text, pg in g["items"]:
                rows.append({"subject_name": subj_name, "area": g["area"], "stage": st[0], "grade": st[0], "band": st[1], "topic": g["table"], "subtopic": "",
                             "code": f"L{lab}.{n}".replace("+", "p"), "page": pg, "text_zh": clean(text)})
        groups.clear()

    for pno, l in enumerate(open(path, encoding="utf-8"), 1):
        for x in sorted(json.loads(l)["lines"], key=lambda x: x["y"]):
            t = x["t"].strip()
            if not t or HDR.match(t) or t in ("级别", "内容要求", "续表"):
                continue
            if FOOT.match(t):
                break
            if re.match(start, t):
                on = True; continue
            if not on:
                continue
            if re.match(end, t):
                close(); return rows
            m = re.match(r"^[（(](\d+)[）)]\s*(\S{2,12})$", t)
            if m and not t.endswith("。"):
                close(); area = m.group(2); continue
            m = re.match(r"^表\d+\s*(\S.*)$", t)
            if m:
                close(); table = m.group(1); continue
            m = re.match(r"^([一二三])级[+＋]?$", t)
            if m and groups:
                groups[-1]["labels"].append(t.replace("＋", "+")[:2] + ("+" if "+" in t or "＋" in t else "")); continue
            m = re.match(r"^(\d+)[.．、]\s*(.*)$", t)
            if m and area:
                if int(m.group(1)) == 1 or not groups:
                    groups.append({"labels": [], "items": [], "area": area, "table": table})
                groups[-1]["items"].append([m.group(1), m.group(2), pno]); continue
            if groups and groups[-1]["items"]:
                groups[-1]["items"][-1][1] += t
    close()
    return rows


if __name__ == "__main__":
    mode = sys.argv[3] if len(sys.argv) > 3 else "text"
    json.dump({"table": parse_table, "coded": parse_coded, "para": parse_para, "strand": parse_strand, "bullets": parse_bullets, "blocks": parse_blocks, "levels": parse_levels}.get(mode, parse)(sys.argv[1], sys.argv[2]), sys.stdout, ensure_ascii=False, indent=1)
