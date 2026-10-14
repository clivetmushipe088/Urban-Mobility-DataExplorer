"""Print every number used in docs/report.md, straight from the database.

Run from the backend folder after the pipeline:   python insights.py
Counts are scaled by 1 / sample_rate (like the API); averages need no scaling.
"""
import random
import time

import db
from top_k import top_k


def rows(sql, params=()):
    with db.get_connection() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def main():
    meta = {r["key"]: r["value"] for r in rows("SELECT * FROM meta")}
    factor = 1 / float(meta["sample_rate"])
    print("== Pipeline run")
    for key in ("source_file", "rows_read", "rows_clean", "rows_stored", "sample_rate"):
        print(f"  {key:<12} {meta[key]}")

    print("\n== Rows removed per cleaning rule")
    read = int(meta["rows_read"])
    for r in rows("SELECT SUBSTR(reason, 9) AS reason, CAST(details AS INTEGER) AS n FROM exclusion_log "
                  "WHERE reason LIKE 'summary:%' ORDER BY n DESC"):
        print(f"  {r['reason']:<24}{r['n']:>10,}  {r['n'] / read * 100:6.2f}%")

    print("\n== Insight 1: rush hour is when taxis crawl (weekdays vs weekends)")
    for r in rows("""
        SELECT CASE WHEN pickup_dow < 5 THEN 'weekday' ELSE 'weekend' END AS day_type, pickup_hour,
               COUNT(*) AS n, ROUND(AVG(avg_speed_mph), 1) AS mph
        FROM trips WHERE pickup_hour IN (5, 8, 13, 17, 22) GROUP BY 1, 2 ORDER BY 1, 2"""):
        print(f"  {r['day_type']:<8} {r['pickup_hour']:02d}:00  {r['mph']:>5} mph  "
              f"~{round(r['n'] * factor):>9,} trips")

    print("\n== Insight 2: Manhattan short hops dominate, and short trips cost most per mile")
    for r in rows("""
        SELECT pz.borough, COUNT(*) AS n FROM trips t JOIN zones pz ON pz.zone_id = +t.pickup_zone_id
        GROUP BY 1 ORDER BY 2 DESC LIMIT 3"""):
        print(f"  {r['borough']:<10} ~{round(r['n'] * factor):>10,} pickups")
    for r in rows("""
        SELECT CASE WHEN trip_distance < 1 THEN 'a) < 1 mi' WHEN trip_distance < 3 THEN 'b) 1-3 mi'
                    WHEN trip_distance < 10 THEN 'c) 3-10 mi' ELSE 'd) 10+ mi' END AS band,
               COUNT(*) AS n, ROUND(AVG(fare_amount), 2) AS fare, ROUND(AVG(fare_per_mile), 2) AS per_mile
        FROM trips GROUP BY 1 ORDER BY 1"""):
        print(f"  {r['band']:<11} {r['n'] / int(meta['rows_stored']) * 100:5.1f}% of trips  avg fare ${r['fare']:>6}  "
              f"${r['per_mile']:>5}/mile")

    print("\n== Insight 3: tipping - card vs cash, and by time of day (card trips only)")
    for r in rows("""
        SELECT payment_type, COUNT(*) AS n, ROUND(AVG(tip_amount), 2) AS tip FROM trips
        GROUP BY 1 ORDER BY 2 DESC LIMIT 2"""):
        label = {1: "card", 2: "cash"}.get(r["payment_type"], r["payment_type"])
        print(f"  {label:<5} ~{round(r['n'] * factor):>10,} trips  average recorded tip ${r['tip']}")
    for r in rows("""
        SELECT CASE WHEN pickup_hour BETWEEN 6 AND 9 THEN 'a) 06-09 morning rush'
                    WHEN pickup_hour BETWEEN 10 AND 15 THEN 'b) 10-15 midday'
                    WHEN pickup_hour BETWEEN 16 AND 19 THEN 'c) 16-19 evening rush'
                    ELSE 'd) 20-05 night' END AS period,
               ROUND(AVG(tip_pct), 2) AS tip_pct
        FROM trips WHERE payment_type = 1 GROUP BY 1 ORDER BY 1"""):
        print(f"  {r['period']:<24} {r['tip_pct']}% average tip")

    print("\n== Suspicious records that passed every rule")
    for r in rows("""
        SELECT id, fare_amount, trip_distance, duration_min, fare_per_mile FROM trips
        WHERE fare_per_mile > 100 ORDER BY fare_per_mile DESC LIMIT 3"""):
        print(f"  trip {r['id']}: ${r['fare_amount']} for {r['trip_distance']} mi in {r['duration_min']} min "
              f"(${r['fare_per_mile']}/mile)")
    n = rows("SELECT COUNT(*) AS n FROM trips WHERE fare_per_mile > 50")[0]["n"]
    print(f"  trips over $50/mile: {n:,} in the sample (~{round(n * factor):,} estimated)")

    print("\n== Algorithm check: hand-written heap vs built-in sort on real route counts")
    routes = rows("SELECT pickup_zone_id AS pu, dropoff_zone_id AS dz, COUNT(*) AS n "
                  "FROM trips GROUP BY 1, 2")
    random.Random(1).shuffle(routes)
    start = time.perf_counter()
    for _ in range(20):
        best = top_k(routes, 10, key=lambda r: r["n"])
    heap_ms = (time.perf_counter() - start) / 20 * 1000
    start = time.perf_counter()
    for _ in range(20):
        reference = sorted(routes, key=lambda r: r["n"], reverse=True)[:10]   # baseline only
    sort_ms = (time.perf_counter() - start) / 20 * 1000
    same = [r["n"] for r in best] == [r["n"] for r in reference]
    print(f"  {len(routes):,} routes, k = 10: heap {heap_ms:.2f} ms, built-in sort {sort_ms:.2f} ms, "
          f"same answer: {same}")


if __name__ == "__main__":
    main()
