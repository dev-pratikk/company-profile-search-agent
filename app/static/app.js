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
  copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a1 1 0 0 1 1-1h10"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
  warn: '<path d="M12 3 2 20h20z"/><path d="M12 10v4M12 17h.01"/>',
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

/* ---- social platforms: official icon (the platform's own favicon) ---- */
const PLATFORM_KEYS = [
  [/linked\s*in/i, "linkedin.com"], [/facebook/i, "facebook.com"], [/instagram/i, "instagram.com"],
  [/you\s*tube/i, "youtube.com"], [/whats\s*app/i, "whatsapp.com"], [/telegram/i, "telegram.org"],
  [/twitter|^x\b/i, "x.com"], [/pinterest/i, "pinterest.com"], [/tik\s*tok/i, "tiktok.com"],
  [/threads/i, "threads.net"], [/github/i, "github.com"],
];
const PLATFORM_HOSTS = {
  "linkedin.com": "linkedin.com", "facebook.com": "facebook.com", "fb.com": "facebook.com",
  "instagram.com": "instagram.com", "youtube.com": "youtube.com", "youtu.be": "youtube.com",
  "x.com": "x.com", "twitter.com": "x.com", "whatsapp.com": "whatsapp.com", "wa.me": "whatsapp.com",
  "t.me": "telegram.org", "telegram.me": "telegram.org", "pinterest.com": "pinterest.com",
  "tiktok.com": "tiktok.com", "threads.net": "threads.net", "github.com": "github.com",
};
const platformOfKey = (key) => (PLATFORM_KEYS.find(([re]) => re.test(key.trim())) || [])[1] || null;
function platformOfUrl(url) {
  const h = hostOf(url);
  const base = Object.keys(PLATFORM_HOSTS).find((d) => h === d || h.endsWith("." + d));
  return base ? PLATFORM_HOSTS[base] : null;
}
function brandIcon(domain) {
  const img = el("img", { class: "brand-ic", alt: "", referrerpolicy: "no-referrer", loading: "lazy",
                          src: `https://www.google.com/s2/favicons?domain=${domain}&sz=64` });
  img.onerror = () => img.remove();
  return img;
}

// "**Phone:** +91 ..." / "Phone: ..." / "Kite — trading platform"  ->  bold key, normal-weight value.
const KEY_RE = /^(?:\*\*|__)?([^:*_[\]\n]{1,48}?)(?:\*\*|__)?\s*(?::|\s[–—]\s)\s*(?:\*\*|__)?\s*(.+)$/;
function keyed(text, ctx) {
  const m = text.match(KEY_RE);
  if (!m || /https?:|https?$|www\.|@/i.test(m[1].trim()) || m[2].startsWith("//")
      || m[1].trim().split(/\s+/).length > 7) return inline(text, ctx);
  const key = m[1].trim();
  const platform = platformOfKey(key);
  return [
    platform ? brandIcon(platform) : null,
    el("span", { class: "k" }, inline(key, ctx)), ": ",
    el("span", { class: "v" }, inline(m[2], platform ? { ...ctx, noIcon: true } : ctx)),
  ];
}

function socialLink(url, content, ctx) {
  const platform = !ctx.noIcon && platformOfUrl(url);
  return platform ? [brandIcon(platform), ext(url, content)] : ext(url, content);
}

function inline(text, ctx) {
  const out = [];
  let last = 0;
  for (const m of text.matchAll(INLINE)) {
    if (m.index > last) out.push(text.slice(last, m.index));
    if (m[1] != null || m[2] != null) out.push(el("strong", {}, inline(m[1] ?? m[2], ctx)));
    else if (m[3] != null) out.push(socialLink(m[4], inline(m[3], ctx), ctx));
    else if (m[5] != null) out.push(citeNumbers(m[5]).map((n) => citeChip(n, ctx)));
    else if (m[6] != null) out.push(el("code", {}, m[6]));
    else if (m[7] != null) {
      let u = m[7];
      const trail = (u.match(/[.,;:!?]+$/) || [""])[0];
      if (trail) u = u.slice(0, -trail.length);
      out.push(socialLink(u, prettyUrl(u), ctx), trail);
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

  const flushPara = () => { if (para.length) { root.append(el("p", {}, keyed(para.join(" "), ctx))); para = []; } };
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
      top.node.append(el("li", {}, keyed(m[3], ctx)));
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
   Official website card
   ========================================================================= */
const CONFIDENCE = {
  provided: ["You provided", "good"],
  email: ["From contact email", "good"],
  high: ["High confidence", "good"],
  medium: ["Likely", "mid"],
  low: ["Not sure", "bad"],
};

function logoNode(name, urls) {
  const initial = el("div", { class: "logo fallback" }, (name || "?").trim()[0]?.toUpperCase() || "?");
  const list = urls.filter(Boolean);
  if (!list.length) return initial;
  const img = el("img", { class: "logo", alt: "", referrerpolicy: "no-referrer" });
  let i = 0;
  img.onerror = () => { i += 1; if (i < list.length) img.src = list[i]; else img.replaceWith(initial); };
  img.src = list[0];
  return img;
}

function siteCard(name, site, onPick) {
  if (!site) {
    return el("article", { class: "glass phead" },
      el("div", { class: "sk l", style: "margin:0" }),
      el("div", {}, el("div", { class: "pname" }, name),
        el("div", { class: "muted" }, "Finding the official website…")));
  }
  if (!site.domain) {
    return el("article", { class: "glass phead" }, logoNode(name, []),
      el("div", {}, el("div", { class: "pname" }, name),
        el("div", { class: "muted" }, "Could not identify the official website. The report will try to find it; " +
          "for a better result, enter the website or location and search again.")));
  }

  const fromEmail = site.via === "contact email";
  const [confLabel, confCls] = CONFIDENCE[fromEmail ? "email" : site.confidence] || ["", ""];
  const warn = !fromEmail && (site.ambiguous || site.confidence === "low");
  const alts = (site.candidates || []).slice(0, 4);

  // Email given: also show what web search found, if it's a different website.
  const s2 = site.search_site;
  const searchRow = fromEmail
    ? s2
      ? el("div", { class: "pweb second" },
          el("span", { class: "muted" }, "Found by web search:"),
          ext(s2.url, prettyUrl(s2.url), "site"),
          (() => { const b = el("button", { type: "button", class: "alt" }, "Use this instead"); b.onclick = () => onPick(s2.domain); return b; })())
      : site.search_agrees
        ? el("div", { class: "muted second" }, "Web search found the same website.")
        : site.search_error
          ? el("div", { class: "muted second" }, "Web search could not run: ", site.search_error)
          : null
    : null;

  const altRow = alts.length && !fromEmail && site.confidence !== "high" && site.confidence !== "provided"
    ? el("div", { class: "alts" }, el("span", { class: "muted" }, "Not the right company? Other matches:"),
        alts.map((c) => {
          const b = el("button", { type: "button", class: "alt", title: c.title || c.url }, c.domain);
          b.onclick = () => onPick(c.domain);
          return b;
        }))
    : null;

  return el("article", { class: "glass phead" },
    logoNode(name, [`https://www.google.com/s2/favicons?domain=${encodeURIComponent(site.domain)}&sz=128`, site.favicon]),
    el("div", {},
      el("div", { class: "pname" }, site.matched_name || name),
      site.matched_name
        ? el("div", { class: "muted" }, "Showing results for ", el("b", {}, site.matched_name), ` (you typed “${name}”)`)
        : null,
      el("div", { class: "pweb" },
        icon("globe"),
        ext(site.url, prettyUrl(site.url), "site"),
        confLabel ? el("span", { class: `tag ${confCls}` }, confLabel) : null),
      searchRow,
      warn
        ? el("div", { class: "warnbox" }, icon("warn"),
            el("div", {}, site.ambiguous
              ? `Several companies are named “${name}”. Make sure this is the right website, or add a location and search again.`
              : "This website could not be confirmed. Check it, or enter the right website and search again."))
        : null,
      altRow));
}

/* =========================================================================
   Research report view
   ========================================================================= */
function renderReport(d) {
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
    d.model === "search"
      ? el("span", { class: "tag" }, "Tavily Search · quick report")
      : el("span", { class: "tag" }, "Tavily Research"),
    d.model && d.model !== "search" ? el("span", { class: "tag" }, `model: ${d.model}`) : null,
    el("span", { class: "tag" }, `${numbered.length} sources`),
    d.credits != null ? el("span", { class: "tag" }, `${d.credits} credits`) : null,
    d.duration_ms != null ? el("span", { class: "tag" }, `${Math.round(d.duration_ms / 1000)}s`) : null,
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

  const prompt = d.prompt
    ? el("details", { class: "prompt" }, el("summary", {}, "Prompt sent to Tavily Research"), el("pre", {}, d.prompt))
    : null;

  return el("article", { class: "glass report" },
    el("div", { class: "rbar" }, el("div", { class: "rmeta" }, meta), copy),
    d.note ? el("div", { class: "rnote" }, d.note) : null,
    renderMarkdown(body, ctx),
    sources,
    prompt);
}

function researchLoading() {
  const sub = el("div", { class: "rsub" }, "Searching and reading sources. This usually takes 30–120 seconds.");
  const started = Date.now();
  const timer = setInterval(() => {
    if (!sub.isConnected) return clearInterval(timer);
    sub.textContent = `Searching and reading sources… ${Math.round((Date.now() - started) / 1000)}s (usually 30–120s)`;
  }, 1000);
  return el("div", { class: "glass researching" },
    el("div", { class: "rhead" }, el("span", { class: "spin" }), "Writing the company report"),
    sub,
    ["40%", "92%", "85%", "70%", "30%", "88%", "76%"].map((w) => el("div", { class: "sk", style: `width:${w}` })));
}

function messageCard(title, text) {
  return el("article", { class: "glass card" }, el("h3", {}, title), el("p", {}, text));
}

/* =========================================================================
   Search flow: 1) find the official website  2) research report
   ========================================================================= */
let CONFIG = { configured: false, model: null };

async function loadConfig() {
  try {
    CONFIG = await (await fetch("/api/config")).json();
    const u = CONFIG.usage;
    const left = u ? u.limit - u.used : null;
    $("#provider").replaceChildren(
      el("span", { class: `prov ${CONFIG.configured ? "on" : ""}`, title: CONFIG.configured ? "Connected" : "TAVILY_API_KEY missing in .env" },
        el("i"), CONFIG.configured ? `Tavily · research model: ${CONFIG.model}` : "Tavily · no API key"),
      u ? el("span", { class: `prov ${left < 250 ? "low" : "on"}`, title: `${u.plan || "Plan"}: ${u.used} of ${u.limit} credits used` },
        el("i"), `${left} of ${u.limit} credits left`) : null);
  } catch { /* non-critical */ }
}

async function post(path, payload) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail?.[0]?.msg || data.detail || `HTTP ${res.status}`);
  return data;
}

let searchId = 0;

$("#form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const nameField = form.company_name;
  const nameWrap = nameField.closest(".field");
  if (!nameField.value.trim()) { nameWrap.classList.add("invalid"); nameField.focus(); return; }
  nameWrap.classList.remove("invalid");

  const status = $("#status");
  status.className = "";
  status.textContent = "";
  if (!CONFIG.configured) {
    status.className = "err";
    status.textContent = "TAVILY_API_KEY is not set. Add it to .env and restart.";
    return;
  }

  const id = ++searchId; // ignore results from an older search
  const payload = Object.fromEntries(new FormData(form).entries());
  const name = payload.company_name.trim();
  const btn = $("#submit");
  btn.disabled = true;
  btn.querySelector("span").textContent = "Searching…";

  const pick = (domain) => { form.domain.value = domain; form.requestSubmit(); };
  let head = siteCard(name, null, pick);
  const pane = el("div", { class: "pane" });
  $("#results").replaceChildren(head, pane);
  const setHead = (node) => { head.replaceWith(node); head = node; };

  try {
    // Step 1: official website
    const site = await post("/api/resolve", payload);
    if (id !== searchId) return;
    setHead(siteCard(name, site, pick));

    // Step 2: report, anchored to that website
    pane.replaceChildren(researchLoading());
    const report = await post("/api/report", {
      ...payload,
      company_name: site.matched_name || payload.company_name, // corrected spelling, if any
      domain: site.domain,
      domain_confidence: site.confidence,
      other_domain: site.search_site?.domain || null,
    });
    if (id !== searchId) return;
    pane.replaceChildren(report.content?.trim()
      ? renderReport(report)
      : messageCard("No report", "Tavily Research finished but returned no report. Try again."));
    loadConfig(); // refresh the credits counter
  } catch (err) {
    if (id !== searchId) return;
    if (head.querySelector(".sk")) setHead(siteCard(name, { domain: null }, pick));
    pane.replaceChildren(messageCard("Search failed", err.message));
  } finally {
    if (id === searchId) {
      btn.disabled = false;
      btn.querySelector("span").textContent = "Search";
    }
  }
});

$("#form").company_name.addEventListener("input", (e) => e.target.closest(".field").classList.remove("invalid"));
$("#form").addEventListener("reset", () => {
  searchId++;
  $("#results").replaceChildren();
  $("#status").textContent = "";
  $("#status").className = "";
  $("#submit").disabled = false;
  $("#submit").querySelector("span").textContent = "Search";
});

loadConfig();
