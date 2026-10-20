"""Extract England National Curriculum programmes of study (computing, history, geography, citizenship, art and design,
music, languages) from the gov.uk content API into data/uk_nc_other.json (committed; loader needs no network).

Licence: Open Government Licence v3.0 - collection page https://www.gov.uk/government/collections/national-curriculum:
"All content is available under the Open Government Licence v3.0, except where otherwise stated" (fetched 2026-10-20).
Non-statutory example boxes (div.call-to-action) are dropped; each statutory bullet (nested bullets folded in) = one standard.

    uv run python scripts/uk_nc/extract_other_subjects.py
"""
import json
import re
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

API = "https://www.gov.uk/api/content"
P = "/government/publications/national-curriculum-in-england-{s}-programmes-of-study/national-curriculum-in-england-{s}-programmes-of-study"
# (slug, html path, our subject, label)
SUBJECTS = [
    ("computing", None, "cs", "Computing"), ("history", None, "social-studies", "History"),
    ("geography", None, "social-studies", "Geography"),
    ("citizenship", P.format(s="citizenship") + "-for-key-stages-3-and-4", "social-studies", "Citizenship"),
    ("art-and-design", None, "arts", "Art and design"), ("music", None, "arts", "Music"),
    ("languages-progammes", "/government/publications/national-curriculum-in-england-languages-progammes-of-study/national-curriculum-in-england-languages-progammes-of-study", "world-languages", "Languages"),  # sic: gov.uk slug typo
]
KS_GRADE = {"1": ("1", "KS1"), "2": ("3", "KS2"), "3": ("7", "KS3"), "4": ("HS", "KS4")}


class Walker(HTMLParser):
    """Collect (heading-context, bullet text) for statutory <li>; skip div.call-to-action."""
    def __init__(self):
        super().__init__()
        self.skip = 0; self.divdepth = []; self.ul = 0; self.h = None; self.buf = []
        self.ks = None; self.dom = ""; self.items = []; self.li_stack = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "div":
            self.divdepth.append("call-to-action" in (a.get("class") or ""))
            self.skip += self.divdepth[-1]
        elif tag in ("h2", "h3", "h4"):
            self.h = tag; self.buf = []
        elif tag == "li" and not self.skip:
            self.li_stack.append([[], []])  # [own text pieces, child bullet texts]
        elif tag == "ul":
            self.ul += 1

    def handle_endtag(self, tag):
        if tag == "div" and self.divdepth:
            self.skip -= self.divdepth.pop()
        elif tag in ("h2", "h3", "h4") and self.h == tag:
            t = " ".join("".join(self.buf).split()); self.h = None
            m = re.match(r"Key stage (\d)", t)
            if m:
                self.ks, self.dom = m.group(1), ""
            elif t not in ("Purpose of study", "Aims", "Attainment targets", "Subject content") and not t.startswith("Examples"):
                self.dom = t
        elif tag == "li" and not self.skip and self.li_stack:
            own, kids = self.li_stack.pop()
            text = " ".join("".join(own).split()).rstrip(":")
            if kids:
                text = f"{text}: " + "; ".join(kids)
            if self.li_stack:
                self.li_stack[-1][1].append(text)
            elif self.ks and text:
                self.items.append((self.ks, self.dom, text))
        elif tag == "ul":
            self.ul -= 1

    def handle_data(self, d):
        if self.h:
            self.buf.append(d)
        elif self.li_stack and not self.skip:
            self.li_stack[-1][0].append(d)


def main():
    out = []
    for slug, path, subject, label in SUBJECTS:
        path = path or P.format(s=slug)
        body = json.load(urllib.request.urlopen(API + path))["details"]["body"]
        body = body.replace("&nbsp;", " ")
        w = Walker(); w.feed(body)
        # top-level own text of an li that has nested kids is read before the nested ul begins
        for ks, dom, text in w.items:
            g, band = KS_GRADE[ks]
            out.append({"subject": subject, "label": label, "slug": slug, "ks": ks, "grade": g, "grade_band": band,
                        "domain": f"{label}: {dom}" if dom else label, "text": text,
                        "url": "https://www.gov.uk" + path})
    Path(__file__).parents[2].joinpath("data", "uk_nc_other.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    from collections import Counter
    print(len(out), Counter((o["label"], o["ks"]) for o in out))


if __name__ == "__main__":
    main()
