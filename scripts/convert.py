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
from common import (ABILITIES, ICON, Pack, SYSTEM_STATS, Words, clean_lines, esc, journal_doc, li, make_id, modifier, num, p, paragraph,  # noqa: E402
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


def raw_lines(pdf, first, last):
    """Lines of PDF pages in content-stream order (the story order of the book), without running heads, page numbers and the epigraph
    quotes ('“...” / — Leviathan Wakes') that float in the margins."""
    out = []
    for t in pdftotext(pdf, first, last, "-raw"):
        out += [l.strip() for l in t.splitlines() if l.strip() and not re.fullmatch(r"\d{1,3}|\d+: [A-Z][A-Za-z &]+", l.strip())]
    res = []
    for l in out:
        if re.match(r"^— [A-Z][^.]{2,50}$", l):
            k = len(res) - 1
            while k >= 0 and len(res) - k <= 7 and not res[k].startswith("“"):
                k -= 1
            if k >= 0 and res[k].startswith("“"):
                del res[k:]
                continue
        res.append(l)
    return res


def item_entries(pdf, pages, label=r"(?:COST\s*(?:\d+|-|\*)|(?:\d+\+?|\d+ OR \d+)\s+SLOTS?)"):
    """[{name, cost, lines}] for the 'NAME COST n' (or 'NAME n SLOTS') entries of the pages, with the text that follows each heading
    in the book's story order, up to the next heading."""
    lines = raw_lines(pdf, min(pages), max(pages))
    out, cur, prev = [], None, None
    for l in lines:
        m = re.match(r"^(.+?)\s*(" + label + r")$", l)
        if m and m.group(1).replace("’", "'").upper() == m.group(1):
            if (m.group(1), m.group(2)) == prev:       # every heading is printed twice (dark text and its white shadow)
                continue
            prev = (m.group(1), m.group(2))
            cost = re.sub(r"^COST\s*", "", m.group(2))
            if cur is not None and not cur["lines"] and cur["cost"] == cost and cur["name"].endswith(m.group(1)):
                continue        # 'TOOLKIT, ELECTRONICS COST 7' printed again as 'ELECTRONICS COST 7' 
            cur = {"name": m.group(1).rstrip(), "cost": cost, "lines": []}
            out.append(cur)
            continue
        if cur is None:
            continue
        if re.fullmatch(r"ARMOR|BONUS PENALTY|ARMOR BONUS|[+\-–−]?\d", l):
            continue        # cells of a table that sits inside the text (Heads-Up Display)
        letters = [c for c in l if c.isalpha()]
        headingish = len(letters) >= 4 and sum(c.isupper() for c in letters) >= 0.75 * len(letters) and not re.search(r"[a-z]{3}", l)      # small capitals leave a stray lowercase letter
        if headingish and not l.startswith("AREA OF EFFECT") and not re.fullmatch(r"[A-Z0-9 .,+\-–−/()x×]*\d[A-Z0-9 .,+\-–−/()x×]*", l):
            cur = None
            continue
        cur["lines"].append(l)
    return out


ACRONYMS = {"Smg": "SMG", "Emp": "EMP", "Hud": "HUD", "Lva": "LVA", "Av": "AV", "Mmc": "MMC", "bobbi": "Bobbi"}


def item_name(raw):
    name = smallcaps(raw)
    return re.sub(r"\b(Smg|Emp|Hud|Lva|Av|Mmc|bobbi)\b", lambda m: ACRONYMS[m.group(1)], name)


def item_desc(e, pdf):
    """Description paragraphs of an entry: a leading 'AREA OF EFFECT ...' label stays its own paragraph."""
    lines = list(e["lines"])
    head = []
    if lines and lines[0].startswith("AREA OF EFFECT"):
        head.append(f"<p><strong>{esc(smallcaps(lines.pop(0)).replace('Area Of Effect', 'Area of Effect'))}</strong></p>")
    text_ = para(lines, pdf).replace("hard?ened", "hardened") if lines else ""
    if text_ and not re.search(r"[.!?)”]$", text_):
        text_ += "."
    return "".join(head) + (p(text_) if text_ else "")


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
        if name == "Heads-Up Display":        # the Space Suit Protection sidebar interrupts its text; the rest follows the sidebar table
            raw = raw_lines(pdf, 72, 73)
            k = next(i for i, l in enumerate(raw) if l.startswith("information like overview maps"))
            e["lines"] = e["lines"] + raw[k:k + 3]
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
    m = re.match(r"^(\d+)d(\d+)(?:([+-]\d+))?$", formula)
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


def build_implants(pdf):
    pack = Pack("implants")
    for e in item_entries(pdf, range(99, 104), label=r"((?:\d+\+?|\d+ OR \d+)\s+SLOTS?)"):
        name = item_name(e["name"])
        slots = e["cost"].title().replace("Or", "or")
        pack.item(name, "equipment", {
            "longDesc": f"<p><strong>Capacity:</strong> {esc(slots)}</p>" + item_desc({"lines": e["lines"]}, pdf), "shortDesc": slots, "weight": 0, "cost": 0,
            "quantity": 1, "equiped": False, "modifiers": {},
        }, "briefcase.svg", folder="Enhancement Implants")
    return pack


# --------------------------------------------------------------------------- sample spaceships (p146-153)

SIZES = {"Tiny": 1, "Small": 2, "Medium": 3, "Large": 4, "Huge": 5, "Gigantic": 6, "Colossal": 7, "Titanic": 8}
COMPETENCE = {"Incompetent": 0, "Poor": 1, "Average": 2, "Capable": 3, "Skilled": 4, "Elite": 5}
SHIP_FOLDERS = {"Small Craft": ("Shuttle", "Drop Ship", "Ship’s Boat"), "Freighters": ("Small Freighter", "Freighter", "Medium Freighter", "Large Freighter"),
                "Warships": ("Light Frigate", "Light Frigate (Transport Union Advanced)", "Heavy Frigate", "Destroyer", "Cruiser", "Battleship"),
                "Other Ships": ("Heavy Scout", "Colony Ship")}
SHIP_ICON = "systems/age-system/resources/imgs/actor-icon/rocket.svg"


def ship_lines(pdf):
    lines = raw_lines(pdf, 145, 155)
    start = next(i for i, l in enumerate(lines) if l == "SHuTTLE")
    end = next(i for i, l in enumerate(lines) if l == "SPACE COMBAT")
    return lines[start:end]


def build_ships(pdf):
    pack = Pack("ships", "Actor")
    lines = ship_lines(pdf)
    starts = [i for i, l in enumerate(lines) if l.startswith("SIZE.")]
    for n, i in enumerate(starts):
        name_line = lines[i - 1]
        if name_line.startswith("("):
            name_line = lines[i - 2] + " " + name_line
        end = starts[n + 1] - 1 if n + 1 < len(starts) else len(lines)
        if n + 1 < len(starts) and lines[starts[n + 1] - 1].startswith("("):
            end -= 1
        body = lines[i:end]
        text_ = " ".join(body)
        name = item_name(name_line)
        size = re.search(r"SIZE\.\s*(\w+) \((\d+) meters long\)", text_)
        hull = re.search(r"HULL\.?\s*(\d+)d(\d+)(?:\+(\d+))?", text_)
        crew = re.search(r"CREW\.?\s*(\d+) \((\d+)", text_)
        comp = re.search(r"COMPETENCE\.?\s*(\w+)(?: to (\w+))?", text_)
        drive = re.search(r"DRIVE\.?\s*(.+?)(?= SENSORS|\s\*|$)", text_)
        sens = re.search(r"SENSORS\.?\s*(\d+)", text_)
        assert size and hull and crew and comp and sens, f"ship {name}: unexpected stat block"
        qual = re.search(r"QUALITIES\.?\s*(.*?)\s*FLAWS\.?\s*(.*)$", text_)
        # weapons: names followed by 'RANGE... DAMAGE' lines
        wsec = re.search(r"WEAPONS\.?\s*(.*?)\s*QUALITIES", text_)
        items, parts = [], []
        for l in body[next((k for k, x in enumerate(body) if x.startswith("WEAPONS") and not re.search(r"WEAPONS\.? None", x)), len(body)):]:
            if l.startswith("QUALITIES"):
                break
            if l.startswith("WEAPONS"):
                rest = re.sub(r"^WEAPONS\.?\s*", "", l)
                if rest:
                    parts.append(rest)
                continue
            parts.append(l)
        weapon_lines, cur = [], []
        for l in parts:
            cur.append(l)
            if re.search(r"DAMAGE$", l):
                weapon_lines.append(cur)
                cur = []
        competence_txt = comp.group(0).split(None, 1)[1] if " " in comp.group(0) else comp.group(1)
        desc = (f"<p><strong>Competence:</strong> {esc(competence_txt)}</p>"
                f"<p><strong>Qualities:</strong> {esc(squash(qual.group(1)))}</p><p><strong>Flaws:</strong> {esc(squash(qual.group(2)))}</p>"
                f"<p><strong>Crew:</strong> {crew.group(1)} ({crew.group(2)})</p><p><strong>Size:</strong> {esc(size.group(1))} ({size.group(2)} meters long)</p>")
        did = make_id("ships", name)
        folder = next((f for f, names in SHIP_FOLDERS.items() if name in names), "Other Ships")
        pack.actor(name, "spaceship", {
            "size": SIZES[size.group(1)], "drive": squash(drive.group(1)).rstrip("*").strip() if drive else "", "description": desc,
            "hull": {"nrDice": int(hull.group(1)), "diceType": int(hull.group(2)), "extraValue": int(hull.group(3) or 0)},
            "crew": {"min": int(crew.group(1)), "current": int(crew.group(1)), "typical": int(crew.group(1)), "competence": COMPETENCE[comp.group(1).title()]},
            "systems": {"sensors": {"mod": int(sens.group(1))}},
        }, folder=folder, img=SHIP_ICON)
        actor = pack.docs[-1]
        actor["items"] = []
        for wl in weapon_lines:
            wtext = squash(" ".join(wl))
            m = re.match(r"^(.*?)\s*((?:FORE|AFT|FULL COVERAGE)?[^,]*,? ?(?:CLOSE|MEDIUM|LONG) RANGE.*?(\d+D6) DAMAGE|AFT, CLOSE RANGE, 0 DAMAGE)$", wtext)
            dmg = re.search(r"(\d+D6|0) DAMAGE$", wtext)
            wname = re.sub(r"\s*(FORE|AFT|FULL COVERAGE|MEDIUM RANGE|CLOSE RANGE|LONG RANGE).*$", "", wtext)
            iid = make_id(did, wname)
            actor["items"].append({"name": smallcaps(wname).replace("×", "×"), "type": "shipfeatures", "img": ICON + "processor.svg", "_id": iid,
                                   "_key": f"!actors.items!{actor['_id']}.{iid}", "flags": {}, "effects": [], "folder": None, "sort": 0, "_stats": SYSTEM_STATS,
                                   "system": {"type": "weapon", "damage": (dmg.group(1).lower() if dmg else ""), "quality": "quality", "isActive": True,
                                              "longDesc": p(smallcaps(wtext[len(wname):].strip(" ,")) if wtext[len(wname):].strip(" ,") else "")}})
    return pack


# --------------------------------------------------------------------------- adversaries and supporting characters (p251-266)

ADV_FOLDERS = {
    "Criminals": ("Bounty Hunter", "Gang Boss", "Pirate", "Pirate Captain", "Saboteur", "Smuggler", "Smuggler Captain", "Thug"),
    "Law and Security": ("Police Detective", "Police Officer", "Transport Union Security", "Transport Union Inspector"),
    "Military and Intelligence": ("Laconian Agent", "Laconian Black Ops", "Martian Marine", "Soldier", "Spy", "Veteran"),
    "Specialists": ("Ambassador", "Engineer", "Pilot"),
    "Machines": ("Combat Drone (Minor)", "Combat Drone (Moderate)", "Combat Drone (Major)", "Combat Mech"),
    "Aliens and Monsters": ("Hydrapod", "Death Slug", "Project Caliban Hybrid", "Mimic Lizard", "Ultrasalix", "Vomit Zombie", "Slithersquirrel"),
    "Supporting Characters": ("Zeroes", "Argo Dimas", "Cassidy Cooker", "Ohemaa Gbeho", "Tong Liu"),
}
ABL_NAMES = {"Accuracy": "acc", "Communication": "comm", "Constitution": "cons", "Dexterity": "dex", "Fighting": "fight", "Intelligence": "int",
             "Perception": "per", "Strength": "str", "Willpower": "will"}
ACTOR_IMG = "systems/age-system/resources/imgs/actor-icon/sensousness.svg"


def adversary_blocks(pdf):
    L = raw_lines(pdf, 245, 266)
    idx = [i for i, l in enumerate(L) if l == "ABILITIES (FOCUSES)"]
    out = []
    for n, i in enumerate(idx):
        end = idx[n + 1] - 2 if n + 1 < len(idx) else len(L)
        out.append((L[i - 1], L[i + 1:end], i))
    return L, out


def parse_adversary(name, body):
    stop = re.compile(r"^(SPEED FORTUNE|WEAPON ATTACK|SPECIAL FEATURES|Threat:|THREAT:)")
    k = next((j for j, l in enumerate(body) if stop.match(l)), len(body))
    abl_text = " ".join(body[:k])
    abilities, focuses = {}, {}
    for m in re.finditer(r"(" + "|".join(ABL_NAMES) + r")\s*([−–-]?\s*\d+)\s*(?:\(([^)]*)\))?", abl_text):
        key = ABL_NAMES[m.group(1)]
        abilities[key] = num(m.group(2).replace(" ", ""))
        focuses[key] = [x.strip() for x in (m.group(3) or "").split(",") if x.strip()]
    assert len(abilities) == 9, f"{name}: abilities {abl_text!r}"
    out = {"abilities": abilities, "focuses": focuses, "weapons": [], "features": [], "speed": None}
    rest = body[k:]
    if rest and rest[0].startswith("SPEED FORTUNE"):
        m = re.match(r"^(\d+)(?: \(([^)]*)\))? (\d+) (\d+) (.+)$", rest[1])
        assert m, f"{name}: stats line {rest[1]!r}"
        out.update(speed=int(m.group(1)), speed_note=m.group(2), fortune=int(m.group(3)), defense=int(m.group(4)), armor=m.group(5))
        rest = rest[2:]
    if rest and rest[0].startswith("WEAPON ATTACK"):
        j = next((q for q, l in enumerate(rest) if q and (l.startswith("SPECIAL FEATURES") or l.upper().startswith("THREAT:"))), len(rest))
        for l in rest[1:j]:
            m = re.match(r"^(.+?) ([+−–-]\d+) (\d+d\d+(?:\s*[+−–-]\s*\d+)?)(?: (.+))?$", l)
            if m:
                out["weapons"].append((m.group(1), num(m.group(2)), re.sub(r"\s+", "", m.group(3)).replace("−", "-").replace("–", "-"), m.group(4) or ""))
        rest = rest[j:]
    if rest and rest[0].startswith("SPECIAL FEATURES"):
        j = next((q for q, l in enumerate(rest) if l.upper().startswith("THREAT:")), len(rest))
        cur = None
        for l in rest[1:j]:
            m = re.match(r"^([A-Z][A-Za-z0-9 ’'\-()/,]{2,40}): (.*)$", l)
            if m:
                cur = [m.group(1), [m.group(2)]]
                out["features"].append(cur)
            elif cur:
                cur[1].append(l)
        rest = rest[j:]
    th = next((re.sub(r"^Threat:\s*", "", l, flags=re.I) for l in rest if l.upper().startswith("THREAT:") and len(l) > 8), "")
    out["threat"] = th.split()[0].title() if th else ""
    return out


def heading_like(l):
    letters = [c for c in l if c.isalpha()]
    return len(letters) >= 4 and sum(c.isupper() for c in letters) >= 0.75 * len(letters) and not re.search(r"[a-z]{3}", l)


def adversary_descriptions(L, names):
    """Paragraphs printed under a name heading that is not followed by a stat block, in the story order of the book."""
    out = {}
    keys = {n: re.sub(r"[^a-z]", "", n.lower()) for n in names}
    for i, l in enumerate(L):
        key = re.sub(r"[^a-z]", "", l.lower())
        hit = next((n for n, k in keys.items() if heading_like(l) and (key == k or key.startswith(k))), None)
        if not hit or hit in out:
            continue
        if i + 1 < len(L) and (L[i + 1] == l or L[i + 1] == "ABILITIES (FOCUSES)"):
            continue
        j, texts = i + 1, []
        while j < len(L) and not heading_like(L[j]) and not re.fullmatch(r"\d{3}", L[j]) and not L[j].startswith(("Threat:", "AKA:", "HOMEWORLD:")):
            texts.append(L[j])
            j += 1
        out[hit] = texts
    return out


def named_blocks(pdf):
    """The stat blocks of the named characters printed in the setting chapters: (name, subtitle, body lines)."""
    L = raw_lines(pdf, 166, 213)
    idx = [i for i, l in enumerate(L) if l == "ABILITIES (FOCUSES)"]
    out = []
    for n, i in enumerate(idx):
        end = idx[n + 1] - 4 if n + 1 < len(idx) else len(L)
        out.append((L[i - 3], L[i - 1], L[i + 1:end], i))
    return L, out


def build_adversaries(pdf):
    pack = Pack("adversaries", "Actor")
    L, blocks_ = adversary_blocks(pdf)
    named = [(n, sub, body, i) for n, sub, body, i in named_blocks(pdf)[1]]
    jobs = [(raw_name, body, None) for raw_name, body, i in blocks_] + [(n, body, sub) for n, sub, body, i in named]
    for raw_name, body, subtitle in jobs:
        name = item_name(raw_name)
        name = re.sub(r"\s*\((Minor|Moderate|Major)\)", lambda m: f" ({m.group(1)})", name)
        a = parse_adversary(name, body)
        folder = "Named Characters" if subtitle else next((f for f, ns in ADV_FOLDERS.items() if name in ns), None)
        assert folder, f"adversary without a folder: {name!r}"
        feats = f"<p><em>{esc(smallcaps(subtitle).replace(', ', ', '))}</em></p>" if subtitle else ""
        for label, lines_ in a["features"]:
            feats += f"<p><strong>{esc(smallcaps(label))}:</strong> {esc(para(lines_, pdf))}</p>"
        if a.get("armor") is not None:
            feats += f"<p><strong>Armor + Toughness:</strong> {a['armor']}</p>"
        if a.get("speed_note"):
            feats += f"<p><strong>Speed:</strong> {esc(a['speed_note'])}</p>"
        system = {
            "threat": a["threat"], "abilities": {k: {"value": v} for k, v in a["abilities"].items()},
            "speed": {"base": a["speed"] or 10}, "defense": {"base": a.get("defense", 10)},
            "health": {"set": a.get("fortune", 10), "value": a.get("fortune", 10)}, "features": feats, "statBlockView": True,
        }
        pack.actor(name, "char", system, folder=folder, img=ACTOR_IMG)
        actor = pack.docs[-1]
        actor["flags"] = {"core": {"sheetClass": "age-system.ageSystemSheetCharStatBlock"}}
        actor["prototypeToken"]["actorLink"] = False
        actor["items"] = []
        for key, fs in a["focuses"].items():
            for fname in fs:
                iid = make_id(actor["_id"], fname + key)
                actor["items"].append({"name": fname, "type": "focus", "img": ICON + "gift-of-knowledge.svg", "_id": iid, "_key": f"!actors.items!{actor['_id']}.{iid}",
                                       "flags": {}, "effects": [], "folder": None, "sort": 0, "_stats": SYSTEM_STATS,
                                       "system": {"useAbl": key, "initialValue": 2, "longDesc": ""}})
        for wname, atk, dmg, note in a["weapons"]:
            iid = make_id(actor["_id"], wname)
            n_, d_, extra = dice(dmg.replace("+-", "-"))
            ranged = wname.lower() in ("pistol", "rifle", "stun gun") or "gun" in wname.lower()
            actor["items"].append({"name": wname, "type": "weapon", "img": ICON + "fist.svg", "_id": iid, "_key": f"!actors.items!{actor['_id']}.{iid}",
                                   "flags": {}, "effects": [], "folder": None, "sort": 0, "_stats": SYSTEM_STATS,
                                   "system": {"longDesc": p(f"Attack roll {atk:+d}" + (f"; {note}" if note else "")), "useAbl": "acc" if ranged else "fight", "nrDice": n_, "diceType": d_,
                                              "extraValue": extra, "dmgAbl": "no-abl", "dmgType": "wound", "dmgSource": "penetrating" if "enetrating" in note else "normalDamage",
                                              "damageFormula": dmg, "weight": 0, "cost": 0, "quantity": 1, "equiped": False, "ranged": ranged}})
    descs = adversary_descriptions(L, [n for n, _, _ in blocks_])
    for doc in pack.docs:
        raw = next((n for n in descs if item_name(n) == doc["name"].replace(" (", " (")), None)
        if raw and descs[raw]:
            doc["system"]["features"] = p(para(descs[raw], pdf)) + doc["system"]["features"]
    return pack


# --------------------------------------------------------------------------- character creation (p27-44)

CLASSES = ("OUTSIDER", "LOWER", "MIDDLE", "UPPER")
CLASS_NAMES = {"OUTSIDER": "Outsider", "LOWER": "Lower Class", "MIDDLE": "Middle Class", "UPPER": "Upper Class"}
TYPES = ("SKILLED", "PHYSICAL", "SOCIAL")
BEN_ROW = re.compile(r"^(\d+(?:[–-]\d+)?) (.+)$")


def split_blocks(L, header, first=0, last=None):
    """[(match, lines)] for the lines between heading lines; a heading printed twice in a row counts once."""
    out, cur = [], None
    for l in L[first:last]:
        m = header.match(l)
        if m:
            if cur is not None and not cur[1]:
                continue                    # the shadow copy of the heading
            cur = (m, [])
            out.append(cur)
        elif cur is not None:
            cur[1].append(l)
    return out


def field(lines, label, stops):
    """Text of 'LABEL ...' up to the next line starting with one of `stops` (labels or headings)."""
    k = next((i for i, l in enumerate(lines) if l == label or l.startswith(label + " ")), None)
    if k is None:
        return None
    out = [lines[k][len(label):].strip()]
    for l in lines[k + 1:]:
        if any(l == x or l.startswith(x + " ") for x in stops) or l.isupper() and len(l) > 8 or l.startswith(("“", "—", "EXAMPLE")):
            break
        out.append(l)
    return " ".join(x for x in out if x)


def parse_backgrounds(pdf):
    L = raw_lines(pdf, 28, 34)
    header = re.compile(r"^([A-Z]+) (" + "|".join(CLASSES) + r")$")
    out = []
    for m, lines in split_blocks(L, header):
        name = smallcaps(m.group(1))
        k = next((i for i, l in enumerate(lines) if l.startswith("ABILITY ")), None)
        if k is None:
            continue
        desc = para(lines[:k], pdf)
        rest = lines[k:]
        ability = field(rest, "ABILITY", ("FOCUS", "TALENT"))
        focus = field(rest, "FOCUS", ("TALENT",))
        talent = field(rest, "TALENT", (name.upper() + " BENEFITS",))
        b = next(i for i, l in enumerate(rest) if l == name.upper() + " BENEFITS")
        rows = []
        for l in rest[b + 1:]:
            mm = BEN_ROW.match(l)
            if mm and not l.startswith("2D6"):
                rows.append((mm.group(1), mm.group(2)))
            if rows and rows[-1][0] == "12":
                break
        assert len(rows) == 8, f"{name}: benefits {rows}"
        out.append({"name": name, "cls": CLASS_NAMES[m.group(2)], "desc": desc, "ability": ability, "focus": focus, "talent": talent, "benefits": rows})
    return out


def parse_professions(pdf):
    L = raw_lines(pdf, 34, 41)
    header = re.compile(r"^([A-Z]+) (" + "|".join(TYPES) + r"), (" + "|".join(CLASSES) + r")$")
    out = []
    for m, lines in split_blocks(L, header):
        k = next((i for i, l in enumerate(lines) if l.startswith("FOCUS")), None)
        if k is None:
            continue
        desc = para([l for l in lines[:k] if not l.startswith(("“", "—"))], pdf)
        focus = field(lines[k:], "FOCUS", ("TALENT",))
        talent = field(lines[k:], "TALENT", ())
        out.append({"name": smallcaps(m.group(1)), "type": m.group(2).title(), "cls": CLASS_NAMES[m.group(3)], "desc": desc, "focus": focus, "talent": talent})
    by = {x["name"]: x for x in out}
    # printing errors and layout accidents of the book
    brawler = by["Brawler"]
    assert brawler["focus"].endswith("Style"), "Brawler layout changed"
    brawler["focus"], brawler["talent"] = brawler["talent"], brawler["focus"]       # focus and talent are printed swapped
    by["Dilettante"]["focus"] = "Intelligence (Research) or Perception (choose one)"
    tech, sec = by["Technician"], by["Security"]
    assert tech["talent"].startswith("Expertise, Hacking, or Maker focus on keeping"), "Technician layout changed"
    tail = re.search(r"Maker (focus on keeping.*?safe\.) FOCUS (.*?) TALENT (.*)$", tech["talent"])
    soldier_focus, soldier_talent = sec["focus"], sec["talent"]      # printed in the middle of Security's text
    tech["talent"] = "Expertise, Hacking, or Maker"
    sec["desc"] += " " + tail.group(1)
    sec["focus"], sec["talent"] = tail.group(2), tail.group(3)
    L = raw_lines(pdf, 34, 41)
    k = next(i for i, l in enumerate(L) if l == "SOLDIER PHYSICAL, LOWER")
    j = next(i for i, l in enumerate(L) if i > k + 1 and l == "CAREGIVER")
    out.append({"name": "Soldier", "type": "Physical", "cls": "Lower Class", "desc": para(L[k + 2:j], pdf), "focus": soldier_focus, "talent": soldier_talent})
    return sorted(out, key=lambda x: x["name"])


def parse_drives(pdf):
    L = raw_lines(pdf, 36, 46)
    names = ("ACHIEVER", "BUILDER", "CAREGIVER", "ECSTATIC", "JUDGE", "LEADER", "NETWORKER", "PENITENT", "PROTECTOR", "REBEL", "SURVIVOR", "VISIONARY")
    header = re.compile(r"^(" + "|".join(names) + r")$")
    blocks_ = split_blocks(L, header)
    # the last drive is followed by the Income section
    end = next(i for i, l in enumerate(L) if l == "INCOME")
    out, pending = {}, None
    for m, lines in blocks_:
        name = m.group(1)
        if name == "VISIONARY":
            lines = lines[: next(i for i, l in enumerate(lines) if l == "INCOME")] if "INCOME" in lines else lines
        k = next((i for i, l in enumerate(lines) if l.startswith("TALENT")), None)
        if k is None:
            pending = {"name": name, "lines": lines}
            out[name] = pending
            continue
        out[name] = {"name": name, "lines": lines[: k + 1]}
        extra = lines[k + 1:]
        if extra and pending is not None and not any(l.startswith("TALENT") for l in pending["lines"]):
            pending["lines"] = pending["lines"] + extra       # the rest of the previous drive is printed after this one (page layout)
            pending = None
    result = []
    for name in names:
        lines = out[name]["lines"]
        k = next(i for i, l in enumerate(lines) if l.startswith("TALENT"))
        text_ = para([l for l in lines[:k] if not l.startswith(("STEP 6", "DRIVE", "Roll 1d6"))], pdf)
        qd = re.search(r"Your quality is (.*?)\s*Your downfall is (.*)$", text_)
        talent = lines[k][len("TALENT"):].strip()
        result.append({"name": smallcaps(name), "desc": text_[: qd.start()].strip() if qd else text_, "quality": qd.group(1) if qd else "",
                       "downfall": qd.group(2) if qd else "", "talent": talent.replace("Contract or", "Contacts or")})      # 'Contract' is a misprint
    return result


def parse_origins(pdf):
    L = raw_lines(pdf, 27, 29)
    out = []
    for name in ("BELTER", "EARTHER", "MARTIAN"):
        k = next(i for i, l in enumerate(L) if l == name)
        j = next((i for i, l in enumerate(L) if i > k and (l in ("BELTER", "EARTHER", "MARTIAN", "STEP 4: BACkGROuNd") or l.startswith("EXAMPLE"))), len(L))
        body = L[k + 1:j]
        t = next(i for i, l in enumerate(body) if l.startswith("As a"))
        traits, cur = [], None
        for l in body[t + 1:]:
            if l.startswith("• "):
                cur = [l[2:]]
                traits.append(cur)
            elif cur is not None:
                cur.append(l)
        out.append({"name": smallcaps(name), "desc": para(body[:t], pdf), "intro": body[t], "traits": [para(x, pdf) for x in traits]})
    return out


def build_creation(pdf):
    pack = Pack("character-creation", "JournalEntry")
    journal_doc(pack, "Origins", [(o["name"], p(o["desc"]) + p(o["intro"]) + "<ul>" + "".join(f"<li>{esc(t)}</li>" for t in o["traits"]) + "</ul>") for o in parse_origins(pdf)])
    journal_doc(pack, "Backgrounds", [
        (b["name"], f"<p><em>{b['cls']}</em></p>" + p(b["desc"]) + "<ul>" + li("Ability", b["ability"]) + li("Focus", b["focus"]) + li("Talent", b["talent"]) + "</ul>"
         + f"<h2>{esc(b['name'])} Benefits</h2>" + table_html(["2d6 Roll", "Benefit"], b["benefits"])) for b in sorted(parse_backgrounds(pdf), key=lambda x: x["name"])])
    journal_doc(pack, "Professions", [
        (x["name"], f"<p><em>{x['type']}, {x['cls']}</em></p>" + p(x["desc"]) + "<ul>" + li("Focus", x["focus"]) + li("Talent", x["talent"]) + "</ul>") for x in parse_professions(pdf)])
    journal_doc(pack, "Drives", [
        (d["name"], p(d["desc"]) + "<ul>" + li("Quality", d["quality"]) + li("Downfall", d["downfall"]) + li("Talent", d["talent"]) + "</ul>") for d in parse_drives(pdf)])
    return pack


def ranges(text_):
    parts = [int(x) for x in re.split(r"[–-]", text_)]
    return parts[0], parts[-1]


def build_creation_tables(pdf):
    pack = Pack("creation-tables")
    L = raw_lines(pdf, 25, 46)
    # social class by origin (2d6)
    k = next(i for i, l in enumerate(L) if l == "BELTER EARTHER MARTIAN")
    rows = [re.match(r"^(\S+) (\S+) (\S+) (Outsider|Lower Class|Middle Class|Upper Class)$", l) for l in L[k + 1:k + 5]]
    assert all(rows), "social class table changed"
    for col, origin in enumerate(("Belter", "Earther", "Martian"), 1):
        table_doc(pack, f"Social Class ({origin})", "2d6", f"Social class of a {origin} character.",
                  [(*ranges(m.group(col)), m.group(4)) for m in rows], "Backgrounds")
    # backgrounds by social class (1d6)
    for cls in ("OUTSIDER", "LOWER CLASS", "MIDDLE CLASS", "UPPER CLASS"):
        k = next(i for i, l in enumerate(L) if l == cls and L[i + 1] == "BACKGROUNDS")
        res = []
        for l in L[k + 2:k + 9]:
            m = re.match(r"^(\d+(?:[–-]\d+)?) ([A-Z][a-z]+)$", l)
            if m:
                res.append((*ranges(m.group(1)), m.group(2)))
        assert len(res) == 3, f"{cls}: backgrounds {res}"
        table_doc(pack, f"{cls.title()} Backgrounds", "1d6", f"Backgrounds of the {cls.lower()} social class.", res, "Backgrounds")
    # benefits of each background (2d6)
    for b in parse_backgrounds(pdf):
        table_doc(pack, f"{b['name']} Benefits", "2d6", f"Benefits table of the {b['name']} background ({b['cls']}).",
                  [(*ranges(r), t) for r, t in b["benefits"]], "Benefits")
    # drives
    k = next(i for i, l in enumerate(L) if l.startswith("D6 COLUMN 1 COLUMN 2"))
    col1, col2 = [], []
    for l in L[k + 1:k + 7]:
        m = re.match(r"^(\d) (\w+) (\w+)$", l)
        assert m, f"drive table row {l!r}"
        col1.append(m.group(2))
        col2.append(m.group(3))
    table_doc(pack, "Drive Column", "1d6", "Roll 1d6: 1–3 = roll on Column 1, 4–6 = roll on Column 2 of the Drive table.", [(1, 3, "Column 1"), (4, 6, "Column 2")], "Drives")
    table_doc(pack, "Drive (Column 1)", "1d6", "Drives, column 1.", [(i + 1, i + 1, n) for i, n in enumerate(col1)], "Drives")
    table_doc(pack, "Drive (Column 2)", "1d6", "Drives, column 2.", [(i + 1, i + 1, n) for i, n in enumerate(col2)], "Drives")
    # determining abilities (3d6)
    k = next(i for i, l in enumerate(L) if l == "3D6 ROLL ABILITY SCORE")
    res = []
    for l in L[k + 1:k + 20]:
        m = re.match(r"^(\d+) ([−–-]?\d)$", l)
        if m:
            res.append((int(m.group(1)), num(m.group(2))))
    assert len(res) == 16, f"ability table {res}"
    rows_ = []
    for score in sorted({v for _, v in res}):
        rolls = [r for r, v in res if v == score]
        rows_.append((min(rolls), max(rolls), f"Ability score {score:+d}" if score else "Ability score 0"))
    table_doc(pack, "Determining Abilities", "3d6", "Roll once per ability (in order) and read the ability score.", rows_, "Ability Scores")
    return pack


# --------------------------------------------------------------------------- prose chapters (journals)

from blocks import book  # noqa: E402


def split_pages(bl, level=1, intro="Introduction"):
    """[(title, blocks)] with one entry per heading of `level`; blocks before the first one go under `intro`."""
    out, cur = [], [intro, []]
    for b in bl:
        if b[0] == "h" and b[1] == level:
            if cur[1]:
                out.append(cur)
            cur = [b[2], []]
        else:
            cur[1].append(b)
    if cur[1]:
        out.append(cur)
    return out


def chapter_pages(pdf, first, last, skip=(), skip_pages=(), stop_at=(), limit=16000, intro="Introduction"):
    """[(title, html)] for PDF pages first..last: one page per top-level heading, split at the next heading level when a page gets longer than `limit`."""
    pages, words_ = book(pdf)
    bl = []
    for n in range(first, last + 1):
        bl += prose.blocks_from_page(prose.prepare(pages[n]), words_)
    for i, b in enumerate(bl):
        if b[0] == "h" and b[2].strip() in stop_at:
            bl = bl[:i]
            break
    bl = prose.merge_paragraphs(bl, words_)
    bl = prose._drop_sections(bl, set(skip))
    out = []

    def emit(title, body, level):
        html_ = prose.render(body)
        if len(html_) > limit and level < 4:
            parts = split_pages(body, level + 1, "Overview")
            if len(parts) > 1:
                for t, sub in parts:
                    emit(f"{title}: {t}" if t != "Overview" else title, sub, level + 1)
                return
        if body:
            out.append((squash(title), html_))

    for t, body in split_pages(bl, 1, intro):
        if t.strip() in skip_pages:
            continue
        emit(t, body, 1)
    return out


BUILDERS = {"talents": build_talents, "focuses": build_focuses, "stunts": build_stunts,
            "equipment": build_equipment, "character-creation": build_creation, "creation-tables": build_creation_tables, "adversaries": build_adversaries, "ships": build_ships, "implants": build_implants, "weapons": build_weapons, "armor": build_armor, "shields": build_shields}


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
