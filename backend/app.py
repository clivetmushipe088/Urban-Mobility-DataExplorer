import os
import threading
from functools import wraps

from flask import Flask, jsonify, request, send_file
from flask_cors import CORS

import config 
import db 
from filters import FilterError, build_filters, build_sort
from top_k import top_k

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

FARE_BUCKETS = ["$0-5", "$5-10", "$10-15", "$15-20", "$20-30", "$30-50", "$50+"]
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


_cache = {"db_mtime": None, "responses": {}}


def cached(view):

    @wraps(view)
    def wrapper(*args, **kwargs):
        mtime = config.DB_PATH.stat().st_mtime if config.DB_PATH.exists() else None
        if mtime != _cache["db_mtime"]:
            _cache["db_mtime"], _cache["responses"] = mtime, {}
        key = request.full_path
        if key not in _cache["responses"]:
            _cache["responses"][key] = view(*args, **kwargs).get_json()
        return jsonify(_cache["responses"][key])
    return wrapper


def query(sql: str, params=(), one: bool = False):

    with db.get_connection() as conn:
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    if one:
        return rows[0] if rows else None
    return rows

def sample_factor() -> float:

    row = query("SELECT value FROM meta WHERE key = 'sample_rate'", one=True)
    return 1 / float(row["value"]) if row else 1.0


def scale(rows, *fields):

    factor = sample_factor()
    for r in rows:
        for f in fields:
            if r.get(f) is not None:
                r[f] = round(r[f] * factor, 2) if isinstance(r[f], float) else round(r[f] * factor)
    return rows

def page_args():

    try:
        page = max(1, int(request.args.get("page", 1)))
        per_page = int(request.args.get("per_page", config.DEFAULT_PER_PAGE))
    except ValueError:
        raise FilterError("'page' and 'per_page' must be whole numbers") from None
    return page, min(max(1, per_page), config.MAX_PER_PAGE)


# -------------- errors

@app.errorhandler(FilterError)
def bad_request(err):
    return jsonify(error=str(err)), 400

@app.errorhandler(404)
def not_found(_err):
    return jsonify(error="not found"), 404

@app.errorhandler(405)
def method_not_allowed(_err):
    return jsonify(error="Method not allowed"), 405

@app.errorhandler(500)
def server_error(_err):
    return jsonify(error="internal server error"), 500


#------------------meta

@app.get("/api/health")
def health():
    ready = db.is_db_ready()
    meta = {r["key"]: r["value"] for r in query("SELECT * FROM meta")} if ready else {}
    return jsonify(status="ok" if ready else "degraded", db_ready=ready,
                   table_counts=db.table_counts() if config.DB_PATH.exists() else {},  run=meta)


@app.get("/api/zones")
def zones():
    return jsonify(query("SELECT * FROM zones ORDER BY borough, zone_name"))

@app.get("/api/zones.geojson")
def zones_geojson():
    """Zone polygons for the map (written by convert_zones.py)."""
    path = config.DATA_DIR / "taxi_zones.geojson"
    if not path.exists():
        return jsonify(error="taxi_zones.geojson missing - run convert_zones.py"), 404
    return send_file(path, mimetype="application/geo+json")


@app.get("/api/boroughs")
def boroughs():
    return jsonify(query(
        "SELECT borough, COUNT(*) AS zones FROM zones "
        "WHERE borough NOT IN ('Unknown', 'N/A') GROUP BY borough ORDER BY borough "))


# ----------- trips

TRIP_SELECT = """
    SELECT t.*, pz.zone_name AS pickup_zone, pz.borough AS pickup_borough,
            dz.zone_name AS dropoff_zone, dz.borough AS dropoff_borough
    FROM trips t
    CROSS JOIN zones pz ON pz.zone_id = t.pickup_zone_id
    CROSS JOIN zones dz ON dz.zone_id = t.dropoff_zone_id
"""

@app.get("/api/trips")
@cached
def trips():
    """Paginated, filterble, sortable trip list."""
    where, params = build_filters(request.args)
    page, per_page = page_args()
    total = query(f"SELECT COUNT(*) AS n FROM trips t{where}", params, one=True)["n"]
    rows = query(TRIP_SELECT + where + build_sort(request.args) + " LIMIT ? OFFSET ?", 
                 params + [per_page, (page - 1) * per_page])
    return jsonify(data=rows, page=page, per_page=per_page, total=total, 
                   total_pages=(total + per_page - 1) // per_page)


@app.get("/api/trips/<int:trip_id>")
def trip(trip_id):
    row = query(TRIP_SELECT + " WHERE t.id = ?", [trip_id], one=True)
    if row is None:
        return jsonify(error=f"trip {trip_id} not found"), 404
    return jsonify(row)

# ------------ analystics

@app.get("/api/summary")
@cached
def summary():
    """Headline numbers for the KPI cards."""
    where, params = build_filters(request.args)
    row = query(f"""
        SELECT COUNT(*) AS total_trips,
                ROUND(SUM(total_amount), 2) AS total_revenue,
                ROUND(AVG(fare_amount), 2) AS avg_fare,
                ROUND(AVG(trip_distance), 2) AS avg_distance,
                ROUND(AVG(duration_min), 2) AS avg_duration_min,
                ROUND(AVG(avg_speed_mph), 2) AS avg_speed_mph,
                ROUND(AVG(tip_pct), 2) AS avg_tip_pct,
                ROUND(AVG(passenger_count), 2) AS avg_passengers
        FROM trips t{where}""", params, one=True)
    row = {k: (v if v is not None else 0) for k, v in row.items()}
    row["sampled_trips"] = row["total_trips"]
    row["sample_rate"] = round(1 / sample_factor(), 4)
    return jsonify(scale([row], "total_trips", "total_revenue")[0])

@app.get("/api/by-hour")
@cached
def by_hour():

    where, params = build_filters(request.args)
    rows = query(f""" 
        SELECT pickup_hour AS hour, COUNT(*) AS trips,
                ROUND(AVG(fare_amount), 2) AS avg_fare,
                ROUND(AVG(avg_speed_mph), 2) AS avg_speed_mph
        FROM trips t{where} GROUP BY pickup_hour""", params)
    found = {r["hour"]: r for r in scale(rows, "trips")}
    return jsonify([found.get(h, {"hour": h, "trips": 0, "avg_fare": 0, "avg_speed_mph": 0})
                    for h in range(24)])


@app.get("/api/heatmap")
@cached
def heatmap():
    """Day-of-week """
    where, params = build_filters(request.args)
    rows = query(f"""
        SELECT pickup_dow AS dow, pickup_hour AS hour, COUNT(*) AS trips,
                ROUND(COUNT(*) * 1.0 / COUNT(DISTINCT pickup_date), 1) AS avg_trips,
                ROUND(AVG(avg_speed_mph), 2) AS avg_speed_mph
        FROM trips t{where} GROUP BY pickup_dow, pickup_hour""", params)
    for r in rows:
        r["day"] = DAY_NAMES[r["dow"]]
    return jsonify(scale(rows, "trips", "avg_trips"))

@app.get("/api/by-borough")
@cached
def by_borough():
    """Trips amd money per pickup"""
    where, params = build_filters(request.args)
    rows = query(f"""
        SELECT pz.borough, COUNT(*) AS trips,
                ROUND(AVG(t.fare_amount), 2) AS avg_fare,
                ROUND(SUM(t.total_amount), 2) AS revenue,
                ROUND(AVG(t.trip_distance), 2) AS avg_distance,
                ROUND(AVG(t.tip_pct), 2) AS avg_tip_pct
        FROM trips t JOIN zones pz ON pz.zone_id = +t.pickup_zone_id{where}
        GROUP BY pz.borough ORDER BY trips DESC""", params)
    total = sum(r["trips"] for r in rows) or 1
    for r in rows:
        r["share_pct"] = round(r["trips"] / total * 100, 2)
    return jsonify(scale(rows, "trips", "revenue"))

@app.get("/api/fare-distribution")
@cached
def fare_distribution():
    """Histrogram of fares in"""
    where, params = build_filters(request.args)
    rows = query(f"""
        SELECT CASE WHEN fare_amount < 5 THEN 0 WHEN fare_amount < 10 THEN 1
                    WHEN fare_amount < 15 THEN 2 WHEN fare_amount < 20 THEN 3
                    WHEN fare_amount < 30 THEN 4 WHEN fare_amount < 50 THEN 5
                    ELSE 6 END AS bucket, COUNT(*) AS trips
        FROM trips t{where} GROUP BY bucket""", params)
    counts = {r["bucket"]: r["trips"] for r in scale(rows, "trips")}
    return jsonify([{"bucket": label, "trips": counts.get(i, 0)}
                    for i, label in enumerate(FARE_BUCKETS)])

@app.get("/api/zone-stats")
@cached
def zone_stats():
    """Per-zone totals for the map. """
    where, params = build_filters(request.args)
    column = "dropoff_zone_id" if request.args.get("direction") == "dropoff" else "pickup_zone_id"
    rows = query(f"""
        SELECT +t.{column} AS zone_id, COUNT(*) AS trips,
                ROUND(AVG(t.fare_amount), 2) AS avg_fare,
                ROUND(AVG(t.avg_speed_mph), 2) AS avg_speed_mph,
                ROUND(AVG(t.tip_pct), 2) AS avg_tip_pct
        FROM trips t{where} GROUP BY zone_id""", params)
    return jsonify(scale(rows, "trips"))


@app.get("/api/top-routes")
@cached
def top_routes():
    """Busiest pickup -> dropoff zone pairs, ranked by our hand-written heap (top_k.py). 
    
    SQL only groups the trips into routes; the ranking itself is done by top_k(),"""

    where, params = build_filters(request.args)
    try:
        k = min(max(int(request.args.get("k", 10)), 1), 50)
    except ValueError:
        raise FilterError("'k' must be a whole number") from None

    with db.get_connection() as conn:
        cursor = conn.execute(f"""
            SELECT +t.pickup_zone_id AS pickup_zone_id, +t.dropoff_zone_id AS dropoff_zone_id,
                    COUNT(*) AS trips, ROUND(AVG(t.fare_amount), 2) AS avg_fare,
                    ROUND(AVG(t.duration_min), 2) AS avg_duration_min,
                    ROUND(AVG(t.trip_distance), 2) AS avg_distance
            FROM trips t{where} GROUP BY 1, 2""", params)
        best = [dict(r) for r in top_k(cursor, k, key=lambda r: r["trips"])]

    names = {z["zone_id"]: z for z in query("SELECT zone_id, zone_name, borough FROM zones")}
    for rank, route in enumerate(best, start=1):
        pickup, dropoff = names[route["pickup_zone_id"]], names[route["dropoff_zone_id"]]
        route.update(rank=rank, pickup_zone=pickup["zone_name"], pickup_borough=pickup["borough"],
                     dropoff_zone=dropoff["zone_name"], dropoff_borough=dropoff["borough"])
    return jsonify(scale(best, "trips"))

# ----------- data quality

@app.get("/api/exclusions/summary")
def exclusions_summary():
    """How many raw rows each cleaning rule removed"""
    rows = query("""
        SELECT SUBSTR(reason, 9) AS reason, CAST(details AS INTEGER) AS count
        FROM exclusion_log WHERE reason LIKE 'summary:%' ORDER BY count DESC""")
    return jsonify(total_excluded=sum(r["count"] for r in rows), reasons=rows)

@app.get("/api/exclusions")
def exclusions():
    """A few example excluded records, optionally for one reason."""
    reason = request.args.get("reason", "").strip()
    _, per_page = page_args()
    sql = "SELECT row_index, reason, details FROM exclusion_log WHERE reason NOT LIKE 'summary:%'"
    params = []
    if reason:
        sql += " AND reason = ?"
        params.append(reason)
    return jsonify(query(sql + " ORDER BY id LIMIT ?", params + [min(per_page, 100)]))

DEFAULT_VIEWS = ["/api/summary", "/api/by-hour", "/api/heatmap", "/api/by-borough", 
                 "/api/fare-distribution", "/api/zone-stats", "/api/trips", "/api/top-routes"]

def warm_cache():
    """Pre_compute the unfiltered dashboard in the background so the first page load is fast"""
    with app.test_client() as client:
        for url in DEFAULT_VIEWS:
            client.get(url)
    print(" * cache warmed: unfiltered dashboard is ready")

if __name__ == "__main__":
    if not db.is_db_ready():
        print("Database is empty - run:  python pipeline.py --reset")
    else:
        threading.Thread(target=warm_cache, daemon=True).start()
    app.run(port=5001, debug=os.environ.get("CITYPULSE_DEBUG") == "1")