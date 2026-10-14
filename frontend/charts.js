/* CityPulse visuals: hourly charts, borough + fare charts (Chart.js), the weekday x hour
   heatmap (a plain CSS grid) and the zone map (Leaflet). Loaded after app.js and reuses its
   helpers: api(), widgets, state, fmt, escapeHtml(), setWidgetStatus(), runWidget(). */
"use strict";

const COLORS = {
  series: "#2a78d6",                       // one series per chart -> categorical slot 1
  grid: "#e1e0d9",
  axis: "#c3c2b7",
  text: "#52514e",
  // Sequential green ramp (an Excel-style colour scale): light = low, dark = high.
  ramp: ["#eef7f1", "#d2eadb", "#acd7bb", "#7fbf95", "#52a46f", "#2f8650", "#196638", "#0b4a25"],
  empty: "#f3f3f3",
};
const compact = new Intl.NumberFormat("en-US", { notation: "compact" }).format;
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const hourLabel = (h) => `${String(h).padStart(2, "0")}:00`;

// --------------------------------------------------------------------------- Chart.js setup

const charts = {};  // canvas id -> Chart instance

function requireLibrary(name, global) {
  if (!window[global]) throw new Error(`${name} did not load (check your internet connection).`);
}

if (window.Chart) {
  Chart.defaults.font.family = '"Segoe UI", Calibri, Aptos, system-ui, sans-serif';
  Chart.defaults.font.size = 12;
  Chart.defaults.color = COLORS.text;
  Chart.defaults.borderColor = COLORS.grid;
  Chart.defaults.maintainAspectRatio = false;
  Chart.defaults.animation.duration = 300;
  Chart.defaults.plugins.legend.display = false;   // one series per chart: the title names it
  Object.assign(Chart.defaults.plugins.tooltip, {
    backgroundColor: "#ffffff", titleColor: "#1f1f1f", bodyColor: "#1f1f1f",
    borderColor: "#b3b0ad", borderWidth: 1, cornerRadius: 0, displayColors: false, padding: 8,
  });
}

/** Replace the chart on a canvas (destroy first, so redraws never stack). */
function drawChart(canvasId, config) {
  requireLibrary("Chart.js", "Chart");
  if (charts[canvasId]) charts[canvasId].destroy();
  charts[canvasId] = new Chart(document.getElementById(canvasId), config);
}

function axes(xTitle, yTitle, yTicks) {
  return {
    x: { grid: { display: false }, border: { color: COLORS.axis }, ticks: { maxRotation: 0 },
         title: { display: Boolean(xTitle), text: xTitle } },
    y: { beginAtZero: true, border: { display: false }, ticks: { callback: yTicks },
         title: { display: Boolean(yTitle), text: yTitle } },
  };
}

// --------------------------------------------------------------------------- hourly charts

widgets.push({
  id: "hourly",
  async load(filters) {
    const rows = await api("/by-hour", filters);
    state.hourly = rows;
    const labels = rows.map((r) => String(r.hour).padStart(2, "0"));

    drawChart("chart-trips-hour", {
      type: "bar",
      data: { labels, datasets: [{ data: rows.map((r) => r.trips), backgroundColor: COLORS.series,
                                   maxBarThickness: 26 }] },
      options: {
        scales: axes("Pickup hour", "Trips", compact),
        plugins: { tooltip: { callbacks: {
          title: (items) => hourLabel(items[0].dataIndex),
          label: (item) => `${fmt.int.format(item.raw)} trips` } } },
      },
    });

    drawChart("chart-speed-hour", {
      type: "line",
      data: { labels, datasets: [{
        data: rows.map((r) => (r.trips ? r.avg_speed_mph : null)),
        borderColor: COLORS.series, backgroundColor: COLORS.series,
        borderWidth: 2, pointRadius: 3, pointHoverRadius: 5, tension: 0.25 }] },
      options: {
        interaction: { mode: "index", intersect: false },
        scales: axes("Pickup hour", "Average speed (mph)", (v) => v),
        plugins: { tooltip: { callbacks: {
          title: (items) => hourLabel(items[0].dataIndex),
          label: (item) => `${fmt.num1.format(item.raw)} mph average` } } },
      },
    });

    renderHighlights();
    if (!rows.some((r) => r.trips)) setWidgetStatus("hourly", "No trips match these filters.");
  },
});

// --------------------------------------------------------------------------- heatmap

/** Colour for a value 0..1 on the green ramp. */
function rampColor(t) {
  const step = Math.min(COLORS.ramp.length - 1, Math.floor(t * COLORS.ramp.length));
  return COLORS.ramp[step];
}

function scaleLegend(low, high) {
  const swatches = COLORS.ramp.map((c) => `<span style="background:${c}"></span>`).join("");
  return `<span>${low}</span><span class="scale-swatches">${swatches}</span><span>${high}</span>`;
}

widgets.push({
  id: "heatmap",
  async load(filters) {
    const rows = await api("/heatmap", filters);
    const values = {};
    let max = 0;
    for (const r of rows) {
      values[`${r.dow}-${r.hour}`] = r.avg_trips;
      if (r.avg_trips > max) max = r.avg_trips;
    }

    let html = '<span class="hm-corner"></span>';
    for (let h = 0; h < 24; h++) html += `<span class="hm-col">${h}</span>`;
    DAYS.forEach((day, d) => {
      html += `<span class="hm-row">${day}</span>`;
      for (let h = 0; h < 24; h++) {
        const v = values[`${d}-${h}`] || 0;
        const color = v ? rampColor(v / max) : COLORS.empty;
        const tip = `${day} ${hourLabel(h)}: about ${fmt.int.format(Math.round(v))} trips per hour`;
        html += `<span class="hm-cell" style="background:${color}" title="${tip}"></span>`;
      }
    });
    $("heatmap").innerHTML = html;
    $("heatmap-scale").innerHTML = scaleLegend("0", `${fmt.int.format(Math.round(max))} trips/hour`);
    if (!rows.length) setWidgetStatus("heatmap", "No trips match these filters.");
  },
});

// --------------------------------------------------------------------------- borough + fare charts

widgets.push({
  id: "boroughs",
  async load(filters) {
    const rows = await api("/by-borough", filters);
    state.boroughs = rows;
    drawChart("chart-borough", {
      type: "bar",
      data: {
        labels: rows.map((r) => `${r.borough} (${fmt.num1.format(r.share_pct)}%)`),
        datasets: [{ data: rows.map((r) => r.trips), backgroundColor: COLORS.series, maxBarThickness: 22 }],
      },
      options: {
        indexAxis: "y",
        scales: {
          x: { beginAtZero: true, ticks: { callback: compact }, title: { display: true, text: "Trips" } },
          y: { grid: { display: false } },
        },
        plugins: { tooltip: { callbacks: { label: (item) => {
          const r = rows[item.dataIndex];
          return [`${fmt.int.format(r.trips)} trips`, `Average fare ${fmt.money.format(r.avg_fare)}`,
                  `Average distance ${fmt.num1.format(r.avg_distance)} mi`];
        } } } },
      },
    });
    renderHighlights();
    if (!rows.length) setWidgetStatus("boroughs", "No trips match these filters.");
  },
});

widgets.push({
  id: "fares",
  async load(filters) {
    const rows = await api("/fare-distribution", filters);
    const total = rows.reduce((sum, r) => sum + r.trips, 0) || 1;
    drawChart("chart-fare", {
      type: "bar",
      data: { labels: rows.map((r) => r.bucket),
              datasets: [{ data: rows.map((r) => r.trips), backgroundColor: COLORS.series,
                           maxBarThickness: 48 }] },
      options: {
        scales: axes("Meter fare", "Trips", compact),
        plugins: { tooltip: { callbacks: { label: (item) =>
          `${fmt.int.format(item.raw)} trips (${fmt.num1.format(item.raw / total * 100)}%)` } } },
      },
    });
    if (!rows.some((r) => r.trips)) setWidgetStatus("fares", "No trips match these filters.");
  },
});

// --------------------------------------------------------------------------- highlights

/** Two or three plain-language findings computed from the data already on screen. */
function renderHighlights() {
  const items = [];
  const hours = (state.hourly || []).filter((r) => r.trips > 0);
  if (hours.length) {
    const busiest = hours.reduce((a, b) => (b.trips > a.trips ? b : a));
    const slowest = hours.reduce((a, b) => (b.avg_speed_mph < a.avg_speed_mph ? b : a));
    const fastest = hours.reduce((a, b) => (b.avg_speed_mph > a.avg_speed_mph ? b : a));
    items.push(`The busiest pickup hour is <strong>${hourLabel(busiest.hour)}</strong>, ` +
               `with about ${fmt.int.format(busiest.trips)} trips.`);
    items.push(`Taxis are slowest at <strong>${hourLabel(slowest.hour)}</strong> ` +
               `(${fmt.num1.format(slowest.avg_speed_mph)} mph) and fastest at ` +
               `<strong>${hourLabel(fastest.hour)}</strong> (${fmt.num1.format(fastest.avg_speed_mph)} mph): ` +
               `${fmt.num1.format(fastest.avg_speed_mph / slowest.avg_speed_mph)}x faster.`);
  }
  const top = (state.boroughs || [])[0];
  if (top) {
    items.push(`<strong>${escapeHtml(top.borough)}</strong> accounts for ` +
               `${fmt.num1.format(top.share_pct)}% of pickups.`);
  }
  $("highlights").innerHTML = items.length
    ? items.map((text) => `<li>${text}</li>`).join("")
    : "<li>No trips match these filters.</li>";
}

// --------------------------------------------------------------------------- zone map

const MAP_METRICS = {
  trips: { label: "Trips", format: (v) => fmt.int.format(v) },
  avg_fare: { label: "Average fare", format: (v) => fmt.money.format(v) },
  avg_speed_mph: { label: "Average speed", format: (v) => `${fmt.num1.format(v)} mph` },
  avg_tip_pct: { label: "Average tip (card)", format: (v) => `${fmt.num1.format(v)}%` },
};
const MIN_TRIPS_FOR_AVERAGES = 100;  // averages from a handful of trips are noise
const mapState = { map: null, layer: null, geo: null, stats: [] };

/** Split values into `count` groups of equal size; returns the upper bound of each group. */
function quantileBreaks(values, count) {
  const sorted = [...values].sort((a, b) => a - b);
  const breaks = [];
  for (let i = 1; i <= count; i++) {
    breaks.push(sorted[Math.min(sorted.length - 1, Math.ceil((i / count) * sorted.length) - 1)]);
  }
  return breaks;
}

function colorFor(value, breaks) {
  const step = breaks.findIndex((b) => value <= b);
  return COLORS.ramp[step === -1 ? COLORS.ramp.length - 1 : step];
}

const mapWidget = {
  id: "map",
  async load(filters) {
    requireLibrary("Leaflet", "L");
    const params = { ...filters, direction: $("map-direction").value };
    const [geo, stats] = await Promise.all([
      mapState.geo || api("/zones.geojson"),
      api("/zone-stats", params),
    ]);
    mapState.geo = geo;
    mapState.stats = stats;
    renderMap();
    if (!stats.length) setWidgetStatus("map", "No trips match these filters.");
  },
};
widgets.push(mapWidget);

/** Draw (or redraw) the choropleth. Leaflet needs a visible box, so this waits for the tab. */
function renderMap() {
  if (!mapState.geo || $("map").offsetParent === null) return;
  if (!mapState.map) {
    // No street basemap: like an Excel map chart, the zones themselves are the picture
    // (and nothing depends on a third-party tile server during a demo).
    mapState.map = L.map("map", { zoomSnap: 0.25, attributionControl: false })
      .setView([40.70, -73.94], 10.25);
  }
  mapState.map.invalidateSize();

  const metric = $("map-metric").value;
  const { label, format } = MAP_METRICS[metric];
  const usable = (s) => s && s[metric] > 0 && (metric === "trips" || s.trips >= MIN_TRIPS_FOR_AVERAGES);
  const byZone = {};
  for (const s of mapState.stats) byZone[s.zone_id] = s;
  const values = mapState.stats.filter(usable).map((s) => s[metric]);
  const breaks = values.length ? quantileBreaks(values, COLORS.ramp.length) : [];

  if (mapState.layer) mapState.layer.remove();
  mapState.layer = L.geoJSON(mapState.geo, {
    style: (feature) => {
      const s = byZone[feature.properties.LocationID];
      return { fillColor: usable(s) ? colorFor(s[metric], breaks) : COLORS.empty,
               fillOpacity: 1, color: "#ffffff", weight: 0.8 };
    },
    onEachFeature: (feature, layer) => {
      const p = feature.properties;
      const s = byZone[p.LocationID];
      const value = usable(s) ? format(s[metric]) : "not enough trips";
      layer.bindTooltip(`<strong>${escapeHtml(p.zone)}</strong> (${escapeHtml(p.borough)})<br>` +
                        `${label}: ${value}`, { sticky: true });
      layer.on({
        mouseover: (e) => e.target.setStyle({ weight: 2, color: "#1f1f1f" }),
        mouseout: (e) => mapState.layer.resetStyle(e.target),
      });
    },
  }).addTo(mapState.map);

  $("map-legend").innerHTML = breaks.length
    ? scaleLegend(format(Math.min(...values)), format(Math.max(...values))) +
      `<span class="muted">Each shade holds an equal number of zones. Grey: no trips` +
      `${metric === "trips" ? "" : ` or fewer than ${MIN_TRIPS_FOR_AVERAGES}`}.</span>`
    : "";
}

document.addEventListener("DOMContentLoaded", () => {
  $("map-metric").addEventListener("change", renderMap);
  $("map-direction").addEventListener("change", () => runWidget(mapWidget));
});
