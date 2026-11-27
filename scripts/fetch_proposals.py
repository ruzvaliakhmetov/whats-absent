"""Find the Unicode proposal documents behind each character on the page.

The UCD does not say which document proposed a character, but the UTC minutes do: every
decision to accept or provisionally assign characters is a consensus item such as
  [183-C8] Consensus: Provisionally assign one code point U+1C8B CYRILLIC SMALL LETTER
  YERU WITH CONNECTING BAR in the Cyrillic Extended-C block based on L2/25-112.
  [Ref. 1.5 in L2/25-091R]
This script reads the minutes of every UTC meeting (found through the yearly L2 document
registers), keeps the consensus items that accept, assign or encode characters, and takes
the code points and the documents they cite (the part after "[Ref." is the committee's own
report and is dropped).

Code points can move between a provisional assignment and the release, so an item counts
for a character only when it was taken at most ten years before the character's Unicode
version came out. An item that gives only a block's range counts for the block's characters
unless another item names the character's own code point.

Output: data/proposals.json  {"items": {"183-C8": {"docs": ["L2/25-112"], "minutes": url}},
                              "runs": [[0x1C8B, 0x1C8B, ["183-C8"]], ...],
                              "titles": {"L2/25-112": "title from the L2 register"}}
Downloads are cached in data/cache/minutes/. Run by hand; the weekly workflow only reads
the JSON.
"""
import html
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache" / "minutes"
OUT = ROOT / "data" / "proposals.json"
UA = {"User-Agent": "whats-absent/0.1"}
FIRST_YEAR = 2005

ITEM = re.compile(r"\[\s*(\d{2,3})-C(\d+[a-z]?)\s*\]")
NEXT = re.compile(r"\[\s*\d{2,3}-[A-Z]{1,2}\d+[a-z]?\s*\]")
# L2 documents and WG 2 documents; "IRG N2513" is an IRG document, not WG 2, and is skipped.
DOC = re.compile(r"\bL2/(\d{2})-(\d{3})([A-Za-z]\d*)?|\bWG\s*2\s*N\s?(\d{4})|(?<!IRG )\bN(\d{4})\b")
CP = re.compile(r"U\+([0-9A-F]{4,6})(?:\s*(?:\.\.|…|–|—|-|to|through)\s*(?:U\+)?([0-9A-F]{4,6}))?")


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read().decode("utf-8", "replace")


def cached(name, url):
    p = CACHE / name
    if not p.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        p.write_text(get(url))
    return p.read_text()


def text_of(s):
    s = re.sub(r"(?is)<(script|style).*?</\1>", " ", s)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).replace(" ", " ")


def minutes_docs():
    """(url, text) of every UTC minutes document."""
    out = []
    import datetime as dt
    for y in range(FIRST_YEAR, dt.date.today().year + 1):
        try:
            reg = cached(f"Register-{y}.html", f"https://www.unicode.org/L2/L{y}/Register-{y}.html")
        except Exception as e:  # the current year's register may not exist yet
            print("  no register for", y, e, file=sys.stderr)
            continue
        for row in re.findall(r"(?is)<tr.*?</tr>", reg):
            t = text_of(row)
            m = re.search(r"UTC #(\d+) Minutes", t)
            h = re.findall(r'href="([^"]+\.htm)"', row)
            if m and h:
                out.append((int(m.group(1)), f"https://www.unicode.org/L2/L{y}/{h[0]}"))
    # Minutes not yet listed in a register: follow the resolver for item C1 of later meetings.
    last = max(n for n, _ in out)
    for n in range(last + 1, last + 12):
        try:
            r = get(f"https://www.unicode.org/cgi-bin/GetL2Ref.pl?{n}-C1")
        except Exception:
            break
        m = re.search(r'url=(https://www\.unicode\.org/L2/L\d{4}/\d+\.htm)', r)
        if not m:
            break
        out.append((n, m.group(1)))
    docs = []
    for n, url in sorted(set(out)):
        docs.append((n, url, text_of(cached(url.rsplit("/", 1)[-1], url))))
    return docs


def doc_ids(s):
    ids = []
    for m in DOC.finditer(s):
        if m.group(1):
            ids.append(f"L2/{m.group(1)}-{m.group(2)}{m.group(3) or ''}")
        else:
            ids.append(f"N{m.group(4) or m.group(5)}")
    return list(dict.fromkeys(ids))


# Only decisions to encode characters; not renames, property or glyph changes.
ENCODE = re.compile(r"for encoding|provisional(?:ly)? assign|for (?:a )?future version|for inclusion"
                    r"|\baccepts? (?:the )?[\d,]+ [^.;]{0,60}?(?:characters|ideographs|code points)", re.I)
# "with block "Makasar" at U+11EE0..U+11EFF", "in a new Ol Onal block that extends from U+1E5D0..U+1E5FF":
# the block's range, not the characters; used only when an item gives no other code points.
BLOCK_RANGE = re.compile(r"block[^.;]{0,80}?U\+[0-9A-F]{4,6}\s*(?:\.\.|…|–|-|to|through)\s*(?:U\+)?[0-9A-F]{4,6}\)?", re.I)
NEW_BLOCKS = re.compile(r"(?:[^.]|\.\.)*\bapproves? (?:the )?new blocks?\b(?:[^.]|\.\.)*\.?", re.I)  # ".." is a range
# The committee's own working papers, cited next to the proposal: "Recommendations to UTC #183 on
# Script Proposals", "CJK & Unihan Group Recommendations for UTC #180". Recognised by their title
# in the L2 register and shown only when an item cites nothing else (CJK: the proposal is an IRG paper).
REPORT = re.compile(r"Recommendations (?:to|for) UTC|Group Recommendations|UTC #\d+ Minutes|\bAgenda\b"
                    r"|Comments on Public Review", re.I)

# Release year of each Unicode version: a decision counts for a character only if it was taken
# at most this many years before the character's version came out (and not after).
RELEASED = {"1.1": 1993, "2.0": 1996, "2.1": 1998, "3.0": 1999, "3.1": 2001, "3.2": 2002, "4.0": 2003,
            "4.1": 2005, "5.0": 2006, "5.1": 2008, "5.2": 2009, "6.0": 2010, "6.1": 2012, "6.2": 2012,
            "6.3": 2013, "7.0": 2014, "8.0": 2015, "9.0": 2016, "10.0": 2017, "11.0": 2018, "12.0": 2019,
            "12.1": 2019, "13.0": 2020, "14.0": 2021, "15.0": 2022, "15.1": 2023, "16.0": 2024,
            "17.0": 2025, "18.0": 2026}
MAX_YEARS = 10


def cps_in(s):
    out = set()
    for c in CP.finditer(s):
        a = int(c.group(1), 16)
        b = int(c.group(2), 16) if c.group(2) else a
        if a <= b and b - a <= 0x3000:
            out.update(range(a, b + 1))
    return out


def items_of(n, url, text):
    year = int(re.search(r"/L(\d{4})/", url).group(1))
    for m in ITEM.finditer(text):
        if int(m.group(1)) != n:
            continue
        rest = text[m.end():m.end() + 4000]
        nxt = NEXT.search(rest)
        main = (rest[:nxt.start()] if nxt else rest).strip()
        if not ENCODE.search(main):
            continue
        # "The UTC approves new blocks U+10780..U+107BF Latin Extended-F and U+1DF00..U+1DFFF ...":
        # a sentence that only creates blocks names no characters.
        chars_part = NEW_BLOCKS.sub(" ", main)
        cps = cps_in(BLOCK_RANGE.sub(" ", chars_part))
        by_block = not cps
        if by_block:  # "Accept 69 Garay characters in a new Garay block (U+10D40..U+10D8F)"
            ranges = BLOCK_RANGE.findall(chars_part)
            # several: "range U+323B0..U+3347B (block: U+323B0..U+3347F)" - the narrowest is the characters
            cps = min((cps_in(r) for r in ranges), key=len, default=set())
        docs = doc_ids(main)
        ver = re.search(r"\bUnicode (?:[Vv]ersion )?(\d+\.\d)", main)
        if cps and docs:
            key = f"{m.group(1)}-C{m.group(2)}"
            yield key, {"cps": cps, "docs": docs, "text": main, "year": year, "by_block": by_block,
                        "version": ver.group(1) if ver else None, "minutes": f"{url}#{key}"}


def register_titles():
    titles = {}
    for f in sorted(CACHE.glob("Register-*.html")):
        for row in re.findall(r"(?is)<tr.*?</tr>", f.read_text()):
            m = re.match(r"\s*(L2/\d\d-\d{3}[A-Za-z0-9]*)\s+(.*?)\s*$", text_of(row))
            if m:
                titles[m.group(1)] = m.group(2)
    return titles


def main():
    age = {}  # every assigned code point -> the Unicode version that added it
    for line in (ROOT / "data" / "raw" / "DerivedAge.txt").read_text().splitlines():
        line = line.split("#")[0].strip()
        if line:
            rng, v = (x.strip() for x in line.split(";"))
            a, _, z = rng.partition("..")
            for c in range(int(a, 16), int(z or a, 16) + 1):
                age[c] = v
    items, chars, used = {}, {}, {}
    docs_list = minutes_docs()  # also fills the register cache
    titles = register_titles()

    def title(d):  # "L2/25-232R" is listed as L2/25-232 (or L2/25-232R2) in the register
        if not d.startswith("L2/"):
            return ""  # WG 2 documents: no register here
        base = re.sub(r"[A-Za-z]\d*$", "", d)
        return titles.get(d) or titles.get(base) or next((t for k, t in titles.items() if k.startswith(base)), "")
    for n, url, text in docs_list:
        for key, it in items_of(n, url, text):
            ok = [c for c in it["cps"] & age.keys()
                  if RELEASED[age[c]] - MAX_YEARS <= it["year"] <= RELEASED[age[c]]
                  and it["version"] in (None, age[c])]
            if not ok:
                continue
            docs = [d for d in it["docs"] if not REPORT.search(title(d))] or it["docs"]
            items[key] = {"docs": docs, "minutes": it["minutes"]}
            for d in docs:
                if title(d):
                    used[d] = title(d)
            for c in ok:
                chars.setdefault(f"{c:04X}", []).append((key, it["by_block"]))
    # An item that only gives the block's range ("35 characters in a new Latin Extended-F block
    # (U+10780..U+107BF)") also covers characters added to that block later; when another item
    # names the character's own code point, that one wins.
    for c, ks in chars.items():
        named = [k for k, by_block in ks if not by_block]
        chars[c] = named or [k for k, _ in ks]
    keep = {k for ks in chars.values() for k in ks}
    # Stored as runs [first, last, [items]] of consecutive characters with the same items.
    runs = []
    for c in sorted(chars, key=lambda h: int(h, 16)):
        cp, ks = int(c, 16), chars[c]
        if runs and runs[-1][1] == cp - 1 and runs[-1][2] == ks:
            runs[-1][1] = cp
        else:
            runs.append([cp, cp, ks])
    items = {k: v for k, v in items.items() if k in keep}
    used = {d: t for d, t in used.items() if any(d in items[k]["docs"] for k in items)}
    OUT.write_text(json.dumps({"items": items, "runs": runs, "titles": used}, indent=0, sort_keys=True,
                              ensure_ascii=False) + "\n")
    print(f"{len(chars)} characters have a proposal; {len(items)} consensus items", file=sys.stderr)


if __name__ == "__main__":
    main()
