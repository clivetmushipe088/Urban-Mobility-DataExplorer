import json
import sys
from pathlib import Path

import shapefile
from pyproj import CRS, Transformer

import config


def reproject(coords, transform):

    if isinstance(coords[0], (int, float)):
        lng, lat = transform(coords[0], coords[1])
        return [round(lng, 5), round(lat, 5)] 
    return [reproject(c, transform) for c in coords]

def convert(source: Path, target: Path) -> int:

    reader = shapefile.Reader(str(source))
    prj = source.with_suffix(".prj")
    if source.suffix == ".zip":
        import zipfile
        with zipfile.ZipFile(source) as zf:
            wkt = zf.read(next(n for n in zf.namelist() if n.endswith(".prj"))).decode()
    else:
        wkt = prj.read_text()
    transform = Transformer.from_crs(CRS.from_wkt(wkt), "EPSG:4326", always_xy=True).transform

    features = []
    for record in reader.shapeRecords():
        props = {k.lower(): v for k, v in record.record.as_dict().items()}
        geometry = record.shape.__geo_interface__
        features.append({
            "type": "Feature",
            "properties": {
                "LocationID": int(props["locationid"]),
                "zone": props.get("zone"),
                "borough": props.get("borough"),
            },
            "geometry": {"type": geometry["type"],
                         "coordinates": reproject(geometry["coordinates"], transform)},
        })

    target.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    return len(features)


if __name__ == "__main__":
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else config.DATA_DIR / "taxi_zones.zip"
    out = config.DATA_DIR / "taxi_zones.geojson"
    count = convert(src, out)
    print(f"Wrote {count} zone shapes to {out}")
