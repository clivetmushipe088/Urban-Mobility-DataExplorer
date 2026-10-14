CREATE TABLE IF NOT EXISTS zones (
    zone_id INTEGER PRIMARY KEY,
    borough TEXT NOT NULL,
    zone_name TEXT NOT NULL,
    service_zone TEXT,
    centroid_lat REAL,
    centroid_log REAL
);

CREATE TABLE IF NOT EXISTS trips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pickup_ts TEXT NOT NULL,
    dropoff_ts TEXT NOT NULL,
    passenger_count INTEGER NOT NULL,
    trip_distance REAL NOT NULL,
    pickup_zone_id INTEGER NOT NULL REFERENCES zones(zone_id),
    dropoff_zone_id INTEGER NOT NULL REFERENCES zones(zone_id),
    payment_type INTEGER,
    fare_amount REAL NOT NULL,
    tip_amount REAL NOT NULL,
    total_amount REAL NOT NULL,
    -- derived features
    duration_min REAL NOT NULL,
    avg_speed_mph REAL NOT NULL,
    fare_per_mile REAL NOT NULL,
    tip_pct REAL,
    -- stored for fast grouping/filtering
    pickup_hour INTEGER NOT NULL,
    pickup_dow INTEGER NOT NULL,
    pickup_date TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS exclusion_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file TEXT NOT NULL,
    row_index INTEGER,
    reason TEXT NOT NULL,
    details TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_trips_pickup_ts ON trips(pickup_ts);
CREATE INDEX IF NOT EXISTS idx_trips_pickup_zone ON trips(pickup_zone_id);
CREATE INDEX IF NOT EXISTS idx_trips_dropoff_zone ON trips(dropoff_zone_id);
CREATE INDEX IF NOT EXISTS idx_trips_pickup_date ON trips(pickup_date);
CREATE INDEX IF NOT EXISTS idx_trips_pickup_hour ON trips(pickup_hour);
CREATE INDEX IF NOT EXISTS idx_trips_fare ON trips(fare_amount);
CREATE INDEX IF NOT EXISTS idx_excl_reason ON exclusion_log(reason);

