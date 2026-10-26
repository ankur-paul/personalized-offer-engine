// The world charts (T41; QnA Q54): what the whole world has done since the clock start, in four cards. An ES module
// that needs none of the page's other scripts: mountWorld(root) fetches /world, draws inline SVG and refreshes. To
// move it to another page, serve /world, include world.js and world.css, and call mountWorld on an empty element.

const GROUPS = [
  ["paid", "Paid Offer"],
  ["nudge", "Nudge (₹0)"],
  ["nothing", "No Offer: nothing worth sending"],
  ["frequency_cap", "No Offer: frequency cap"],
  ["budget", "No Offer: weekly budget spent"],
  ["other_rules", "No Offer: other Rules"],
];
const OFFER_TYPES = {
  pct_category: "% off a category", flat_above_min: "₹ off above a minimum basket", free_shipping: "Free shipping",
  points_multiplier: "Points multiplier", nudge: "Nudge",
};
const RULES = {
  none: "nothing worth sending", frequency_cap_count: "frequency cap", holdout_pct: "Holdout", opt_out: "Opt-out",
  cooldown_days_after_redemption: "cooldown after a Redemption", fatigue_dismissals: "Fatigue Pause",
  min_days_since_signup: "days since signup", weekly_budget: "weekly budget spent", per_offer_cost_cap: "per-offer cost cap",
  nudge_needs_reminder: "nothing to remind about",
};
// Response Classes, with the Glossary's own words for each.
const CLASSES = [
  ["persuadable", "Persuadable", "buys only with an Offer"],
  ["sure_thing", "Sure Thing", "buys anyway"],
  ["lost_cause", "Lost Cause", "doesn't buy either way"],
  ["sleeping_dog", "Sleeping Dog", "less likely to buy because of an Offer"],
];
const CHOOSERS = [["agent", "Agent (Claude)"], ["rules", "Rules chooser"], ["fallback", "Fallback"]];
const GAP = 2;
const RADIUS = 4;
const MAX_BAR = 24;

const count = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const oneDp = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const dayFormat = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short" });

const esc = (text) =>
  String(text ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const series = (i) => `var(--series-${i + 1})`;
const rupees = (v) => `₹${count.format(Math.round(v || 0))}`;
const share = (part, whole) => (whole ? `${oneDp.format((100 * part) / whole)}%` : "—");
const sum = (values) => values.reduce((a, b) => a + b, 0);

function parseLocal(iso) {
  const [d, t = "00:00"] = iso.split("T");
  const [y, m, day] = d.split("-").map(Number);
  const [h, min] = t.split(":").map(Number);
  return new Date(y, m - 1, day, h, min);
}
const dayText = (iso) => dayFormat.format(parseLocal(iso));
const timeText = (iso) => `${dayText(iso)}, ${iso.slice(11, 16)}`;

function compact(v) {
  if (v < 1000) return count.format(v);
  const k = v / 1000;
  return `${Number.isInteger(k) ? k : k.toFixed(1)}K`;
}

// A round top for the axis and four or so gridlines under it.
function scale(max) {
  if (max <= 0) return { top: 1, ticks: [0, 1] };
  const raw = max / 4;
  const pow = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * pow).find((s) => s >= raw);
  const top = step * Math.ceil(max / step);
  const ticks = [];
  for (let v = 0; v <= top + step / 2; v += step) ticks.push(v);
  return { top, ticks };
}

// A bar with a rounded data end and a square base: `end` is "top" for columns, "right" for horizontal bars.
function bar(x, y, w, h, end, fill, extra = "") {
  const r = Math.min(RADIUS, end === "top" ? h : w, end === "top" ? w / 2 : h / 2);
  const d =
    end === "top"
      ? `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`
      : `M${x},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h - r}Q${x + w},${y + h} ${x + w - r},${y + h}H${x}Z`;
  return `<path class="seg" d="${d}" style="fill:${fill}"${extra}/>`;
}

function offerText(latest) {
  if (!latest.offer_type) return `No Offer (${RULES[latest.binding_rule ?? "none"] ?? latest.binding_rule.replaceAll("_", " ")})`;
  const p = latest.params || {};
  switch (latest.offer_type) {
    case "pct_category":
      return `${p.pct}% off ${latest.category ?? ""}`.trim();
    case "flat_above_min":
      return `${rupees(p.amount)} off over ${rupees(p.min_basket)}`;
    case "points_multiplier":
      return `${p.multiplier}× points`;
    case "nudge":
      return "Nudge (₹0)";
    default:
      return OFFER_TYPES[latest.offer_type] ?? latest.offer_type;
  }
}

function legend(items) {
  return `<ul class="legend">${items
    .map(([label, i]) => `<li><span class="swatch" style="background:${series(i)}"></span>${esc(label)}</li>`)
    .join("")}</ul>`;
}

function table(head, rows) {
  const cell = (tag, v) => `<${tag}${typeof v === "number" || /^[₹\d−-]/.test(String(v)) ? ' class="num"' : ""}>${esc(v)}</${tag}>`;
  return `<table><thead><tr>${head.map((h) => cell("th", h)).join("")}</tr></thead><tbody>${rows
    .map((r) => `<tr>${r.map((v) => cell("td", v)).join("")}</tr>`)
    .join("")}</tbody></table>`;
}

const CARDS = `
  <section class="chart" data-chart="days">
    <h3 data-terms>Decisions per simulated day</h3>
    <p class="what" data-terms>Every Decision of each day, by what came out and, for No Offer, which Rule stopped it.</p>
    <div class="legend-slot"></div>
    <div class="plot"></div>
    <details><summary>Show table</summary><div class="table-wrap"></div></details>
  </section>
  <section class="chart" data-chart="funnel">
    <h3 data-terms>Offers sent, Claimed and Redeemed</h3>
    <p class="what" data-terms>The Holdout gets no Offers, so the gap in orders per 100 Customers outside and inside it is what Offers changed.</p>
    <div class="plot"></div>
    <dl class="tiles"></dl>
    <details><summary>Show table</summary><div class="table-wrap"></div></details>
  </section>
  <section class="chart truth" data-chart="truth">
    <span class="hidden-tag">Hidden from the engine: simulator only</span>
    <h3 data-terms>Who got the paid Offers, by Response Class</h3>
    <p class="what" data-terms>If the engine found the Customers an Offer moves, Persuadables' share of paid Offers would sit above their share of Customers, and Sure Things' below.</p>
    <div class="legend-slot"></div>
    <div class="plot"></div>
    <dl class="tiles"></dl>
    <details><summary>Show table</summary><div class="table-wrap"></div></details>
  </section>
  <section class="chart" data-chart="choosers">
    <h3 data-terms>Who decided</h3>
    <p class="what"></p>
    <dl class="tiles"></dl>
    <ul class="people"></ul>
  </section>`;

export function mountWorld(root, options = {}) {
  const opts = { url: "/world", intervalMs: 5000, terms: null, ...options };
  // `opts.terms(text)` returns escaped HTML with Glossary tooltips, or null to fall back to plain escaped text.
  const terms = (text) => opts.terms?.(text) ?? esc(text);
  root.classList.add("world");
  root.setAttribute("aria-labelledby", "world-title");
  root.innerHTML = `<header class="world-head"><h2 id="world-title">The world so far</h2><p class="since"></p></header>
    <div class="world-grid">${CARDS}</div>`;
  const card = (name) => root.querySelector(`[data-chart="${name}"]`);
  const tip = document.createElement("div");
  tip.className = "world-tip";
  tip.setAttribute("role", "tooltip");
  tip.hidden = true;
  document.body.append(tip);
  const tips = new Map();
  let data = null;
  let shown = "";
  let busy = false;
  let width = 0;

  // --- Tooltip: one per page, built with textContent ---

  function showTip(el, x, y) {
    const t = tips.get(el.dataset.tip);
    if (!t) return;
    tip.replaceChildren();
    const title = document.createElement("div");
    title.className = "tip-title";
    title.textContent = t.title;
    tip.append(title);
    for (const row of t.rows) {
      const line = document.createElement("div");
      line.className = "tip-row";
      const key = document.createElement("span");
      key.className = "key";
      key.style.background = row.color ?? "transparent";
      const value = document.createElement("strong");
      value.textContent = row.value;
      const label = document.createElement("span");
      label.textContent = row.label;
      line.append(key, value, label);
      tip.append(line);
    }
    for (const note of t.notes ?? []) {
      const p = document.createElement("div");
      p.className = "tip-note";
      p.textContent = note;
      tip.append(p);
    }
    tip.hidden = false;
    if (x == null) {
      const r = el.getBoundingClientRect();
      x = r.left + r.width / 2;
      y = r.top;
    }
    const w = tip.offsetWidth;
    const h = tip.offsetHeight;
    tip.style.left = `${Math.max(8, Math.min(x + 12, window.innerWidth - w - 8))}px`;
    tip.style.top = `${y + 12 + h > window.innerHeight - 8 ? Math.max(8, y - h - 12) : y + 12}px`;
  }
  const hideTip = () => (tip.hidden = true);
  root.addEventListener("pointermove", (e) => {
    const el = e.target.closest?.("[data-tip]");
    if (el) showTip(el, e.clientX, e.clientY);
    else hideTip();
  });
  root.addEventListener("pointerleave", hideTip);
  root.addEventListener("focusin", (e) => (e.target.dataset?.tip ? showTip(e.target) : hideTip()));
  root.addEventListener("focusout", hideTip);
  document.addEventListener("keydown", (e) => e.key === "Escape" && hideTip());
  window.addEventListener("scroll", hideTip, { passive: true });

  // --- Cards ---

  function renderDays() {
    const c = card("days");
    const plot = c.querySelector(".plot");
    const days = data.days;
    c.querySelector(".legend-slot").innerHTML = legend(GROUPS.map(([, label], i) => [label, i]));
    if (!days.length) {
      plot.innerHTML = `<p class="empty">No Decisions since the clock start yet. Advance the Simulation Clock in the console.</p>`;
      c.querySelector(".table-wrap").innerHTML = "";
      return;
    }
    const W = Math.max(plot.clientWidth, 280);
    const [top, bottom, left, right, H] = [24, 28, 48, 8, 200];
    const totals = days.map((d) => sum(Object.values(d.groups)));
    const { top: max, ticks } = scale(Math.max(...totals));
    const band = (W - left - right) / days.length;
    const bw = Math.min(MAX_BAR, Math.max(4, band * 0.6));
    const y = (v) => top + H - (v / max) * H;
    const labelEvery = Math.ceil(56 / band);
    const peak = totals.indexOf(Math.max(...totals));
    let svg = `<g class="grid">${ticks.map((v) => `<line x1="${left}" x2="${W - right}" y1="${y(v)}" y2="${y(v)}"/>`).join("")}</g>`;
    svg += ticks.map((v) => `<text x="${left - 8}" y="${y(v) + 5}" text-anchor="end">${compact(v)}</text>`).join("");
    days.forEach((d, i) => {
      const x = left + band * i + (band - bw) / 2;
      const key = `days:${i}`;
      let base = top + H;
      const nonzero = GROUPS.map(([g], gi) => [d.groups[g], gi]).filter(([n]) => n > 0);
      let marks = "";
      nonzero.forEach(([n, gi], k) => {
        const hp = (n / max) * H;
        const h = Math.max(1, hp - (k > 0 ? GAP : 0));
        const yy = base - hp;
        marks += k === nonzero.length - 1 ? bar(x, yy, bw, h, "top", series(gi)) : `<rect class="seg" x="${x}" y="${yy}" width="${bw}" height="${h}" style="fill:${series(gi)}"/>`;
        base -= hp;
      });
      const label = `${dayText(d.day)}: ${count.format(totals[i])} Decisions`;
      svg += `<g class="col" tabindex="0" data-tip="${key}" role="img" aria-label="${esc(label)}">
        <rect class="hit" x="${left + band * i}" y="${top}" width="${band}" height="${H}"/>${marks}</g>`;
      if (band >= 40 || i === peak || i === days.length - 1)
        svg += `<text class="value" x="${x + bw / 2}" y="${y(totals[i]) - 8}" text-anchor="middle">${compact(totals[i])}</text>`;
      if ((days.length - 1 - i) % labelEvery === 0)
        svg += `<text x="${x + bw / 2}" y="${top + H + 20}" text-anchor="middle">${esc(dayText(d.day))}</text>`;
      tips.set(key, {
        title: label,
        rows: GROUPS.map(([g, name], gi) => ({ color: series(gi), value: count.format(d.groups[g]), label: name })).reverse(),
        notes: details(d),
      });
    });
    plot.innerHTML = `<svg viewBox="0 0 ${W} ${top + H + bottom}" height="${top + H + bottom}" aria-label="Decisions per simulated day">${svg}</svg>`;
    c.querySelector(".table-wrap").innerHTML = table(
      ["Day", ...GROUPS.map(([, name]) => name), "Total", "Details"],
      days.map((d, i) => [dayText(d.day), ...GROUPS.map(([g]) => count.format(d.groups[g])), count.format(totals[i]), details(d).join(" · ")]),
    );
  }

  function details(d) {
    const offers = Object.entries(d.offers).filter(([t]) => t !== "nudge");
    const stops = Object.entries(d.no_offer).filter(([r]) => !["none", "frequency_cap_count", "weekly_budget"].includes(r));
    const notes = [];
    if (offers.length) notes.push(`Paid: ${offers.map(([t, n]) => `${OFFER_TYPES[t] ?? t} ${count.format(n)}`).join(", ")}`);
    if (stops.length) notes.push(`Other Rules: ${stops.map(([r, n]) => `${RULES[r] ?? r.replaceAll("_", " ")} ${count.format(n)}`).join(", ")}`);
    return notes;
  }

  function renderFunnel() {
    const c = card("funnel");
    const plot = c.querySelector(".plot");
    const f = data.funnel;
    const rows = [["Offers sent", f.sent], ["Claimed", f.claimed], ["Redeemed", f.redeemed]];
    if (!f.sent) {
      plot.innerHTML = `<p class="empty">No Offers sent since the clock start yet.</p>`;
    } else {
      const W = Math.max(plot.clientWidth, 280);
      const [labelW, valueW, rowH, bh] = [104, 120, 36, 20];
      const span = W - labelW - valueW;
      let svg = "";
      rows.forEach(([name, n], i) => {
        const key = `funnel:${i}`;
        const w = Math.max(2, (n / f.sent) * span);
        const yy = i * rowH + (rowH - bh) / 2;
        const text = i ? `${count.format(n)} · ${share(n, f.sent)}` : count.format(n);
        svg += `<g class="row" tabindex="0" data-tip="${key}" role="img" aria-label="${esc(`${name}: ${text}`)}">
          <rect class="hit" x="0" y="${i * rowH}" width="${W}" height="${rowH}"/>
          <text x="0" y="${yy + 15}">${esc(name)}</text>${bar(labelW, yy, w, bh, "right", series(0))}
          <text class="value" x="${labelW + w + 8}" y="${yy + 15}">${esc(text)}</text></g>`;
        tips.set(key, { title: name, rows: [{ color: series(0), value: count.format(n), label: i ? `${share(n, f.sent)} of Offers sent` : "since the clock start" }] });
      });
      plot.innerHTML = `<svg viewBox="0 0 ${W} ${rows.length * rowH}" height="${rows.length * rowH}" aria-label="Offers sent, Claimed and Redeemed">${svg}</svg>`;
    }
    const h = data.holdout;
    const per100 = (g) => (g.customers ? oneDp.format((100 * g.orders) / g.customers) : "—");
    c.querySelector(".tiles").innerHTML = [
      tile("Offer spend", rupees(f.spend), `on ${count.format(f.redeemed)} Redemptions`),
      tile("Orders per 100 Customers, outside the Holdout", per100(h.treated), `${count.format(h.treated.customers)} Customers`),
      tile(`Inside the Holdout (${oneDp.format(h.pct)}%)`, per100(h.holdout), `${count.format(h.holdout.customers)} Customers`),
    ].join("");
    c.querySelector(".table-wrap").innerHTML = table(
      ["Step", "Offers", "Share of sent"],
      rows.map(([name, n]) => [name, count.format(n), share(n, f.sent)]),
    );
  }

  function tile(label, value, sub = "") {
    return `<div><dt>${terms(label)}</dt><dd>${esc(value)}${sub ? ` <span class="sub">${esc(sub)}</span>` : ""}</dd></div>`;
  }

  function renderTruth() {
    const c = card("truth");
    const plot = c.querySelector(".plot");
    const byClass = Object.fromEntries(data.truth.map((r) => [r.response_class, r]));
    const customers = sum(data.truth.map((r) => r.customers));
    const paid = sum(data.truth.map((r) => r.paid));
    c.querySelector(".legend-slot").innerHTML = legend([["Share of Customers", 0], ["Share of paid Offers", 1]]);
    const W = Math.max(plot.clientWidth, 280);
    const [labelW, valueW, rowH, bh] = [120, 64, 44, 14];
    const values = CLASSES.flatMap(([rc]) => [
      customers ? (byClass[rc]?.customers ?? 0) / customers : 0,
      paid ? (byClass[rc]?.paid ?? 0) / paid : 0,
    ]);
    const max = Math.max(...values, 0.01);
    const span = W - labelW - valueW;
    let svg = "";
    CLASSES.forEach(([rc, name, words], i) => {
      const r = byClass[rc] ?? { customers: 0, paid: 0, nudges: 0, spend: 0 };
      const key = `truth:${i}`;
      const pair = [[r.customers, customers], [r.paid, paid]];
      let marks = "";
      pair.forEach(([n, whole], s) => {
        const v = whole ? n / whole : 0;
        const w = Math.max(v > 0 ? 2 : 0, (v / max) * span);
        const yy = i * rowH + 6 + s * (bh + GAP);
        if (w) marks += bar(labelW, yy, w, bh, "right", series(s));
        marks += `<text class="value" x="${labelW + w + 8}" y="${yy + 12}">${whole ? share(n, whole) : "—"}</text>`;
      });
      svg += `<g class="row" tabindex="0" data-tip="${key}" role="img" aria-label="${esc(`${name}: ${share(r.customers, customers)} of Customers, ${share(r.paid, paid)} of paid Offers`)}">
        <rect class="hit" x="0" y="${i * rowH}" width="${W}" height="${rowH}"/>
        <text x="0" y="${i * rowH + 22}">${esc(name)}</text>${marks}</g>`;
      tips.set(key, {
        title: `${name}: ${words}`,
        rows: [
          { color: series(0), value: share(r.customers, customers), label: `of Customers (${count.format(r.customers)})` },
          { color: series(1), value: share(r.paid, paid), label: `of paid Offers (${count.format(r.paid)})` },
          { value: count.format(r.nudges), label: "Nudges" },
          { value: rupees(r.spend), label: "spent on their Redemptions" },
        ],
      });
    });
    plot.innerHTML = `<svg viewBox="0 0 ${W} ${CLASSES.length * rowH}" height="${CLASSES.length * rowH}" aria-label="Paid Offers by Response Class">${svg}</svg>`;
    const sure = byClass.sure_thing?.spend ?? 0;
    c.querySelector(".tiles").innerHTML = tile("Spent on Sure Things", rupees(sure), `${share(sure, data.funnel.spend)} of ${rupees(data.funnel.spend)} Offer spend`);
    c.querySelector(".table-wrap").innerHTML = table(
      ["Response Class", "Customers", "Share", "Paid Offers", "Share", "Nudges", "Spend"],
      CLASSES.map(([rc, name]) => {
        const r = byClass[rc] ?? { customers: 0, paid: 0, nudges: 0, spend: 0 };
        return [name, count.format(r.customers), share(r.customers, customers), count.format(r.paid), share(r.paid, paid), count.format(r.nudges), rupees(r.spend)];
      }),
    );
  }

  function renderChoosers() {
    const c = card("choosers");
    const chats = data.chats;
    c.querySelector(".what").innerHTML = terms(
      `The agent decides only for the ${chats.length} chat-attached Customers below. The rules chooser decides for everyone else, and is the Fallback when the agent's answer fails Validation.`,
    );
    c.querySelector(".tiles").innerHTML = CHOOSERS.map(([k, name]) => tile(name, count.format(data.choosers[k] ?? 0))).join("");
    c.querySelector(".people").innerHTML = chats.length
      ? chats
          .map((ch) => {
            const who = ch.name ?? ch.customer_id;
            const kind = ch.kind === "tester" ? "Tester" : "Customer Bot";
            const caseText = [ch.case, kind, ch.opted_out ? "opted out" : null].filter(Boolean).join(" · ");
            const latest = ch.latest
              ? `Latest ${timeText(ch.latest.at)}: ${offerText(ch.latest)}, by the ${ch.latest.chooser === "agent" ? "agent" : ch.latest.chooser === "fallback" ? "Fallback" : "rules chooser"}`
              : "No Decision yet";
            return `<li><span><span class="who">${esc(who)}</span> <span class="case">${esc(caseText)}</span></span>
              <span class="count">${count.format(ch.decisions)} Decisions · ${count.format(ch.offers)} Offers</span>
              <span class="latest">${terms(latest)}</span></li>`;
          })
          .join("")
      : `<li class="empty">No chat-attached Customers. Link one with <code>offer-engine chats link</code>.</li>`;
  }

  function render() {
    const focused = root.contains(document.activeElement) ? document.activeElement.dataset?.tip : null;
    tips.clear();
    root.querySelector(".since").textContent =
      `Since ${timeText(data.since)} · simulated time ${timeText(data.time)} · Testers' copies are left out of the charts`;
    renderDays();
    renderFunnel();
    renderTruth();
    renderChoosers();
    for (const el of root.querySelectorAll("[data-terms]")) el.innerHTML = terms(el.textContent);
    for (const c of root.querySelectorAll(".chart")) c.classList.remove("stale");
    if (focused) root.querySelector(`[data-tip="${focused}"]`)?.focus();
  }

  async function refresh() {
    if (document.hidden || busy) return;
    busy = true;
    try {
      const response = await fetch(opts.url);
      if (!response.ok) throw new Error(`${response.status}`);
      const text = await response.text();
      // Same numbers: keep the current render, so hover and focus stay put.
      if (text === shown) return;
      shown = text;
      data = JSON.parse(text);
      render();
    } catch {
      // Keep the last render, dimmed, until the next refresh works.
      for (const c of root.querySelectorAll(".chart")) c.classList.add("stale");
    } finally {
      busy = false;
    }
  }

  const resize = new ResizeObserver(([entry]) => {
    if (!data || entry.contentRect.width === width) return;
    width = entry.contentRect.width;
    render();
  });
  resize.observe(root);
  refresh();
  const timer = setInterval(refresh, opts.intervalMs);
  return {
    refresh,
    redraw: () => data && render(),
    stop() {
      clearInterval(timer);
      resize.disconnect();
      tip.remove();
    },
  };
}
