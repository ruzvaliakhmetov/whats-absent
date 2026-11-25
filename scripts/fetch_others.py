"""Download the "other open fonts" from their original sources.

Output: data/upstream/<key>/<files> and data/upstream/others.json with, per font,
the files, version (name ID 5), release tag/date and where it came from.
Licence texts go to site/LICENSES/.

Alari Xuwasun Jurchen is published only in the login-protected cloud of dorontu.com
(folder 女真文资料/女真文字体). mkpoli/jurchen-input keeps the downloaded file together with
its SHA-256; we take it from there and refuse it unless the hash matches.
"""
import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
UP = ROOT / "data" / "upstream"
LIC = ROOT / "site" / "LICENSES"
UA = {"User-Agent": "whats-absent/0.1"}

# Order = preference when several fonts draw the same character.
SOURCES = [
    {
        "key": "alari", "name": "Alari Xuwasun Jurchen", "home": "https://dorontu.com/",
        "mirror": {
            "url": "https://raw.githubusercontent.com/mkpoli/jurchen-input/0553441/data/alari/AlariXuwasunJurchen-Regular.otf",
            "file": "AlariXuwasunJurchen-Regular.otf",
            "sha256": "41c71fc276e80044034e9719779c7cbcb2ec9f4329e49eae9e37d27b06469df7",
            "original": "dorontu.com/#/cloud, 女真文资料/女真文字体, AlariXuwasunJurchen-Regular（公测版）.otf",
            "hash_record": "https://github.com/mkpoli/jurchen-input/blob/main/docs/materials.md",
        },
        "licence": None,  # generated from the font's own name table
    },
    {
        "key": "sealie", "name": "Sealie", "home": "https://github.com/iebb/Sealie",
        "github_release": "iebb/Sealie", "assets": ["Sealie-Regular.woff"],
        "licence_asset": "LICENSE-OFL.txt",
    },
    {
        "key": "unihieroglyphica", "name": "UniHieroglyphica",
        "home": "https://github.com/thesaurus-linguae-aegyptiae/unihieroglyphica",
        "github_files": ("thesaurus-linguae-aegyptiae/unihieroglyphica", "main",
                         ["font_files/UniHieroglyphica.ttf"]),
        "licence_file": "OFL.txt",
    },
    {
        "key": "plangothic", "name": "Plangothic",
        "home": "https://github.com/Fitzgerald-Porthmouth-Koenigsegg/Plangothic_Project",
        "github_release": "Fitzgerald-Porthmouth-Koenigsegg/Plangothic_Project",
        "assets": ["PlangothicP1-Regular.ttf", "PlangothicP2-Regular.ttf"],
        "licence_repo_file": "LICENSE-OFL.txt",
    },
]


def get(url, binary=True):
    headers = dict(UA)
    if url.startswith("https://api.github.com/") and os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=600) as r:
        data = r.read()
    return data if binary else data.decode("utf-8")


def gh_json(path):
    return json.loads(get("https://api.github.com/" + path, binary=False))


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    print(f"  {path.relative_to(ROOT)}  {len(data) / 1e6:.1f} MB")


def main():
    meta = {}
    for s in SOURCES:
        key, d = s["key"], UP / s["key"]
        print(s["name"])
        info = {"name": s["name"], "home": s["home"], "files": []}
        if "mirror" in s:
            m = s["mirror"]
            data = get(m["url"])
            got = hashlib.sha256(data).hexdigest()
            if got != m["sha256"]:
                warn = "::warning::" if os.environ.get("GITHUB_ACTIONS") else "  "
                print(f"{warn}SHA-256 mismatch for {m['file']}: {got}; expected {m['sha256']}. "
                      "Check the original and update the hash.", file=sys.stderr)
                continue
            save(d / m["file"], data)
            info.update(files=[m["file"]], source=m["hash_record"], release="public beta",
                        original=m["original"], sha256=got)
        elif "github_release" in s:
            repo = s["github_release"]
            rel = gh_json(f"repos/{repo}/releases/latest")
            info.update(source=f"https://github.com/{repo}/releases/tag/{rel['tag_name']}",
                        release=rel["tag_name"], released=rel["published_at"][:10])
            assets = {a["name"]: a["browser_download_url"] for a in rel["assets"]}
            for name in s["assets"]:
                save(d / name, get(assets[name]))
                info["files"].append(name)
            if "licence_asset" in s:
                save(LIC / f"{key}-OFL.txt", get(assets[s["licence_asset"]]))
            if "licence_repo_file" in s:
                save(LIC / f"{key}-OFL.txt",
                     get(f"https://raw.githubusercontent.com/{repo}/{rel['tag_name']}/{s['licence_repo_file']}"))
        elif "github_files" in s:
            repo, branch, files = s["github_files"]
            commit = gh_json(f"repos/{repo}/commits/{branch}")
            sha = commit["sha"]
            info.update(source=f"https://github.com/{repo}/tree/{sha[:7]}",
                        release=f"{branch}@{sha[:7]}", released=commit["commit"]["committer"]["date"][:10])
            for f in files:
                name = f.rsplit("/", 1)[-1]
                save(d / name, get(f"https://raw.githubusercontent.com/{repo}/{sha}/{f}"))
                info["files"].append(name)
            save(LIC / f"{key}-OFL.txt",
                 get(f"https://raw.githubusercontent.com/{repo}/{sha}/{s['licence_file']}"))
        vers = []
        for f in info["files"]:
            v = (TTFont(d / f, lazy=True)["name"].getDebugName(5) or "").split(";")[0].replace("Version ", "").strip()
            vers.append(v if len(info["files"]) == 1 else f"{Path(f).stem.split('-')[0].replace(s['name'].replace(' ', ''), '')} {v}")
        info["version"] = " · ".join(vers)
        if "released" not in info:  # fall back to a date in the version string, e.g. "October 12, 2026"
            import datetime as dt
            for part in (TTFont(d / info["files"][0], lazy=True)["name"].getDebugName(5) or "").split(";"):
                try:
                    info["released"] = dt.datetime.strptime(part.strip(), "%B %d, %Y").date().isoformat()
                except ValueError:
                    pass
        font = TTFont(d / info["files"][0], lazy=True)
        if s.get("licence", "x") is None:
            n = font["name"]
            ofl = (ROOT / "data" / "OFL-1.1.txt").read_text()
            text = (f"{n.getDebugName(1)} {n.getDebugName(5)}\n"
                    f"Designers: {n.getDebugName(9)}. Vendor: {n.getDebugName(8)}, {n.getDebugName(11)}\n"
                    f"The font carries no separate copyright line.\n\n{n.getDebugName(13)}\n\n{ofl}")
            (LIC / f"{key}-OFL.txt").write_text(text)
        info["licence"] = f"{key}-OFL.txt"
        meta[key] = info
    (UP / "others.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False))
    print("wrote", (UP / "others.json").relative_to(ROOT))


if __name__ == "__main__":
    main()
