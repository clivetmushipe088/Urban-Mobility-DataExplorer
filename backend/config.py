from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = BASE_DIR / "database" / "citypulse.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

ZONES_CSV = DATA_DIR / "taxi_zone_lookup.csv"
TRIPS_GLOB = "yellow_tripdata_*.parquet"
GEOJSON_GLOB = "taxi_zones*.*json"

CLEAN_RULES = {
    "fare": (0, 500),
    "distance": (0, 100),
    "passengers": (1, 6),
    "max_duration_min": 360,
    "max_speed_mph": 80,
}
UNKNOWN_ZONE_IDS = (264, 265)

MAX_LOGGED_PER_REASON = 50_000
BATCH_SIZE = 250_000
SAMPLE_RATE = 0.20
SAMPLE_SPEED = 42

DEFAULT_PER_PAGE = 50
MAX_PER_PAGE = 500