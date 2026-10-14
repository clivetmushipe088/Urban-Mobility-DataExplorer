/* CityPulse tables: top routes, the trip explorer (server-side sort + paging + detail popup),
   the data-quality sheet, and the sheet tabs. Loaded after app.js and charts.js. */
"use strict";

const PAYMENT = { 1: "Card", 2: "Cash", 3: "No charge", 4: "Dispute", 5: "Unknown", 6: "Voided" };
const pct = (v) => (v === null || v === undefined ? "-" : `${fmt.num1.format(v)}%`);
const fixed1 = new Intl.NumberFormat("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const sharePct = (part, whole) => (part / whole < 0.001 ? "<0.1%" : `${fixed1.format(part / whole * 100)}%`);

// --------------------------------------------------------------------------- top routes

widgets.push({
  id: "routes",
  async load(filters) {
    const rows = await api("/top-routes", { ...filters, k: 10 });
    $("routes-body").innerHTML = rows.map((r) => `
      <tr>
        <th scope="row">${r.rank}</th>
        <td>${escapeHtml(r.pickup_zone)} <span class="muted">${escapeHtml(r.pickup_borough)}</span></td>
        <td>${escapeHtml(r.dropoff_zone)} <span class="muted">${escapeHtml(r.dropoff_borough)}</span></td>
        <td class="num">${fmt.int.format(r.trips)}</td>
        <td class="num">${fmt.money.format(r.avg_fare)}</td>
        <td class="num">${fixed1.format(r.avg_duration_min)}</td>
        <td class="num">${fixed1.format(r.avg_distance)}</td>
      </tr>`).join("");
    if (!rows.length) setWidgetStatus("routes", "No trips match these filters.");
  },
});

// --------------------------------------------------------------------------- trip explorer

const tripView = { page: 1, per_page: 25, sort_by: "pickup_ts", sort_order: "desc", filterKey: "" };

const tripsWidget = {
  id: "trips",
  async load(filters) {
    const key = JSON.stringify(filters);
    if (key !== tripView.filterKey) {          // new filters -> back to page 1
      tripView.filterKey = key;
      tripView.page = 1;
    }
    const { page, per_page, sort_by, sort_order } = tripView;
    const res = await api("/trips", { ...filters, page, per_page, sort_by, sort_order });

    $("trips-body").innerHTML = res.data.map((t, i) => `
      <tr data-id="${t.id}" tabindex="0" title="Show trip details">
        <th scope="row">${fmt.int.format((res.page - 1) * res.per_page + i + 1)}</th>
        <td>${escapeHtml(t.pickup_ts)}</td>
        <td>${escapeHtml(t.pickup_zone)}</td>
        <td>${escapeHtml(t.dropoff_zone)}</td>
        <td class="num">${fixed1.format(t.trip_distance)}</td>
        <td class="num">${fixed1.format(t.duration_min)}</td>
        <td class="num">${fmt.money.format(t.fare_amount)}</td>
        <td class="num">${pct(t.tip_pct)}</td>
        <td class="num">${fixed1.format(t.avg_speed_mph)}</td>
        <td>${PAYMENT[t.payment_type] || "-"}</td>
      </tr>`).join("");

    $("trips-page").textContent = res.total
      ? `Page ${fmt.int.format(res.page)} of ${fmt.int.format(res.total_pages)} ` +
        `(${fmt.int.format(res.total)} stored sample trips)`
      : "No trips match these filters.";
    $("trips-prev").disabled = res.page <= 1;
    $("trips-next").disabled = res.page >= res.total_pages;
    markSortedColumn();
  },
};
widgets.push(tripsWidget);

function markSortedColumn() {
  for (const button of document.querySelectorAll("#trips-head button[data-sort]")) {
    const active = button.dataset.sort === tripView.sort_by;
    button.closest("th").setAttribute("aria-sort",
      active ? (tripView.sort_order === "asc" ? "ascending" : "descending") : "none");
    button.dataset.arrow = active ? (tripView.sort_order === "asc" ? "▲" : "▼") : "";
  }
}

function onSortClick(event) {
  const button = event.target.closest("button[data-sort]");
  if (!button) return;
  if (tripView.sort_by === button.dataset.sort) {
    tripView.sort_order = tripView.sort_order === "asc" ? "desc" : "asc";   // same column: flip
  } else {
    tripView.sort_by = button.dataset.sort;
    tripView.sort_order = "desc";
  }
  tripView.page = 1;
  runWidget(tripsWidget);
}

function changePage(step) {
  tripView.page = Math.max(1, tripView.page + step);
  runWidget(tripsWidget);
}

// --------------------------------------------------------------------------- trip detail popup

function detailRow(label, value) {
  return `<dt>${label}</dt><dd>${value}</dd>`;
}

async function openTrip(id) {
  const dialog = $("trip-dialog");
  $("trip-detail").innerHTML = "<p class='muted'>Loading...</p>";
  dialog.showModal();
  try {
    const t = await api(`/trips/${id}`);
    $("trip-title").textContent = `Trip #${t.id}`;
    $("trip-detail").innerHTML = "<dl>" + [
      detailRow("Pickup", `${escapeHtml(t.pickup_ts)}<br>${escapeHtml(t.pickup_zone)}, ${escapeHtml(t.pickup_borough)}`),
      detailRow("Dropoff", `${escapeHtml(t.dropoff_ts)}<br>${escapeHtml(t.dropoff_zone)}, ${escapeHtml(t.dropoff_borough)}`),
      detailRow("Passengers", t.passenger_count),
      detailRow("Distance", `${fmt.num1.format(t.trip_distance)} miles`),
      detailRow("Duration", `${fmt.num1.format(t.duration_min)} minutes`),
      detailRow("Average speed", `${fmt.num1.format(t.avg_speed_mph)} mph`),
      detailRow("Fare", fmt.money.format(t.fare_amount)),
      detailRow("Fare per mile", fmt.money.format(t.fare_per_mile)),
      detailRow("Tip", `${fmt.money.format(t.tip_amount)} (${pct(t.tip_pct)} of fare)`),
      detailRow("Total charged", fmt.money.format(t.total_amount)),
      detailRow("Payment", PAYMENT[t.payment_type] || "-"),
    ].join("") + "</dl>";
  } catch (err) {
    if (err.name !== "AbortError") {
      $("trip-detail").innerHTML = `<p class="form-error">${escapeHtml(err.message)}</p>`;
    }
  }
}

function onTripRow(event) {
  const row = event.target.closest("tr[data-id]");
  if (!row) return;
  if (event.type === "keydown" && event.key !== "Enter") return;
  openTrip(row.dataset.id);
}

// --------------------------------------------------------------------------- data quality

const RULES = {
  missing_values: "A required field was empty (almost always passenger count)",
  duplicate: "Exact repeat of an earlier record",
  bad_zone: "Pickup or dropoff zone is Unknown (264/265) or not in the lookup",
  out_of_range_date: "Pickup date is outside the file's month",
  non_positive_duration: "Dropoff time is at or before pickup time",
  outlier_duration: "Trip lasted more than 6 hours",
  outlier_fare: "Fare is $0 or less, or above $500",
  outlier_distance: "Distance is 0 or above 100 miles",
  outlier_passengers: "Passenger count is not between 1 and 6",
  impossible_speed: "Average speed above 80 mph",
};

widgets.push({
  id: "quality",
  async load() {                         // filters do not apply: these rows never reached the DB
    const q = await api("/exclusions/summary");
    const read = Number(state.run?.rows_read) || 0;
    $("quality-summary").innerHTML = read
      ? `<strong>${fmt.int.format(q.total_excluded)}</strong> of ${fmt.int.format(read)} raw rows ` +
        `(${fmt.num1.format(q.total_excluded / read * 100)}%) were removed during cleaning. ` +
        "Each row is counted under the first rule it broke. Click a rule to see examples."
      : `${fmt.int.format(q.total_excluded)} raw rows were removed during cleaning.`;
    const max = Math.max(1, ...q.reasons.map((r) => r.count));
    $("quality-body").innerHTML = q.reasons.map((r) => `
      <tr data-reason="${escapeHtml(r.reason)}" tabindex="0" title="Show examples">
        <td><code>${escapeHtml(r.reason)}</code></td>
        <td>${RULES[r.reason] || ""}</td>
        <td class="num">${fmt.int.format(r.count)}</td>
        <td class="num">${read ? sharePct(r.count, read) : "-"}</td>
        <td class="bar-cell"><span class="databar" style="width:${(r.count / max) * 100}%"></span></td>
      </tr>`).join("");
  },
});

async function showExamples(event) {
  const row = event.target.closest("tr[data-reason]");
  if (!row || (event.type === "keydown" && event.key !== "Enter")) return;
  const reason = row.dataset.reason;
  $("examples-title").textContent = `Examples: ${reason}`;
  $("examples-body").innerHTML = "<tr><td colspan='2' class='muted'>Loading...</td></tr>";
  $("examples").hidden = false;
  try {
    const rows = await api("/exclusions", { reason, per_page: 10 });
    $("examples-body").innerHTML = rows.map((r) => `
      <tr><td class="num">${fmt.int.format(r.row_index)}</td><td>${escapeHtml(r.details)}</td></tr>`).join("");
  } catch (err) {
    if (err.name !== "AbortError") {
      $("examples-body").innerHTML = `<tr><td colspan="2" class="form-error">${escapeHtml(err.message)}</td></tr>`;
    }
  }
}

// --------------------------------------------------------------------------- sheet tabs

const SHEETS = { overview: "Overview", map: "Zone map", trips: "Trips", quality: "Data quality" };

function showSheet(name) {
  if (!SHEETS[name]) name = "overview";
  for (const el of document.querySelectorAll("[data-sheet]")) el.hidden = el.dataset.sheet !== name;
  for (const tab of document.querySelectorAll(".sheet-tab")) {
    const active = tab.dataset.tab === name;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  }
  document.querySelector(".name-box").textContent = SHEETS[name];
  history.replaceState(null, "", `#${name}`);
  if (name === "map") renderMap();   // Leaflet can only draw once its box is visible
}

document.addEventListener("DOMContentLoaded", () => {
  for (const tab of document.querySelectorAll(".sheet-tab")) {
    tab.addEventListener("click", () => showSheet(tab.dataset.tab));
  }
  showSheet(location.hash.slice(1));

  $("trips-head").addEventListener("click", onSortClick);
  $("trips-prev").addEventListener("click", () => changePage(-1));
  $("trips-next").addEventListener("click", () => changePage(1));
  $("trips-per-page").addEventListener("change", (e) => {
    tripView.per_page = Number(e.target.value);
    tripView.page = 1;
    runWidget(tripsWidget);
  });
  $("trips-body").addEventListener("click", onTripRow);
  $("trips-body").addEventListener("keydown", onTripRow);
  $("trip-close").addEventListener("click", () => $("trip-dialog").close());
  $("quality-body").addEventListener("click", showExamples);
  $("quality-body").addEventListener("keydown", showExamples);
});
