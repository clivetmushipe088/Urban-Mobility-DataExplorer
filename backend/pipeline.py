import argparse
import json
import re
import time 
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

import config
import db

# Raw TLC column -> our schema name. Only these columns are read from the parquet file.
SOURCE_COLUMNS = {
    "tpep_pickup_datetime": "pickup_ts",
    "tpep_dropoff_datetime": "dropoff_ts",
    "passenger_count": "passenger_count",
    "trip_distance": "trip_distance",
    "pulocationid": "pickup_zone_id",
    "dolocationid": "dropoff_zone_id",
    "payment_type": "payment_type",
    "fare_amount": "fare_amount",
    "tip_amount": "tip_amount",
    "total_amount": "total_amount",
}
REQUIRED = [c for c in SOURCE_COLUMNS.values() if c != "payment_type"]
DUPLICATE_KEY = ["pickup_ts", "dropoff_ts", "pickup_zone_id", "dropoff_zone_id", "fare_amount", "trip_distance"]

# Column order used for INSERT (never rely on Dataframe coulmn order).
TRIP_COLUMNS = [
    "pickup_ts", "dropoff_ts", "passenger_count", "trip_distance", "pickup_zone_id", "dropoff_zone_id", "payment_type", "fare_amount", "tip_amount", "total_amount", "duration_min", "avg_speed_mph", "fare_per_mile", "tip_pct", "pickup_hour", "pickup_dow", "pickup_date",
]
INSERT_CHUNK = 50_000

# ---------- extract

def read_zones(path: Path) -> pd.DataFrame:
    """Read texi_zone_lookup.csv and rename columns to the schema names."""
    zones = pd.read_csv(path)
    zones.columns = [c.strip().lower() for c in zones.columns]
    zones = zones.rename(columns={"locationid": "zone_id", "zone": "zone_name"})
    zones["zone_id"] = zones["zone_id"].astype(int)
    zones["borough"] = zones["borough"].fillna("Unknown")
    zones["zone_name"] = zones["zone_name"].fillna("Unknown")
    zones["service_zone"] = zones["service_zone"].fillna("N/A")
    return zones[["zone_id", "borough", "zone_name", "service_zone"]]

def zone_centroids(path: Path | None) -> dict:
    if path is None or not path.exists():
        print(" ! taxi_zones GeoJSON not found - zones will have no centroilds")
        return{}

    geo = json.loads(path.read_text())
    sums = {}
    for feature in geo.get("features", []):
        props = {k.lower(): v for k, v in (feature.get("properties") or {}).items()}
        raw_id = props.get("locationid", props.get("location_id", props.get("objectid")))
        geometry = feature.get("geometry") or {}
        if raw_id is None or not geometry:
            continue
        zone_id = int(float(raw_id))

        if geometry["type"] == "Polygon":
            outer_rings = [geometry["coordinates"][0]]
        elif geometry["type"] == "MultiPolygon":
            outer_rings = [polygon[0] for polygon in geometry["coordinates"]]
        else:
            continue

        acc = sums.setdefault(zone_id, [0.0, 0.0, 0])
        for ring in outer_rings:
            if len(ring) > 1 and ring[0] == ring[-1]:
                ring = ring[:-1]
            for lng, lat, *_ in ring:
                acc[0] += lng
                acc[1] += lat
                acc[2] += 1

    centroids = {zid: (s[1] / s[2], s[0] / s[2]) for zid, s in sums.items() if s[2]}
    sample = next(iter(centroids.values()), (0, 0))
    if abs(sample[0]) > 90 or abs(sample[1]) > 180:
        print(" ! GeoJSON is not in lat/lng (probably NY Sate Plane) - reroject to WGS84")
        return {}
    return centroids

def file_month(path: Path) -> tuple[int, int] | None:
    """Year and month"""
    match = re.search(r"(\d{4})-(\d{2})", path.name)
    return (int(match.group(1)), int(match.group(2))) if match else None

def iter_trip_batches(path: Path, limit: int | None):
    parquet = pq.ParquetFile(path)
    actual = {name.lower(): name for name in parquet.schema_arrow.names}
    wanted = [actual[c] for c in SOURCE_COLUMNS if c in actual]
    offset = 0
    for batch in parquet.iter_batches(batch_size=config.BATCH_SIZE, columns=wanted):
        df = batch.to_pandas()
        df.columns = [SOURCE_COLUMNS[c.lower()] for c in df.columns]
        if limit is not None and offset + len(df) > limit:
            df = df.iloc[: limit - offset ]
        df.index = range(offset, offset + len(df))
        offset += len(df)
        yield df
        if limit is not None and offset >= limit:
            break


# ------- clean

def clean(df: pd.DataFrame, valid_zone_ids: set, year: int, month: int):

    rules = config.CLEAN_RULES
    df = df.copy()
    df["pickup_ts"] = pd.to_datetime(df["pickup_ts"], errors="coerce")
    df["dropoff_ts"] = pd.to_datetime(df["dropoff_ts"], errors="coerce")
    duration = (df["dropoff_ts"] - df["pickup_ts"]).dt.total_seconds() / 60
    speed = df["trip_distance"] / (duration / 60)
    pu, do = df["pickup_zone_id"], df["dropoff_zone_id"]
    bad_ids = set(config.UNKNOWN_ZONE_IDS)

    checks = [
        ("missing_values", df[REQUIRED].isna().any(axis=1),
        lambda h: "null in: " + df.loc[h, REQUIRED].isna().apply(
            lambda r: ",".join(r.index[r]), axis=1)),
        ("duplicate", df.duplicated(subset=DUPLICATE_KEY, keep="first"),
         lambda h: pd.Series("same as an earlier row in this batch", index=df.index[h])),
        ("bad_zone", ~pu.isin(valid_zone_ids) | ~do.isin(valid_zone_ids)
         | pu.isin(bad_ids) | do.isin(bad_ids),
         lambda h: "pu=" + pu[h].astype(str) + " do=" + do[h].astype(str)),
        ("out_of_range_date", (df["pickup_ts"].dt.year != year)
         | (df["pickup_ts"].dt.month != month),
         lambda h: "pickup_ts=" + df.loc[h, "pickup_ts"].astype(str)),
        ("non_positive_duration", duration <= 0,
         lambda h: "duration_min=" + duration[h].round(2).astype(str)),
        ("outlier_duration", duration > rules["max_duration_min"],
         lambda h: "duration_min=" + duration[h].round(2).astype(str)),
        ("outlier_fare", (df["fare_amount"] <= rules["fare"][0])
         | (df["fare_amount"] > rules["fare"][1]),
         lambda h: "fare_amount=" + df.loc[h, "fare_amount"].astype(str)),
        ("outlier_distance", (df["trip_distance"] <= rules["distance"][0])
         | (df["trip_distance"] > rules["distance"][1]),
         lambda h: "trip_distance=" + df.loc[h, "trip_distance"].astype(str)),
        ("outlier_passengers", (df["passenger_count"] < rules["passengers"][0])
         | (df["passenger_count"] > rules["passengers"][1]),
         lambda h: "passenger_count=" + df.loc[h, "passenger_count"].astype(str)),
         ("impossible_speed", speed > rules["max_speed_mph"],
          lambda h: "speed_mph=" + speed[h].round(1).astype(str)),
    ]


    keep = pd.Series(True, index=df.index)
    exclusions = []
    for reason, mask, details in checks:
        hit = keep & mask.fillna(False)
        if hit.any():
            exclusions.append((reason, details(hit).str.slice(0, 200)))
            keep &= ~hit
    return df[keep].copy(), exclusions


def add_features(df: pd.DataFrame) -> pd.DataFrame:

    df["passenger_count"] = df["passenger_count"].astype(int)
    df["pickup_zone_id"] = df["pickup_zone_id"].astype(int)
    df["dropoff_zone_id"] = df["dropoff_zone_id"].astype(int)
    df["payment_type"] = df["payment_type"].astype("Int64")

    minutes = (df["dropoff_ts"] - df["pickup_ts"]).dt.total_seconds() / 60
    df["duration_min"] = minutes.round(2)
    df["avg_speed_mph"] = (df["trip_distance"] / (minutes / 60)).round(2)
    df["fare_per_mile"] = (df["fare_amount"] / df["trip_distance"]).round(2)
    tip_pct = (df["tip_amount"] / df["fare_amount"] * 100).clip(0, 100).round(2)
    df["tip_pct"] = tip_pct.where(df["payment_type"] == 1)

    df["pickup_hour"] = df["pickup_ts"].dt.hour
    df["pickup_dow"] = df["pickup_ts"].dt.dayofweek
    df["pickup_date"] = df["pickup_ts"].dt.strftime("%Y-%m-%d")
    df["pickup_ts"] = df["pickup_ts"].dt.strftime("%Y-%m-%d %H:%M:%S")
    df["dropoff_ts"] = df["dropoff_ts"].dt.strftime("%Y-%m-%d %H:%M:%S")
    return df


# ---------load

def load_zones(conn, zones: pd.DataFrame, centroids: dict) -> None:
    """insert all zones with their map centroid (NULL when unknown)."""
    rows = [
        (int(z.zone_id), z.borough, z.zone_name, z.service_zone,
         *centroids.get(int(z.zone_id), (None, None)))
         for z in zones.itertuples(index=False)
    ]
    conn.executemany("INsert INTO zones Values (?, ?, ?, ?, ?, ?)", rows)

def load_trips(conn, df: pd.DataFrame) -> None:

    frame = df[TRIP_COLUMNS].astype(object)
    frame = frame.where(frame.notna(), None)
    rows = frame.values.tolist()
    sql = (f"INSERT INTO trips ({', '.join(TRIP_COLUMNS)}) "
           f"VALUES ({', '.join('?' * len(TRIP_COLUMNS))})")
    for start in range(0, len(rows), INSERT_CHUNK):
        conn.executemany(sql, rows[start:start + INSERT_CHUNK])


def log_exclusions(conn, source: str, exclusions, totals: dict) -> None:

    for reason, details in exclusions:
        already = totals.get(reason, 0)
        totals[reason] = already + len(details)
        room = config.MAX_LOGGED_PER_REASON - already
        if room > 0:
            sample = details.head(room)
            conn.executemany(
                "INSERT INTO exclusion_log (source_file, row_index, reason, details) "
                "VALUES (?, ?, ?, ?)",
                [(source, int(i), reason, text) for i, text in sample.items()],
            )


# --------------- run

def find_file(pattern: str) -> Path | None:

    matches = sorted(config.DATA_DIR.glob(pattern))
    return matches[0] if matches else None

def run_pipeline(trip_file: Path, limit: int | None = None, reset: bool = False) -> dict:

    started = time.time()
    db.init_db(reset=reset)
    period = file_month(trip_file)
    totals, read, kept = {}, 0, 0

    with db.get_connection() as conn:
        conn.execute("PRAGMA synchronous = OFF")
        conn.execute("DELETE FROM trips")
        conn.execute("DELETE FROM exclusion_log")
        conn.execute("DELETE FROM zones")

        zones = read_zones(config.ZONES_CSV)
        load_zones(conn, zones, zone_centroids(find_file(config.GEOJSON_GLOB)))
        valid_ids = set(zones["zone_id"])
        print(f"Loaded {len(zones)} zones")

        for batch in iter_trip_batches(trip_file, limit):
            if period is None: 
                ts = pd.to_datetime(batch["pickup_ts"], errors="coerce")
                period = (int(ts.dt.year.mode()[0]), int(ts.dt.month.mode()[0]))
            clean_df, exclusions = clean(batch, valid_ids, *period)
            load_trips(conn, add_features(clean_df))
            log_exclusions(conn, trip_file.name, exclusions, totals)
            conn.commit()
            read += len(batch)
            kept += len(clean_df)
            print(f" processed {read:,} rows ({kept:,} kept)")

        conn.executemany(
            "INSERT INTO exclusion_log (source_file, row_index, reason, details) "
            "VALUES (?, NULL, ?, ?)",
            [(trip_file.name, f"summary:{r}", str(n)) for r, n in totals.items()],
        )
        conn.commit()

    excluded = read - kept
    print(f"\n{'reason':<24}{'rows':>12}{'% of read' :>12}")
    for reason, count in totals.items():
        print(f"{reason:<24}{count:>12,}{count / max(read, 1) * 100:>11.2f}%")
    print(f"{'-' * 48}\n{'read':<24}{read:>12,}\n{'kept':<24}{kept:>12,}"
          f"\n{'excluded':<24}{excluded:>12,}\nfinished in {time.time() - started:.1f}s")
    return {"zones": len(zones), "read": read, "trips": kept, "excluded": excluded}


def main() -> None:
    parser = argparse.ArgumentParser(description="Load NYC taxi data into SQLite.")
    parser.add_argument("--file", type=Path, help="parquet file (default: first in data/)")
    parser.add_argument("--limit", type=int, help="only process the first N rows")
    parser.add_argument("--reset", action="store_true", help="delete and recreate the DB file")
    args = parser.parse_args()

    trip_file = args.file or find_file(config.TRIPS_GLOB)
    if trip_file is None or not config.ZONES_CSV.exists():
        raise SystemExit(f"Put yellow_tripdata_*.parquet and taxi_zone_lookup.csv in "
                         f"{config.DATA_DIR}")
    run_pipeline(trip_file, args.limit, args.reset)


if __name__ == "__main__":
    main()