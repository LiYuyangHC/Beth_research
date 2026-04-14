"""
generate_aoi.py
───────────────
Reads gauges.csv, picks the gauge specified in config_gauges.py,
buffers it by BUFFER_RADIUS_M (default 1 km), and saves a GeoJSON
that the Planet pipeline uses as its AOI.

Run once per gauge before planet_lookup.py:
    python generate_aoi.py

Requires: geopandas, shapely
    pip install geopandas shapely
"""

import json
import pandas as pd
from pathlib import Path
from shapely.geometry import Point
import geopandas as gpd

import config as cfg


def generate_aoi():
    # ── Load gauge table ────────────────────────────────
    gauges = pd.read_csv(cfg.GAUGES_CSV)
    row = gauges[gauges['gauge_id'] == cfg.GAUGE_ID]

    if row.empty:
        raise ValueError(
            f"Gauge '{cfg.GAUGE_ID}' not found in {cfg.GAUGES_CSV}. "
            f"Available: {gauges['gauge_id'].tolist()}"
        )

    lon = float(row['lon'].values[0])
    lat = float(row['lat'].values[0])
    print(f"[generate_aoi] Gauge: {cfg.GAUGE_ID}  |  lon={lon}, lat={lat}")

    # ── Buffer in metres (project → buffer → reproject back) ────
    point_gdf = gpd.GeoDataFrame(
        {'gauge_id': [cfg.GAUGE_ID]},
        geometry=[Point(lon, lat)],
        crs='EPSG:4326'
    )

    utm_zone = int((lon + 180) / 6) + 1
    hemisphere = 'north' if lat >= 0 else 'south'
    utm_crs = f'+proj=utm +zone={utm_zone} +{hemisphere} +datum=WGS84 +units=m +no_defs'

    buffer_wgs84 = (
        point_gdf
        .to_crs(utm_crs)
        .assign(geometry=lambda gdf: gdf.geometry.buffer(cfg.BUFFER_RADIUS_M))
        .to_crs('EPSG:4326')
    )

    # ── Save GeoJSON ─────────────────────────────────────
    out_path = Path(cfg.aoi_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    geom = buffer_wgs84.geometry.values[0]
    geojson_dict = {
        "type": "Polygon",
        "coordinates": [list(geom.exterior.coords)]
    }

    with open(out_path, 'w') as f:
        json.dump(geojson_dict, f, indent=2)

    area_km2 = buffer_wgs84.to_crs(utm_crs).geometry.area.values[0] / 1e6
    print(f"[generate_aoi] AOI saved  → {out_path}")
    print(f"[generate_aoi] Area: {area_km2:.2f} km²  (should be ~3.14 km²)")
    return str(out_path)


if __name__ == '__main__':
    generate_aoi()