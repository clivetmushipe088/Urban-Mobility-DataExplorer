/* CityPulse dashboard: talks to the Flask API and fills every widget.
   Every number on the page comes from the server with the current filters applied. */
"use strict";

const API_BASE = "http://127.0.0.1:5001/api";

// --------------------------------------------------------------------------- helpers

const $ = (id) => document.getElementById(id);

/** Escape text from the API before putting it into innerHTML. */
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

const fmt = {
  int: new Intl.NumberFormat("en-US"),
  money: new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }),
  bigMoney: new Intl.NumberFormat("en-US", {
    style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 1 }),
  num1: new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }),
};

// --------------------------------------------------------------------------- API

const inflight = {};  // path -> AbortController, so a newer request cancels an older one

/** GET API_BASE + path with query params (empty values are dropped). Throws Error on failure. */
async function api(path, params = {}) {
  const url = new URL(API_BASE + path);
  for (const [key, value] of Object.entries(params)) {
    if (value !== "" && value !== null && value !== undefined) url.searchParams.set(key, value);
  }
  if (inflight[path]) inflight[path].abort();
  const controller = new AbortController();
  inflight[path] = controller;

  let response;
  try {
    response = await fetch(url, { signal: controller.signal });
  } catch (err) {
    if (err.name === "AbortError") throw err;
    throw new Error("Cannot reach the API. Is python app.py running?");
  }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || `Request failed (HTTP ${response.status})`);
  return body;
}

// --------------------------------------------------------------------------- state & widgets

const state = { filters: {} };

/** Read the filter form into a plain object (blank fields are left out). */
function readFilters() {
  const filters = {};
  for (const [key, value] of new FormData($("filters"))) {
    if (String(value).trim() !== "") filters[key] = String(value).trim();
  }
  return filters;
}

/** Simple checks before asking the server (the server validates again). */
function checkFilters(f) {
  const pairs = [["min_fare", "max_fare", "fare"], ["min_distance", "max_distance", "distance"]];
  for (const [lo, hi, name] of pairs) {
    if (f[lo] && f[hi] && Number(f[lo]) > Number(f[hi])) return `Minimum ${name} is above the maximum.`;
  }
  if (f.start_date && f.end_date && f.start_date > f.end_date) return "Start date is after end date.";
  return "";
}

/** Show the active filters as a spreadsheet formula in the formula bar. */
function showFormula(f) {
  const parts = [];
  if (f.borough) parts.push(`Borough="${f.borough}"`);
  if (f.start_date) parts.push(`Date>=${f.start_date}`);
  if (f.end_date) parts.push(`Date<=${f.end_date}`);
  if (f.hour_from) parts.push(`Hour>=${f.hour_from}`);
  if (f.hour_to) parts.push(`Hour<=${f.hour_to}`);
  if (f.min_fare) parts.push(`Fare>=${f.min_fare}`);
  if (f.max_fare) parts.push(`Fare<=${f.max_fare}`);
  if (f.min_distance) parts.push(`Miles>=${f.min_distance}`);
  if (f.max_distance) parts.push(`Miles<=${f.max_distance}`);
  if (f.passengers) parts.push(`Passengers=${f.passengers}`);
  $("formula").textContent = `=FILTER(Trips${parts.length ? ", " + parts.join(", ") : ""})`;
}

/*
 * Each widget = { id, load(filters) }. `id` matches a data-widget="..." element in index.html.
 * Part 7 adds more widgets to this list; loadDashboard() runs them all in parallel.
 */
const widgets = [];

function widgetElement(id) {
  return document.querySelector(`[data-widget="${id}"]`);
}

/** Show a message under a widget. kind: "" (info), "error". retry: function or null. */
function setWidgetStatus(id, message, kind = "", retry = null) {
  const status = widgetElement(id)?.querySelector(".card-status");
  if (!status) return;
  status.className = `card-status ${kind}`;
  status.textContent = message;
  if (retry) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "Retry";
    button.addEventListener("click", retry);
    status.append(button);
  }
}

/** Run one widget with loading / error handling, so one failure never blanks the page. */
async function runWidget(widget) {
  const el = widgetElement(widget.id);
  el?.classList.add("is-loading");
  setWidgetStatus(widget.id, "");
  try {
    await widget.load(state.filters);
  } catch (err) {
    if (err.name === "AbortError") return;  // a newer request replaced this one
    setWidgetStatus(widget.id, err.message, "error", () => runWidget(widget));
  } finally {
    el?.classList.remove("is-loading");
  }
}

async function loadDashboard() {
  await Promise.allSettled(widgets.map(runWidget));
  $("last-updated").textContent =
    "Updated " + new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

// --------------------------------------------------------------------------- KPI cards

widgets.push({
  id: "summary",
  async load(filters) {
    const s = await api("/summary", filters);
    const empty = s.sampled_trips === 0;
    $("kpi-trips").textContent = empty ? "0" : fmt.int.format(s.total_trips);
    $("kpi-revenue").textContent = empty ? "-" : fmt.bigMoney.format(s.total_revenue);
    $("kpi-fare").textContent = empty ? "-" : fmt.money.format(s.avg_fare);
    $("kpi-distance").textContent = empty ? "-" : fmt.num1.format(s.avg_distance) + " mi";
    $("kpi-speed").textContent = empty ? "-" : fmt.num1.format(s.avg_speed_mph) + " mph";
    $("kpi-tip").textContent = empty ? "-" : fmt.num1.format(s.avg_tip_pct) + "%";
    $("sample-note").textContent = s.sample_rate < 1
      ? `Counts and revenue are estimated from a ${Math.round(s.sample_rate * 100)}% random ` +
        `sample (${fmt.int.format(s.sampled_trips)} stored trips match these filters).`
      : `${fmt.int.format(s.sampled_trips)} trips match these filters.`;
    $("status-summary").textContent = empty ? "No matching trips" :
      `Count: ${fmt.int.format(s.total_trips)}    Average fare: ${fmt.money.format(s.avg_fare)}` +
      `    Sum: ${fmt.bigMoney.format(s.total_revenue)}`;
    if (empty) setWidgetStatus("summary", "No trips match these filters. Try widening them.");
  },
});

// --------------------------------------------------------------------------- connection & boot

function setConnection(ok, text) {
  $("status-dot").className = "dot " + (ok ? "ok" : "down");
  $("status-text").textContent = text;
}

function showBanner(message) {
  $("banner-text").textContent = message;
  $("banner").hidden = !message;
}

async function fillBoroughs() {
  const select = $("f-borough");
  if (select.options.length > 1) return;  // already filled
  for (const b of await api("/boroughs")) {
    select.add(new Option(`${b.borough} (${b.zones} zones)`, b.borough));
  }
}

async function boot() {
  showBanner("");
  try {
    const health = await api("/health");
    if (!health.db_ready) throw new Error("The database is empty. Run: python pipeline.py --reset");
    state.run = health.run;
    setConnection(true, "API connected");
    await fillBoroughs();
  } catch (err) {
    setConnection(false, "API offline");
    showBanner(err.message);
    return;
  }
  loadDashboard();
}

function onSubmit(event) {
  event.preventDefault();
  const filters = readFilters();
  const problem = checkFilters(filters);
  $("filter-error").textContent = problem;
  $("filter-error").hidden = !problem;
  if (problem) return;
  state.filters = filters;
  showFormula(filters);
  loadDashboard();
}

function onReset() {
  // The form clears itself after this event, so read the (empty) filters on the next tick.
  setTimeout(() => {
    $("filter-error").hidden = true;
    state.filters = {};
    showFormula({});
    loadDashboard();
  });
}

document.addEventListener("DOMContentLoaded", () => {
  $("filters").addEventListener("submit", onSubmit);
  $("filters").addEventListener("reset", onReset);
  $("banner-retry").addEventListener("click", boot);
  boot();
});
