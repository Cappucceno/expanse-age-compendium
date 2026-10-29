#!/usr/bin/env python3
"""Convert The Expanse RPG: Transport Union Edition (PDF) into Foundry pack sources for the AGE System.

Usage: scripts/convert.py PATH/TO/The_Expanse_-_Transport_Union_Edition.pdf [--out packs/_source] [--only talents,focuses,...]

The PDF is read with `pdftotext` and `pdftohtml` (poppler-utils) and is never stored in the repository.
Output is one JSON per document in packs/_source/<pack>/, plus `_folder-*.json` for folders.
Ids are deterministic (hash of pack + name), so reruns produce stable diffs.

Page numbers below are PDF pages (printed page number + 2).
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (ABILITIES, Pack, SYSTEM_STATS, Words, clean_lines, esc, journal_doc, li, make_id, modifier, num, p, paragraph,  # noqa: E402
                    pdftotext, table_doc, table_html)

COL = ((0, 306), (306, 306))          # x, width of the two text columns in PDF points
RUNNING = re.compile(r"^(\d{1,2}: [A-Z][A-Za-z &]+|\d{1,3}|[A-Z][A-Za-z ]+ \d{1,3}|The Expanse \d+)$")
_BOOK = {}


def words(pdf):
    if "w" not in _BOOK:
        _BOOK["w"] = Words(" ".join(pdftotext(pdf, 1, 290)))
        try:
            with open("/usr/share/dict/words", encoding="utf-8") as f:
                _BOOK["dict"] = {w.strip().lower() for w in f if w.strip().isalpha()}
        except OSError:
            _BOOK["dict"] = set()
    return _BOOK["w"]


def fix_split_words(s):
    """pdftotext sometimes leaves a space inside a word ('informa tion'); rejoin when the join is a word and the parts are not."""
    d = _BOOK.get("dict", set())
    known = _BOOK["w"].known

    def fix(m):
        a, b = m.group(1), m.group(2)
        if (a + b).lower() in d | known and not (a.lower() in d and b.lower() in d):
            return a + b
        return m.group(0)
    return re.sub(r"\b([a-z]{3,}) ([a-z]{2,})\b", fix, s)


def hyphens(s):
    return re.sub(r"\bSelf(?=[A-Z])", "Self-", s)


def squash(s):
    return re.sub(r"\s+", " ", s).strip()


def col_lines(pdf, first, last, cols=COL):
    """Lines of PDF pages first..last: left column, then right column, page by page; running heads and page numbers dropped."""
    out = []
    for pg in range(first, last + 1):
        for x, w in cols:
            t = pdftotext(pdf, pg, pg, "-x", str(x), "-y", "0", "-W", str(w), "-H", "792")[0]
            out += [l.strip() for l in t.splitlines() if l.strip() and not RUNNING.match(l.strip())]
    return out


def join_lines(lines, pdf):
    """Join wrapped lines; a line-end hyphen is dropped when the joined word is a dictionary word or one of its halves is not a word."""
    words(pdf)
    d = _BOOK["dict"]
    out = ""
    for l in lines:
        l = l.strip()
        if not l:
            continue
        if not out:
            out = l
        elif out.endswith("-") and l[:1].islower() and re.search(r"[A-Za-z]-$", out):
            last = re.split(r"[^A-Za-z]", out[:-1])[-1].lower()
            first = re.match(r"[A-Za-z]*", l).group(0).lower()
            drop = (last + first) in d or not (last in d and first in d)
            out = (out[:-1] if drop else out) + l
        else:
            out += " " + l
    return re.sub(r"\s{2,}", " ", out)


def para(lines, pdf):
    return hyphens(fix_split_words(join_lines(lines, pdf)))


def smallcaps(s):
    """Headings set in small capitals come out with stray lowercase capitals ('ACAdEMIC'): restore the title case."""
    s = s.strip()
    def cap(w):
        return "-".join(x.capitalize() for x in w.split("-"))
    out = " ".join(cap(w) if w.lower() not in ("of", "and", "the", "in", "to", "a") else w.lower() for w in s.lower().split())
    return re.sub(r"\((\w)", lambda m: "(" + m.group(1).upper(), out).replace("’S", "’s")


# --------------------------------------------------------------------------- talents and specializations (p48-65)

DEGREE_LINES = ("NOVICE", "EXPERT", "MASTER")


def parse_talent_blocks(lines, pdf):
    """[{name, requirement, desc, deg, flavor}] for every 'NAME / REQUIREMENTS: ...' block in the lines."""
    reqs = [i for i, l in enumerate(lines) if re.match(r"REQUIREMENTS?:", l)]
    out = []
    for n, i in enumerate(reqs):
        stop = reqs[n + 1] - 1 if n + 1 < len(reqs) else len(lines)
        nxt = lines[stop].upper() if n + 1 < len(reqs) else None
        if nxt:      # the next entry is a specialization when its name already heads a text before its talent block
            heading = next((k for k in range(stop - 1, i, -1) if lines[k].upper() == nxt), None)
            if heading is not None:
                stop = heading
        name = lines[i - 1]
        if sum(c.isupper() for c in name) < 0.6 * sum(c.isalpha() for c in name):
            continue        # the sample entry of the 'how to read talents' sidebar
        body = lines[i:stop]
        req = [re.sub(r"^REQUIREMENTS?:", "", body[0]).strip()]
        k = 1
        # the requirement can wrap onto further lines until the description sentence starts (a capital after a full stop)
        is_spec = any(lines[q].upper() == name.upper() for q in range((reqs[n - 1] if n else 0) + 1, i - 1))
        while k < len(body) and not re.match(r"^(NOVICE|EXPERT|MASTER)\b", body[k]) and (
                (is_spec and not req[-1].endswith((".", "focus", "focuses"))) or
                req[-1].endswith((",", " and", " or", " the", " a", "/")) or body[k][:1].islower() or body[k].startswith("(")):
            req.append(body[k])
            k += 1
        desc, deg, key = [], {d: [] for d in DEGREE_LINES}, None
        for l in body[k:]:
            m = re.match(r"^(NOVICE|EXPERT|MASTER)\b\s*(.*)$", l)
            if m:
                key = m.group(1)
                if m.group(2):
                    deg[key].append(m.group(2))
            elif key:
                deg[key].append(l)
            else:
                desc.append(l)
        out.append({"name": name, "idx": i - 1, "requirement": para(req, pdf), "desc": para(desc, pdf) if desc else "",
                    "deg": {d: para(v, pdf) for d, v in deg.items()}})
    return out


def spec_flavor(lines, name, start, stop, pdf):
    """Paragraphs between a specialization's heading and its talent block: the description and the Synergies note."""
    j = next((k for k in range(stop - 1, start - 1, -1) if lines[k].upper() == name.upper()), None)
    if j is None:
        return None
    chunk = lines[j + 1:stop]
    side = next((k for k, l in enumerate(chunk) if l.upper().startswith("STACKED TALENTS")), None)
    if side is not None:      # the 'Stacked Talents and Specializations' sidebar sits inside the first specialization
        syn = chunk.index("SYNERGIES") if "SYNERGIES" in chunk else len(chunk)
        del chunk[side:syn]
    if "SYNERGIES" in chunk:
        k = chunk.index("SYNERGIES")
        return [para(chunk[:k], pdf), "<em>Synergies:</em> " + para(chunk[k + 1:], pdf)]
    return [para(chunk, pdf)]


def build_talents(pdf):
    pack = Pack("talents")
    lines = col_lines(pdf, 48, 65)
    # the intro of the Specializations section is printed over artwork and comes out in pieces: drop it
    cut = next(i for i, l in enumerate(lines) if l == "IzATIONS")
    first_spec = next(i for i, l in enumerate(lines) if i > cut and l.upper() == "ACADEMIC")
    del lines[cut:first_spec]
    # the intro of the Talents section runs across both columns, and the first talents are interleaved with it
    a = next(i for i, l in enumerate(lines) if l == "ENTS")
    b = next(i for i, l in enumerate(lines) if i > a and l == "EXPERT" and lines[i + 1].startswith("When you move"))
    del lines[a:b]
    a = next(i for i, l in enumerate(lines) if l == "SPECIALI")
    b = next(i for i, l in enumerate(lines) if i > a and l == "EXPERT")
    del lines[a:b]
    blocks_ = parse_talent_blocks(lines, pdf)
    prev_end = 0
    for b in blocks_:
        name = smallcaps(b["name"])
        flavor = spec_flavor(lines, b["name"], prev_end, b["idx"], pdf)
        prev_end = b["idx"]
        spec = flavor is not None
        long_ = ("".join(p(x) if not x.startswith("<em>") else f"<p>{x}</p>" for x in flavor) if spec else "") + (p(b["desc"]) if b["desc"] else "")
        system = {"longDesc": long_, "shortDesc": "", "requirement": b["requirement"], "type": "spec" if spec else "talent", "degree": 0, "activate": True}
        for i, d in enumerate(DEGREE_LINES):
            system[f"degree{i}"] = {"desc": p(b["deg"][d]) if b["deg"][d] else "", "isActive": True}
        pack.item(name, "talent", system, "skills.svg", folder="Specializations" if spec else "Talents")
    return pack


# --------------------------------------------------------------------------- ability focuses (p45-47)

FOCUS_ENTRY = re.compile(r"^([A-Z][A-Za-z\- ]{2,30}): (.*)$")
ABILITY_HEAD = re.compile(r"^(" + "|".join(ABILITIES).upper() + r") FOCUSES$")


def build_focuses(pdf):
    pack = Pack("focuses")
    ability, cur = None, None
    for l in col_lines(pdf, 45, 47):
        m = ABILITY_HEAD.match(l.upper()) if l.isupper() else None
        if m:
            ability, cur = m.group(1).capitalize(), None
            continue
        if ability is None:
            continue
        m = FOCUS_ENTRY.match(l)
        if m and m.group(1).upper() == m.group(1) and m.group(1) != "OPTIONAL":
            cur = {"name": smallcaps(m.group(1)), "abl": ability, "lines": [m.group(2)]}
            pack.docs_pending = getattr(pack, "docs_pending", []) + [cur]
        elif cur is not None and not cur["lines"][-1].endswith((".", "!", "?")):
            cur["lines"].append(l)
        else:
            cur = None
    for f in pack.docs_pending:
        pack.item(f["name"], "focus", {"longDesc": p(para(f["lines"], pdf)), "useAbl": ABILITIES[f["abl"]], "initialValue": 2},
                  "gift-of-knowledge.svg", folder=f["abl"], uid=f"{f['abl']}:{f['name']}")
    return pack


BUILDERS = {"talents": build_talents, "focuses": build_focuses}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "packs" / "_source"))
    ap.add_argument("--only", default=",".join(BUILDERS))
    a = ap.parse_args()
    pdf = Path(a.pdf)
    if not pdf.is_file():
        sys.exit(f"PDF not found: {pdf}")
    words(pdf)
    for name in a.only.split(","):
        BUILDERS[name](pdf).write(a.out)


if __name__ == "__main__":
    main()
