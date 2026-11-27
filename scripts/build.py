"""Build site/data.json + subset fonts for the What's absent page.

Inputs (data/raw): UnicodeData.txt, Blocks.txt, Scripts.txt, DerivedAge.txt,
notofonts_repos.json, unifont*.otf; data/noto_cmaps.json (scripts/fetch_noto.py).
"""
import datetime as dt
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from fontTools import subset
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
SITE = ROOT / "site"
FONTS = SITE / "fonts"
UNICODE_VERSION = "18.0.0"
UNIFONT = ["unifont-18.0.01.otf", "unifont_upper-18.0.01.otf"]
UNIFONT_VERSION = "18.0.01"
SKIP_GC = {"Cc", "Cs", "Co"}
# Invisible format characters: no glyph to draw, nothing for a font to add.
SKIP_BLOCKS = {"Variation Selectors", "Variation Selectors Supplement", "Tags"}
# Large ideographic/hieroglyphic blocks: on the page but hidden until the viewer turns them on.
OPT_IN_GROUPS = [
    ("cjk", re.compile(r"^CJK ")),
    ("egyptian", re.compile(r"^Egyptian Hieroglyph")),
    ("seal", re.compile(r"^Seal$")),
    ("jurchen", re.compile(r"^Jurchen")),
]
# Other open fonts that already draw some of the gaps: downloaded from their original
# sources by scripts/fetch_others.py (data/upstream/others.json, in order of preference).
UPSTREAM = ROOT / "data" / "upstream"
# Script-specific fonts are used only in their own blocks; Plangothic covers the rest.
OTHER_SCOPE = {
    "alari": re.compile(r"^Jurchen"),
    "sealie": re.compile(r"^Seal$"),
    "unihieroglyphica": re.compile(r"^Egyptian Hieroglyph"),
}
SLICE_BITS = 10  # one woff2 per 1024 code points, loaded only when its characters are on screen
# Fonts bigger than this are not loaded live in the browser (CJK, emoji).
MAX_LIVE_FONT = 3_000_000

SCRIPT_REPO = {
    "Latin": "latin-greek-cyrillic", "Greek": "latin-greek-cyrillic",
    "Cyrillic": "latin-greek-cyrillic",
    "Han": "noto-cjk", "Hiragana": "noto-cjk", "Katakana": "noto-cjk",
    "Hangul": "noto-cjk", "Bopomofo": "noto-cjk", "Katakana_Or_Hiragana": "noto-cjk",
    "Nko": "nko", "Braille": "symbols",
}
EXTERNAL_REPOS = {
    "noto-cjk": "https://github.com/notofonts/noto-cjk",
    "noto-emoji": "https://github.com/googlefonts/noto-emoji",
}


def parse_ranges(path):
    """Lines like '0000..001F ; Value # ...' -> list of (a, b, value)."""
    out = []
    for line in open(path, encoding="utf-8"):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        rng, val = [x.strip() for x in line.split(";", 1)]
        a, _, b = rng.partition("..")
        out.append((int(a, 16), int(b or a, 16), val))
    return out


def load_unicodedata():
    ud, first = {}, None
    for line in open(RAW / "UnicodeData.txt", encoding="utf-8"):
        p = line.split(";")
        cp, name, gc = int(p[0], 16), p[1], p[2]
        if name.endswith(", First>"):
            first = cp
            continue
        if name.endswith(", Last>"):
            label = name[1:-7]
            for c in range(first, cp + 1):
                ud[c] = (None, gc, label)  # algorithmic name
            continue
        if name == "<control>" and p[10]:
            name = p[10]
        ud[cp] = (name, gc, None)
    return ud


def algorithmic_name(cp, label):
    if label.startswith("CJK Ideograph") or label.startswith("Tangut Ideograph") \
            or label.startswith("Seal") or label.startswith("Jurchen"):
        prefix = {
            "CJK": "CJK UNIFIED IDEOGRAPH-", "Tangut": "TANGUT IDEOGRAPH-",
            "Seal": "SEAL CHARACTER-", "Jurchen": "JURCHEN CHARACTER-",
        }[label.split()[0]]
        return f"{prefix}{cp:X}"
    if label.startswith("Hangul Syllable"):
        return f"HANGUL SYLLABLE U+{cp:04X}"
    return f"{label.upper()}-{cp:X}"


def load_cov():
    cm = json.loads((ROOT / "data" / "noto_cmaps.json").read_text())
    per_repo = defaultdict(set)
    fam_cov = {}
    for repo, r in cm.items():
        for fam, f in r["families"].items():
            s = set()
            for a, b in f["cps"]:
                s.update(range(a, b + 1))
            fam_cov[(repo, fam)] = s
            per_repo[repo] |= s
    allcov = set().union(*per_repo.values())
    return cm, per_repo, fam_cov, allcov


def preview_family(repo, fams):
    """The family whose rendering the Noto column shows: plain "Noto Sans", else "Noto Sans <Script>"."""
    names = list(fams)
    if "Noto Sans" in names:
        return "Noto Sans"
    skip = ("Mono", "Display", "UI", "Unjoined", "Looped", "Supplement")
    for pref in ("Noto Sans ", "Noto Serif ", "Noto "):
        for n in names:
            if n.startswith(pref) and not any(w in n.split() for w in skip):
                return n
    return names[0]


def _has_glyph(path, cp, blank=False):
    """The font maps cp; with blank=True, also require that the glyph draws nothing."""
    from fontTools.pens.boundsPen import BoundsPen
    font = TTFont(path, lazy=True)
    gname = (font.getBestCmap() or {}).get(cp)
    if gname is None:
        return False
    if not blank:
        return True
    gs = font.getGlyphSet()
    pen = BoundsPen(gs)
    gs[gname].draw(pen)
    return pen.bounds is None


def _subset_bytes(data, cps, flavor):
    import io
    opts = subset.Options()
    opts.layout_features = ["*"]
    opts.notdef_outline = True
    opts.name_IDs = ["*"]
    opts.name_languages = ["*"]
    font = TTFont(io.BytesIO(data), recalcTimestamp=False)
    sub = subset.Subsetter(opts)
    sub.populate(unicodes=cps)
    sub.subset(font)
    font.flavor = flavor
    out = io.BytesIO()
    font.save(out)
    return out.getvalue()


def _ranges(cps):
    out = []
    for c in sorted(cps):
        if out and c == out[-1][1] + 1:
            out[-1][1] = c
        else:
            out.append([c, c])
    return out


def build_unifont(cps, out):
    """Merge the needed glyphs of unifont and unifont_upper into one TrueType font.

    Both are CID-keyed CFF, which fontTools cannot merge, so the outlines are redrawn
    as TrueType contours. Unifont is made of pixel squares, so this is exact."""
    from fontTools.pens.cu2quPen import Cu2QuPen
    from fontTools.pens.reverseContourPen import ReverseContourPen
    fonts = [TTFont(RAW / f, recalcTimestamp=False) for f in UNIFONT]
    upm = fonts[0]["head"].unitsPerEm
    order, glyphs, metrics, cmap = [".notdef"], {}, {}, {}
    src0 = fonts[0].getGlyphSet()
    pen = TTGlyphPen(None)
    src0[".notdef"].draw(ReverseContourPen(Cu2QuPen(pen, 1)))
    glyphs[".notdef"], metrics[".notdef"] = pen.glyph(), fonts[0]["hmtx"][".notdef"]
    for c in sorted(cps):
        font = next((f for f in fonts if c in f.getBestCmap()), None)
        if font is None:
            continue
        gname = f"u{c:04X}"
        gs = font.getGlyphSet()
        src = font.getBestCmap()[c]
        pen = TTGlyphPen(None)
        gs[src].draw(ReverseContourPen(Cu2QuPen(pen, 1)))
        order.append(gname)
        glyphs[gname] = pen.glyph()
        adv, _ = font["hmtx"][src]
        metrics[gname] = (adv, 0)
        cmap[c] = gname
    fb = FontBuilder(upm, isTTF=True)
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap(cmap)
    fb.setupGlyf(glyphs)
    glyf = fb.font["glyf"]
    for g in order:  # lsb must equal xMin, or TrueType renderers shift the outline
        glyf[g].recalcBounds(glyf)
    fb.setupHorizontalMetrics({g: (metrics[g][0], getattr(glyf[g], "xMin", 0)) for g in order})
    os2 = fonts[0]["OS/2"]
    fb.setupHorizontalHeader(ascent=os2.sTypoAscender, descent=os2.sTypoDescender)
    name = fonts[0]["name"]
    fb.setupNameTable({
        "familyName": "WA Unifont subset", "styleName": "Regular",
        "copyright": name.getDebugName(0),
        "version": name.getDebugName(5),
        "licenseDescription": name.getDebugName(13) or "",
    })
    fb.setupOS2(sTypoAscender=os2.sTypoAscender, sTypoDescender=os2.sTypoDescender,
                usWinAscent=os2.usWinAscent, usWinDescent=os2.usWinDescent)
    fb.setupPost()
    fb.font["head"].created = fb.font["head"].modified = fonts[0]["head"].modified
    fb.font.recalcTimestamp = False
    fb.font.flavor = "woff2"
    fb.save(out)
    return len(order) - 1


def make_tofu_font(path):
    """A font whose cmap (format 13) maps every code point to one box glyph."""
    upm = 1000
    fb = FontBuilder(upm, isTTF=True)
    fb.setupGlyphOrder([".notdef", "box", "empty"])
    pen = TTGlyphPen(None)
    o, i = (80, 0, 520, 760), (140, 60, 460, 700)
    for (x0, y0, x1, y1), cw in ((o, False), (i, True)):
        pts = [(x0, y0), (x0, y1), (x1, y1), (x1, y0)]
        if cw:
            pts = pts[::-1]
        pen.moveTo(pts[0])
        for p in pts[1:]:
            pen.lineTo(p)
        pen.closePath()
    box = pen.glyph()
    fb.setupGlyf({".notdef": box, "box": box, "empty": TTGlyphPen(None).glyph()})
    fb.setupHorizontalMetrics({".notdef": (600, 80), "box": (600, 80), "empty": (0, 0)})
    fb.setupHorizontalHeader(ascent=880, descent=-120)
    fb.setupCharacterMap({0x20: "box"})
    fb.setupNameTable({"familyName": "WA Tofu", "styleName": "Regular"})
    fb.setupOS2(sTypoAscender=880, sTypoDescender=-120, usWinAscent=880, usWinDescent=120)
    fb.setupPost()
    from fontTools.ttLib.tables._c_m_a_p import CmapSubtable
    sub = CmapSubtable.newSubtable(13)
    sub.platformID, sub.platEncID, sub.language = 3, 10, 0
    sub.cmap = {}
    for a, b in ((0x20, 0x40000), (0xE0000, 0xE0200)):
        sub.cmap.update(dict.fromkeys(range(a, b), "box"))
    # A base the page puts before a combining mark: draw nothing, so a missing mark is one box.
    for c in (0x20, 0xA0, 0x25CC):
        sub.cmap[c] = "empty"
    fb.font["cmap"].tables.append(sub)
    fb.font.flavor = "woff2"
    fb.font["head"].created = fb.font["head"].modified = 0x7C259DC0  # fixed: 2010-01-01
    fb.font.recalcTimestamp = False
    fb.save(path)


def main():
    FONTS.mkdir(parents=True, exist_ok=True)
    ud = load_unicodedata()
    blocks = parse_ranges(RAW / "Blocks.txt")
    script_of, age_of = {}, {}
    for a, b, v in parse_ranges(RAW / "Scripts.txt"):
        for c in range(a, b + 1):
            script_of[c] = v
    for a, b, v in parse_ranges(RAW / "DerivedAge.txt"):
        for c in range(a, b + 1):
            age_of[c] = v
    known_repos = set(json.loads((RAW / "notofonts_repos.json").read_text()))
    cm, per_repo, fam_cov, allcov = load_cov()

    uni_cov = set()
    for f in UNIFONT:
        uni_cov |= set(TTFont(RAW / f).getBestCmap())

    # Script -> repo: by name, by explicit map, or by best coverage.
    script_cps = defaultdict(list)
    for c, s in script_of.items():
        if c in ud:
            script_cps[s].append(c)

    def repo_for_script(s):
        if s in SCRIPT_REPO:
            return SCRIPT_REPO[s]
        slug = s.lower().replace("_", "-")
        if slug in cm or slug in known_repos:
            return slug
        if s in ("Common", "Inherited", "Unknown"):
            return None
        cnt = Counter()
        for c in script_cps[s]:
            for r, cov in per_repo.items():
                if c in cov:
                    cnt[r] += 1
        if cnt:
            return cnt.most_common(1)[0][0]
        return None

    script_repo = {s: repo_for_script(s) for s in script_cps}

    others_meta = json.loads((UPSTREAM / "others.json").read_text())
    other_files = []  # (key, path, cmap set), in order of preference
    for key, info in others_meta.items():
        for name in info["files"]:
            path = UPSTREAM / key / name
            other_files.append((key, path, set(TTFont(path, lazy=True).getBestCmap() or {})))
        # Base for combining marks, from the font itself: its dotted circle, else its own
        # space if that glyph is blank (Plangothic draws a visible "NBSP" label, so no-break
        # space is not used). A mark is never shown on a glyph from another font.
        paths = [p for k, p, _ in other_files if k == key]
        info["base"] = next((f"{b:04X}" for b in (0x25CC, 0x20)
                             if all(_has_glyph(p, b, blank=(b != 0x25CC)) for p in paths)), None)

    def other_file_for(c, block):
        return next(((k, p) for k, p, cps_ in other_files
                     if c in cps_ and (k not in OTHER_SCOPE or OTHER_SCOPE[k].search(block))), (None, None))

    def other_index(c, block):
        # Which of the font's files draws c (Plangothic has P1 and P2): picks the per-slice family.
        k, p = other_file_for(c, block)
        return [pp for kk, pp, _ in other_files if kk == k].index(p) if p else 0

    block_of = {}

    out_blocks, missing_all, repos_used = [], [], set()
    for a, b, name in blocks:
        if name in SKIP_BLOCKS:
            continue
        cps = [c for c in range(a, b + 1) if c in ud and ud[c][1] not in SKIP_GC]
        if not cps:
            continue
        cnt = Counter()
        for c in cps:
            for r, cov in per_repo.items():
                if c in cov:
                    cnt[r] += 1
        block_repo = cnt.most_common(1)[0][0] if cnt else None
        miss = [c for c in cps if c not in allcov]
        if not miss:
            continue
        if block_repo is None:
            ds0 = Counter(script_of.get(c, "Unknown") for c in miss).most_common(1)[0][0]
            if ds0 in ("Common", "Inherited"):
                block_repo = "music" if "Music" in name else ("symbols" if ds0 == "Common" else None)
        recs = []
        for c in miss:
            nm, gc, label = ud[c]
            s_ = script_of.get(c, "Unknown")
            repo = script_repo.get(s_) if s_ not in ("Common", "Inherited") else None
            repo = repo or block_repo or script_repo.get(s_)
            if repo:
                repos_used.add(repo)
            recs.append({"c": c, "g": gc, "s": s_, "a": age_of.get(c, ""),
                         "r": repo, "u": int(c in uni_cov), "o": other_file_for(c, name)[0], "f": other_index(c, name),
                         "n": nm if nm is not None else algorithmic_name(c, label)})
            missing_all.append(c)
            block_of[c] = name
        defaults = {k: Counter(r[k] for r in recs).most_common(1)[0][0] for k in "gsaruof"}
        # Algorithmic names share one prefix per block: store it, not every name.
        prefix = None
        alg = [r for r in recs if ud[r["c"]][0] is None]
        if alg:
            prefix = alg[0]["n"].rsplit("-", 1)[0] + "-"
        runs, names, ov = [], {}, {}
        for r in recs:
            c = r["c"]
            if runs and c == runs[-1][1] + 1:
                runs[-1][1] = c
            else:
                runs.append([c, c])
            if not (prefix and r["n"] == f"{prefix}{c:X}"):
                names[c] = r["n"]
            o = {k: r[k] for k in "gsaruof" if r[k] != defaults[k]}
            if o:
                ov[c] = o
        if defaults["s"] not in ("Common", "Inherited", "Unknown") and defaults["r"] is None:
            defaults["x"] = defaults["s"].lower().replace("_", "-")
        out_blocks.append({
            "name": name, "start": a, "end": b, "assigned": len(cps),
            "covered": len(cps) - len(miss), "missing": len(miss),
            "new": sum(1 for r in recs if r["a"] == UNICODE_VERSION[:4]),
            "group": next((g for g, rx in OPT_IN_GROUPS if rx.search(name)), None),
            "d": defaults, "prefix": prefix, "runs": runs, "names": names, "ov": ov,
        })

    repos = {}
    for r in sorted(repos_used):
        info = {"url": EXTERNAL_REPOS.get(r, f"https://github.com/notofonts/{r}")}
        fams = cm.get(r, {}).get("families", {})
        if fams:
            fam = preview_family(r, fams)
            url = fams[fam]["url"]
            info["family"] = fam
            # The Noto column puts U+25CC before a combining mark only if this font has its own.
            if any(a <= 0x25CC <= b for a, b in fams[fam]["cps"]):
                info["dc"] = 1
            cache = ROOT / "data" / "cache" / re.sub(r"[^A-Za-z0-9._-]", "_", url.split("/", 3)[-1])
            if cache.exists() and cache.stat().st_size <= MAX_LIVE_FONT:
                info["font"] = url
        repos[r] = info

    props = proposals_for(out_blocks)
    data = {
        "unicode": UNICODE_VERSION,
        "unifont": UNIFONT_VERSION,
        "built": dt.date.today().isoformat(),
        "families": sum(len(r["families"]) for r in cm.values()),
        "total_missing": len(missing_all),
        "repos": repos,
        "others": {k: {kk: v[kk] for kk in ("name", "home", "version", "release", "released", "source", "original", "sha256", "base") if kk in v}
                   for k, v in others_meta.items()},
        "docs": props,
        "blocks": out_blocks,
    }
    # Keep the previous build date when nothing else changed, so a weekly rebuild
    # with no news leaves the site byte-for-byte the same (and the workflow commits nothing).
    old_path = SITE / "data.json"
    if old_path.exists():
        try:
            old = json.loads(old_path.read_text())
            new = json.loads(json.dumps(data, ensure_ascii=False))  # same key types as the file
            if {**old, "built": None} == {**new, "built": None}:
                data["built"] = old["built"]
        except ValueError:
            pass
    (SITE / "data.json").write_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False))

    # Unifont: the glyphs this page shows, from both Unifont files, in ONE font, so that
    # a plane-1 combining mark and Unifont's own U+25CC can be shaped together.
    n = build_unifont(set(missing_all) | {0x25CC}, FONTS / "unifont.woff2")
    for old in FONTS.glob("unifont-[01].woff2"):
        old.unlink()
    print("unifont", n, "glyphs")
    make_tofu_font(FONTS / "tofu.woff2")

    # Other fonts: each source file is cut to the gaps it is chosen for, then sliced
    # into 1024-code-point woff2 files with one @font-face (unicode-range) each.
    odir = FONTS / "other"
    odir.mkdir(exist_ok=True)
    for old in odir.glob("*.woff2"):
        old.unlink()
    assigned = defaultdict(set)
    for c in missing_all:
        k, path = other_file_for(c, block_of[c])
        if path:
            assigned[path].add(c)
    css = ["/* Generated by scripts/build.py from data/upstream (see LICENSES/). */"]
    for key, path, cps_ in other_files:
        want = assigned.get(path)
        if not want:
            continue
        mark_base = int(others_meta[key]["base"], 16) if others_meta[key].get("base") else None
        extra = {mark_base} if mark_base else set()
        base = _subset_bytes(path.read_bytes(), want | extra, flavor=None)
        buckets = defaultdict(set)
        for c in want:
            buckets[c >> SLICE_BITS].add(c)
        for bk, cps_b in sorted(buckets.items()):
            fname = f"{key}-{path.stem.lower()}-{bk << SLICE_BITS:06x}.woff2"
            (odir / fname).write_bytes(_subset_bytes(base, cps_b | extra, flavor="woff2"))
            rng = ",".join(f"U+{a:X}" if a == b else f"U+{a:X}-{b:X}" for a, b in _ranges(cps_b | extra))
            ver = __import__("hashlib").sha1((odir / fname).read_bytes()).hexdigest()[:8]
            # One family per slice: a combining mark and the base before it must come from the same
            # file, and slices of one font share the base, so they cannot share a family name.
            fi = [p for k, p, _ in other_files if k == key].index(path)
            css.append(f"@font-face{{font-family:'O-{key}-{fi}-{bk:x}';font-display:block;"
                       f"src:url(fonts/other/{fname}?v={ver}) format('woff2');unicode-range:{rng}}}")
        print("other font", key, path.name, len(want), "chars,", len(buckets), "slices")
    (SITE / "other-fonts.css").write_text("\n".join(css) + "\n")
    write_unifont_licence()
    write_licences_page(data)
    stamp_versions()
    print("blocks", len(out_blocks), "missing", len(missing_all))


def write_unifont_licence():
    """Unifont's licence, with the copyright line of the exact version we ship."""
    name = TTFont(RAW / UNIFONT[0])["name"]
    ofl = (ROOT / "data" / "OFL-1.1.txt").read_text()
    text = (f"GNU Unifont {name.getDebugName(5)}\n{name.getDebugName(0)}\n\n"
            f"{name.getDebugName(13)}\nhttps://unifoundry.com/unifont/\n\n{ofl}")
    (SITE / "LICENSES" / "Unifont-OFL.txt").write_text(text)


USE = {
    "plangothic": "Most scripts and symbols, and the CJK extension blocks.",
    "sealie": "The Seal block.",
    "unihieroglyphica": "Egyptian hieroglyph blocks.",
    "alari": "The Jurchen blocks.",
}


def proposals_for(blocks):
    """Attach the proposal documents of data/proposals.json (made by fetch_proposals.py) to the blocks.

    Returns {"titles": {doc: title}, "sets": [[doc, ...], ...]}; each block gets "p": runs
    [first, last, set index] of consecutive characters citing the same documents.
    """
    path = ROOT / "data" / "proposals.json"
    if not path.exists():
        for b in blocks:
            b["p"] = []
        return {"titles": {}, "sets": []}
    pr = json.loads(path.read_text())
    items_at = {}
    for a, z, ks in pr["runs"]:
        for c in range(a, z + 1):
            items_at[c] = ks
    sets, index, titles = [], {}, {}
    for b in blocks:
        runs = []
        for a, z in b["runs"]:
            for c in range(a, z + 1):
                docs = []
                for item in items_at.get(c, []):
                    docs += [d for d in pr["items"][item]["docs"] if d not in docs]
                if not docs:
                    continue
                key = tuple(docs)
                if key not in index:
                    index[key] = len(sets)
                    sets.append(docs)
                    titles.update({d: pr["titles"][d] for d in docs if d in pr["titles"]})
                i = index[key]
                if runs and runs[-1][2] == i and runs[-1][1] == c - 1:
                    runs[-1][1] = c
                else:
                    runs.append([c, c, i])
        b["p"] = runs
    return {"titles": titles, "sets": sets}


def write_licences_page(data):
    from html import escape
    parts = []
    for key, o in data["others"].items():
        src = o.get("source")
        src_html = (f' · <a href="{escape(src)}">{escape(o.get("release", "source"))}</a>'
                    if src and not o.get("original") else "")
        if o.get("original"):
            src_html += (f'<br>Original: {escape(o["original"])} (login required). File taken from '
                         f'<a href="https://github.com/mkpoli/jurchen-input">mkpoli/jurchen-input</a>, '
                         f'SHA-256 <code>{o["sha256"][:16]}…</code> matches the hash recorded '
                         f'<a href="{escape(src)}">there</a>')
        date = f' ({o["released"]})' if o.get("released") else ""
        parts.append(f"""  <section id="{key}">
    <h2>{escape(o["name"])} {escape(o.get("version", ""))}</h2>
    <p>“Other open fonts” column: {USE.get(key, "")}</p>
    <p class="meta">SIL OFL 1.1 · <a href="{escape(o["home"])}">home</a>{src_html}{date} · <a href="{key}-OFL.txt">licence</a></p>
  </section>""")
    tpl = (ROOT / "scripts" / "licences.template.html").read_text()
    html = tpl.replace("{{others}}", "\n".join(parts)).replace("{{built}}", data["built"])
    (SITE / "LICENSES" / "index.html").write_text(html)


def stamp_versions():
    """Cache-busting: ?v=<hash of the file> on every local asset the page loads."""
    import hashlib
    def h(rel):
        return hashlib.sha1((SITE / rel).read_bytes()).hexdigest()[:8]
    app = SITE / "app.js"
    js = re.sub(r'fetch\("data\.json(\?v=[^"]*)?"\)', f'fetch("data.json?v={h("data.json")}")', app.read_text())
    app.write_text(js)
    style = SITE / "style.css"
    style.write_text(re.sub(r"url\((fonts/[A-Za-z0-9_.-]+\.woff2)(\?v=[0-9a-f]+)?\)",
                            lambda m: f"url({m.group(1)}?v={h(m.group(1))})", style.read_text()))
    html = (SITE / "index.html").read_text()
    for rel in ("style.css", "other-fonts.css", "app.js"):
        html = re.sub(rf'"{re.escape(rel)}(\?v=[^"]*)?"', f'"{rel}?v={h(rel)}"', html)
    (SITE / "index.html").write_text(html)


if __name__ == "__main__":
    # String hashing is randomised per process and the subsetter walks some sets of glyph
    # names, so pin the seed: the same input must give byte-identical fonts.
    import os
    import sys
    if os.environ.get("PYTHONHASHSEED") != "0":
        os.execve(sys.executable, [sys.executable, *sys.argv], {**os.environ, "PYTHONHASHSEED": "0"})
    main()
