"use strict";

const CHUNK = 96;
const $ = (s, el = document) => el.querySelector(s);
const hex = (c) => c.toString(16).toUpperCase().padStart(4, "0");
const slug = (s) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
const fmt = (n) => n.toLocaleString("en-US");
const IGNORABLE = /^(Variation Selectors|Tags)/;
const GROUPS = ["cjk", "egyptian", "seal", "jurchen"];
const store = {
  get(k) { try { return localStorage.getItem("wa:" + k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem("wa:" + k, v); } catch { /* private mode */ } },
};

let DATA, NEWV;
const loadedFonts = new Map();

function notoFamily(repo) {
  const r = DATA.repos[repo];
  if (!r || !r.font) return null;
  const fam = "N-" + repo;
  if (!loadedFonts.has(repo)) {
    const ff = new FontFace(fam, `url(${r.font})`);
    loadedFonts.set(repo, ff);
    ff.load().then((f) => document.fonts.add(f)).catch(() => {});
  }
  return fam;
}

// Proposal documents: data.json lists each set of documents once ("docs.sets") and every block
// has runs [first, last, set] of characters citing that set ("p"). Made by scripts/fetch_proposals.py.
function docURL(d) {
  return d.startsWith("L2/")
    ? `https://www.unicode.org/cgi-bin/GetMatchingDocs.pl?${d}`
    : `https://www.unicode.org/cgi-bin/GetMatchingWG2Docs.pl?${d}`;
}
const esc = (t) => t.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
function docsHTML(set) {
  if (set == null) return "";
  const docs = DATA.docs.sets[set];
  const shown = docs.slice(0, 4).map((d) => {
    const t = DATA.docs.titles[d];
    return `<a href="${docURL(d)}" target="_blank" rel="noopener"${t ? ` title="${esc(t)}"` : ""}>${d.startsWith("N") ? "WG2 " + d : d}</a>`;
  });
  const more = docs.length > 4 ? ` +${docs.length - 4}` : "";
  return `<div class="docs">${docs.length > 1 ? "Proposals" : "Proposal"}: ${shown.join(", ")}${more}</div>`;
}

function charsOf(b) {
  const out = [];
  const pr = b.p || [];
  let pi = 0;
  for (const [a, z] of b.runs) {
    for (let c = a; c <= z; c++) {
      const o = b.ov[c] || {};
      out.push({
        c,
        n: b.names[c] || (b.prefix + hex(c)),
        g: o.g ?? b.d.g, s: o.s ?? b.d.s, a: o.a ?? b.d.a,
        r: "r" in o ? o.r : b.d.r, u: o.u ?? b.d.u, o: "o" in o ? o.o : b.d.o, f: o.f ?? b.d.f ?? 0,
        p: (() => { while (pi < pr.length && pr[pi][1] < c) pi++; return pi < pr.length && pr[pi][0] <= c ? pr[pi][2] : null; })(),
      });
    }
  }
  return out;
}

function repoLink(repo, script) {
  if (repo) {
    const r = DATA.repos[repo];
    return `<a href="${r ? r.url : "https://github.com/notofonts/" + repo}" target="_blank" rel="noopener" title="${r && r.family ? r.family : repo}">${repo} ↗</a>`;
  }
  const s = script && !/^(Common|Inherited|Unknown)$/.test(script) ? script.replace(/_/g, " ") : "";
  return `<a class="nr" href="https://github.com/notofonts" target="_blank" rel="noopener" title="${s ? "No notofonts repo for " + s + " yet" : "No obvious repo"}">no repo yet</a>`;
}

const isMark = (ch) => /^M[nce]$/.test(ch.g);
const DC = "\u25CC";

function otherHTML(ch, txt) {
  if (!ch.o) return `<div class="pv"><span class="cap">Other fonts</span><div class="g na">none yet</div><span class="lbl">&nbsp;</span></div>`;
  const f = DATA.others[ch.o];
  const tip = `${f.name} ${f.version || ""}${f.release ? " · " + f.release : ""}${f.released ? " (" + f.released + ")" : ""}`;
  // A combining mark sits on a base from the same font: its dotted circle, or its own space.
  const base = isMark(ch) && f.base ? String.fromCodePoint(parseInt(f.base, 16)) : "";
  return `<div class="pv"><span class="cap">Other fonts</span><div class="g mk" style="font-family:'O-${ch.o}-${ch.f}-${(ch.c >> 10).toString(16)}','WA Tofu'">${base}${txt}</div><a href="${f.source || f.home}" target="_blank" rel="noopener" title="${tip}">${f.name} ↗</a></div>`;
}

function cellHTML(ch) {
  const isNew = ch.a === NEWV;
  const txt = String.fromCodePoint(ch.c);
  const fam = ch.r ? notoFamily(ch.r) : null;
  const notoFont = fam ? `font-family:'${fam}','WA Tofu'` : "font-family:'WA Tofu'";
  const mark = isMark(ch);
  const uni = ch.u
    ? `<div class="g uni">${mark ? DC : ""}${txt}</div>`
    : `<div class="g na">not in Unifont</div>`;
  return `<div class="row" id="u${hex(ch.c)}">
  <div class="meta-c">
    <div class="cp"><button title="Copy character" data-copy="${ch.c}">U+${hex(ch.c)}</button>${isNew ? `<span class="pill">NEW ${NEWV}</span>` : ""}</div>
    <div class="name">${ch.n}</div>
    ${docsHTML(ch.p)}
  </div>
  <div class="pv"><span class="cap">GNU Unifont</span>${uni}<span class="lbl">&nbsp;</span></div>
  <div class="pv"><span class="cap">Noto</span><div class="g noto" style="${notoFont}">${txt}</div>${repoLink(ch.r, ch.s)}</div>
  ${otherHTML(ch, txt)}
</div>`;
}

/* ---------- lazy chunk rendering ---------- */
function estimateHeight(n) {
  return n * (window.innerWidth <= 900 ? 200 : 120);
}

const io = new IntersectionObserver((entries) => {
  for (const e of entries) {
    if (!e.isIntersecting) continue;
    const ph = e.target;
    io.unobserve(ph);
    renderChunk(ph);
  }
}, { rootMargin: "1200px 0px" });

function renderChunk(ph) {
  const chars = ph._chars;
  const onlyNew = $("#f-new").checked;
  const html = chars.filter((ch) => !onlyNew || ch.a === NEWV).map(cellHTML).join("");
  const wrap = document.createElement("div");
  wrap.className = "chunk";
  wrap.innerHTML = html;
  ph.replaceWith(wrap);
}

function fillGrid(sec) {
  const grid = $(".rows", sec);
  grid.innerHTML = "";
  const onlyNew = $("#f-new").checked;
  const all = sec._chars.filter((ch) => !onlyNew || ch.a === NEWV);
  for (let i = 0; i < all.length; i += CHUNK) {
    const ph = document.createElement("div");
    ph.className = "ph";
    ph._chars = all.slice(i, i + CHUNK);
    ph.style.height = estimateHeight(ph._chars.length) + "px";
    grid.appendChild(ph);
    io.observe(ph);
  }
}

/* ---------- page ---------- */
function blockHeader(b) {
  const pct = (100 * b.covered / b.assigned);
  const pctTxt = pct === 0 ? "0" : pct < 1 ? "<1" : pct > 99 && pct < 100 ? ">99" : Math.round(pct);
  const repo = b.d.r;
  const r = repo && DATA.repos[repo];
  const repoTxt = repo
    ? `Repo: <a href="${r ? r.url : "#"}" target="_blank" rel="noopener">notofonts/${repo}</a>${r && r.family ? ` · ${r.family}` : ""}`
    : `<span class="pill norepo">No Noto repo yet</span>${b.d.x ? ` for ${b.d.s.replace(/_/g, " ")}` : ""}`;
  return `<div class="bh">
    <h2><a href="#${slug(b.name)}">${b.name}</a></h2>
    <span class="range">U+${hex(b.start)}–U+${hex(b.end)}</span>
    ${b.new ? `<span class="pill">${fmt(b.new)} new in ${NEWV}</span>` : ""}
    <div class="meta"><b>${fmt(b.missing)}</b> missing of ${fmt(b.assigned)} assigned · Noto covers ${pctTxt}% · ${repoTxt}</div>
    <div class="meta charts">${chartLinks(b)}</div>
  </div>`;
}

// Unicode code charts: the whole block, and per version the delta chart with only the characters
// that version added (Unicode-17.0/U170-1E6C0.pdf). There is no delta chart for 1.1.
const CHARTS = "https://www.unicode.org/charts/PDF/";
function chartLinks(b) {
  const start = hex(b.start);
  const ages = new Set([b.d.a]);
  for (const o of Object.values(b.ov)) if (o.a) ages.add(o.a);
  const vers = [...ages].filter((v) => v && v !== "1.1").sort((x, y) => parseFloat(x) - parseFloat(y));
  const ext = `target="_blank" rel="noopener"`;
  const delta = vers.map((v) =>
    `<a href="${CHARTS}Unicode-${v}/U${v.replace(".", "")}-${start}.pdf" ${ext} title="Characters added to this block in Unicode ${v}">${v}</a>`);
  return `Unicode charts: <a href="${CHARTS}U${start}.pdf" ${ext}>whole block</a>${delta.length ? " · added in " + delta.join(", ") : ""}`;
}

function build() {
  NEWV = DATA.unicode.split(".").slice(0, 2).join(".");
  const set = (k, v) => document.querySelectorAll(`[data-k="${k}"]`).forEach((el) => (el.textContent = v));
  set("unicode", NEWV);
  set("unicode-short", NEWV);
  set("unifont", DATA.unifont);
  set("built", DATA.built);
  set("families", fmt(DATA.families));
  set("others", Object.values(DATA.others).map((o) => `${o.name} ${o.release || o.version}`).join(", "));
  for (const g of GROUPS) {
    const n = DATA.blocks.filter((b) => b.group === g).reduce((s, b) => s + b.missing, 0);
    set("g-" + g, fmt(n));
    const box = $("#g-" + g);
    box.checked = store.get("g-" + g) === "1";
    box.addEventListener("change", () => { store.set("g-" + g, box.checked ? "1" : "0"); applyFilters(); });
  }

  const content = $("#content");
  const list = $("#blocklist");
  const jump = $("#jump");
  for (const b of DATA.blocks) {
    const id = slug(b.name);
    const sec = document.createElement("section");
    sec.className = "block";
    sec.id = id;
    sec._block = b;
    Object.defineProperty(sec, "_chars", { get() { return this.__c || (this.__c = charsOf(b)); } });
    sec.innerHTML = blockHeader(b) + `<div class="table"><div class="head"><span>Code point</span><span>GNU Unifont</span><span>Noto</span><span>Other open fonts</span></div><div class="rows"></div></div>`;
    content.appendChild(sec);

    const li = document.createElement("li");
    li.dataset.name = b.name.toLowerCase();
    li.innerHTML = `<a href="#${id}"><span class="bn">${b.name}${b.new ? '<span class="dot-new" title="Has characters new in ' + NEWV + '"></span>' : ""}</span><span class="bc">${fmt(b.missing)}</span><span class="bar"><i style="width:${(100 * b.covered / b.assigned).toFixed(1)}%"></i></span></a>`;
    list.appendChild(li);
    sec._li = li;

    const opt = document.createElement("option");
    opt.value = id;
    opt.textContent = `${b.name} — ${fmt(b.missing)}`;
    jump.appendChild(opt);
    sec._opt = opt;
  }
  applyFilters();
  trackActive();
  if (location.hash) requestAnimationFrame(() => goTo(location.hash.slice(1)));
}

function groupOn(g) { return !g || $("#g-" + g).checked; }

function applyFilters() {
  const onlyNew = $("#f-new").checked;
  const noIgn = $("#f-ign").checked;
  let total = 0, blocks = 0, fresh = 0;
  for (const sec of document.querySelectorAll("section.block")) {
    const b = sec._block;
    const hide = (onlyNew && !b.new) || (noIgn && IGNORABLE.test(b.name)) || !groupOn(b.group);
    sec.hidden = hide;
    sec._li.classList.toggle("filtered", hide);
    sec._li.style.display = hide ? "none" : "";
    sec._opt.hidden = hide;
    sec._opt.disabled = hide;
    if (!hide) {
      if (sec._filled !== onlyNew) { fillGrid(sec); sec._filled = onlyNew; }
      total += onlyNew ? b.new : b.missing; blocks++; fresh += b.new;
    }
  }
  const set = (k, v) => document.querySelectorAll(`[data-k="${k}"]`).forEach((el) => (el.textContent = v));
  set("total", fmt(total));
  set("blocks", fmt(blocks));
  set("new", fmt(fresh));
}

/* A link or search can point into a block whose group is switched off: switch it on. */
function reveal(sec) {
  const g = sec._block.group;
  if (g && !groupOn(g)) {
    $("#g-" + g).checked = true;
    store.set("g-" + g, "1");
  }
  if ($("#f-new").checked && !sec._block.new) $("#f-new").checked = false;
  if ($("#f-ign").checked && IGNORABLE.test(sec._block.name)) $("#f-ign").checked = false;
  if (sec.hidden) applyFilters();
}

function goTo(id) {
  let target = document.getElementById(id);
  // U+XXXX lookup
  const m = /^(?:u\+?)?([0-9a-f]{4,6})$/i.exec(id);
  if (!target && m) {
    const c = parseInt(m[1], 16);
    const sec = [...document.querySelectorAll("section.block")].find((s) => s._block.start <= c && c <= s._block.end);
    if (!sec) return false;
    reveal(sec);
    const ph = [...sec.querySelectorAll(".ph")].find((p) => p._chars.some((ch) => ch.c === c));
    if (ph) { io.unobserve(ph); renderChunk(ph); }
    target = document.getElementById("u" + hex(c));
    if (!target) { sec.scrollIntoView(); return true; }
    document.querySelectorAll(".row.hit").forEach((el) => el.classList.remove("hit"));
    target.classList.add("hit");
    target.scrollIntoView({ block: "center" });
    return true;
  }
  if (target && target._block) reveal(target);
  if (target) target.scrollIntoView();
  return !!target;
}

function trackActive() {
  let current = null;
  const obs = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (e.isIntersecting) {
        const sec = e.target;
        if (current) current._li.firstChild.classList.remove("active");
        current = sec;
        const a = sec._li.firstChild;
        a.classList.add("active");
        const box = $("#blocklist");
        const r = a.getBoundingClientRect(), br = box.getBoundingClientRect();
        if (r.top < br.top || r.bottom > br.bottom) a.scrollIntoView({ block: "nearest" });
        $("#jump").value = sec.id;
      }
    }
  }, { rootMargin: "0px 0px -85% 0px" });
  document.querySelectorAll("section.block").forEach((s) => obs.observe(s));
}

/* ---------- events ---------- */
document.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-copy]");
  if (btn) {
    const t = String.fromCodePoint(+btn.dataset.copy);
    navigator.clipboard?.writeText(t).then(() => {
      const old = btn.textContent;
      btn.textContent = "copied";
      setTimeout(() => (btn.textContent = old), 900);
    }).catch(() => {});
  }
});
$("#q").addEventListener("input", (e) => {
  const q = e.target.value.trim().toLowerCase();
  const m = /^(?:u\+?)?([0-9a-f]{4,6})$/.exec(q);
  const cp = m ? parseInt(m[1], 16) : null;
  for (const sec of document.querySelectorAll("section.block")) {
    const b = sec._block;
    const byName = b.name.toLowerCase().includes(q);
    const byCp = cp !== null && b.start <= cp && cp <= b.end;
    sec._li.classList.toggle("hidden", !!q && !byName && !byCp);
  }
});
$("#q").addEventListener("keydown", (e) => {
  if (e.key !== "Enter") return;
  const q = e.target.value.trim();
  if (/^(u\+?)?[0-9a-f]{4,6}$/i.test(q)) { goTo(q); return; }
  const li = [...document.querySelectorAll("#blocklist li")].find((l) => !l.classList.contains("hidden") && l.style.display !== "none");
  if (li) li.firstChild.click();
});
$("#jump").addEventListener("change", (e) => goTo(e.target.value));
window.addEventListener("hashchange", () => goTo(location.hash.slice(1)));
["#f-new", "#f-ign"].forEach((s) => $(s).addEventListener("change", () => applyFilters()));
let rT;
window.addEventListener("resize", () => {
  clearTimeout(rT);
  rT = setTimeout(() => document.querySelectorAll(".ph").forEach((ph) => {
    ph.style.height = estimateHeight(ph._chars.length) + "px";
  }), 150);
});

fetch("data.json?v=b8b09d6a").then((r) => r.json()).then((d) => { DATA = d; build(); });
