"""Download every Noto family's Regular font and record its cmap.

Output: data/noto_cmaps.json
  { repo: { "families": { family: { "url": ..., "cps": [[start, end], ...] } } } }
"""
import io
import json
import os
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fontTools.ttLib import TTFont, TTCollection

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
CACHE = ROOT / "data" / "cache"
OUT = ROOT / "data" / "noto_cmaps.json"
CDN = "https://cdn.jsdelivr.net/gh/notofonts/notofonts.github.io/"
RAWGH = "https://raw.githubusercontent.com/notofonts/notofonts.github.io/main/"

# Families living outside the notofonts.github.io monorepo.
EXTRA = {
    "noto-cjk": {
        "Noto Sans CJK": "https://cdn.jsdelivr.net/gh/notofonts/noto-cjk@main/Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf",
        "Noto Serif CJK": "https://raw.githubusercontent.com/notofonts/noto-cjk/main/Serif/OTF/SimplifiedChinese/NotoSerifCJKsc-Regular.otf",
    },
    "noto-emoji": {
        "Noto Color Emoji": "https://raw.githubusercontent.com/google/fonts/main/ofl/notocoloremoji/NotoColorEmoji-Regular.ttf",
    },
}
EXTRA_REPO_URL = {
    "noto-cjk": "https://github.com/notofonts/noto-cjk",
    "noto-emoji": "https://github.com/googlefonts/noto-emoji",
}

PREFS = [
    r"/unhinted/ttf/[^/]*-Regular\.ttf$",
    r"/full/ttf/[^/]*-Regular\.ttf$",
    r"/googlefonts/ttf/[^/]*-Regular\.ttf$",
    r"/hinted/ttf/[^/]*-Regular\.ttf$",
    r"-Regular\.(ttf|otf)$",
    r"\.(ttf|otf)$",
]


def pick(files, family):
    stem = family.replace(" ", "")
    own = [f for f in files if f.rsplit("/", 1)[-1].startswith(stem + "-") or f.rsplit("/", 1)[-1].startswith(stem + "[")]
    files = own or files
    for pat in PREFS:
        for f in files:
            if re.search(pat, f):
                return f
    return None


def ranges(cps):
    cps = sorted(cps)
    out = []
    for c in cps:
        if out and c == out[-1][1] + 1:
            out[-1][1] = c
        else:
            out.append([c, c])
    return out


def fetch(url):
    CACHE.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^A-Za-z0-9._-]", "_", url.split("/", 3)[-1])
    p = CACHE / name
    if not p.exists():
        urls = [url]
        if url.startswith(CDN):
            urls.append(RAWGH + url[len(CDN):])
        err = None
        for u in urls:
            try:
                req = urllib.request.Request(u, headers={"User-Agent": "whats-absent/0.1"})
                with urllib.request.urlopen(req, timeout=300) as r:
                    p.write_bytes(r.read())
                break
            except Exception as e:  # noqa: BLE001
                err = e
        else:
            raise err
    return p.read_bytes()


def cmap_of(data):
    if data[:4] == b"ttcf":
        f = TTCollection(io.BytesIO(data)).fonts[0]
    else:
        f = TTFont(io.BytesIO(data), lazy=True)
    return set(f.getBestCmap().keys())


def job(repo, family, url):
    try:
        cps = cmap_of(fetch(url))
        print(f"ok  {repo:28} {family:40} {len(cps)}", flush=True)
        return repo, family, url, ranges(cps)
    except Exception as e:  # noqa: BLE001
        print(f"ERR {repo} {family} {url}: {e}", file=sys.stderr, flush=True)
        return repo, family, url, None


def github_api(path):
    """GET api.github.com/<path>, with GITHUB_TOKEN when set (Actions), following pagination."""
    headers = {"User-Agent": "whats-absent/0.1", "Accept": "application/vnd.github+json"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    out, url = [], "https://api.github.com/" + path
    while url:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r:
            out.extend(json.loads(r.read()))
            m = re.search(r'<([^>]+)>;\s*rel="next"', r.headers.get("Link", ""))
            url = m.group(1) if m else None
    return out


def refresh_sources():
    """Latest Noto state (families and files per repo) and the list of notofonts repos."""
    req = urllib.request.Request(
        "https://raw.githubusercontent.com/notofonts/notofonts.github.io/main/state.json",
        headers={"User-Agent": "whats-absent/0.1"})
    with urllib.request.urlopen(req, timeout=120) as r:
        (RAW / "state.json").write_bytes(r.read())
    repos = sorted(r["name"] for r in github_api("orgs/notofonts/repos?per_page=100"))
    (RAW / "notofonts_repos.json").write_text(json.dumps(repos, indent=0))
    print("refreshed state.json and", len(repos), "notofonts repos")


def main():
    if "--no-refresh" not in sys.argv:
        refresh_sources()
    state = json.loads((RAW / "state.json").read_text())
    tasks = []
    for repo, v in state.items():
        if repo == "test" or not isinstance(v, dict):
            continue
        for fam, info in v.get("families", {}).items():
            f = pick(info.get("files", []), fam)
            if f:
                tasks.append((repo, fam, CDN + f))
    for repo, fams in EXTRA.items():
        for fam, url in fams.items():
            tasks.append((repo, fam, url))

    out = {}
    with ThreadPoolExecutor(8) as ex:
        for repo, fam, url, rng in ex.map(lambda t: job(*t), tasks):
            if rng is None:
                continue
            r = out.setdefault(repo, {
                "url": EXTRA_REPO_URL.get(repo, f"https://github.com/notofonts/{repo}"),
                "families": {},
            })
            r["families"][fam] = {"url": url, "cps": rng}
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    print("wrote", OUT, len(out), "repos")


if __name__ == "__main__":
    main()
