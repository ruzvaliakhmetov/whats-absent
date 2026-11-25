# What's absent

An overview page for Noto contributors: every character encoded in Unicode 18.0
that no Noto font covers yet, grouped by block. Each cell shows the GNU Unifont
reference glyph, the live Noto rendering (a box means not covered) and a link to
the notofonts repository where the character belongs.

## Layout

- `scripts/fetch_noto.py` — downloads the Regular of every Noto family listed in
  `notofonts.github.io/state.json` (plus Noto CJK and Noto Color Emoji) and saves
  their cmaps to `data/noto_cmaps.json`. Fonts are cached in `data/cache/`.
- `scripts/build.py` — combines the UCD files, Unifont and the Noto cmaps into
  `site/data.json`, subsets Unifont to the missing characters and builds a
  "tofu" fallback font.
- `site/` — the static page (`index.html`, `style.css`, `app.js`). Deploy this folder as is.

## Rebuild

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

`fetch_noto.py` also refreshes `data/raw/state.json` and the list of notofonts repos
(pass `--no-refresh` to skip). Then rebuild:

```bash
rm -rf data/cache && .venv/bin/python scripts/fetch_noto.py && .venv/bin/python scripts/fetch_others.py && .venv/bin/python scripts/build.py
```

Preview locally:

```bash
python3 -m http.server 8790 --directory site
```

## Rules

- Coverage = union of the cmaps of all Noto families (Sans, Serif and others).
- Excluded: control (Cc), surrogate (Cs) and private-use (Co) code points.
- Repo per character: by Unicode Script (e.g. `Garay` → `notofonts/garay`);
  Common/Inherited characters go to whichever repo already covers most of the block.
  Scripts without a notofonts repo are marked "no repo yet".
- CJK, Egyptian hieroglyph, Seal and Jurchen blocks are on the page but hidden by default; a checkbox
  per group turns them on (`OPT_IN_GROUPS` in `scripts/build.py`). The choice is remembered in the
  viewer's browser, and a link or search into a hidden block switches its group on.
- The third column shows another open font that already draws the character. `scripts/fetch_others.py`
  downloads each one from its original source and records version and release in `data/upstream/others.json`;
  order of preference: Alari Xuwasun Jurchen, Sealie, UniHieroglyphica, Plangothic.
  - Plangothic: latest GitHub release of Fitzgerald-Porthmouth-Koenigsegg/Plangothic_Project (P1 + P2).
  - Sealie: latest GitHub release of iebb/Sealie.
  - UniHieroglyphica: `main` of thesaurus-linguae-aegyptiae/unihieroglyphica (no releases there).
  - Alari Xuwasun Jurchen: published only in the login-protected cloud of dorontu.com
    (女真文资料/女真文字体, public beta of 2026-10-12). The script takes the file from
    mkpoli/jurchen-input, which keeps it with its SHA-256 in `docs/materials.md`, and refuses it
    unless the hash matches. A new beta means a new hash in `scripts/fetch_others.py`.
  - Script-specific fonts are used only in their own blocks (`OTHER_SCOPE` in `scripts/build.py`).
  `build.py` cuts each font to the characters it is chosen for, slices it into 1024-code-point woff2
  files and writes `site/other-fonts.css` and `site/LICENSES/index.html` (with versions).
- Combining marks are shown on a base from the same font, never from another one: GNU Unifont uses
  its own U+25CC (both Unifont files are merged into one subset so plane-1 marks can reach it);
  Plangothic, UniHieroglyphica and Alari have no U+25CC, so their own blank space is the base
  (Plangothic's no-break space draws a visible label and is not used). Every slice carries that base,
  so each slice has its own family name (`O-<font>-<file>-<1024-block>`): under one shared family the
  browser could take the base from one slice and the mark from another, and Safari then draws a box.
  The Noto column shows the
  mark alone: it is missing there, and once Noto has it the character leaves the list.
- `build.py` is reproducible: same input, byte-identical `site/` (fixed font timestamps, fixed
  `PYTHONHASHSEED`), so the weekly workflow commits only real changes.
- The Noto column loads the repo's font live from notofonts.github.io (via jsDelivr),
  so a character added upstream shows up before the next rebuild. CJK and emoji fonts
  are too large to load and always show the box.

## Publishing

`site/` is a complete static site (about 24 MB, mostly font slices that load only when their
characters are on screen). Upload its contents as is to any static host: GitHub Pages,
Cloudflare Pages, Netlify or a plain web server. It works from a subfolder too, all paths are relative.

- It must be served over HTTP(S); opened as a local file it cannot load `data.json`.
- `.nojekyll` is there for GitHub Pages.
- `scripts/build.py` stamps `?v=<hash>` on the CSS, JS and `data.json` links, so after a rebuild
  visitors get the new files without clearing their cache.
- External requests at runtime: Google Fonts (Inter, IBM Plex Mono) and jsDelivr (live Noto fonts).

## Weekly rebuild and GitHub Pages

`.github/workflows/rebuild.yml` runs every Monday at 04:17 UTC and on demand (Actions → Rebuild and
deploy → Run workflow). It fetches the latest Noto fonts and the other open fonts, runs `build.py`,
writes a summary (counts and font versions), commits `site/` and `data/raw/` if anything changed,
and publishes `site/` to GitHub Pages. A push to `main` that touches `site/` only publishes.

Setup, once:
- Settings → Pages → Build and deployment → Source: **GitHub Actions**.
- Settings → Actions → General → Workflow permissions: **Read and write permissions**.

Notes:
- A rebuild with nothing new changes nothing: `build.py` is reproducible and keeps the previous
  build date, so no commit is made.
- Downloads (`data/cache/`, `data/upstream/`) are not committed; see `.gitignore`.
- If the Alari hash check fails (a new beta), the run still builds and publishes, with Jurchen's
  third column empty, and shows a warning naming the hash to put in `scripts/fetch_others.py`.
