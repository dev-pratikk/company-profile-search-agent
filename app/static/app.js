const $ = (s) => document.querySelector(s);

/* =========================================================================
   DOM helpers — web data is only ever inserted as text, never as HTML.
   ========================================================================= */
function el(tag, attrs = {}, ...children) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") n.className = v;
    else n.setAttribute(k, v);
  }
  for (const c of children.flat(Infinity)) if (c != null && c !== false) n.append(c);
  return n;
}

// Static icon markup (constants only, never user data).
const ICONS = {
  phone: '<path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2"/>',
  mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
  pin: '<path d="M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11z"/><circle cx="12" cy="10" r="2.5"/>',
  share: '<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="m8.6 13.5 6.8 4M15.4 6.5l-6.8 4"/>',
  box: '<path d="M21 8 12 3 3 8v8l9 5 9-5z"/><path d="m3 8 9 5 9-5M12 13v8"/>',
  link: '<path d="M10 14a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1"/><path d="M14 10a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1"/>',
  check: '<path d="m5 12 5 5 9-10"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  out: '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a1 1 0 0 1 1-1h10"/>',
};
function icon(name) {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("viewBox", "0 0 24 24");
  s.innerHTML = ICONS[name];
  return s;
}

const prettyUrl = (u) => u.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "");
const hostOf = (u) => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return u; } };
const faviconFor = (u) => `https://www.google.com/s2/favicons?domain=${encodeURIComponent(hostOf(u))}&sz=64`;
const ext = (url, content, cls) =>
  el("a", { href: url, target: "_blank", rel: "noopener noreferrer", class: cls }, content ?? prettyUrl(url));
const none = (t = "Not found") => el("p", { class: "none" }, t);

/* =========================================================================
   Markdown renderer for the research report (safe: builds DOM nodes).
   Supports headings, paragraphs, nested lists, tables, quotes, rules,
   **bold**, *italic*, `code`, [links](url), bare URLs, emails and [n] citations.
   ========================================================================= */

// Pull the trailing "Sources" block ("[1] https://..." lines) out of the report.
function splitSources(md) {
  const lines = md.replace(/\r/g, "").split("\n");
  const isHeader = (l) => /^\s*(#{1,6}\s*)?(\*\*|__)?\s*(sources|references|citations)\s*:?\s*(\*\*|__)?\s*:?\s*$/i.test(l);
  for (let i = lines.length - 1; i >= 0; i--) {
    if (!isHeader(lines[i])) continue;
    const map = {};
    for (const l of lines.slice(i + 1)) {
      const m = l.match(/^\s*(?:[-*]\s*)?(?:\[(\d+)\]|(\d+)[.)])\s*(.*)$/);
      if (!m) continue;
      const rest = m[3];
      const link = rest.match(/\[([^\]]*)\]\((https?:\/\/[^)\s]+)\)/);
      let url = link ? link[2] : (rest.match(/https?:\/\/\S+/) || [])[0];
      if (!url) continue;
      url = url.replace(/[.,;)]+$/, "");
      const title = link ? link[1] : rest.replace(url, "").replace(/^[\s\-–:|]+|[\s\-–:|]+$/g, "");
      map[m[1] || m[2]] = { url, title };
    }
    if (Object.keys(map).length) return { body: lines.slice(0, i).join("\n"), map };
  }
  return { body: md, map: {} };
}

const INLINE = new RegExp([
  /\*\*(.+?)\*\*|__(.+?)__/.source,                                  // 1,2 bold
  /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/.source,                      // 3,4 link
  /\[(\d+(?:\s*[,–-]\s*\d+)*)\]/.source,                              // 5 citation(s)
  /`([^`]+)`/.source,                                                 // 6 code
  /(https?:\/\/[^\s<>"'\])]+)/.source,                                // 7 bare url
  /([A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})/.source, // 8 email
  /(?<![\w*])\*(?![\s*])([^*]+?)\*(?!\w)/.source,                     // 9 italic
].join("|"), "g");

function citeNumbers(s) {
  const out = [];
  for (const part of s.split(/\s*,\s*/)) {
    const r = part.match(/^(\d+)\s*[–-]\s*(\d+)$/);
    if (r) for (let i = +r[1]; i <= +r[2] && out.length < 30; i++) out.push(String(i));
    else out.push(part.trim());
  }
  return out;
}

function inline(text, ctx) {
  const out = [];
  let last = 0;
  for (const m of text.matchAll(INLINE)) {
    if (m.index > last) out.push(text.slice(last, m.index));
    if (m[1] != null || m[2] != null) out.push(el("strong", {}, inline(m[1] ?? m[2], ctx)));
    else if (m[3] != null) out.push(ext(m[4], inline(m[3], ctx)));
    else if (m[5] != null) out.push(citeNumbers(m[5]).map((n) => citeChip(n, ctx)));
    else if (m[6] != null) out.push(el("code", {}, m[6]));
    else if (m[7] != null) {
      let u = m[7];
      const trail = (u.match(/[.,;:!?]+$/) || [""])[0];
      if (trail) u = u.slice(0, -trail.length);
      out.push(ext(u, prettyUrl(u)), trail);
    }
    else if (m[8] != null) out.push(el("a", { href: "mailto:" + m[8] }, m[8]));
    else if (m[9] != null) out.push(el("em", {}, inline(m[9], ctx)));
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function citeChip(n, ctx) {
  const src = ctx.cite(n);
  if (!src) return el("span", { class: "cite" }, n);
  const a = el("a", { class: "cite", href: src.url, target: "_blank", rel: "noopener noreferrer",
                      title: `[${n}] ${src.title || ""}\n${src.url}` });
  const img = el("img", { src: src.favicon || faviconFor(src.url), alt: n, referrerpolicy: "no-referrer", loading: "lazy" });
  img.onerror = () => {
    if (src.favicon && img.src !== faviconFor(src.url)) { img.src = faviconFor(src.url); return; }
    img.replaceWith(n);
  };
  a.append(img);
  return a;
}

function renderMarkdown(md, ctx) {
  const root = el("div", { class: "md" });
  const lines = md.replace(/\r/g, "").split("\n");
  let para = [];
  let stack = []; // open lists: [{indent, node}]

  const flushPara = () => { if (para.length) { root.append(el("p", {}, inline(para.join(" "), ctx))); para = []; } };
  const closeLists = () => { stack = []; };

  for (let i = 0; i < lines.length; i++) {
    const raw = lines[i];
    const t = raw.trim();
    let m;
    if (!t) { flushPara(); closeLists(); continue; }

    if ((m = t.match(/^(#{1,6})\s+(.*?)\s*#*$/))) {
      flushPara(); closeLists();
      root.append(el("h" + m[1].length, {}, inline(m[2], ctx)));
      continue;
    }
    if (/^(-{3,}|\*{3,}|_{3,})$/.test(t)) { flushPara(); closeLists(); root.append(el("hr")); continue; }

    if (t.startsWith("|") && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
      flushPara(); closeLists();
      const cells = (l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      const head = cells(raw);
      const rows = [];
      i += 2;
      while (i < lines.length && lines[i].trim().startsWith("|")) rows.push(cells(lines[i++]));
      i--;
      root.append(el("div", { class: "tablewrap" }, el("table", {},
        el("thead", {}, el("tr", {}, head.map((c) => el("th", {}, inline(c, ctx))))),
        el("tbody", {}, rows.map((r) => el("tr", {}, r.map((c) => el("td", {}, inline(c, ctx)))))))));
      continue;
    }

    if ((m = raw.match(/^(\s*)([-*+]|\d+[.)])\s+(.*)$/))) {
      flushPara();
      const indent = m[1].replace(/\t/g, "  ").length;
      const tag = /\d/.test(m[2]) ? "OL" : "UL";
      while (stack.length && indent < stack.at(-1).indent) stack.pop();
      let top = stack.at(-1);
      if (top && indent === top.indent && top.node.tagName !== tag) { stack.pop(); top = stack.at(-1); }
      if (!top || indent > top.indent) {
        const list = el(tag.toLowerCase());
        if (top) (top.node.lastElementChild || top.node).append(list);
        else root.append(list);
        stack.push({ indent, node: list });
        top = stack.at(-1);
      }
      top.node.append(el("li", {}, inline(m[3], ctx)));
      continue;
    }

    if (stack.length && /^\s+/.test(raw)) { // continuation of a list item
      const li = stack.at(-1).node.lastElementChild;
      if (li) { li.append(" ", ...inline(t, ctx)); continue; }
    }

    if ((m = t.match(/^>\s?(.*)$/))) { flushPara(); closeLists(); root.append(el("blockquote", {}, inline(m[1], ctx))); continue; }

    closeLists();
    para.push(t);
  }
  flushPara();
  return root;
}

/* =========================================================================
   Research report view
   ========================================================================= */
function renderReport(r) {
  const d = r.data || {};
  const { body, map } = splitSources(d.content || "");
  const byUrl = new Map((d.sources || []).map((s) => [s.url.replace(/\/$/, ""), s]));

  // Number -> source. Prefer the report's own numbered list; fall back to API order.
  const numbered = Object.keys(map).length
    ? Object.entries(map).map(([n, s]) => {
        const api = byUrl.get(s.url.replace(/\/$/, ""));
        return [n, { url: s.url, title: api?.title || s.title || prettyUrl(s.url), favicon: api?.favicon }];
      })
    : (d.sources || []).map((s, i) => [String(i + 1), s]);
  const lookup = new Map(numbered);
  const ctx = { cite: (n) => lookup.get(String(n)) };

  const meta = [
    el("span", { class: "tag" }, "Tavily Research"),
    d.model ? el("span", { class: "tag" }, `model: ${d.model}`) : null,
    el("span", { class: "tag" }, `${numbered.length} sources`),
    d.credits != null ? el("span", { class: "tag" }, `${d.credits} credits`) : null,
    r.duration_ms != null ? el("span", { class: "tag" }, `${Math.round(r.duration_ms / 1000)}s`) : null,
  ];
  const copy = el("button", { type: "button", class: "iconbtn", title: "Copy report as Markdown" }, icon("copy"), el("span", {}, "Copy"));
  copy.onclick = async () => {
    try {
      await navigator.clipboard.writeText(d.content);
      copy.lastChild.textContent = "Copied";
    } catch { copy.lastChild.textContent = "Copy failed"; }
    setTimeout(() => (copy.lastChild.textContent = "Copy"), 1600);
  };

  const sources = numbered.length
    ? el("div", { class: "rsources" }, el("h3", {}, "Sources"),
        el("ol", {}, numbered.map(([n, s]) => {
          const img = el("img", { src: s.favicon || faviconFor(s.url), alt: "", referrerpolicy: "no-referrer", loading: "lazy" });
          img.onerror = () => img.replaceWith(el("span", { class: "fb" }));
          return el("li", { class: "rsrc" },
            el("span", { class: "n" }, `[${n}]`), img,
            el("span", { class: "t" }, ext(s.url, s.title || prettyUrl(s.url)), el("span", { class: "h" }, hostOf(s.url))));
        })))
    : null;

  return el("article", { class: "glass report" },
    el("div", { class: "rbar" }, el("div", { class: "rmeta" }, meta), copy),
    renderMarkdown(body, ctx),
    sources);
}

function researchLoading() {
  const sub = el("div", { class: "rsub" }, "Searching and reading sources. This usually takes 30–90 seconds.");
  const started = Date.now();
  const timer = setInterval(() => {
    if (!sub.isConnected) return clearInterval(timer);
    sub.textContent = `Searching and reading sources… ${Math.round((Date.now() - started) / 1000)}s (usually 30–90s)`;
  }, 1000);
  return el("div", { class: "glass researching" },
    el("div", { class: "rhead" }, el("span", { class: "tab-dot" }), "Writing the research report"),
    sub,
    ["40%", "92%", "85%", "70%", "30%", "88%", "76%"].map((w) => el("div", { class: "sk", style: `width:${w}` })));
}

/* =========================================================================
   Verified details view (official website + The Companies API)
   ========================================================================= */
const VIA = {
  "website structured data": ["Official website", "site"],
  "official website": ["Official website", "site"],
  "The Companies API": ["Companies API", "api"],
  "web search": ["Web search", "web"],
  "you provided": ["You provided", "user"],
};
function sourceChips(sources = []) {
  const seen = new Set();
  return sources.flatMap((s) => {
    const [label, cls] = VIA[s.via] || [s.via, ""];
    if (seen.has(label)) return [];
    seen.add(label);
    return s.url
      ? [el("a", { class: `chip ${cls}`, href: s.url, target: "_blank", rel: "noopener noreferrer", title: s.url }, label, icon("out"))]
      : [el("span", { class: `chip ${cls}` }, label)];
  });
}

function card(title, iconName, count, ...body) {
  return el("section", { class: "glass pcard" },
    el("h3", {}, el("span", { class: "ic" }, icon(iconName)), title, count ? el("span", { class: "count" }, count) : null),
    body);
}

function row(it, valueNode, ...tags) {
  return el("li", { class: "row" },
    el("div", { class: "rv" }, valueNode ?? it.value, tags),
    el("div", { class: "chips" }, sourceChips(it.sources)));
}

function sourcesList(list, label = "sources") {
  if (!list?.length) return null;
  return el("details", { class: "srcs" },
    el("summary", {}, `${list.length} ${label}`),
    el("ol", {}, list.map((s) => el("li", {}, ext(s.url, s.title)))));
}

function linkPills(pages, label) {
  if (!pages?.length) return null;
  return el("div", { class: "sub" },
    el("div", { class: "sublabel" }, label),
    el("div", { class: "linkpills" }, pages.map((p) => ext(p.url, p.title || prettyUrl(p.url), "linkpill"))));
}

const SOCIAL = {
  linkedin: ["LinkedIn", "in"], x_twitter: ["X / Twitter", "X"], facebook: ["Facebook", "f"],
  instagram: ["Instagram", "IG"], youtube: ["YouTube", "▶"],
};

function logoNode(name, candidates = []) {
  const initial = el("div", { class: "logo fallback" }, (name || "?").trim()[0]?.toUpperCase() || "?");
  if (!candidates.length) return initial;
  const img = el("img", { class: "logo", alt: `${name} logo`, referrerpolicy: "no-referrer" });
  let i = 0;
  img.onerror = () => { i += 1; if (i < candidates.length) img.src = candidates[i]; else img.replaceWith(initial); };
  img.src = candidates[0];
  return img;
}

function profileHeader(d) {
  const p = d.products || {};
  return el("article", { class: "glass phead" },
    logoNode(d.name.value, (d.logo?.candidates || []).map((c) => c.url)),
    el("div", {},
      el("div", { class: "pname" }, d.name.value),
      d.legal_name && d.legal_name.toLowerCase() !== d.name.value.toLowerCase()
        ? el("div", { class: "tagline" }, "Legal name: ", d.legal_name) : null,
      el("div", { class: "pweb" },
        ext(d.website.url, prettyUrl(d.website.url)),
        d.website.reachable ? el("span", { class: "tag good" }, "website online") : el("span", { class: "tag bad" }, "not reachable"),
        p.industry ? el("span", { class: "tag" }, p.industry) : null),
      p.tagline ? el("div", { class: "tagline" }, p.tagline) : null));
}

function placeholderHeader(name) {
  return el("article", { class: "glass phead" },
    el("div", { class: "sk l", style: "margin:0" }),
    el("div", {}, el("div", { class: "pname" }, name), el("div", { class: "sk", style: "width:180px" })));
}

function simpleHeader(name) {
  return el("article", { class: "glass phead" }, logoNode(name), el("div", {}, el("div", { class: "pname" }, name)));
}

function profileBody(d) {
  const phones = d.contact?.phones || [];
  const contact = card("Contact Information", "phone", phones.length ? `${phones.length} found` : null,
    phones.length
      ? el("ul", { class: "rows" }, phones.map((ph) => row(ph,
          el("a", { href: "tel:" + ph.value.replace(/[^\d+]/g, "") }, ph.value),
          ph.label ? el("span", { class: "tag" }, ph.label) : null,
          ph.matches_input ? el("span", { class: "tag good" }, "matches your input") : null)))
      : none("No phone number found"),
    linkPills(d.contact?.pages, "Contact pages"));

  const emails = d.emails || [];
  const email = card("Official Email Address", "mail", emails.length ? `${emails.length} found` : null,
    emails.length
      ? el("ul", { class: "rows" }, emails.map((e) => row(e,
          el("a", { href: "mailto:" + e.value }, e.value),
          e.label ? el("span", { class: "tag" }, e.label) : null,
          e.official ? null : el("span", { class: "tag bad" }, "not company domain"),
          e.matches_input ? el("span", { class: "tag good" }, "matches your input") : null)))
      : none());

  const a = d.address || {};
  const address = card("Company Address", "pin", null,
    a.items?.length ? el("ul", { class: "rows" }, a.items.map((it) => row(it,
      ext("https://www.google.com/maps/search/?api=1&query=" + encodeURIComponent(it.value), it.value)))) : null,
    a.answer ? el("div", { class: "sub" }, el("div", { class: "sublabel" }, "From web search"), el("div", { class: "answer" }, a.answer), sourcesList(a.answer_sources)) : null,
    !a.items?.length && !a.answer ? none() : null);

  const socialKeys = Object.keys(SOCIAL).filter((k) => d.social?.[k]?.length);
  const social = card("Social Media Profiles", "share", socialKeys.length ? `${socialKeys.length} of 5` : null,
    socialKeys.length
      ? el("ul", { class: "socials" }, socialKeys.flatMap((k) => d.social[k].map((s) =>
          el("li", { class: "soc" },
            el("span", { class: `sbadge ${k}` }, SOCIAL[k][1]),
            el("div", {},
              el("div", { class: "sname" }, SOCIAL[k][0]),
              el("div", { class: "surl" }, ext(s.value)),
              el("div", { class: "chips" }, sourceChips(s.sources)))))))
      : none());

  const p = d.products || {};
  const products = el("section", { class: "glass pcard wide" },
    el("h3", {}, el("span", { class: "ic" }, icon("box")), "Products & Services"),
    p.description ? el("div", { class: "answer" }, p.description) : null,
    p.answer ? el("div", { class: "sub" }, el("div", { class: "sublabel" }, "Products & services overview"), el("div", { class: "answer" }, p.answer), sourcesList(p.answer_sources)) : null,
    p.industries?.length ? el("div", { class: "sub" }, el("div", { class: "sublabel" }, "Industries"),
      el("div", { class: "linkpills" }, p.industries.map((i) => el("span", { class: "tag" }, i)))) : null,
    linkPills(p.pages, "Pages on the official website"),
    !p.description && !p.answer && !p.pages?.length ? none() : null);

  const coverage = el("div", { class: "glass coverage-bar" },
    el("div", { class: "coverage" }, Object.entries(d.coverage || {}).map(([k, ok]) =>
      el("span", { class: `cov ${ok ? "yes" : "no"}` }, icon(ok ? "check" : "x"), k))));

  return [coverage, el("div", { class: "pgrid" }, contact, email, address, social, products), allLinks(d), notesBox(d.notes)];
}

// Every link in the profile, split into official site vs other sources.
function allLinks(d) {
  const urls = new Map();
  const add = (u, t) => { if (u && /^https?:/.test(u) && !urls.has(u)) urls.set(u, t || prettyUrl(u)); };
  add(d.website.url, "Official website");
  (d.contact?.pages || []).forEach((p) => add(p.url, p.title));
  (d.products?.pages || []).forEach((p) => add(p.url, p.title));
  Object.values(d.social || {}).flat().forEach((s) => add(s.value));
  [d.name, ...(d.contact?.phones || []), ...(d.emails || []), ...(d.address?.items || []), ...Object.values(d.social || {}).flat()]
    .forEach((it) => (it?.sources || []).forEach((s) => add(s.url)));
  [...(d.address?.answer_sources || []), ...(d.products?.answer_sources || [])].forEach((s) => add(s.url, s.title));

  const domain = d.website.domain;
  const isOfficial = (u) => { const h = hostOf(u); return h === domain || h.endsWith("." + domain); };
  const official = [...urls].filter(([u]) => isOfficial(u));
  const other = [...urls].filter(([u]) => !isOfficial(u));
  const list = (items) => items.length ? el("ul", {}, items.map(([u, t]) => el("li", {}, ext(u, t)))) : none("None");

  return el("details", { class: "glass alllinks" },
    el("summary", {}, el("span", { class: "ic" }, icon("link")), "All links & sources", el("span", { class: "count" }, `${urls.size}`)),
    el("div", { class: "linkgroups" },
      el("div", {}, el("div", { class: "sublabel" }, "Official website"), list(official)),
      el("div", {}, el("div", { class: "sublabel" }, "Other sources"), list(other))));
}

function notesBox(notes) {
  return notes?.length ? el("div", { class: "notes" }, el("ul", {}, notes.map((n) => el("li", {}, n)))) : null;
}

function messageCard(r) {
  return el("article", { class: "glass card" },
    el("h3", {}, r.label, " ", el("span", { class: `tag ${r.status === "ok" ? "good" : "bad"}` }, r.status)),
    el("p", {}, r.summary));
}

function skeleton() {
  return el("div", { class: "glass skeleton" },
    ["40%", "70%", "55%", "62%"].map((w) => el("div", { class: "sk", style: `width:${w}` })));
}

/* =========================================================================
   Config + providers
   ========================================================================= */
let CONFIG = { tools: [], research_model: null };
const isConfigured = (name) => !!CONFIG.tools.find((t) => t.name === name)?.configured;

async function loadConfig() {
  try {
    CONFIG = await (await fetch("/api/tools")).json();
    const providers = CONFIG.tools.flatMap((t) => t.providers || []);
    if (isConfigured("research_report")) providers.push({ name: `Research · ${CONFIG.research_model}`, configured: true });
    $("#providers").replaceChildren(...providers.map((p) =>
      el("span", { class: `prov ${p.configured ? "on" : ""}`, title: p.configured ? "Connected" : "API key missing in .env" },
        el("i"), p.name, p.configured ? null : " · no key")));
  } catch { /* non-critical */ }
}

/* =========================================================================
   Search flow: each tool loads independently and shows when ready.
   ========================================================================= */
async function runTool(name, payload) {
  const res = await fetch(`/api/run/${name}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail?.[0]?.msg || data.detail || `HTTP ${res.status}`);
  return data.result;
}

function buildTabs(panes) {
  const bar = el("nav", { class: "glass tabs", role: "tablist" });
  const buttons = {};
  for (const [key, label] of panes) {
    const dot = el("span", { class: "dot loading" });
    const b = el("button", { type: "button", class: "tab", role: "tab" }, dot, label);
    b.onclick = () => select(key);
    buttons[key] = { b, dot };
    bar.append(b);
  }
  function select(key) {
    for (const [k, { b }] of Object.entries(buttons)) b.classList.toggle("active", k === key);
    document.querySelectorAll(".pane").forEach((p) => p.classList.toggle("hidden", p.dataset.pane !== key));
  }
  return { bar, select, setState: (key, s) => buttons[key] && (buttons[key].dot.className = `dot ${s}`) };
}

$("#form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const nameField = e.target.company_name;
  const nameWrap = nameField.closest(".field");
  if (!nameField.value.trim()) { nameWrap.classList.add("invalid"); nameField.focus(); return; }
  nameWrap.classList.remove("invalid");

  const status = $("#status");
  status.className = "";
  status.textContent = "";
  const hasProfile = isConfigured("company_profile");
  const hasReport = isConfigured("research_report");
  if (!hasProfile && !hasReport) {
    status.className = "err";
    status.textContent = "No API keys configured. Add TAVILY_API_KEY and/or COMPANIES_API_KEY to .env.";
    return;
  }

  const payload = Object.fromEntries(new FormData(e.target).entries());
  const btn = $("#submit");
  btn.disabled = true;
  btn.querySelector("span").textContent = "Searching…";

  // Layout: header, tabs, panes.
  let head = placeholderHeader(payload.company_name.trim());
  const reportPane = hasReport ? el("div", { class: "pane", "data-pane": "report" }, researchLoading()) : null;
  const verifiedPane = hasProfile ? el("div", { class: "pane", "data-pane": "verified" }, skeleton()) : null;
  const tabs = hasReport && hasProfile ? buildTabs([["report", "Report"], ["verified", "Verified details"]]) : null;
  $("#results").replaceChildren(head, tabs?.bar, reportPane, verifiedPane);
  tabs?.select(hasReport ? "report" : "verified");

  const replaceHead = (node) => { head.replaceWith(node); head = node; };
  const jobs = [];

  if (hasProfile) {
    jobs.push(runTool("company_profile", payload).then((r) => {
      if (r.data?.website) {
        replaceHead(profileHeader(r.data));
        verifiedPane.replaceChildren(...profileBody(r.data).filter(Boolean));
      } else {
        replaceHead(simpleHeader(payload.company_name.trim()));
        verifiedPane.replaceChildren(messageCard(r));
      }
      tabs?.setState("verified", r.status);
    }).catch((err) => {
      replaceHead(simpleHeader(payload.company_name.trim()));
      verifiedPane.replaceChildren(messageCard({ label: "Verified details", status: "error", summary: err.message }));
      tabs?.setState("verified", "error");
    }));
  } else {
    replaceHead(simpleHeader(payload.company_name.trim()));
  }

  if (hasReport) {
    jobs.push(runTool("research_report", payload).then((r) => {
      reportPane.replaceChildren(r.status === "ok" ? renderReport(r) : messageCard(r));
      tabs?.setState("report", r.status);
    }).catch((err) => {
      reportPane.replaceChildren(messageCard({ label: "Research Report", status: "error", summary: err.message }));
      tabs?.setState("report", "error");
    }));
  }

  await Promise.allSettled(jobs);
  btn.disabled = false;
  btn.querySelector("span").textContent = "Search";
});

$("#form").company_name.addEventListener("input", (e) => e.target.closest(".field").classList.remove("invalid"));
$("#form").addEventListener("reset", () => {
  $("#results").replaceChildren();
  $("#status").textContent = "";
  $("#status").className = "";
});

loadConfig();
