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
    s = re.sub(r"\bSelf(?=[A-Z])", "Self-", s)
    s = re.sub(r"\b(a|an) (\d+) (penalty|to (?:this|the|all|their|your|attack|Defense|defense|initiative)\b)", r"\1 −\2 \3", s)   # the minus sign is lost
    return s.replace("handdrawn", "hand-drawn").replace("longdistance", "long-distance")


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
        return "-".join(x.capitalize() if i == 0 or x not in ("and", "of", "the", "in", "to") else x for i, x in enumerate(w.split("-")))
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


# --------------------------------------------------------------------------- stunts (p116-128, p155-159)

COST = re.compile(r"^(\d+)(?:[–-](\d+)|(\+))?$")
STUNT_NAME = re.compile(r"^([A-Z0-9][A-Z0-9’'\-!&,. ()/“”]{2,60}): ")
_LAYOUT = {}


def layout(pdf, page, x=0, w=612):
    key = (str(pdf), page, x, w)
    if key not in _LAYOUT:
        _LAYOUT[key] = pdftotext(pdf, page, page, "-layout", "-x", str(x), "-y", "0", "-W", str(w), "-H", "792")[0].splitlines()
    return _LAYOUT[key]


HEADER = re.compile(r"^\s*SP COST\s+STUNT\s*$")


def stunt_tables(pdf, pages, last_title=None):
    """[(title, note, rows)] for the 'SP COST / STUNT' tables on the pages. A table without a title above it continues the previous one."""
    out = []
    for page in pages:
        for x, w, full in ((0, 612, True), (0, 300, False), (300, 312, False)):
            lines = layout(pdf, page, x, w)
            for h, l in enumerate(lines):
                if not HEADER.match(l) or (full and (len(l.rstrip()) < 60 or len(l) - len(l.lstrip()) > 10)):
                    continue
                title, note = None, []
                for j in range(h - 1, max(h - 8, -1), -1):
                    t = lines[j].strip()
                    if t.endswith("STUNTS") and t.isupper():
                        title = t
                        break
                    if t:
                        note.insert(0, t)
                if title is None:
                    title, note = last_title, []
                last_title = title
                rows, text_col = [], None
                for r in lines[h + 1:]:
                    ind = len(r) - len(r.lstrip())
                    if text_col is None:
                        m = re.match(r"^(\s*(?:\d+(?:[–-]\d+|\+)?\s+)?)([A-Z0-9][^:]{1,60}: .*)$", r)
                        if m and STUNT_NAME.match(m.group(2)):
                            text_col = len(m.group(1))
                    long_ = len(r.strip()) > 6
                    cost_line = re.match(r"^\s*\d+(?:[–-]\d+|\+)?\s{2,}\S", r)
                    if text_col is not None and long_ and not cost_line and (ind < text_col - 3 or (r.strip().isupper() and r.strip().endswith("STUNTS"))):
                        break
                    rows.append(r)
                while rows and not rows[-1].strip():
                    rows.pop()
                out.append((title, " ".join(note), rows))
    return out


def parse_stunt_rows(rows):
    """[{cost, text}] from table rows: the cost sits in the left column, the text starts at the first stunt name."""
    nonblank = [r for r in rows if r.strip()]
    col = None
    for r in nonblank:
        m = re.match(r"^(\s*(?:\d+(?:[–-]\d+|\+)?\s+)?)([A-Z0-9][^:]{1,60}: .*)$", r)
        if m and STUNT_NAME.match(m.group(2)):
            col = len(m.group(1))
            break
    assert col is not None, "no stunt rows"
    entries_, cur = [], None
    for r in nonblank:
        left, right = r[:col].strip(), r[col:].strip()
        if STUNT_NAME.match(right) and (cur is None or re.search(r"[.)!?”]$", cur["text"][-1])):
            cur = {"cost": "", "text": [right]}
            entries_.append(cur)
        elif cur is not None and right:
            cur["text"].append(right)
        if left and cur is not None and not cur["cost"] and COST.match(left.replace("−", "-")) and int(re.match(r"\d+", left).group(0)) < 10:
            cur["cost"] = left
    return entries_


def build_stunts(pdf):
    pack = Pack("stunts")
    last = None
    for title, note, rows in stunt_tables(pdf, list(range(116, 129)) + list(range(155, 160))):
        for e in parse_stunt_rows(rows):
            full = squash(" ".join(e["text"]))
            name, desc = full.split(": ", 1)
            assert e["cost"], f"no SP cost for {name!r} in {title}"
            m = COST.match(e["cost"].replace("−", "-"))
            lo = int(m.group(1))
            hi = int(m.group(2)) if m.group(2) else lo
            plus = bool(m.group(3))
            kind = smallcaps(title.replace(" STUNTS", "").replace("&", "AND")).replace("And", "&")
            fixed = hi == lo and not plus
            cost = f"{lo}+" if plus else (f"{lo}–{hi}" if hi > lo else str(lo))
            long_ = f"<p><em>Cost: {cost} SP</em></p>" + (f"<p><em>{esc(note)}</em></p>" if note else "") + p(desc)
            pack.item(smallcaps(name), "stunts", {
                "longDesc": long_, "type": kind, "stuntPoints": lo, "stuntPointsMax": hi, "costType": "fixed" if fixed else "variable",
            }, "split-cross.svg", folder=kind, uid=f"{kind}:{name}")
    return pack


# --------------------------------------------------------------------------- positioned page elements (pdftohtml -xml)

import prose  # noqa: E402

ZW = 918            # width of the XML page space
MIDX = ZW / 2


def page_elements(pdf, n):
    """Text elements of a page without running heads/page numbers and without the white duplicates of dark headings."""
    if "pages" not in _BOOK:
        _BOOK["pages"] = prose.load(pdf)
    els = [e for e in _BOOK["pages"][n] if e["top"] > 70 and e["top"] < 1120 and "VenusRising" not in e["family"] and prose.plain(e["html"]).strip()]
    out = []
    for e in els:
        dup = next((o for o in els if o is not e and abs(o["top"] - e["top"]) <= 2 and abs(o["left"] - e["left"]) <= 2
                    and prose.plain(o["html"]).strip() == prose.plain(e["html"]).strip() and o["color"] == "#ffffff" and e["color"] != "#ffffff"), None)
        white_twin = e["color"] == "#ffffff" and any(o is not e and abs(o["top"] - e["top"]) <= 2 and abs(o["left"] - e["left"]) <= 2
                                                      and prose.plain(o["html"]).strip() == prose.plain(e["html"]).strip() and o["color"] != "#ffffff" for o in els)
        if not white_twin:
            out.append(e)
    return out


def txt(e):
    return re.sub(r"\s+", " ", prose.plain(prose.convert_markup(e["html"]))).strip()


def is_item_head(e):
    return e["size"] == 15 and e["color"] != "#ffffff" and txt(e).replace("’", "'").upper() == txt(e).replace("’", "'") or (e["size"] == 15 and e["color"] in ("#0e4f75",))


def item_entries(pdf, pages):
    """[{name, cost, page, lines}] for entries made of a size-15 heading and a 'COST n' label on the same row, with their text below
    (the text of an entry is read inside its column, or across the whole page for a full-width entry)."""
    out = []
    for n in pages:
        els = page_elements(pdf, n)
        heads = []
        size15 = sorted([e for e in els if e["size"] == 15], key=lambda e: (e["top"], e["left"]))
        rows15 = []
        for e in size15:
            if rows15 and abs(rows15[-1][0]["top"] - e["top"]) <= 3:
                rows15[-1].append(e)
            else:
                rows15.append([e])
        for row in rows15:
            parts = []
            for e in sorted(row, key=lambda e: e["left"]):
                t = txt(e)
                m = re.match(r"^(.+?)\s+COST\s*(\d+|-|\*)$", t)
                if m:
                    name, cost, left, right = m.group(1), m.group(2), e["left"], e["left"] + e["width"]
                elif re.match(r"^COST\s*(\d+|-|\*)$", t) and parts:
                    name, cost, left, right = " ".join(txt(x) for x in parts), re.sub(r"^COST\s*", "", t), parts[0]["left"], e["left"] + e["width"]
                    nm = parts[0]
                    above = [x for x in size15 if 10 < nm["top"] - x["top"] < 30 and abs(x["left"] - nm["left"]) < 6 and not re.match(r"^COST", txt(x))]
                    if above:        # a name that wraps onto two lines has its first line directly above
                        name = txt(above[0]) + " " + name
                else:
                    if not re.match(r"^COST", t):
                        parts.append(e)
                    continue
                name = re.sub(r"(?<!\S)(\S+) \1(?!\S)", r"\1", name)
                full = right > 700 and left < 300
                zone = (0, ZW) if full else ((0, MIDX) if left < MIDX else (MIDX, ZW))
                heads.append({"name": name, "cost": cost, "top": row[0]["top"], "zone": zone, "page": n})
                parts = []
        heads.sort(key=lambda h: h["top"])
        stops = [e for e in els if (e["family"].startswith("Spectrashell") and e["size"] >= 21) or (e["size"] == 17 and e["color"] == "#ffffff")
                 or (e["size"] == 15 and e["color"] != "#ffffff" and not re.search(r"COST\s*(\d+|-|\*)$", txt(e)) and not any(abs(h["top"] - e["top"]) <= 3 for h in heads))]
        for h in heads:
            nxt = [x["top"] for x in heads if x["top"] > h["top"] + 3 and x["zone"][0] < h["zone"][1] and x["zone"][1] > h["zone"][0]]
            nxt += [e["top"] for e in stops if e["top"] > h["top"] + 3 and (e["left"] < h["zone"][1] and e["left"] + e["width"] > h["zone"][0]
                                                                            or (e["family"].startswith("Spectrashell") and e["size"] >= 30))]
            end = min(nxt) if nxt else 10 ** 6
            body = [e for e in els if h["top"] + 3 < e["top"] < end and e["size"] in (13, 14, 15) and h["zone"][0] - 5 <= e["left"] + e["width"] / 2 <= h["zone"][1]
                    and not re.search(r"COST\s*(\d+|-|\*)$", txt(e))]
            h["lines"] = [" ".join(txt(x) for x in ln["els"]) for ln in prose.lines_of(body)]
            if h["name"] == "HEADS-UP DISPLAY":        # the text wraps around a table of numbers
                h["lines"] = [re.sub(r"^(?:[+\-–−]?\d\s+)+", "", re.sub(r"(?<=\s)[+\-–−]\d(?=\s)", "", l)) if "cost" not in l else l for l in h["lines"]]
            h["lines"] = [l for l in h["lines"] if not re.fullmatch(r"[+\-–−]?\d+|ARMOR|BONUS PENALTY|ARMOR ARMOR", l)]
            h["last"] = not nxt
            out.append(h)
    # a left-column entry that ends mid-sentence continues at the top of the right column
    for h in out:
        if h["last"] and h["lines"] and not re.search(r"[.!?)”]$", h["lines"][-1]) and h["zone"] == (0, MIDX):
            els = page_elements(pdf, h["page"])
            zone = (MIDX, ZW)
            tops = [e["top"] for e in els if ((e["family"].startswith("Spectrashell") and e["size"] >= 21) or (e["size"] in (15, 17) and e["color"] != "#ffffff"))
                    and e["left"] < zone[1] and e["left"] + e["width"] > zone[0]]
            first_stop = min(tops or [10 ** 6])
            body = [e for e in els if e["top"] < first_stop and e["size"] in (13, 14) and zone[0] - 5 <= e["left"] + e["width"] / 2 <= zone[1]]
            h["lines"] += [" ".join(txt(x) for x in ln["els"]) for ln in prose.lines_of(body)]
    # an entry that ends mid-sentence at the foot of a page continues at the top of the next one: a right-column entry in the left column
    for h in out:
        if h["last"] and h["lines"] and not re.search(r"[.!?)”]$", h["lines"][-1]) and h["page"] + 1 <= max(pages) + 1 and h["zone"] != (0, ZW):
            els = page_elements(pdf, h["page"] + 1)
            zone = (0, MIDX) if h["zone"][0] > 0 else h["zone"]
            tops = [e["top"] for e in els if ((e["family"].startswith("Spectrashell") and e["size"] >= 21) or (e["size"] in (15, 17) and e["color"] != "#ffffff"))
                    and e["left"] < zone[1] and e["left"] + e["width"] > zone[0]]
            first_stop = min(tops or [10 ** 6])
            body = [e for e in els if e["top"] < first_stop and e["size"] in (13, 14) and zone[0] - 5 <= e["left"] + e["width"] / 2 <= zone[1]]
            if body:
                h["lines"] += [" ".join(txt(x) for x in ln["els"]) for ln in prose.lines_of(body)]
    return out


# --------------------------------------------------------------------------- equipment, weapons and armor (p70-88)

ACRONYMS = {"Smg": "SMG", "Emp": "EMP", "Hud": "HUD", "Lva": "LVA"}


def item_name(raw):
    name = smallcaps(raw)
    return re.sub(r"\b(Smg|Emp|Hud|Lva)\b", lambda m: ACRONYMS[m.group(1)], name)


def item_desc(e, pdf):
    """Description paragraphs of an entry: a leading 'AREA OF EFFECT ...' label stays its own paragraph."""
    lines = list(e["lines"])
    head = []
    if lines and lines[0].startswith("AREA OF EFFECT"):
        head.append(f"<p><strong>{esc(smallcaps(lines.pop(0)).replace('Area Of Effect', 'Area of Effect'))}</strong></p>")
    return "".join(head) + p(para(lines, pdf)) if lines else "".join(head)


GEAR_FOLDERS = {
    "Electronic Equipment": ("Computer Terminal", "Hand Terminal", "Motion Tracker", "Night Vision Goggles", "Signal Jammer", "Thermal Goggles"),
    "Survival Gear": ("Decompression Kit", "Emergency Airlock", "Emergency Seal Kit", "Environment Suit", "Form-Fitting Space Suit", "Heads-Up Display",
                      "Rescue-and-Recovery Kit", "Thruster Pack", "Vac Suit"),
    "Drones": ("Advertising Drone", "Crowd-Suppression Drone", "Freight Drone", "Loader Drone", "Relay Drone", "Sampling Drone", "Security Drone", "Surveillance Drone"),
    "Mechs": ("Construction Mech (Standard)", "Construction Mech (Giant)", "Exoskeleton Mech", "Lifting Mech", "Loader Mech", "Salvage Mech", "Support Mech"),
    "Tools": ("Chemistry Deck", "Machine Shop", "Toolkit, Electronics", "Toolkit, Engineering"),
}


def gear_entries(pdf):
    return item_entries(pdf, range(70, 77))


def build_equipment(pdf):
    pack = Pack("equipment")
    seen = set()
    for e in gear_entries(pdf):
        name = item_name(e["name"])
        folder = next((f for f, names in GEAR_FOLDERS.items() if name in names), None)
        assert folder, f"equipment without a folder: {name!r}"
        seen.add(name)
        pack.item(name, "equipment", {
            "longDesc": item_desc(e, pdf), "weight": 0, "cost": num(e["cost"]), "quantity": 1, "equiped": False, "modifiers": {},
        }, "briefcase.svg", folder=folder)
    missing = {n for names in GEAR_FOLDERS.values() for n in names} - seen
    assert not missing, f"gear not found: {missing}"
    return pack


# weapon -> (category, damage dice, damage ability, ranged, focus, ability)
CLOSE = {"Ceramic Tactical Knife": ("1d6", "str", "light"), "Combat Knife": ("1d6", "str", "light"), "Sword": ("2d6", "str", "heavy"), "Stun Baton": ("1d6", "no-abl", "light")}
PISTOLS = ("Automatic Machine Pistol", "Flechette Pistol", "Semi-Automatic Pistol", "Revolver", "Stun Pistol")
RIFLES = ("Assault Rifle", "Riot Gun", "Shotgun", "Sniper Rifle", "Submachine Gun (SMG)")
GRENADES = {"EMP Grenade": "0", "Flash Grenade": "2d6", "Fragmentation Grenade": "4d6+6", "Homemade Grenade": "3d6+6", "Incendiary Grenade": "4d6",
            "Smoke Grenade": "0", "Suppression Grenade": "0"}


def dice(formula):
    m = re.match(r"^(\d+)d(\d+)(?:\+(\d+))?$", formula)
    return (m.group(1), m.group(2), int(m.group(3) or 0)) if m else ("0", "6", int(formula or 0))


def weapon_system(desc, cost, formula, abl, ranged=False, focus="", rng=0, rng_max=0, penetrating=False, str_min=0):
    n, d, extra = dice(formula)
    s_ = {"longDesc": desc, "useAbl": "acc" if ranged else "fight", "useFocus": focus, "minStr": str_min, "nrDice": n, "diceType": d, "extraValue": extra,
          "dmgAbl": abl, "dmgType": "wound", "dmgSource": "penetrating" if penetrating else "normalDamage", "damageFormula": formula, "weight": 0,
          "cost": cost, "quantity": 1, "equiped": False, "ranged": ranged}
    if ranged:
        s_.update({"range": rng, "rangeMax": rng_max})
    return s_


def build_weapons(pdf):
    pack = Pack("weapons")
    entries_ = {item_name(e["name"]): e for e in item_entries(pdf, range(77, 84))}
    for name, (formula, abl, kind) in CLOSE.items():
        e = entries_[name]
        note = f"<p><em>Damage as a {kind} close weapon{' (Strength does not add to the damage)' if abl == 'no-abl' else ''}.</em></p>"
        pack.item(name, "weapon", weapon_system(item_desc(e, pdf) + note, num(e["cost"]), formula, abl, focus="light weapons" if kind == "light" else "heavy weapons"),
                  "fist.svg", folder="Close Weapons")
    for name in PISTOLS + RIFLES:
        e = entries_[name]
        pistol = name in PISTOLS
        stun = name == "Stun Pistol"
        formula = "1d6" if stun else ("2d6" if pistol else ("4d6" if name == "Sniper Rifle" else "3d6"))
        rng, rng_max = (50, 75) if pistol else (200, 300)
        pack.item(name, "weapon", weapon_system(item_desc(e, pdf), num(e["cost"]), formula, "per", True, "pistols" if pistol else "rifles", rng, rng_max, penetrating=stun),
                  "fist.svg", folder="Pistols" if pistol else "Rifles")
    e = entries_["Grenade Launcher"]
    pack.item("Grenade Launcher", "weapon", weapon_system(item_desc(e, pdf) + "<p><em>Damage is the same as the grenade fired.</em></p>", num(e["cost"]), "0", "no-abl", True,
                                                         "grenades", 150, 350), "fist.svg", folder="Rifles")
    for name, formula in GRENADES.items():
        e = entries_[name]
        pack.item(name, "weapon", weapon_system(item_desc(e, pdf) + "<p><em>Thrown: short range 4 m, long range 8 m (Accuracy (Throwing) test, TN 11).</em></p>", num(e["cost"]), formula, "no-abl", True,
                                                "throwing", 4, 8), "fist.svg", folder="Grenades")
    # generic weapons of the Attack Damage table (p107)
    for name, formula, abl, ranged, focus, cost, rng in (("Generic Light Close Weapon", "1d6", "str", False, "light weapons", 6, 0), ("Generic Heavy Close Weapon", "2d6", "str", False, "heavy weapons", 7, 0),
                                                         ("Generic Pistol", "2d6", "per", True, "pistols", 10, 50), ("Generic Rifle", "3d6", "per", True, "rifles", 12, 200)):
        pack.item(name, "weapon", weapon_system(p("Simplified weapon of the Generic Weapons table, for games that do not need the details of individual weapons."), cost, formula, abl, ranged, focus, rng,
                                                int(rng * 1.5)), "fist.svg", folder="Generic Weapons")
    pack.item("Unarmed Attack", "weapon", weapon_system(p("1d3 + Strength (1d6 with the Striking Style talent)."), 0, "1d3", "str", focus="brawling"), "fist.svg", folder="Generic Weapons")
    pack.item("Makeshift Weapon", "weapon", weapon_system(p("An object not made for combat. The GM may apply the Clumsy, Fragile or Weak drawbacks."), 0, "1d6", "str"), "fist.svg", folder="Generic Weapons")
    return pack


ARMORS = (("Padding", 1, 0, 8), ("Light Armor", 2, 1, 12), ("Medium Armor", 4, 2, 14), ("Light Vacuum Armor", 4, 3, 17), ("Riot Armor", 5, 3, 13), ("Heavy Armor", 6, 3, 16))
SHIELDS = (("Riot Shield", 2, 13), ("Ballistic Shield", 3, 14))


def build_armor(pdf):
    pack = Pack("armor")
    entries_ = {item_name(e["name"]): e for e in item_entries(pdf, range(86, 88))}
    for name, bonus, pen, cost in ARMORS:
        e = entries_[name]
        assert num(e["cost"]) == cost, f"{name}: cost {e['cost']} differs from the table"
        mods = dict([modifier("impactArmor", bonus), modifier("armorPenalty", pen)])
        pack.item(name, "equipment", {
            "longDesc": item_desc(e, pdf) + p(f"Armor bonus +{bonus}, armor penalty {-pen if pen else 0}, Income TN {cost}."), "weight": 0, "cost": cost, "quantity": 1,
            "equiped": False, "modifiers": mods,
        }, "briefcase.svg")
    power = [l for l in pdftotext(pdf, 88, 88, "-layout", "-x", "240", "-W", "372", "-y", "60", "-H", "600")[0].splitlines() if l.strip()]
    lines = [l.strip() for l in power]
    start = lines.index("POWER ARMOR") + 1
    end = next(i for i, l in enumerate(lines) if "(see Interludes in" in l) + 1
    lines.append("Chapter 5).")
    end += 1
    mods = dict([modifier("impactArmor", 12)])
    pack.item("Power Armor", "equipment", {
        "longDesc": p(para(lines[start:end], pdf)) + p("Armor bonus +12, armor penalty 0. Not available for purchase."), "weight": 0, "cost": 0, "quantity": 1, "equiped": False, "modifiers": mods,
    }, "briefcase.svg")
    return pack


def build_shields(pdf):
    pack = Pack("shields")
    entries_ = {item_name(e["name"]): e for e in item_entries(pdf, range(86, 88))}
    for name, bonus, cost in SHIELDS:
        e = entries_[name]
        assert num(e["cost"]) == cost
        pack.item(name, "equipment", {
            "longDesc": item_desc(e, pdf) + p(f"Defense bonus +{bonus}, Income TN {cost}."), "weight": 0, "cost": cost, "quantity": 1, "equiped": False,
            "modifiers": dict([modifier("defense", bonus)]),
        }, "briefcase.svg")
    return pack


BUILDERS = {"talents": build_talents, "focuses": build_focuses, "stunts": build_stunts,
            "equipment": build_equipment, "weapons": build_weapons, "armor": build_armor, "shields": build_shields}


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
