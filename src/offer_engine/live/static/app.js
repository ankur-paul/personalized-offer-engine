// The live engine view (T39): scenario buttons, the pipeline diagram, the stage card and the Latest Decisions
// ticker. The page shows what each trace stage says; it computes no reasons of its own.
"use strict";

const STAGES = ["trigger", "customer", "checks", "eligible_set", "valuation", "agent", "validation", "fallback", "offer"];
const TITLES = {
  trigger: "Trigger", customer: "Customer", checks: "Checks", eligible_set: "Eligible Set", valuation: "Valuation",
  agent: "Agent", validation: "Validation", fallback: "Fallback", offer: "Offer",
};
const MIN_STAGE_MS = 1000;
const TICK_MS = 2000;
const CHECK_TICK_MS = 150;
const TICKER_SHORT = 5;
const TICKER_LONG = 20;
const SVG_NS = "http://www.w3.org/2000/svg";

const CHECK_NAMES = {
  opt_out: "Opt-out", holdout: "Holdout", fatigue_pause: "Fatigue Pause", frequency_cap: "Frequency cap",
  cooldown: "Cooldown after a Redemption", eligibility: "Days since signup", budget: "Weekly budget",
  short_circuit: "Respects the Checks", offer_type: "Offer Type and category allowed", params: "Terms within range",
  cost_cap: "Cost under the per-offer cap", send_window: "Send time in the window",
  featured: "Featured products", caption: "Caption present", reason: "Reason present", caption_check: "Caption Check",
  chooser: "Chooser answered",
};
const PARAM_NAMES = { pct: "Discount", cap: "Cap", amount: "Amount off", min_basket: "Minimum basket", multiplier: "Points multiplier" };
const OFFER_TYPE_NAMES = {
  pct_category: "% off a category", flat_above_min: "₹ off above a minimum basket", free_shipping: "Free shipping",
  points_multiplier: "Points multiplier", nudge: "Nudge (₹0)",
};

const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const $ = (id) => document.getElementById(id);

// --- Formatting ----------------------------------------------------------------------------------

const inr0 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const inr1 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 1 });

function rupees(value) {
  if (value == null) return "no limit";
  const abs = Math.abs(value);
  return (value < 0 ? "−" : "") + "₹" + (abs < 100 ? inr1 : inr0).format(abs);
}

// A chance or Lift held as a fraction.
function fraction(value) {
  return value == null ? "—" : `${(value * 100).toFixed(1)}%`;
}

function percent(value) {
  return value == null ? "no limit" : `${Number(value).toFixed(1)}%`;
}

function paramValue(name, value) {
  if (name === "pct") return percent(value);
  if (name === "multiplier") return value == null ? "no limit" : `${value}×`;
  return rupees(value);
}

function words(code) {
  return code ? String(code).replaceAll("_", " ") : "";
}

function offerText(o) {
  if (!o || !o.offer_type) return "No Offer";
  const p = o.params || {};
  const where = o.category ? ` on ${o.category}` : "";
  switch (o.offer_type) {
    case "pct_category":
      return `${percent(p.pct)} off${where}` + (p.cap != null ? `, up to ${rupees(p.cap)}` : "");
    case "flat_above_min":
      return `${rupees(p.amount)} off orders over ${rupees(p.min_basket)}${where}`;
    case "free_shipping":
      return `Free shipping${where}`;
    case "points_multiplier":
      return `${p.multiplier}× points${where}`;
    case "nudge":
      return `Nudge${where} (₹0)`;
    default:
      return words(o.offer_type);
  }
}

function when(iso) {
  return iso ? iso.replace("T", " ").slice(0, 16) : "—";
}

function escapeHtml(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

// --- Glossary terms ------------------------------------------------------------------------------

const glossary = new Map();
let glossaryPattern = null;

async function loadGlossary() {
  try {
    const entries = await getJson("/glossary");
    for (const { term, definition } of entries) glossary.set(term, definition);
    const terms = [...glossary.keys()].sort((a, b) => b.length - a.length).map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    glossaryPattern = terms.length ? new RegExp(`\\b(${terms.join("|")})s?\\b`, "g") : null;
  } catch {
    glossaryPattern = null;
  }
}

// Escaped text with each Glossary term marked for its tooltip.
function withTerms(text) {
  const safe = escapeHtml(text);
  if (!glossaryPattern) return safe;
  return safe.replace(glossaryPattern, (match, term) => `<span class="term" tabindex="0" data-term="${term}">${match}</span>`);
}

function setupTooltips() {
  const tip = $("tip");
  let current = null;
  const show = (el) => {
    const term = el.dataset.term;
    current = el;
    tip.innerHTML = `<strong>${escapeHtml(term)}</strong>${escapeHtml(glossary.get(term) || "")}`;
    tip.hidden = false;
    el.setAttribute("aria-describedby", "tip");
    const r = el.getBoundingClientRect();
    const w = tip.offsetWidth;
    const h = tip.offsetHeight;
    const left = Math.max(16, Math.min(r.left, window.innerWidth - w - 16));
    const below = r.bottom + 8;
    tip.style.left = `${left}px`;
    tip.style.top = `${below + h > window.innerHeight - 8 ? r.top - h - 8 : below}px`;
  };
  const hide = () => {
    if (current) current.removeAttribute("aria-describedby");
    current = null;
    tip.hidden = true;
  };
  document.addEventListener("mouseover", (e) => {
    const el = e.target.closest?.(".term");
    if (el) show(el);
    else if (current && !current.contains(document.activeElement)) hide();
  });
  document.addEventListener("focusin", (e) => (e.target.classList?.contains("term") ? show(e.target) : hide()));
  document.addEventListener("keydown", (e) => e.key === "Escape" && hide());
  window.addEventListener("scroll", hide, { passive: true });
}

// --- Server --------------------------------------------------------------------------------------

async function getJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const error = new Error(`${response.status} ${response.statusText}`);
    error.status = response.status;
    throw error;
  }
  return response.json();
}

function setStatus(text, bad = false) {
  const el = $("status");
  el.textContent = text;
  el.classList.toggle("bad", bad);
}

// --- Diagram -------------------------------------------------------------------------------------

// Each node's look: idle (not reached), active (pulsing), done, stop (a stop or failure), skip (done, did nothing).
const SYMBOLS = { idle: "", active: "…", done: "✓", stop: "✕", skip: "–" };
const STATE_WORDS = { idle: "not reached", active: "in progress", done: "done", stop: "stopped or failed", skip: "skipped" };

function finalState(stage) {
  const d = stage.data || {};
  switch (stage.name) {
    case "checks":
      return d.stopped_by ? "stop" : "done";
    case "agent":
      if (d.error) return "stop";
      return d.skipped ? "skip" : "done";
    case "validation":
      if (d.ok === false) return "stop";
      return d.ok == null ? "skip" : "done";
    case "fallback":
      return d.ok === false ? "stop" : "done";
    default:
      return "done";
  }
}

function el(name, attrs = {}, parent = null) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (parent) parent.appendChild(node);
  return node;
}

function drawDiagram() {
  const svg = $("diagram");
  const names = STAGES.filter((n) => n !== "fallback" || player.states.fallback !== "idle");
  const width = $("diagram-wrap").clientWidth - 32;
  const n = names.length;
  // One row when it fits, else two rows, else one column.
  let nodeW = 84, nodeH = 56, gapX = 20, gapY = 40, cols = n;
  if (n * (nodeW + gapX) - gapX > width) cols = Math.ceil(n / 2);
  if (cols * (nodeW + gapX) - gapX > width) {
    cols = 1;
    nodeW = Math.max(160, Math.min(width, 320));
    nodeH = 40;
    gapY = 16;
  }
  const rows = Math.ceil(n / cols);
  const totalW = cols * (nodeW + gapX) - gapX;
  const totalH = rows * (nodeH + gapY) - gapY;
  svg.replaceChildren();
  svg.setAttribute("viewBox", `-2 -12 ${totalW + 14} ${totalH + 14}`);
  svg.setAttribute("width", totalW + 14);
  const defs = el("defs", {}, svg);
  for (const kind of ["idle", "done"]) {
    const marker = el("marker", { id: `arrow-${kind}`, viewBox: "0 0 8 8", refX: "8", refY: "4", markerWidth: "8", markerHeight: "8", orient: "auto" }, defs);
    el("path", { d: "M0,0 L8,4 L0,8 z", class: `arrow ${kind === "done" ? "done" : ""}` }, marker);
  }
  const pos = names.map((_, i) => ({ x: (i % cols) * (nodeW + gapX), y: Math.floor(i / cols) * (nodeH + gapY) }));
  names.forEach((name, i) => {
    if (i === 0) return;
    const a = pos[i - 1], b = pos[i];
    const reached = ["done", "skip", "stop"].includes(player.states[names[i - 1]]) && player.states[name] !== "idle";
    let d;
    if (a.y === b.y) d = `M${a.x + nodeW},${a.y + nodeH / 2} H${b.x}`;
    else if (cols === 1) d = `M${a.x + nodeW / 2},${a.y + nodeH} V${b.y}`;
    else {
      const midY = a.y + nodeH + gapY / 2;
      d = `M${a.x + nodeW / 2},${a.y + nodeH} V${midY} H${b.x + nodeW / 2} V${b.y}`;
    }
    el("path", { d, class: `edge ${reached ? "done" : ""}`, "marker-end": `url(#arrow-${reached ? "done" : "idle"})` }, svg);
  });
  names.forEach((name, i) => {
    const state = player.states[name];
    const stage = player.stageFor(name);
    const g = el("g", {
      class: `node ${state} ${stage ? "clickable" : ""} ${player.viewing === name ? "viewing" : ""}`,
      transform: `translate(${pos[i].x},${pos[i].y})`,
      tabindex: stage ? "0" : "-1",
      role: stage ? "button" : "img",
      "aria-label": `${TITLES[name]}: ${STATE_WORDS[state]}`,
    }, svg);
    el("rect", { class: "box", width: nodeW, height: nodeH, rx: 8 }, g);
    if (cols === 1) {
      el("text", { x: 16, y: nodeH / 2, "dominant-baseline": "central" }, g).textContent = TITLES[name];
    } else {
      const parts = TITLES[name].split(" ");
      parts.forEach((part, j) => {
        const y = nodeH / 2 + (j - (parts.length - 1) / 2) * 18;
        el("text", { x: nodeW / 2, y, "text-anchor": "middle", "dominant-baseline": "central" }, g).textContent = part;
      });
    }
    if (SYMBOLS[state]) {
      const badge = el("g", { class: "badge", transform: cols === 1 ? `translate(${nodeW - 20},${nodeH / 2})` : `translate(${nodeW - 4},0)`, "aria-hidden": "true" }, g);
      el("circle", { r: 10 }, badge);
      el("text", { "text-anchor": "middle", "dominant-baseline": "central" }, badge).textContent = SYMBOLS[state];
    }
    if (stage) {
      const open = () => player.view(name);
      g.addEventListener("click", open);
      g.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          open();
        }
      });
    }
  });
}

// --- Player: shows a stream of stages at no more than one per second -----------------------------

const player = {
  generation: 0,
  states: {},
  queue: [],
  shown: [],
  result: null,
  failure: null,
  finished: false,
  completed: false,
  lastShownAt: 0,
  timer: null,
  viewing: null,
  thinking: false,
  title: "",

  start(title) {
    this.generation += 1;
    clearTimeout(this.timer);
    Object.assign(this, {
      states: Object.fromEntries(STAGES.map((n) => [n, "idle"])),
      queue: [], shown: [], result: null, failure: null, finished: false, completed: false,
      lastShownAt: 0, viewing: null, thinking: false, title,
    });
    drawDiagram();
    renderCard(null);
    return this.generation;
  },

  stageFor(name) {
    return this.shown.find((s) => s.name === name) || null;
  },

  add(generation, stage) {
    if (generation !== this.generation) return;
    this.queue.push(stage);
    this.pump();
  },

  finish(generation, result, failure = null) {
    if (generation !== this.generation) return;
    this.finished = true;
    this.result = result;
    this.failure = failure;
    this.pump();
  },

  pump() {
    clearTimeout(this.timer);
    const wait = this.lastShownAt + MIN_STAGE_MS - performance.now();
    if (wait > 0) {
      this.timer = setTimeout(() => this.pump(), wait);
      return;
    }
    if (this.queue.length) {
      this.show(this.queue.shift());
      this.timer = setTimeout(() => this.pump(), MIN_STAGE_MS);
      return;
    }
    if (this.finished) {
      if (!this.completed) this.complete();
      return;
    }
    const last = this.shown[this.shown.length - 1];
    if (last && last.name === "valuation" && !this.thinking) this.think();
  },

  settlePrevious() {
    const last = this.shown[this.shown.length - 1];
    if (last) this.states[last.name] = finalState(last);
  },

  show(stage) {
    this.settlePrevious();
    if (this.thinking && stage.name !== "agent") this.states.agent = "idle";
    this.thinking = false;
    this.shown.push(stage);
    this.states[stage.name] = "active";
    this.lastShownAt = performance.now();
    this.viewing = stage.name;
    drawDiagram();
    renderCard(stage, { animateChecks: true });
  },

  // The agent is answering: its node pulses until its stage arrives.
  think() {
    this.settlePrevious();
    this.thinking = true;
    this.states.agent = "active";
    this.viewing = "agent";
    drawDiagram();
    renderThinking();
  },

  complete() {
    this.completed = true;
    this.thinking = false;
    for (const name of STAGES) if (this.states[name] === "active") this.states[name] = "idle";
    this.settlePrevious();
    if (this.failure) {
      const last = this.shown[this.shown.length - 1];
      if (last && last.name !== "offer") this.states[last.name] = "stop";
    }
    drawDiagram();
    if (this.viewing === "offer" || this.failure || !this.shown.length) renderCard(this.stageFor("offer"));
    onPlaybackDone();
  },

  view(name) {
    const stage = this.stageFor(name);
    if (!stage) return;
    this.viewing = name;
    drawDiagram();
    renderCard(stage);
  },
};

// --- Stage card ----------------------------------------------------------------------------------

// A check stops a Decision; any other stage that goes red failed.
function stateChip(state, name) {
  const cls = { done: "ok", stop: "bad", skip: "idle", idle: "idle", active: "active" }[state];
  const stop = name === "checks" ? "✕ Stopped" : "✕ Failed";
  const text = { done: "✓ Done", stop, skip: "– Skipped", idle: "Not reached", active: "… In progress" }[state];
  return `<span class="state ${cls}">${text}</span>`;
}

function renderCard(stage, { animateChecks = false } = {}) {
  const card = $("card");
  if (player.failure && (!stage || stage.name !== "offer")) {
    card.innerHTML = `<p class="eyebrow">${escapeHtml(player.title)}</p><h2>The run failed</h2>
      <span class="state bad">✕ Failed</span><p>${escapeHtml(player.failure)}</p>`;
    restartFade(card);
    return;
  }
  if (!stage) {
    card.innerHTML = `<p class="eyebrow">${escapeHtml(player.title)}</p><h2>Setting up the scenario<span class="dots"></span></h2>`;
    return;
  }
  const index = player.shown.indexOf(stage) + 1;
  const state = player.states[stage.name];
  card.innerHTML = `
    <p class="eyebrow">${escapeHtml(player.title)} · stage ${index}</p>
    <h2>${withTerms(stage.title)}</h2>
    ${stateChip(state, stage.name)}
    <p class="summary">${withTerms(stage.summary)}</p>
    ${(DETAILS[stage.name] || (() => ""))(stage.data || {})}
    ${stage.name === "offer" ? scenarioLines() : ""}`;
  restartFade(card);
  if (animateChecks) tickChecks(card);
}

function renderThinking() {
  const card = $("card");
  card.innerHTML = `<p class="eyebrow">${escapeHtml(player.title)}</p><h2>${withTerms("Agent")}</h2>
    <span class="state active">… In progress</span>
    <p class="thinking">Claude is thinking<span class="dots"></span></p>`;
  restartFade(card);
}

function restartFade(card) {
  if (reducedMotion.matches) return;
  card.classList.remove("fade");
  void card.offsetWidth;
  card.classList.add("fade");
}

// Validation's checks appear one by one.
function tickChecks(card) {
  const items = [...card.querySelectorAll(".checklist.ticks li")];
  if (reducedMotion.matches || !items.length) return;
  const generation = player.generation;
  items.forEach((li) => li.classList.add("hidden"));
  items.forEach((li, i) =>
    setTimeout(() => generation === player.generation && li.classList.remove("hidden"), (i + 1) * CHECK_TICK_MS));
}

function facts(pairs) {
  const rows = pairs.filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `<dt>${escapeHtml(k)}</dt><dd>${v}</dd>`).join("");
  return rows ? `<dl class="facts">${rows}</dl>` : "";
}

function checklist(items, { ticks = false } = {}) {
  const rows = items.map((it) => {
    const cls = { passed: "ok", stopped: "bad", failed: "bad", "not reached": "idle" }[it.status] || "idle";
    const sym = { ok: "✓", bad: "✕", idle: "–" }[cls];
    const label = CHECK_NAMES[it.name] || words(it.name);
    const detail = [it.detail, ...(it.failures || [])].filter(Boolean).map(escapeHtml).join("<br>");
    const rule = it.rule ? ` <code>${escapeHtml(it.rule)}</code>` : "";
    return `<li class="${cls}"><span class="sym" aria-hidden="true">${sym}</span>
      <div><span class="what">${withTerms(label)}</span> <span class="detail">· ${escapeHtml(it.status)}${rule}</span>
      ${detail ? `<div class="detail">${detail}</div>` : ""}</div></li>`;
  }).join("");
  return `<ul class="checklist ${ticks ? "ticks" : ""}">${rows}</ul>`;
}

function rangeText(name, [lo, hi]) {
  if (lo === hi) return `${PARAM_NAMES[name] || name} ${paramValue(name, lo)}`;
  return `${PARAM_NAMES[name] || name} ${paramValue(name, lo)} – ${paramValue(name, hi)}`;
}

const DETAILS = {
  trigger: (d) => facts([
    ["Trigger", escapeHtml(words(d.kind))],
    ["Customer", escapeHtml(d.customer_id)],
    ["Simulated time", escapeHtml(when(d.at))],
  ]),

  customer: (d) => facts([
    ["Loyalty tier", escapeHtml(d.loyalty_tier)],
    ["City tier", escapeHtml(d.city_tier)],
    ["Device", escapeHtml(d.device)],
    ["Channel", escapeHtml(d.channel)],
    ["Days since signup", escapeHtml(d.days_since_signup)],
    ["Orders, last 90 days", escapeHtml(d.orders_90d)],
    ["Spent, last 90 days", escapeHtml(rupees(d.spent_90d))],
    ["Points balance", escapeHtml(d.points_balance)],
    ["Past Offers", escapeHtml(d.past_offers)],
    ["Chat", escapeHtml(d.chat || "none")],
  ]),

  checks: (d) => checklist(d.items || []),

  eligible_set: (d) => {
    const rows = (d.options || []).map((o, i) => `<tr>
      <td>${i}</td>
      <td>${withTerms(OFFER_TYPE_NAMES[o.offer_type] || words(o.offer_type))}</td>
      <td>${escapeHtml(o.category || "any")}</td>
      <td>${Object.entries(o.ranges || {}).map(([p, r]) => escapeHtml(rangeText(p, r))).join("<br>") || "—"}</td>
      <td>${Object.entries(o.binding_rules || {}).map(([p, r]) => `${escapeHtml(PARAM_NAMES[p] || p)}: <code>${escapeHtml(r)}</code>`).join("<br>") || "—"}</td>
      <td class="num">${escapeHtml(rupees(o.worst_case_cost))}</td>
      <td class="num">${escapeHtml(fraction(o.estimated_lift))}</td></tr>`).join("");
    const dropped = Object.entries(d.dropped || {});
    const window = d.send_window ? `${when(d.send_window[0])} – ${when(d.send_window[1]).slice(11)}` : "none left";
    return `
      ${rows ? `<div class="table-wrap"><table>
        <thead><tr><th>#</th><th>${withTerms("Offer Type")}</th><th>Category</th><th>Allowed terms</th>
        <th>${withTerms("Binding Rules")}</th><th class="num">Worst case</th><th class="num">${withTerms("Estimated Lift")}</th></tr></thead>
        <tbody>${rows}</tbody></table></div>` : "<p>No option is left.</p>"}
      ${facts([
        ["Send window", escapeHtml(window)],
        ["Dropped", dropped.map(([k, r]) => `${escapeHtml(words(k))}: <code>${escapeHtml(r)}</code>`).join("<br>")],
      ])}`;
  },

  valuation: (d) => {
    const options = d.options || [];
    if (!options.length) return "";
    const values = options.map((o) => o.value);
    const neg = Math.max(0, -Math.min(...values));
    const pos = Math.max(0, ...values);
    const span = neg + pos || 1;
    const zero = (neg / span) * 100;
    const rows = options.map((o, i) => {
      const width = (Math.abs(o.value) / span) * 100;
      const left = o.value >= 0 ? zero : zero - width;
      const best = i === d.best && o.value > 0;
      return `<li class="bar-row ${best ? "best" : ""}">
        <div class="bar-head"><span class="label">${escapeHtml(offerText(o))}</span>
          <span class="value ${o.value < 0 ? "neg" : ""}">${escapeHtml(rupees(o.value))}</span></div>
        <div class="bar-track" aria-hidden="true"><div class="bar-fill ${o.value > 0 ? "pos" : ""}" style="left:${left}%;width:${width}%"></div>
          <div class="bar-zero" style="left:calc(${zero}% - 1px)"></div></div>
        <div class="bar-sub">${withTerms("Lift")} ${escapeHtml(fraction(o.lift))} · chance of a ${withTerms("Redemption")} ${escapeHtml(fraction(o.redeem_chance))} ·
          margin ${escapeHtml(rupees(o.margin))} · cost if redeemed ${escapeHtml(rupees(o.cost_if_redeemed))}</div></li>`;
    }).join("");
    return `<section><h3>Value per option</h3><ul class="bars">${rows}</ul></section>`;
  },

  agent: (d) => {
    if (d.skipped) return "";
    const out = d.output || {};
    const chose = out.option_index == null ? null : out.option_index === -1 ? "No Offer" : `option ${out.option_index}`;
    return `
      ${facts([
        ["Model", escapeHtml(d.model)],
        ["Answered in", d.seconds == null ? null : escapeHtml(`${Number(d.seconds).toFixed(1)} s`)],
        ["Chose", chose && escapeHtml(chose)],
        ["Error", d.error && `<span class="state bad">✕ ${escapeHtml(d.error)}</span>`],
      ])}
      ${out.caption ? `<section><h3>Its caption</h3><blockquote class="caption">${escapeHtml(out.caption)}</blockquote></section>` : ""}
      ${out.reason ? `<section><h3>Its reason</h3><p>${escapeHtml(out.reason)}</p></section>` : ""}
      ${d.prompt ? `<details><summary>Show the prompt</summary><pre>${escapeHtml(d.prompt)}</pre></details>` : ""}`;
  },

  validation: (d) => (d.checks && d.checks.length ? checklist(d.checks, { ticks: true }) : ""),

  fallback: (d) => `
    ${facts([
      ["Rejected because", (d.rejected || []).map(escapeHtml).join("<br>")],
      ["Rules chooser chose", escapeHtml(d.proposal)],
    ])}
    ${d.checks && d.checks.length ? `<section><h3>Its ${withTerms("Validation")}</h3>${checklist(d.checks, { ticks: true })}</section>` : ""}`,

  offer: (d) => {
    if (!d.offer_type) {
      return `<p class="big">${withTerms("No Offer")}</p>${facts([["Chosen by", escapeHtml(d.chooser)]])}`;
    }
    return `
      <p class="big">${escapeHtml(offerText(d))}</p>
      ${d.caption ? `<blockquote class="caption">${escapeHtml(d.caption)}</blockquote>` : ""}
      ${facts([
        ["Code", d.code && `<code>${escapeHtml(d.code)}</code>`],
        ["Send at", escapeHtml(when(d.send_at))],
        ["Expires", escapeHtml(when(d.expires_at))],
        ["Worst-case cost", escapeHtml(rupees(d.worst_case_cost))],
        ["Chosen by", escapeHtml(d.chooser)],
        ["Binding Rule", d.binding_rule && `<code>${escapeHtml(d.binding_rule)}</code>`],
        ["Reason", escapeHtml(d.reason)],
      ])}`;
  },
};

// `ScenarioResult.lines`: text before the first ": " in bold; an indented line belongs to the line above.
function scenarioLines() {
  const r = player.result;
  if (!r) return "";
  const items = [];
  for (const line of r.lines || []) {
    const sub = /^\s+/.test(line);
    const text = line.trim();
    const cut = text.indexOf(": ");
    const html = cut > 0 ? `<strong>${escapeHtml(text.slice(0, cut))}</strong>: ${withTerms(text.slice(cut + 2))}` : withTerms(text);
    if (sub && items.length) items[items.length - 1].subs.push(html);
    else items.push({ html, subs: [] });
  }
  const list = items.length
    ? `<section><h3>What the scenario did</h3><ol class="lines">${items.map((it) =>
        `<li>${it.html}${it.subs.length ? `<ul>${it.subs.map((s) => `<li>${s}</li>`).join("")}</ul>` : ""}</li>`).join("")}</ol></section>`
    : "";
  const check = r.passed
    ? `<span class="state ok">✓ The Decision is what the scenario expects</span>`
    : `<span class="state bad">✕ Not what the scenario expects: ${escapeHtml((r.mismatches || []).join("; "))}</span>`;
  return `${list}${check}`;
}

// --- Scenarios -----------------------------------------------------------------------------------

let stream = null;

async function loadScenarios() {
  const nav = $("scenarios");
  let list;
  try {
    list = await getJson("/scenarios");
  } catch (e) {
    nav.textContent = `Couldn't load the scenarios (${e.message}).`;
    return;
  }
  const groups = new Map();
  for (const s of list) {
    if (!groups.has(s.group)) groups.set(s.group, []);
    groups.get(s.group).push(s);
  }
  nav.replaceChildren();
  for (const [group, items] of groups) {
    const section = document.createElement("section");
    section.className = "group";
    section.innerHTML = `<h3>${escapeHtml(group)}</h3>`;
    for (const s of items) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "scenario";
      button.dataset.name = s.name;
      button.innerHTML = `<span class="name">${escapeHtml(s.title)}</span><span class="proves">${escapeHtml(s.proves)}</span>`;
      button.addEventListener("click", () => runScenario(s, button));
      section.appendChild(button);
    }
    nav.appendChild(section);
  }
}

async function runScenario(scenario, button) {
  let started;
  try {
    started = await getJson(`/scenarios/${encodeURIComponent(scenario.name)}/run`, { method: "POST" });
  } catch (e) {
    setStatus(e.status === 409 ? "A scenario is running" : `Couldn't start the scenario (${e.message})`, true);
    return;
  }
  closeStream();
  markPlaying(button, null);
  setStatus(`Running: ${scenario.title}`);
  const generation = player.start(scenario.title);
  stream = new EventSource(`/runs/${started.run_id}/events`);
  stream.addEventListener("stage", (e) => player.add(generation, JSON.parse(e.data)));
  stream.addEventListener("result", (e) => {
    closeStream();
    player.finish(generation, JSON.parse(e.data));
  });
  stream.addEventListener("failure", (e) => {
    closeStream();
    player.finish(generation, null, JSON.parse(e.data).message);
  });
  stream.onerror = () => {
    closeStream();
    player.finish(generation, null, "Lost the connection to the server.");
  };
}

function closeStream() {
  if (stream) stream.close();
  stream = null;
}

function onPlaybackDone() {
  document.querySelectorAll(".scenario.running").forEach((b) => b.classList.remove("running"));
  if (player.failure) setStatus(`${player.title}: failed`, true);
  else setStatus(`${player.title}: done`);
  refreshTicker();
}

function markPlaying(button, decisionId) {
  document.querySelectorAll(".scenario.running").forEach((b) => b.classList.remove("running"));
  if (button) button.classList.add("running");
  ticker.playing = decisionId;
  renderTicker();
}

// --- Latest Decisions ----------------------------------------------------------------------------

const ticker = { rows: [], long: false, playing: null, failed: false };

async function refreshTicker() {
  if (document.hidden) return;
  try {
    ticker.rows = await getJson("/decisions/latest");
    ticker.failed = false;
  } catch {
    ticker.failed = true;
  }
  renderTicker();
}

function renderTicker() {
  const list = $("ticker");
  const rows = ticker.rows.slice(0, ticker.long ? TICKER_LONG : TICKER_SHORT);
  if (!rows.length) {
    list.innerHTML = `<li class="empty">${ticker.failed ? "Couldn't load Decisions." : "No Decisions yet."}</li>`;
  } else {
    list.innerHTML = rows.map((d) => `<li><button type="button" class="row ${d.id === ticker.playing ? "playing" : ""}"
        data-id="${d.id}" ${d.traced ? "" : "disabled"} title="${d.traced ? "Play this Decision" : "This Decision has no trace"}">
        <span class="when">#${d.id} · ${escapeHtml(d.time)} · ${escapeHtml(d.customer)} · ${escapeHtml(words(d.trigger))}</span>
        <span class="what">${escapeHtml(offerText(parseTerms(d.offer)))}</span></button></li>`).join("");
  }
  const more = $("ticker-more");
  more.hidden = ticker.rows.length <= TICKER_SHORT;
  more.textContent = ticker.long ? `Show ${TICKER_SHORT}` : `Show ${TICKER_LONG}`;
  more.setAttribute("aria-expanded", String(ticker.long));
}

// The server sends Offer terms as "pct_category fashion pct=7 cap=170"; this reads them back for `offerText`.
function parseTerms(text) {
  if (!text || text === "No Offer") return null;
  const [offerType, ...rest] = text.split(" ");
  const params = {};
  let category = null;
  for (const part of rest) {
    const [k, v] = part.split("=");
    if (v === undefined) category = k;
    else params[k] = Number(v);
  }
  return { offer_type: offerType, category, params };
}

async function playDecision(id) {
  let stages;
  try {
    stages = await getJson(`/decisions/${id}/trace`);
  } catch (e) {
    setStatus(`Couldn't load Decision #${id} (${e.message})`, true);
    return;
  }
  closeStream();
  markPlaying(null, id);
  setStatus(`Playing Decision #${id}`);
  const generation = player.start(`Decision #${id}`);
  for (const stage of stages) player.add(generation, stage);
  player.finish(generation, null);
}

// --- Theme ---------------------------------------------------------------------------------------

function setupTheme() {
  const button = $("theme");
  const dark = () => {
    const forced = document.documentElement.dataset.theme;
    return forced ? forced === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
  };
  const label = () => (button.textContent = dark() ? "Light theme" : "Dark theme");
  try {
    const saved = localStorage.getItem("live-theme");
    if (saved === "light" || saved === "dark") document.documentElement.dataset.theme = saved;
  } catch { /* storage blocked: follow the system */ }
  label();
  button.addEventListener("click", () => {
    const next = dark() ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("live-theme", next); } catch { /* not remembered */ }
    label();
  });
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", label);
}

// --- Start ---------------------------------------------------------------------------------------

async function main() {
  setupTheme();
  setupTooltips();
  player.states = Object.fromEntries(STAGES.map((n) => [n, "idle"]));
  drawDiagram();
  let width = 0;
  new ResizeObserver(([entry]) => {
    if (entry.contentRect.width === width) return;
    width = entry.contentRect.width;
    drawDiagram();
  }).observe($("diagram-wrap"));
  $("ticker").addEventListener("click", (e) => {
    const row = e.target.closest("button.row");
    if (row && !row.disabled) playDecision(Number(row.dataset.id));
  });
  $("ticker-more").addEventListener("click", () => {
    ticker.long = !ticker.long;
    renderTicker();
  });
  await loadGlossary();
  // The intro card's terms get tooltips too.
  const intro = $("card").querySelector("p:last-child");
  intro.innerHTML = withTerms(intro.textContent.replace(/\s+/g, " "));
  await loadScenarios();
  refreshTicker();
  setInterval(refreshTicker, TICK_MS);
}

main();
