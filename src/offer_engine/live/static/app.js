// The live engine view (T39, T40): scenario buttons, the pipeline diagram, the stage card, the Latest Decisions
// ticker, and after the Offer stage the outcome and truth panels; above the diagram, the counters and controls. The
// page shows what each trace stage says; it computes no reasons of its own.
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
// What a stop at Checks reads as on the Offer card: "Stopped by the Holdout".
const STOPPED_BY = {
  opt_out: "Opt-out", holdout: "Holdout", fatigue_pause: "Fatigue Pause", frequency_cap: "frequency cap",
  cooldown: "cooldown after a Redemption", eligibility: "minimum days since signup",
};
// Rule keys as plain words; the key itself goes in a `title` for anyone debugging.
const RULE_NAMES = {
  opt_out: "Opt-out", holdout_pct: "Holdout", fatigue_dismissals: "Fatigue Pause", frequency_cap_count: "Frequency cap",
  cooldown_days_after_redemption: "Cooldown after a Redemption", min_days_since_signup: "Days since signup",
  weekly_budget: "Weekly budget", per_offer_cost_cap: "Per-offer cost cap", margin_floor_pct: "Margin floor",
  max_pct_by_category: "Most % off for the category", max_pct_by_loyalty_tier: "Most % off for the loyalty tier",
  max_flat_amount: "Most ₹ off", max_points_multiplier: "Most points multiplier", max_send_delay_hours: "Send delay",
};
const CHOOSER_NAMES = { agent: "agent", rules: "rules chooser", fallback: "Fallback" };
// The ticker's chip for a Decision the LLM was called for (T44); a rules Decision has none.
const CHOOSER_CHIPS = {
  agent: ["Agent", "Chosen by the agent"],
  fallback: ["Fallback", "The agent's answer failed Validation; the rules chooser decided"],
};
const PARAM_NAMES = { pct: "Discount", cap: "Cap", amount: "Amount off", min_basket: "Minimum basket", multiplier: "Points multiplier" };
// Response Classes, with the Glossary's own words for each.
const RESPONSE_CLASSES = {
  persuadable: ["Persuadable", "buys only with an Offer"], sure_thing: ["Sure Thing", "buys anyway"],
  lost_cause: ["Lost Cause", "doesn't buy either way"], sleeping_dog: ["Sleeping Dog", "less likely to buy because of an Offer"],
};
// ADR 0004: the agent moves the chance by at most this share of itself.
const FIT_CAP = 0.3;
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

const dayFormat = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short" });

// "2026-12-06 10:00" or "2026-12-06T10:00:00" as "6 Dec, 10:00", the charts' format.
function shortWhen(iso) {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return `${dayFormat.format(new Date(y, m - 1, d))}, ${iso.slice(11, 16)}`;
}

// The Offer in a few words, for a ticker row.
function shortOffer(o) {
  if (!o || !o.offer_type) return "No Offer";
  const p = o.params || {};
  switch (o.offer_type) {
    case "pct_category":
      return `${percent(p.pct)} off ${o.category || ""}`.trim();
    case "flat_above_min":
      return `${rupees(p.amount)} off over ${rupees(p.min_basket)}`;
    case "points_multiplier":
      return `${p.multiplier}× points`;
    default:
      return offerText(o);
  }
}

function ruleName(key) {
  return `<span title="${escapeHtml(key)}">${escapeHtml(RULE_NAMES[key] || words(key))}</span>`;
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

// Keeps a term's tooltip on its first use in `card` only, and never in a heading, so the underlines that remain stand
// out (T43).
function firstUseOnly(card) {
  const seen = new Set();
  for (const term of card.querySelectorAll("[data-term]")) {
    if (term.closest("h1, h2, h3") || seen.has(term.dataset.term)) term.replaceWith(term.textContent);
    else seen.add(term.dataset.term);
  }
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

// Each node's look: idle (not reached), active (pulsing), done, stop (a stop or failure), skip (done, did nothing),
// passed (never ran: the Decision went past it after a stop), none (the Offer stage of a No Offer).
const SYMBOLS = { idle: "", active: "…", done: "✓", stop: "✕", skip: "–", passed: "", none: "–" };
const STATE_WORDS = {
  idle: "not reached", active: "in progress", done: "done", stop: "stopped or failed", skip: "skipped",
  passed: "skipped after the stop", none: "no Offer sent",
};

// The Offer node reads "No Offer" once its stage says so.
function nodeTitle(name) {
  const stage = name === "offer" ? player.stageFor("offer") : null;
  return stage && !stage.data?.offer_type ? "No Offer" : TITLES[name];
}

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
    case "offer":
      return d.offer_type ? "done" : "none";
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
    const from = player.states[names[i - 1]], to = player.states[name];
    const passed = from === "passed" || to === "passed";
    const reached = !passed && ["done", "skip", "stop"].includes(from) && to !== "idle";
    let d;
    if (a.y === b.y) d = `M${a.x + nodeW},${a.y + nodeH / 2} H${b.x}`;
    else if (cols === 1) d = `M${a.x + nodeW / 2},${a.y + nodeH} V${b.y}`;
    else {
      const midY = a.y + nodeH + gapY / 2;
      d = `M${a.x + nodeW / 2},${a.y + nodeH} V${midY} H${b.x + nodeW / 2} V${b.y}`;
    }
    el("path", { d, class: `edge ${reached ? "done" : ""} ${passed ? "passed" : ""}`, "marker-end": `url(#arrow-${reached ? "done" : "idle"})` }, svg);
  });
  names.forEach((name, i) => {
    const state = player.states[name];
    const stage = player.stageFor(name);
    const g = el("g", {
      class: `node ${state} ${stage ? "clickable" : ""} ${player.viewing === name ? "viewing" : ""}`,
      transform: `translate(${pos[i].x},${pos[i].y})`,
      tabindex: stage ? "0" : "-1",
      role: stage ? "button" : "img",
      "aria-label": `${nodeTitle(name)}: ${STATE_WORDS[state]}`,
    }, svg);
    el("rect", { class: "box", width: nodeW, height: nodeH, rx: 8 }, g);
    if (cols === 1) {
      el("text", { x: 16, y: nodeH / 2, "dominant-baseline": "central" }, g).textContent = nodeTitle(name);
    } else {
      const parts = nodeTitle(name).split(" ");
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
  // A played-back Decision's ID and Offer; a scenario run's come with its result.
  replay: null,

  start(title, replay = null) {
    this.generation += 1;
    clearTimeout(this.timer);
    Object.assign(this, {
      states: Object.fromEntries(STAGES.map((n) => [n, "idle"])),
      queue: [], shown: [], result: null, failure: null, finished: false, completed: false,
      lastShownAt: 0, viewing: null, thinking: false, title, replay,
    });
    drawDiagram();
    renderCard(null);
    renderPanels();
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
    // A stage the Decision jumped over (after a stop at Checks) is skipped, not still to come.
    for (const name of STAGES.slice(0, STAGES.indexOf(stage.name))) {
      if (name !== "fallback" && this.states[name] === "idle") this.states[name] = "passed";
    }
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
    renderPanels();
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
  const cls = { done: "ok", stop: "bad", skip: "idle", idle: "idle", active: "active", passed: "idle", none: "idle" }[state];
  const stop = name === "checks" ? "✕ Stopped" : "✕ Failed";
  const text = {
    done: "✓ Done", stop, skip: "– Skipped", idle: "Not reached", active: "… In progress",
    passed: "– Skipped after the stop", none: "– Nothing sent",
  }[state];
  return `<span class="state ${cls}">${text}</span>`;
}

// Why a Decision ended in No Offer, in plain words; the stage's own reason, with any rule key, is the `title`.
function noOfferReason(d) {
  const stop = player.stageFor("checks")?.data.stopped_by;
  if (stop) return `Stopped by the ${STOPPED_BY[stop] || words(stop)}`;
  const text = (d.reason || "").replace(/^No Offer:\s*/, "").replace(/\s*\([a-z_]+\)$/, "");
  return text ? text[0].toUpperCase() + text.slice(1) : "Nothing was worth sending";
}

// A stage's summary where the trace's own would show rule keys or repeat the details below it.
const SUMMARIES = {
  checks: (d) => (d.stopped_by ? `Stopped by the ${STOPPED_BY[d.stopped_by] || words(d.stopped_by)}` : "Every check passed"),
  offer: (d) => (d.offer_type ? "" : noOfferReason(d)),
};

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
  const state = player.states[stage.name];
  const data = stage.data || {};
  const summary = SUMMARIES[stage.name] ? SUMMARIES[stage.name](data) : stage.summary;
  card.innerHTML = `
    <p class="eyebrow">${escapeHtml(player.title)} · ${escapeHtml(TITLES[stage.name])} stage</p>
    <h2>${escapeHtml(nodeTitle(stage.name))}</h2>
    ${stateChip(state, stage.name)}
    ${summary ? `<p class="summary" title="${escapeHtml(stage.summary)}">${withTerms(summary)}</p>` : ""}
    ${(DETAILS[stage.name] || (() => ""))(data)}
    ${stage.name === "offer" ? scenarioLines() : ""}`;
  firstUseOnly(card);
  restartFade(card);
  if (animateChecks) tickChecks(card);
}

function renderThinking() {
  const card = $("card");
  card.innerHTML = `<p class="eyebrow">${escapeHtml(player.title)} · Agent stage</p><h2>Agent</h2>
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
    const rule = it.rule ? ` title="${escapeHtml(it.rule)}"` : "";
    return `<li class="${cls}"${rule}><span class="sym" aria-hidden="true">${sym}</span>
      <div><span class="what">${withTerms(label)}</span> <span class="detail">· ${escapeHtml(it.status)}</span>
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
    if (!d.offer_type) return facts([["Chosen by", escapeHtml(CHOOSER_NAMES[d.chooser] || d.chooser)]]);
    return `
      <p class="big">${escapeHtml(offerText(d))}</p>
      ${d.caption ? `<blockquote class="caption">${escapeHtml(d.caption)}</blockquote>` : ""}
      ${facts([
        ["Code", d.code && `<code>${escapeHtml(d.code)}</code>`],
        ["Send at", escapeHtml(when(d.send_at))],
        ["Expires", escapeHtml(when(d.expires_at))],
        ["Worst-case cost", escapeHtml(rupees(d.worst_case_cost))],
        ["Chosen by", escapeHtml(CHOOSER_NAMES[d.chooser] || d.chooser)],
        ["Binding Rule", d.binding_rule && ruleName(d.binding_rule)],
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

// --- Outcome and truth panels (T40): only once the Offer stage is shown ----------------------------

function renderPanels() {
  const panels = $("panels");
  const offer = player.stageFor("offer");
  if (!player.completed || player.failure || !offer) {
    panels.replaceChildren();
    return;
  }
  const r = player.result;
  const trigger = player.stageFor("trigger");
  const decisionId = r ? r.decision_id : player.replay && player.replay.decisionId;
  const customerId = r ? r.customer_id : trigger && trigger.data.customer_id;
  const offerId = r ? r.offer_id : player.replay && player.replay.offerId;
  // A scenario run brings its outcome; a playback fetches the stored one (undefined while it loads).
  const outcome = r ? r.outcome : offerId != null ? undefined : null;
  panels.innerHTML = `${offer.data.offer_type ? outcomePanel(offerId, offer.data, outcome) : ""}
    <section class="card panel truth" id="truth" aria-labelledby="truth-title">
      <span class="hidden-label">Hidden from the engine: simulator only</span>
      <h2 id="truth-title">What the simulator knows</h2>
      <p class="summary">Loading the ${withTerms("Ground Truth")}<span class="dots"></span></p>
    </section>`;
  panels.querySelectorAll(".panel").forEach(firstUseOnly);
  if (customerId && decisionId != null) loadTruth(player.generation, customerId, decisionId);
  if (offer.data.offer_type && outcome === undefined) loadOutcome(player.generation, offerId);
}

function outcomePanel(offerId, offer, outcome) {
  const alt = `Offer Card: ${offerText(offer)}, code ${offer.code || ""}, valid until ${when(offer.expires_at)}`;
  const image = offerId != null
    ? `<img class="offer-card" src="/offers/${offerId}/card.png" alt="${escapeHtml(alt)}" width="800" height="450">` : "";
  const steps = outcome ? outcomeSteps(outcome)
    : outcome === undefined ? `<p class="summary">Loading what the ${withTerms("Customer")} did<span class="dots"></span></p>`
    : noReaction();
  return `<section class="card panel" aria-labelledby="outcome-title">
      <p class="eyebrow">After the Offer</p>
      <h2 id="outcome-title">What the Customer did</h2>
      <div class="outcome-grid">${image}<div class="outcome-steps" id="outcome-steps">${steps}</div></div>
    </section>`;
}

function outcomeSteps(o) {
  const top = Math.max(o.p_base, o.p_used);
  // Chances are a few percent, so the scale ends just past the larger one, at a whole number of 5 points.
  const scale = Math.min(1, Math.max(0.05, Math.ceil((top * 1.25) / 0.05) * 0.05));
  const at = (p) => `${Math.min(100, (p / scale) * 100)}%`;
  const nudge = o.fit == null
    ? "No Customer Bot, so no message-fit nudge"
    : `${o.fit * FIT_CAP >= 0 ? "+" : "−"}${Math.abs(o.fit * FIT_CAP * 100).toFixed(0)}% for message fit, capped at ±${FIT_CAP * 100}%`;
  const flip = o.buys
    ? `<span class="state ok">✓ Buys</span>`
    : `<span class="state idle">✕ Doesn't buy</span>`;
  const answer = o.buys ? ["ok", "✓ Claimed; the Redemption comes before expiry"]
    : o.claims ? ["idle", "Claimed, then doesn't buy"] : ["idle", "– Not now"];
  return `
    <section>
      <h3>Chance of buying in 7 days</h3>
      <div class="meter" role="img" aria-label="${escapeHtml(`From ${fraction(o.p_base)} to ${fraction(o.p_used)}`)}">
        <div class="meter-fill" style="width:${at(o.p_used)}"></div>
        <div class="meter-base" style="left:calc(${at(o.p_base)} - 1px)"></div>
      </div>
      <div class="meter-scale" aria-hidden="true"><span>0%</span><span>${fraction(scale)}</span></div>
      <div class="meter-key"><span class="key-base">${withTerms("Ground Truth")} with this Offer ${fraction(o.p_base)}</span>
        <span class="key-used">after the nudge ${fraction(o.p_used)}</span></div>
      <p>${escapeHtml(nudge)}</p>
    </section>
    <section><h3>The seeded flip</h3>${flip}</section>
    <section>
      <h3>The reply</h3>
      ${o.reply ? `<blockquote class="reply"><span class="who">${withTerms("Customer Bot")}</span>${escapeHtml(replyText(o.reply))}</blockquote>` : ""}
      <span class="state ${answer[0]}">${withTerms(answer[1])}</span>
      ${o.bot_reply ? `<blockquote class="reply"><span class="who">${withTerms("Offer Bot")}</span>${escapeHtml(o.bot_reply)}</blockquote>` : ""}
    </section>`;
}

function noReaction() {
  return `<p class="summary">No reaction yet: the ${withTerms("Customer")} hasn't answered this ${withTerms("Offer")}.</p>`;
}

// A played-back Offer's outcome, from the simulator's stored reaction or fate (T44).
async function loadOutcome(generation, offerId) {
  let html;
  try {
    const { outcome } = await getJson(`/offers/${offerId}/outcome`);
    html = outcome ? outcomeSteps(outcome) : noReaction();
  } catch (e) {
    html = `<p class="summary">Couldn't load what the ${withTerms("Customer")} did (${escapeHtml(e.message)}).</p>`;
  }
  const steps = $("outcome-steps");
  if (generation !== player.generation || !steps) return;
  steps.innerHTML = html;
  firstUseOnly(steps.closest(".panel"));
}

// The Customer Bot's message without its `/claim CODE` or `/notnow CODE` line; the chip below says which it was.
function replyText(reply) {
  return reply.split("\n").filter((line) => !line.trim().startsWith("/")).join("\n").trim();
}

async function loadTruth(generation, customerId, decisionId) {
  let truth;
  try {
    truth = await getJson(`/customers/${encodeURIComponent(customerId)}/truth?decision_id=${decisionId}`);
  } catch (e) {
    truth = { error: e.message };
  }
  const panel = $("truth");
  if (generation !== player.generation || !panel) return;
  panel.innerHTML = truthPanel(truth);
  firstUseOnly(panel);
}

function truthPanel(t) {
  const head = `<span class="hidden-label">Hidden from the engine: simulator only</span>
    <h2 id="truth-title">What the simulator knows</h2>`;
  if (t.error) return `${head}<p class="summary">Couldn't load the ${withTerms("Ground Truth")} (${escapeHtml(t.error)}).</p>`;
  const [name, meaning] = RESPONSE_CLASSES[t.response_class] || [words(t.response_class), ""];
  const options = (player.stageFor("eligible_set")?.data.options) || [];
  const estimated = (o) => options.find((e) => e.offer_type === o.offer_type && e.category === o.category)?.estimated_lift;
  const signed = (v) => (v > 0 ? "+" : v < 0 ? "−" : "") + fraction(Math.abs(v));
  const rows = t.options.map((o) => `<tr class="${o.chosen ? "chosen" : ""}">
      <td>${o.chosen ? "✓ " : ""}${withTerms(OFFER_TYPE_NAMES[o.offer_type] || words(o.offer_type))}${o.category ? ` · ${escapeHtml(o.category)}` : ""}${o.chosen ? " (sent)" : ""}</td>
      <td class="num">${fraction(o.chance)}</td>
      <td class="num">${signed(o.lift)}</td>
      <td class="num">${estimated(o) == null ? "—" : signed(estimated(o))}</td></tr>`).join("");
  return `${head}
    <dl class="facts">
      <dt>${withTerms("Response Class")}</dt><dd><strong>${escapeHtml(name)}</strong>${meaning ? ` (${escapeHtml(meaning)})` : ""}</dd>
      <dt>Chance of buying in 7 days with no Offer</dt><dd>${escapeHtml(fraction(t.no_offer))}</dd>
    </dl>
    ${rows ? `<div class="table-wrap"><table>
      <thead><tr><th>Option</th><th class="num">True chance</th><th class="num">True ${withTerms("Lift")}</th>
      <th class="num">${withTerms("Estimated Lift")}</th></tr></thead><tbody>${rows}</tbody></table></div>
      <p class="note">True chances are at the deepest terms each option allowed, and the sent Offer at its own terms.
        Estimated Lift is the engine's guess of the most an Offer of that type can add.</p>`
      : `<p class="note">The Decision stopped before the ${withTerms("Eligible Set")}, so there are no options to price.</p>`}`;
}

// --- Counters and controls (T40) -----------------------------------------------------------------

const counts = { failed: false };

async function refreshCounters() {
  if (document.hidden) return;
  let c;
  try {
    c = await getJson("/counters");
  } catch {
    if (!counts.failed) $("counters").innerHTML = `<div><dt>World</dt><dd class="sub">Couldn't load the counters.</dd></div>`;
    counts.failed = true;
    return;
  }
  counts.failed = false;
  const byTrigger = Object.entries(c.decisions);
  const total = (decisions) => Object.values(decisions).reduce((n, k) => n + k, 0);
  // Today's number, then the total since the clock start, so the strip never drops to 0 at midnight (QnA Q55).
  const s = c.since_start;
  const start = new Date(s.since.replace(" ", "T")).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
  const tile = (label, value, since = "", more = "") =>
    `<div><dt>${label}</dt><dd class="value">${value}</dd>` +
    (since ? `<dd class="since">${since} since ${escapeHtml(start)}</dd>` : "") + more + "</div>";
  // The Trigger breakdown stays folded, keeping its open state across refreshes.
  const open = $("counters").querySelector("details")?.open ? " open" : "";
  const breakdown = byTrigger.length
    ? `<dd><details${open}><summary>by ${withTerms("Trigger")}</summary><ul class="breakdown">${byTrigger
        .map(([t, k]) => `<li><span>${escapeHtml(words(t))}</span><span>${inr0.format(k)}</span></li>`).join("")}</ul></details></dd>`
    : "";
  $("counters").innerHTML = [
    tile(withTerms("Simulation Clock"), escapeHtml(shortWhen(c.time))),
    tile(`${withTerms("Decisions")} today`, inr0.format(total(c.decisions)), inr0.format(total(s.decisions)), breakdown),
    tile("Offers sent today", inr0.format(c.offers_sent), inr0.format(s.offers_sent)),
    tile(`${withTerms("Claims")} today`, inr0.format(c.claims), inr0.format(s.claims)),
    tile(`${withTerms("Redemptions")} today`, inr0.format(c.redemptions), inr0.format(s.redemptions)),
    tile("Offer spend today", escapeHtml(rupees(c.spend)), escapeHtml(rupees(s.spend))),
  ].join("");
  firstUseOnly($("counters"));
}

async function loadAgentMode(promise = getJson("/agent-mode")) {
  let state;
  try {
    state = await promise;
  } catch (e) {
    setStatus(e.status === 400 ? "Live needs ANTHROPIC_API_KEY in .env" : `Couldn't switch the agent (${e.message})`, true);
    return;
  }
  for (const button of document.querySelectorAll("#agent-switch button")) {
    const live = button.dataset.mode === "live";
    button.setAttribute("aria-pressed", String(button.dataset.mode === state.mode));
    button.disabled = live && !state.live_ready && state.mode !== "live";
    button.title = live
      ? (state.live_ready ? "Scenario runs call Claude" : "Live needs ANTHROPIC_API_KEY in .env")
      : "Scenario runs play back recorded answers";
  }
}

function setupControls() {
  $("agent-switch").addEventListener("click", (e) => {
    const button = e.target.closest("button[data-mode]");
    if (!button || button.disabled || button.getAttribute("aria-pressed") === "true") return;
    loadAgentMode(getJson("/agent-mode", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode: button.dataset.mode }),
    })).then(() => setStatus(`Agent: ${button.textContent} for scenario runs`));
  });
  const box = $("reset");
  const ask = () => {
    box.innerHTML = `<button type="button" class="danger-outline" id="reset-ask">Reset</button>`;
  };
  box.addEventListener("click", async (e) => {
    const id = e.target.id;
    if (id === "reset-ask") {
      box.innerHTML = `<span>Go back to the snapshot? Everything since is lost.</span>
        <button type="button" class="danger" id="reset-yes">Reset the world</button>
        <button type="button" class="ghost" id="reset-no">Cancel</button>`;
      $("reset-no").focus();
    } else if (id === "reset-no") {
      ask();
      $("reset-ask").focus();
    } else if (id === "reset-yes") {
      box.innerHTML = `<span>Resetting<span class="dots"></span></span>`;
      try {
        const done = await getJson("/reset", { method: "POST" });
        setStatus(`Reset: the clock is back at ${done.time}`);
      } catch (err) {
        setStatus(err.status === 409 ? "A scenario is running; reset when it ends" : `Couldn't reset (${err.message})`, true);
      }
      ask();
      refreshCounters();
      refreshTicker();
    }
  });
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
  showDiagram();
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

// A playback started from the rail happens at the top of the main column, often out of sight: bring it into view.
function showDiagram() {
  $("diagram-wrap").scrollIntoView({ block: "start", behavior: reducedMotion.matches ? "auto" : "smooth" });
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

// `filter` is "all" or "agent"; the server filters, so "agent" lists the newest agent Decisions (T44).
const ticker = { rows: [], long: false, playing: null, failed: false, filter: "all" };
const TICKER_FILTER_KEY = "live-ticker-filter";

async function refreshTicker() {
  if (document.hidden) return;
  const filter = ticker.filter;
  let rows = null;
  try {
    rows = await getJson(filter === "agent" ? "/decisions/latest?chooser=agent" : "/decisions/latest");
  } catch { /* shown below */ }
  // The filter changed while this was loading: the newer request draws the list.
  if (filter !== ticker.filter) return;
  ticker.failed = rows === null;
  if (rows) ticker.rows = rows;
  renderTicker();
}

function setupTickerFilter() {
  try {
    if (localStorage.getItem(TICKER_FILTER_KEY) === "agent") ticker.filter = "agent";
  } catch { /* storage blocked: show all */ }
  const box = $("ticker-filter");
  const mark = () => box.querySelectorAll("button").forEach((b) =>
    b.setAttribute("aria-pressed", String(b.dataset.filter === ticker.filter)));
  mark();
  box.addEventListener("click", (e) => {
    const button = e.target.closest("button[data-filter]");
    if (!button || button.dataset.filter === ticker.filter) return;
    ticker.filter = button.dataset.filter;
    try { localStorage.setItem(TICKER_FILTER_KEY, ticker.filter); } catch { /* not remembered */ }
    mark();
    ticker.rows = [];
    renderTicker();
    refreshTicker();
  });
}

function renderTicker() {
  const list = $("ticker");
  const rows = ticker.rows.slice(0, ticker.long ? TICKER_LONG : TICKER_SHORT);
  if (!rows.length) {
    const none = ticker.filter === "agent"
      ? "No agent Decisions yet. The agent decides for Customers with a chat: run a scenario or advance the clock."
      : "No Decisions yet.";
    list.innerHTML = `<li class="empty">${ticker.failed ? "Couldn't load Decisions." : none}</li>`;
  } else {
    // Line 1: the outcome, then who; line 2: the Trigger and when. The full Offer and the IDs are in the title.
    list.innerHTML = rows.map((d) => {
      const offer = parseTerms(d.offer);
      const who = d.customer_name || d.customer;
      const title = `Decision #${d.id}: ${offerText(offer)} for ${d.customer_name ? `${who} (${d.customer})` : who}. ` +
        (d.traced ? "Play this Decision" : "This Decision has no trace");
      const chip = CHOOSER_CHIPS[d.chooser];
      // A term inside a button keeps its hover tooltip but takes no focus of its own.
      const replied = d.reacted ? ` · ${withTerms("Customer Bot").replace(' tabindex="0"', "")} replied` : "";
      return `<li><button type="button" class="row ${d.id === ticker.playing ? "playing" : ""}"
        data-id="${d.id}" data-offer="${d.offer_id ?? ""}" ${d.traced ? "" : "disabled"} title="${escapeHtml(title)}">
        <span class="what"><strong class="${offer ? "ok" : ""}">${offer ? "✓" : "–"} ${escapeHtml(shortOffer(offer))}</strong>${chip
          ? `<span class="chip ${d.chooser}" title="${escapeHtml(chip[1])}">${chip[0]}</span>` : ""}
          <span class="who">${escapeHtml(who)}</span></span>
        <span class="when ${replied ? "replied" : ""}">${escapeHtml(words(d.trigger))} · ${escapeHtml(shortWhen(d.time))}${replied}</span></button></li>`;
    }).join("");
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

async function playDecision(id, offerId = null) {
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
  const generation = player.start(`Decision #${id}`, { decisionId: id, offerId });
  showDiagram();
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
  setupControls();
  setupTickerFilter();
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
    if (row && !row.disabled) playDecision(Number(row.dataset.id), row.dataset.offer ? Number(row.dataset.offer) : null);
  });
  $("ticker-more").addEventListener("click", () => {
    ticker.long = !ticker.long;
    renderTicker();
  });
  await loadGlossary();
  // The world charts (world.js) redraw their titles with Glossary tooltips once these are known.
  document.dispatchEvent(new Event("glossary"));
  // The intro card's terms get tooltips too.
  const intro = $("card").querySelector("p:last-child");
  intro.innerHTML = withTerms(intro.textContent.replace(/\s+/g, " "));
  firstUseOnly($("card"));
  await loadScenarios();
  loadAgentMode();
  refreshTicker();
  refreshCounters();
  setInterval(refreshTicker, TICK_MS);
  setInterval(refreshCounters, TICK_MS);
}

main();
