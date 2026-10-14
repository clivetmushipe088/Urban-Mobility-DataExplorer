# CityPulse: NYC Taxi Mobility Explorer

A full-stack dashboard over the NYC TLC **January 2019 Yellow Taxi** trip records:

- a Python pipeline cleans 7.7 million raw trips and logs every row it removes;
- SQLite stores the result in a small star schema;
- a Flask API serves filtered aggregates;
- a spreadsheet-style web dashboard lets you explore when, where and how New Yorkers take taxis.

![Dashboard overview](docs/img/dashboard-overview.png)

## Features

- **Filters everywhere:** borough, date range, hour range (wraps past midnight, e.g. 22 → 4),
  fare, distance and passengers. Every number on the page is recomputed on the server with the
  same filters, and the active filters appear in the formula bar as `=FILTER(Trips, ...)`.
- **Overview sheet:**
  - 6 KPI cells;
  - trips by hour;
  - average speed by hour (a congestion proxy);
  - a weekday × hour heatmap;
  - trips by borough and a fare histogram;
  - auto-generated highlights;
  - the **top 10 routes, ranked by a hand-written min-heap**.
- **Zone map sheet:** a choropleth of all 263 taxi zones. Colour by trips, fare, speed or tip;
  count zones by pickup or dropoff.
- **Trips sheet:** browse the stored trips. Sort by clicking column headers (done on the server),
  page through results, and click a row for full trip details.
- **Data quality sheet:** how many raw rows each cleaning rule removed, with example records.

## Quick start

You need Python 3.10+ and about 2 GB of free disk space.

```bash
# 1. environment
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt

# 2. data (from the TLC Trip Record Data page)
cd data
curl -LO https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_2019-01.parquet
curl -LO https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv
curl -LO https://d37ci6vzurychx.cloudfront.net/misc/taxi_zones.zip
cd ../backend

# 3. reproject the zone shapefile (NY State Plane -> lat/lng GeoJSON)
python convert_zones.py

# 4. clean + load the database (about 30-90 s; prints a table of removed rows)
python pipeline.py --reset

# 5. start the API (keep this terminal open) -> http://127.0.0.1:5001/api/health
python app.py
```

In a second terminal, from the project root:
```bash
python3 -m http.server 8080 -d frontend      # open http://localhost:8080
```

Pipeline options:

- `--limit N` processes only the first N rows, for a quick test.
- `--sample-rate 1` stores every clean trip instead of 20%. This needs plenty of RAM; see the
  section below.

## Project structure

```
backend/
  config.py          paths, cleaning thresholds, sample rate
  schema.sql         zones, trips, exclusion_log, meta + indexes
  db.py              connection helper, init_db()
  convert_zones.py   shapefile -> data/taxi_zones.geojson
  pipeline.py        extract -> clean (10 rules) -> features -> sample -> load
  filters.py         query string -> parameterised WHERE clause
  top_k.py           hand-written MinHeap + top_k (no heapq / sorted)
  app.py             Flask API (15 endpoints, response cache)
  test_top_k.py      pytest suite for the algorithm
  insights.py        prints every figure used in the report
frontend/
  index.html  styles.css  app.js  charts.js  tables.js
docs/
  report.md          technical report
  img/               architecture diagram + figures
data/                downloaded TLC files (parquet ignored by git)
database/            citypulse.db (ignored by git)
```

## API

Base URL: `http://127.0.0.1:5001/api`. Every endpoint marked *filters* accepts:

- `borough`, `zone_id`;
- `start_date`, `end_date` (YYYY-MM-DD);
- `hour_from`, `hour_to` (0–23);
- `min_fare`, `max_fare`, `min_distance`, `max_distance`;
- `passengers` (1–6).

Invalid values return **HTTP 400** with `{"error": "..."}`.

| Method & path | Filters | Returns |
|---|---|---|
| `GET /health` | | status, table counts, pipeline run facts |
| `GET /zones` | | all 265 zones with centroids |
| `GET /zones.geojson` | | zone polygons for the map |
| `GET /boroughs` | | boroughs with zone counts |
| `GET /summary` | yes | KPI totals and averages |
| `GET /by-hour` | yes | 24 rows: trips, average fare, average speed |
| `GET /heatmap` | yes | weekday × hour trip counts and averages |
| `GET /by-borough` | yes | trips, revenue, share % per pickup borough |
| `GET /fare-distribution` | yes | fare histogram buckets |
| `GET /zone-stats` | yes | per-zone totals; `direction=pickup\|dropoff` |
| `GET /top-routes` | yes | busiest routes ranked by `top_k()`; `k=1..50` |
| `GET /trips` | yes | paginated list; `page`, `per_page`, `sort_by`, `sort_order` |
| `GET /trips/<id>` | | one trip with zone names |
| `GET /exclusions/summary` | | rows removed per cleaning rule |
| `GET /exclusions` | | example removed rows; `reason`, `per_page` |

Example: `curl "http://127.0.0.1:5001/api/summary?borough=Bronx&hour_from=22&hour_to=4"`

## Data pipeline in brief

**Cleaning.** The pipeline applies ten rules in order and logs each removed row under the first
rule it broke:

- missing values;
- duplicates;
- unknown zones;
- dates outside the month;
- non-positive duration, or longer than 6 hours;
- fare outside $0–500;
- distance outside 0–100 miles;
- passengers outside 1–6;
- speed over 80 mph.

**Derived features:**

- `duration_min`;
- `avg_speed_mph`, a congestion proxy;
- `fare_per_mile`;
- `tip_pct`, for card trips only, because cash tips are never recorded.

**Sampling.** Every raw row is cleaned, so the exclusion counts are exact, but a seeded random
**20%** of clean trips is stored. The API scales counts and sums ×5. The full month was too slow
to query interactively on an 8 GB laptop; the estimate lands within 0.005% of the true count.

Details, figures and the three insights are in **[docs/report.md](docs/report.md)**.

## Tests

```bash
cd backend
pytest test_top_k.py -q                           # 12 tests: heap, top-k, edge cases, random checks
grep -n "heapq\|sorted(\|\.sort(" top_k.py || echo "no built-in sorting"
python insights.py                                 # recomputes every number in the report
```

## Known limitations

- One month of data, stored as a 20% sample. Counts are estimates; averages are exact for the
  sample.
- Duplicates are detected within each 250k-row batch, not across batches.
- Some implausible records pass every rule, e.g. a $100 fare for 0.01 miles; a fare-per-mile rule
  is future work.
- Development servers only. The API has no authentication and allows any origin (CORS `*`).

## Data source

NYC Taxi & Limousine Commission, [TLC Trip Record Data](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page).
