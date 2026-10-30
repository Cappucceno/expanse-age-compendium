"""Turn running text of the Modern AGE PDF into HTML, using the positions and fonts from `pdftohtml -xml`.

The book is typeset in two columns with a few fixed typefaces, so headings, bold/italic lead-ins, bullets, paragraphs
and simple tables can be recognised from fonts and coordinates alone.
"""
import html
import re
import subprocess
from collections import defaultdict

PAGE_W = 918          # width of the XML page space (the PDF page is 612 pt wide)
MID = PAGE_W / 2
LINE_TOL = 6          # elements within this many units vertically are on the same line
PARA_GAP = 24         # a vertical step bigger than this between two lines starts a new paragraph
CELL_GAP = 30         # horizontal gap between two elements of a line above which they are table cells
HEAD_TOP = 70         # running heads sit above this
FOOTER_TOP = 1120
BODY = ("#1d1d1b", "#231f20")

TEXT = re.compile(r'<text top="(-?\d+)" left="(-?\d+)" width="(\d+)" height="(\d+)" font="(\d+)">(.*?)</text>', re.S)
FONT = re.compile(r'<fontspec id="(\d+)" size="(\d+)" family="([^"]*)" color="([^"]*)"')


def load(pdf):
    xml = subprocess.run(["pdftohtml", "-xml", "-i", "-stdout", str(pdf)], check=True, capture_output=True, text=True).stdout
    fonts = {m.group(1): (int(m.group(2)), m.group(3).split("+")[-1], m.group(4)) for m in FONT.finditer(xml)}
    pages = {}
    for chunk in re.split(r"<page ", xml)[1:]:
        num = int(re.match(r'number="(\d+)"', chunk).group(1))
        els = []
        for m in TEXT.finditer(chunk):
            top, left, width, height, font, body = m.groups()
            size, family, color = fonts[font]
            els.append({"top": int(top), "left": int(left), "width": int(width), "size": size, "family": family,
                        "color": color, "html": body, "page": num})
        pages[num] = els
    return pages


def heading_level(el):
    """h1..h4 for the heading typefaces of the Transport Union Edition, None for body text."""
    white = el["color"] in ("#ffffff", "#f6f6f6")
    fam, s = el["family"], el["size"]
    if fam.startswith("Spectrashell"):
        if white:
            return 1 if s >= 40 else (2 if s >= 30 else (4 if s >= 20 else None))
        if s >= 30:
            return 2
        if s >= 20:
            return 3
        return None
    if fam.startswith("ProximaNova") and s == 15 and not white:
        return 4
    return None


def titlecase(s):
    """Small-capital headings come out with stray lowercase capitals ('PLAYING YOuR CHARACTER'): restore a title case."""
    small = ("of", "and", "the", "in", "to", "a", "for", "on", "vs.")
    words = s.strip().lower().split()
    out = [w if (i and w in small) else "-".join(x.capitalize() for x in w.split("-")) for i, w in enumerate(words)]
    return re.sub(r"\((\w)", lambda m: "(" + m.group(1).upper(), " ".join(out)).replace("’S", "’s")


def convert_markup(h):
    """Inline markup from pdftohtml -> HTML (bold/italic only)."""
    h = re.sub(r"<(/?)b>", lambda m: f"<{m.group(1)}strong>", h)
    h = re.sub(r"<(/?)i>", lambda m: f"<{m.group(1)}em>", h)
    h = re.sub(r"<a [^>]*>|</a>", "", h)
    return h


def plain(h):
    return html.unescape(re.sub(r"<[^>]+>", "", h))


def fix_small_caps(els):
    """Nothing to do in this book: its small capitals are handled when a heading is turned into a title (titlecase)."""
    return


def prepare(els):
    """Page elements without running heads, page numbers and the white shadow copies of dark headings."""
    keep = []
    for e in els:
        if e["top"] <= HEAD_TOP or e["top"] >= FOOTER_TOP or "VenusRising" in e["family"]:
            continue
        t = plain(e["html"]).strip()
        if not t:
            continue
        if e["color"] == "#ffffff" and any(o is not e and o["color"] != "#ffffff" and abs(o["top"] - e["top"]) <= 2 and abs(o["left"] - e["left"]) <= 2
                                           and plain(o["html"]).strip() == t for o in els):
            continue
        keep.append(e)
    return keep


def lines_of(els):
    """Group elements into visual lines, left to right."""
    out = []
    for e in sorted(els, key=lambda e: (e["top"], e["left"])):
        for ln in out:
            if abs(ln["top"] - e["top"]) <= LINE_TOL:
                ln["els"].append(e)
                break
        else:
            out.append({"top": e["top"], "els": [e]})
    for ln in out:
        ln["els"].sort(key=lambda e: e["left"])
        ln["left"] = ln["els"][0]["left"]
    return out


def split_columns(els):
    """Elements -> segments in reading order. A row with an element crossing the page middle is full width and splits
    the page into bands; inside a band the left column is read before the right one."""
    rows = lines_of(els)
    full_tops, full = [], []
    for ln in rows:
        if any(e["left"] < MID - 20 and e["left"] + e["width"] > MID + 20 for e in ln["els"]):
            full_tops.append(ln["top"])
            full.append(ln["els"])
    segs = []
    bounds = [-10**6] + sorted(full_tops) + [10**6]
    full_by_top = dict(zip(full_tops, full))
    last_full = False
    for lo, hi in zip(bounds, bounds[1:]):
        if lo in full_by_top:
            if last_full:
                segs[-1] = segs[-1] + full_by_top[lo]   # consecutive full-width rows read as one block
            else:
                segs.append(list(full_by_top[lo]))
            last_full = True
        band = [e for ln in rows if lo < ln["top"] < hi and ln["top"] not in full_by_top for e in ln["els"]]
        left = [e for e in band if e["left"] + e["width"] / 2 < MID]
        right = [e for e in band if e["left"] + e["width"] / 2 >= MID]
        if last_full and left and not right and min(e["top"] for e in left) - lo <= PARA_GAP:
            segs[-1] = segs[-1] + left       # short last line of a full-width paragraph
            continue
        if left or right:
            last_full = False
        segs += [x for x in (left, right) if x]
    return segs


def is_table_row(ln):
    els = ln["els"]
    if len(els) < 3:
        return False
    gaps = [b["left"] - (a["left"] + a["width"]) for a, b in zip(els, els[1:])]
    return sum(g > CELL_GAP for g in gaps) >= 2


def cells_of(ln):
    cells, cur, last = [], [], None
    for e in ln["els"]:
        if last is not None and e["left"] - last > CELL_GAP:
            cells.append(cur)
            cur = []
        cur.append(e)
        last = e["left"] + e["width"]
    cells.append(cur)
    return ["".join(convert_markup(x["html"]) for x in c).strip() for c in cells]


class Words:
    def __init__(self, text):
        self.known = set(re.findall(r"\b[a-z]{3,}\b", text))
        try:   # a system word list (Debian: wamerican) decides line-end hyphens in words the book uses only once
            with open("/usr/share/dict/words", encoding="utf-8") as f:
                self.dictionary = {w.strip().lower() for w in f if w.strip().isalpha()}
        except OSError:
            self.dictionary = set()

    def join(self, left, right):
        l, r = left.rstrip(), right.lstrip()
        pl, pr = plain(l), plain(r)
        if re.search(r"[A-Za-z]-$", pl) and pr[:1].islower():
            stem = pl[:-1]
            first = re.match(r"[A-Za-z]*", pr).group(0).lower()
            last = re.split(r"[^A-Za-z]", stem)[-1].lower()
            joined = last + first
            drop = joined in self.known or joined in self.dictionary or not (last in self.known and first in self.known)
            if drop:
                l = re.sub(r"-((?:</[a-z]+>)*)$", r"\1", l)
            return l + r
        return l + " " + r


def blocks_from_page(els, words):
    """Yield ('h', level, text) / ('p', html) / ('li', html) / ('table', rows) for one page, in reading order."""
    out = []
    for seg in split_columns(els):
        lines = lines_of(seg)
        para, prev_top, rows = None, None, []
        cap = ""

        def flush_para():
            nonlocal para
            if para is not None:
                out.append(para)
                para = None

        def flush_rows():
            nonlocal rows
            if rows:
                out.append(("table", rows))
                rows = []

        for ln in lines:
            text = "".join(convert_markup(e["html"]) for e in ln["els"]).strip()
            if not plain(text).strip():
                continue
            lvl = heading_level(ln["els"][0])
            first = ln["els"][0]
            if first["color"] == "#ffffff" and first["size"] <= 12 and not lvl and len(ln["els"]) > 1 and all(e["color"] != "#ffffff" for e in ln["els"][1:]):
                # a label on a dark bar (NOVICE, EXAMPLE, a quality name) followed by its text on the same row
                flush_para()
                flush_rows()
                label = html.escape(plain(convert_markup(first["html"])).strip())
                rest = "".join(convert_markup(e["html"]) for e in ln["els"][1:]).strip()
                para = ["p", f"<strong>{label}</strong> {rest}"]
                prev_top = ln["top"]
                continue
            if lvl and all(heading_level(e) for e in ln["els"]):
                flush_para()
                flush_rows()
                size = ln["els"][0]["size"]
                if len(plain(text).strip()) <= 2 and (size >= 60 or plain(text).strip().isdigit()):   # drop cap or list number: glue to the next text line
                    cap = plain(text).strip() + (". " if plain(text).strip().isdigit() else "")
                    continue
                label = titlecase(" ".join(plain(convert_markup(e["html"])).strip() for e in ln["els"]).strip())
                if lvl == 6:
                    out.append(["p", f"<strong>{html.escape(label)}</strong>"])
                    prev_top = ln["top"]
                    continue
                if out and out[-1][0] == "h" and out[-1][1] == lvl and prev_top is not None and ln["top"] - prev_top < 60:
                    out[-1] = ("h", lvl, out[-1][2] + " " + label)   # headings that wrap over two lines
                else:
                    out.append(("h", lvl, label))
                prev_top = ln["top"]
                continue
            if is_table_row(ln):
                flush_para()
                rows.append(cells_of(ln))
                prev_top = ln["top"]
                continue
            flush_rows()
            if cap:
                text, cap = cap + text, ""
            bullet = plain(text).lstrip().startswith("•")
            gap = (ln["top"] - prev_top) if prev_top is not None else 999
            if bullet:
                flush_para()
                para = ["li", re.sub(r"^\s*(<[^>]+>)*•\s*", lambda m: m.group(1) if m.group(1) else "", text)]
            elif para is not None and para[0] in ("p", "li") and gap <= PARA_GAP:
                para[1] = words.join(para[1], text)
            else:
                flush_para()
                para = ["p", text]
            prev_top = ln["top"]
        flush_para()
        flush_rows()
    return [tuple(b) if isinstance(b, list) else b for b in out]


def render(blocks):
    """Blocks -> HTML string, merging consecutive list items and tidying inline tags."""
    html_, in_list = [], False
    for b in blocks:
        if b[0] != "li" and in_list:
            html_.append("</ul>")
            in_list = False
        if b[0] == "li":
            if not in_list:
                html_.append("<ul>")
                in_list = True
            html_.append(f"<li>{tidy(b[1])}</li>")
        elif b[0] == "p":
            html_.append(f"<p>{tidy(b[1])}</p>")
        elif b[0] == "h":
            html_.append(f"<h{b[1]}>{html.escape(re.sub(r'\s+', ' ', b[2]))}</h{b[1]}>")
        elif b[0] == "table":
            html_.append(table(b[1]))
    if in_list:
        html_.append("</ul>")
    return "".join(html_)


def tidy(h):
    h = re.sub(r"</(strong|em)>(\s*)<\1>", r"\2", h)
    h = re.sub(r"<(strong|em)>(\s*)</\1>", r"\2", h)
    h = re.sub(r"\s+", " ", h).strip()
    return h


def table(rows):
    width = max(len(r) for r in rows)
    body = "".join("<tr>" + "".join(f"<td>{tidy(c)}</td>" for c in r + [""] * (width - len(r))) + "</tr>" for r in rows)
    return f"<table><tbody>{body}</tbody></table>"


def chapter_sections(pages, first, last, words, skip=(), skip_pages=(), stop_at=(), drop=None):
    """[(title, html)] for PDF pages first..last, one entry per top-level (h1) heading."""
    blocks = []
    for n in range(first, last + 1):
        els = prepare(pages[n])
        blocks += blocks_from_page(els, words)
    for i, b in enumerate(blocks):
        if b[0] == "h" and b[2].strip() in stop_at:
            blocks = blocks[:i]
            break
    blocks = merge_paragraphs(blocks, words)
    if drop:
        blocks = [b for b in blocks if not drop(b)]
    sections, cur = [], ["Introduction", []]
    for b in blocks:
        if b[0] == "h" and b[1] == 1:
            if cur[1]:
                sections.append(cur)
            cur = [b[2], []]
        else:
            cur[1].append(b)
    if cur[1]:
        sections.append(cur)
    out = []
    for title, bl in sections:
        if title.strip() in skip_pages:
            continue
        bl = _drop_sections(bl, skip)
        if bl:
            out.append((title, render(bl)))
    return out


def merge_paragraphs(blocks, words):
    out = []
    for b in blocks:
        b = list(b) if isinstance(b, tuple) else b
        if out and b[0] == "p" and out[-1][0] == "p":
            prev = plain(out[-1][1]).rstrip()
            if prev and prev[-1] not in '.!?:)"\u201d\u2019' and plain(b[1]).lstrip()[:1].islower():
                out[-1] = ["p", words.join(out[-1][1], b[1])]
                continue
        out.append(b)
    return [tuple(b) for b in out]


def _drop_sections(blocks, skip):
    """Remove the content under headings whose text is in `skip` (until the next heading of the same or higher level)."""
    out, skipping = [], None
    for b in blocks:
        if b[0] == "h":
            if skipping is not None and b[1] <= skipping:
                skipping = None
            if skipping is None and b[2].strip() in skip:
                skipping = b[1]
                continue
        if skipping is None:
            out.append(b)
    return out
