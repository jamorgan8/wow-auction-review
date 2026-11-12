"use strict";

// ------------------------------------------------------------ utilities
const $ = (sel, root = document) => root.querySelector(sel);
const view = $("#view");
const state = { realm: null, overview: null, charts: [], sort: {} };

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function money(copper) {
  if (copper === null || copper === undefined || isNaN(copper)) return '<span class="muted">–</span>';
  let c = Math.round(copper);
  const neg = c < 0; c = Math.abs(c);
  const g = Math.floor(c / 10000), s = Math.floor(c / 100) % 100, cp = c % 100;
  const parts = [];
  if (g) parts.push(`<span class="g">${g.toLocaleString()}<i>g</i></span>`);
  if (s || (g && cp)) parts.push(`<span class="s">${s}<i>s</i></span>`);
  if (cp || !parts.length) parts.push(`<span class="c">${cp}<i>c</i></span>`);
  return `<span class="money">${neg ? "−" : ""}${parts.join("")}</span>`;
}

function moneyText(copper) {
  if (copper === null || copper === undefined) return "–";
  const c = Math.round(copper);
  const g = Math.floor(c / 10000), s = Math.floor(c / 100) % 100, cp = c % 100;
  return [g ? `${g}g` : "", s ? `${s}s` : "", cp || (!g && !s) ? `${cp}c` : ""].filter(Boolean).join(" ");
}

// "1g 20s 5c", "1.5g", "35s", or a bare number (= gold) -> copper
function parseMoney(text) {
  text = String(text || "").trim().toLowerCase();
  if (!text) return null;
  if (/^\d+(\.\d+)?$/.test(text)) return Math.round(parseFloat(text) * 10000);
  let total = 0, matched = false;
  for (const [, num, unit] of text.matchAll(/(\d+(?:\.\d+)?)\s*([gsc])/g)) {
    matched = true;
    total += parseFloat(num) * { g: 10000, s: 100, c: 1 }[unit];
  }
  return matched ? Math.round(total) : NaN;
}

// Default colours read as prices: rises red, drops green. goodWhenUp flips that (e.g. profit margins).
function pct(change, goodWhenUp = false) {
  if (change === null || change === undefined) return "–";
  let cls = change > 0.005 ? "up" : change < -0.005 ? "down" : "flat";
  if (goodWhenUp && cls !== "flat") cls = cls === "up" ? "down" : "up";
  const sign = change > 0 ? "+" : "";
  const v = Math.abs(change) >= 10 ? `${sign}${Math.round(change * 100).toLocaleString()}%` : `${sign}${(change * 100).toFixed(1)}%`;
  return `<span class="pill ${cls}">${v}</span>`;
}

function itemName(r) {
  const q = r.quality ?? 1;
  return `<span class="${r.named ? "q" + q : "unnamed"}" title="${esc(r.item_key)}">${esc(r.name)}</span>`;
}

const ago = (ts) => {
  if (!ts) return "never";
  const s = Date.now() / 1000 - ts;
  if (s < 90) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400 * 2) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} days ago`;
};

async function api(path, opts = {}) {
  const url = new URL("/api/" + path, location.origin);
  if (state.realm && !opts.method) url.searchParams.set("realm", state.realm);
  for (const [k, v] of Object.entries(opts.params || {})) url.searchParams.set(k, v);
  const res = await fetch(url, {
    method: opts.method || "GET",
    headers: opts.body ? { "Content-Type": "application/json" } : undefined,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

function destroyCharts() {
  state.charts.forEach((c) => c.destroy());
  state.charts = [];
}

const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

// ------------------------------------------------------------ sortable tables
function table(id, rows, columns, { onRow, empty = "Nothing to show yet." } = {}) {
  if (!rows.length) return `<div class="table-wrap"><div class="empty-state">${empty}</div></div>`;
  const sort = state.sort[id];
  if (sort) {
    const col = columns.find((c) => c.key === sort.key);
    const val = col.sortValue || ((r) => r[col.key]);
    rows = [...rows].sort((a, b) => {
      const x = val(a), y = val(b);
      if (x === y) return 0;
      if (x === null || x === undefined) return 1;
      if (y === null || y === undefined) return -1;
      return (x < y ? -1 : 1) * (sort.asc ? 1 : -1);
    });
  }
  const head = columns.map((c) => {
    const cls = [c.num ? "num" : "", sort?.key === c.key ? "sorted" : "", sort?.key === c.key && sort.asc ? "asc" : ""].join(" ");
    return `<th class="${cls}" data-sort="${c.key}" data-table="${id}">${c.label}</th>`;
  }).join("");
  const body = rows.map((r, i) => `<tr data-row="${i}">${columns.map((c) =>
    `<td class="${c.num ? "num" : ""} ${c.key === "name" ? "item" : ""}">${c.render ? c.render(r) : esc(r[c.key])}</td>`).join("")}</tr>`).join("");
  setTimeout(() => {
    const t = document.getElementById(id);
    if (!t) return;
    t.querySelectorAll("tbody tr").forEach((tr) =>
      tr.addEventListener("click", () => (onRow || openItem)(rows[+tr.dataset.row])));
  });
  return `<div class="table-wrap"><table id="${id}"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

document.addEventListener("click", (e) => {
  const th = e.target.closest("th[data-sort]");
  if (!th) return;
  const id = th.dataset.table, key = th.dataset.sort;
  const cur = state.sort[id];
  state.sort[id] = cur?.key === key ? { key, asc: !cur.asc } : { key, asc: false };
  route();
});

const openItem = (r) => { location.hash = `#/item/${encodeURIComponent(r.item_key)}`; };

// shared column definitions
const C = {
  name: { key: "name", label: "Item", render: itemName, sortValue: (r) => r.name.toLowerCase() },
  price: { key: "price", label: "Lowest price", num: true, render: (r) => money(r.price) },
  baseline: { key: "baseline", label: "Usual price", num: true, render: (r) => money(r.baseline) },
  change: { key: "change", label: "Change", num: true, render: (r) => pct(r.change) },
  avail: { key: "available", label: "Listed", num: true, render: (r) => (r.available ?? "–").toLocaleString() },
};

// ------------------------------------------------------------ views
function controls(fields, onChange) {
  const html = fields.map((f) => {
    if (f.options) {
      return `<label>${f.label}<select data-k="${f.k}">${f.options.map(([v, t]) =>
        `<option value="${v}" ${String(f.value) === String(v) ? "selected" : ""}>${t}</option>`).join("")}</select></label>`;
    }
    return `<label>${f.label}<input class="field" type="text" data-k="${f.k}" value="${esc(f.value ?? "")}" placeholder="${esc(f.placeholder || "")}"></label>`;
  }).join("");
  setTimeout(() => {
    view.querySelectorAll(".controls [data-k]").forEach((el) =>
      el.addEventListener("change", () => onChange(el.dataset.k, el.value)));
  });
  return `<div class="controls">${html}</div>`;
}

const prefs = (() => {
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem("ar-prefs") || "{}"); } catch { /* ignore */ }
  const p = Object.assign({ window: 7, direction: "both", minPrice: "", minAvail: "" }, saved);
  p.save = () => { try { localStorage.setItem("ar-prefs", JSON.stringify(p)); } catch { /* ignore */ } };
  return p;
})();

async function viewMovers() {
  const minPrice = parseMoney(prefs.minPrice);
  const data = await api("movers", { params: {
    window: prefs.window, direction: prefs.direction,
    min_price: Number.isFinite(minPrice) ? minPrice : 0, min_available: parseInt(prefs.minAvail) || 0 } });
  const ctl = controls([
    { k: "window", label: "Compare with", value: prefs.window, options: [[3, "previous 3 days"], [7, "previous 7 days"], [14, "previous 14 days"], [30, "previous 30 days"]] },
    { k: "direction", label: "Show", value: prefs.direction, options: [["both", "rises and drops"], ["down", "drops (possible deals)"], ["up", "rises"]] },
    { k: "minPrice", label: "Usual price at least", value: prefs.minPrice, placeholder: "e.g. 50s or 2g" },
    { k: "minAvail", label: "Listed at least", value: prefs.minAvail, placeholder: "e.g. 5" },
  ], (k, v) => { prefs[k] = v; prefs.save(); route(); });
  view.innerHTML = `
    <p class="hint">Lowest price on the latest scanned day (${esc(data.date || "–")}) compared with the median lowest price
      over the ${data.window} days before it. A big drop can be a buying opportunity; a big rise can be a good time to sell.</p>
    ${ctl}
    ${table("movers", data.rows, [C.name, C.price, C.baseline, C.change, C.avail,
      { key: "prior_days", label: "Days compared", num: true }],
      { empty: "No price changes yet. Movers need at least two days of scans — scan again tomorrow." })}`;
}

async function viewSupply() {
  const data = await api("supply", { params: { window: prefs.window } });
  view.innerHTML = `
    <p class="hint">How many units were listed on the latest day (${esc(data.date || "–")}) compared with the median of the
      previous ${prefs.window} days. Shrinking supply often comes before a price rise; a flood of listings often pushes prices down.</p>
    ${table("supply", data.rows, [C.name,
      { key: "available", label: "Listed now", num: true, render: (r) => r.available.toLocaleString() },
      { key: "baseline_available", label: "Usually listed", num: true, render: (r) => r.baseline_available.toLocaleString() },
      C.change, C.price,
      { key: "baseline_price", label: "Usual price", num: true, render: (r) => money(r.baseline_price) }],
      { empty: "No supply changes yet. This needs at least two days of scans." })}`;
}

async function viewVendor() {
  const data = await api("vendor");
  view.innerHTML = `
    <p class="hint">Items a vendor sells (prices Auctionator remembered from vendors you visited), compared with their latest
      lowest AH price. Profit is per unit after the 5% auction house cut. Visit more vendors to fill this list.</p>
    ${table("vendor", data.rows, [C.name,
      { key: "vendor_price", label: "Vendor cost", num: true, render: (r) => money(r.vendor_price) },
      C.price,
      { key: "profit", label: "Profit / unit", num: true, render: (r) => money(r.profit) },
      { key: "margin", label: "Margin", num: true, render: (r) => pct(r.margin, true) },
      C.avail,
      { key: "date", label: "AH price from" }],
      { empty: "No vendor prices yet. Open a vendor window in game with Auctionator enabled." })}`;
}

async function viewWatchlist() {
  const data = await api("watchlist");
  view.innerHTML = `
    <p class="hint">Items you are watching. Add an item from its page; set a price to be alerted below (to buy) or above (to sell).</p>
    ${table("watch", data.rows, [C.name, C.price,
      { key: "spark", label: "Last 30 days", render: (r) => `<canvas class="spark" data-spark="${esc(JSON.stringify(r.spark))}"></canvas>`, sortValue: (r) => r.change },
      C.baseline, C.change,
      { key: "below", label: "Alert below", num: true, render: (r) => money(r.below) },
      { key: "above", label: "Alert above", num: true, render: (r) => money(r.above) },
      { key: "alert", label: "Status", render: (r) => r.alert === "below" ? '<span class="alert-below">Below target — buy?</span>'
          : r.alert === "above" ? '<span class="alert-above">Above target — sell?</span>' : '<span class="muted">–</span>' },
      { key: "note", label: "Note" }],
      { empty: "Your watchlist is empty. Open any item and click “Watch this item”." })}`;
  view.querySelectorAll("canvas.spark").forEach((c) => sparkline(c, JSON.parse(c.dataset.spark)));
}

function sparkline(canvas, values) {
  values = values.filter((v) => v !== null);
  const dpr = window.devicePixelRatio || 1;
  canvas.width = 110 * dpr; canvas.height = 26 * dpr;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  if (values.length < 2) return;
  const min = Math.min(...values), max = Math.max(...values), span = max - min || 1;
  ctx.strokeStyle = cssVar("--chart-low"); ctx.lineWidth = 1.5;
  ctx.beginPath();
  values.forEach((v, i) => {
    const x = 2 + (i / (values.length - 1)) * 106, y = 23 - ((v - min) / span) * 20;
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  });
  ctx.stroke();
}

async function viewPostings() {
  const data = await api("postings");
  view.innerHTML = `
    <p class="hint">What you posted (from Auctionator's posting history) compared with the item's latest lowest price.</p>
    ${table("postings", data.rows, [C.name,
      { key: "time", label: "Posted", render: (r) => new Date(r.time * 1000).toLocaleString() },
      { key: "posted_price", label: "Your price", num: true, render: (r) => money(r.posted_price) },
      { key: "quantity", label: "Qty", num: true },
      { key: "price", label: "Lowest now", num: true, render: (r) => money(r.price) },
      { key: "change", label: "Market vs yours", num: true, render: (r) => pct(r.change) }],
      { empty: "No posting history yet. Post something with Auctionator." })}`;
}

async function viewItem(key) {
  const d = await api("item/" + encodeURIComponent(key));
  const s7 = d.stats["7"], s30 = d.stats["30"], all = d.stats.all;
  const last = d.history[d.history.length - 1];
  const wowhead = d.item_id ? `<a href="https://www.wowhead.com/item=${d.item_id}" target="_blank" rel="noopener">Wowhead ↗</a>` : "";
  const card = (label, value, sub = "") => `<div class="card"><div class="label">${label}</div><div class="value">${value}</div>${sub ? `<div class="sub">${sub}</div>` : ""}</div>`;

  view.innerHTML = `
    <a class="back" href="javascript:history.back()">← Back</a>
    <div class="item-head">
      <h1>${itemName(d)}</h1>
      <span class="meta">${esc(d.item_key)} · ${d.history.length} days of data</span>
      ${wowhead}
    </div>
    <div class="cards">
      ${card("Cheapest in last scan", money(d.current), d.current_ts ? `scanned ${ago(d.current_ts)}` : "")}
      ${card("Lowest on latest day", money(last?.low), last ? esc(last.date) : "")}
      ${card("7-day median", money(s7?.median), s7 ? `${s7.days} days` : "not enough data")}
      ${card("30-day median", money(s30?.median), s30 ? `${s30.days} days` : "not enough data")}
      ${card("All-time range", all ? `${money(all.min)} – ${money(all.max)}` : "–", all ? `${all.days} days` : "")}
      ${card("Listed (latest day)", last?.available != null ? last.available.toLocaleString() : "–", last ? esc(last.date) : "")}
      ${card("Vendor sells for", money(d.vendor_price), d.vendor_price ? "per unit" : "unknown")}
    </div>
    <div class="panel">
      <h2>Price history — daily lowest and highest “cheapest listing”, with units listed</h2>
      <div class="chart-box"><canvas id="chart"></canvas></div>
    </div>
    <div class="grid-2">
      <div class="panel">
        <h2>Watch this item</h2>
        <div class="watch-form">
          <label>Alert below<input class="field" type="text" id="w-below" placeholder="e.g. 1g 50s" value="${d.watch?.below != null ? moneyText(d.watch.below) : ""}"></label>
          <label>Alert above<input class="field" type="text" id="w-above" placeholder="e.g. 3g" value="${d.watch?.above != null ? moneyText(d.watch.above) : ""}"></label>
          <label>Note<input class="field note" type="text" id="w-note" value="${esc(d.watch?.note || "")}"></label>
          <button class="btn primary" id="w-save">${d.watch ? "Update" : "Watch this item"}</button>
          ${d.watch ? '<button class="btn" id="w-remove">Remove</button>' : ""}
        </div>
        <p class="hint" id="w-msg" style="margin-top:8px"></p>
      </div>
      <div class="panel">
        <h2>Daily data</h2>
        ${table("history", [...d.history].reverse(), [
          { key: "date", label: "Date" },
          { key: "low", label: "Lowest", num: true, render: (r) => money(r.low) },
          { key: "high", label: "Highest", num: true, render: (r) => money(r.high) },
          { key: "available", label: "Listed", num: true, render: (r) => (r.available ?? "–").toLocaleString() }],
          { onRow: () => {} })}
      </div>
    </div>`;

  drawItemChart(d);

  $("#w-save").addEventListener("click", async () => {
    const below = parseMoney($("#w-below").value), above = parseMoney($("#w-above").value);
    if (Number.isNaN(below) || Number.isNaN(above)) {
      $("#w-msg").textContent = "Use amounts like 1g 50s, 35s, 80c, or a plain number of gold.";
      return;
    }
    await api("watchlist", { method: "POST", body: { item_key: d.item_key, below, above, note: $("#w-note").value || null } });
    viewItem(key);
  });
  $("#w-remove")?.addEventListener("click", async () => {
    await api("watchlist/" + encodeURIComponent(d.item_key), { method: "DELETE" });
    viewItem(key);
  });
}

function drawItemChart(d) {
  if (!window.Chart) {
    $("#chart").parentElement.innerHTML = '<p class="hint">Chart library could not load (offline?). The daily data table below still works.</p>';
    return;
  }
  const labels = d.history.map((h) => h.date);
  const postsByDate = {};
  for (const p of d.postings) {
    const date = new Date(p.time * 1000);
    const k = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
    postsByDate[k] = p.price;
  }
  for (const k of Object.keys(postsByDate)) if (!labels.includes(k)) labels.push(k);
  labels.sort();
  const byDate = Object.fromEntries(d.history.map((h) => [h.date, h]));
  const grid = cssVar("--border"), muted = cssVar("--muted");
  const chart = new Chart($("#chart"), {
    data: {
      labels,
      datasets: [
        { type: "line", label: "Lowest", data: labels.map((l) => byDate[l]?.low ?? null), borderColor: cssVar("--chart-low"),
          backgroundColor: "rgba(214,168,74,.15)", fill: "+1", tension: 0.25, pointRadius: labels.length > 40 ? 0 : 3, spanGaps: true, yAxisID: "y" },
        { type: "line", label: "Highest", data: labels.map((l) => byDate[l]?.high ?? null), borderColor: cssVar("--chart-high"),
          borderDash: [4, 3], tension: 0.25, pointRadius: 0, spanGaps: true, yAxisID: "y" },
        { type: "line", label: "Your postings", data: labels.map((l) => postsByDate[l] ?? null), showLine: false,
          pointStyle: "triangle", pointRadius: 7, borderColor: cssVar("--chart-post"), backgroundColor: cssVar("--chart-post"), yAxisID: "y" },
        { type: "bar", label: "Listed", data: labels.map((l) => byDate[l]?.available ?? null), backgroundColor: cssVar("--chart-avail"),
          yAxisID: "y2", order: 10 },
      ],
    },
    options: {
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { labels: { color: muted, usePointStyle: true } },
        tooltip: { callbacks: { label: (c) => c.dataset.yAxisID === "y2"
          ? `${c.dataset.label}: ${c.parsed.y?.toLocaleString()}` : `${c.dataset.label}: ${moneyText(c.parsed.y)}` } },
      },
      scales: {
        x: { ticks: { color: muted, maxRotation: 0, autoSkip: true }, grid: { color: grid } },
        y: { position: "left", ticks: { color: muted, callback: (v) => moneyText(v) }, grid: { color: grid }, beginAtZero: false },
        y2: { position: "right", ticks: { color: muted }, grid: { display: false }, beginAtZero: true, title: { display: true, text: "Listed", color: muted } },
      },
    },
  });
  state.charts.push(chart);
}

// ------------------------------------------------------------ search
let searchTimer, searchIdx = -1;
$("#search").addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => runSearch(e.target.value), 180);
});
$("#search").addEventListener("keydown", (e) => {
  const links = [...document.querySelectorAll("#search-results a")];
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    searchIdx = Math.max(0, Math.min(links.length - 1, searchIdx + (e.key === "ArrowDown" ? 1 : -1)));
    links.forEach((a, i) => a.classList.toggle("active", i === searchIdx));
  } else if (e.key === "Enter" && links.length) {
    (links[searchIdx] || links[0]).click();
  } else if (e.key === "Escape") {
    $("#search-results").hidden = true;
  }
});
document.addEventListener("click", (e) => { if (!e.target.closest(".search")) $("#search-results").hidden = true; });

async function runSearch(q) {
  const box = $("#search-results");
  searchIdx = -1;
  if (!q.trim()) { box.hidden = true; return; }
  const { rows } = await api("search", { params: { q } });
  box.innerHTML = rows.length
    ? rows.map((r) => `<a href="#/item/${encodeURIComponent(r.item_key)}">${itemName(r)}<span>${money(r.price)}</span></a>`).join("")
    : `<div class="empty">No matches. Unnamed items can be found by ID.</div>`;
  box.hidden = false;
  box.querySelectorAll("a").forEach((a) => a.addEventListener("click", () => { box.hidden = true; $("#search").value = ""; }));
}

// ------------------------------------------------------------ status, routing
async function loadOverview() {
  const ov = await api("overview");
  state.overview = ov;
  const sel = $("#realm");
  if (!sel.options.length || sel.options.length !== ov.realms.length) {
    sel.innerHTML = ov.realms.map((r) => `<option>${esc(r.realm)}</option>`).join("");
  }
  if (!state.realm && ov.realms.length) state.realm = ov.realms[0].realm;
  sel.value = state.realm;
  const r = ov.realms.find((x) => x.realm === state.realm);
  const st = ov.status || {};
  $("#status").innerHTML = [
    r ? `<span><b>${r.items.toLocaleString()}</b> items · <b>${r.days_tracked}</b> days tracked (${esc(r.first_date)} → ${esc(r.last_date)})</span>` : "<span>No data yet</span>",
    `<span>Last AH scan: <b>${ago(ov.last_scan)}</b></span>`,
    `<span>Data file saved: <b>${ago(ov.last_file_update)}</b></span>`,
    `<span>Names: <b>${ov.items_named.toLocaleString()}/${ov.items_total.toLocaleString()}</b>${st.names_running ? " (looking up…)" : ""}</span>`,
    st.message && st.message !== "ok" ? `<span class="alert-above">${esc(st.message)}</span>` : "",
  ].join("");
  const banner = $("#banner");
  if (!ov.names_file_found && ov.items_named < ov.items_total * 0.9) {
    banner.innerHTML = `Many items show as “Item 12345”. For names of every item (including new WoW Forever items),
      install the companion addon: run <code>python -m auction_review install-addon</code>, start WoW,
      wait a minute, then <code>/reload</code>. Names appear here automatically.`;
    banner.hidden = false;
  } else banner.hidden = true;
}

async function route() {
  destroyCharts();
  const hash = location.hash || "#/movers";
  const [, tab, arg] = hash.match(/^#\/([^/]+)\/?(.*)$/) || [, "movers"];
  document.querySelectorAll("#tabs a").forEach((a) => a.classList.toggle("active", a.dataset.tab === tab));
  try {
    if (!state.overview?.realms.length) {
      view.innerHTML = `<div class="empty-state">No auction data yet. Scan the auction house with Auctionator,
        then <b>/reload</b> or log out so WoW saves the file.</div>`;
      return;
    }
    if (tab === "item") return await viewItem(decodeURIComponent(arg));
    await ({ movers: viewMovers, supply: viewSupply, vendor: viewVendor, watchlist: viewWatchlist, postings: viewPostings }[tab] || viewMovers)();
  } catch (err) {
    view.innerHTML = `<div class="empty-state">Something went wrong: ${esc(err.message)}</div>`;
  }
}

$("#realm").addEventListener("change", (e) => { state.realm = e.target.value; loadOverview().then(route); });
$("#refresh").addEventListener("click", async (e) => {
  const btn = e.currentTarget;
  btn.disabled = true; btn.textContent = "Refreshing…";
  try { await api("refresh", { method: "POST" }); await loadOverview(); await route(); }
  finally { btn.disabled = false; btn.textContent = "Refresh data"; }
});
window.addEventListener("hashchange", route);

// Poll for new data (the server watches Auctionator.lua and ingests on change).
let lastSeen = null;
setInterval(async () => {
  try {
    await loadOverview();
    const marker = `${state.overview.snapshots}|${state.overview.items_named}`;
    if (lastSeen && marker !== lastSeen && !location.hash.startsWith("#/item")) route();
    lastSeen = marker;
  } catch { /* server stopped */ }
}, 30000);

loadOverview().then(() => { lastSeen = `${state.overview.snapshots}|${state.overview.items_named}`; route(); });
