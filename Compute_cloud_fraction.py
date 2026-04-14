"""
compute_cloud_fraction.py
──────────────────────────
Computes per-image cloud fraction over a 1km gauge buffer
using Planet's UDM2 (Usable Data Mask) asset.

Mirrors the GEE logic from GEE_L89_gaugeexport_cc.txt:
  - shadow (QA_PIXEL bit 3)  →  UDM2 band 3 (shadow)
  - cloud  (QA_PIXEL bit 5)  →  UDM2 band 6 (cloud)
  - cirrus (QA_PIXEL bit 7)  →  UDM2 band 5 (heavy haze, closest equivalent)

Output CSV columns match GEE export:
  time, cloud_fraction_1km, satellite, image_id, scene_path

Run after downloading images:
    python compute_cloud_fraction.py

Requires: rasterio, numpy, pandas, shapely, geopandas
    pip install rasterio numpy pandas shapely geopandas
"""

import json
import numpy as np
import pandas as pd
import rasterio
import rasterio.mask
from pathlib import Path
from shapely.geometry import shape

import config as cfg

# UDM2 band indices (1-based, as in rasterio)
# Planet UDM2 band layout:
#   1: clear  2: snow  3: shadow  4: light haze  5: heavy haze  6: cloud
UDM2_SHADOW_BAND = 3
UDM2_CLOUD_BAND  = 6
UDM2_CIRRUS_BAND = 5  # heavy haze — closest to Landsat cirrus


def load_aoi_geometry():
    with open(cfg.aoi_path) as f:
        return shape(json.load(f))


def compute_cloud_fraction_for_scene(udm2_path: Path, aoi_geom) -> float:
    """
    Returns fraction of pixels flagged as shadow, cloud, or cirrus/haze
    within the AOI. Returns NaN if the file cannot be read.
    """
    try:
        with rasterio.open(udm2_path) as src:
            def masked(band):
                data, _ = rasterio.mask.mask(
                    src, [aoi_geom.__geo_interface__],
                    crop=True, indexes=band, nodata=255
                )
                return data

            shadow = masked(UDM2_SHADOW_BAND)
            cloud  = masked(UDM2_CLOUD_BAND)
            cirrus = masked(UDM2_CIRRUS_BAND)

        valid = shadow != 255
        n_valid = valid.sum()
        if n_valid == 0:
            return float('nan')

        cloudy = ((shadow == 1) | (cloud == 1) | (cirrus == 1)) & valid
        return float(cloudy.sum()) / float(n_valid)

    except Exception as e:
        print(f"  [WARN] Could not process {udm2_path.name}: {e}")
        return float('nan')


def parse_scene_metadata(scene_dir: Path):
    """Extract acquisition time and satellite ID from Planet metadata JSON."""
    meta_files = list(scene_dir.glob('*_metadata.json'))
    if not meta_files:
        return None, None
    with open(meta_files[0]) as f:
        meta = json.load(f)
    props = meta.get('properties', {})
    acquired = props.get('acquired', '')[:19].replace('T', ' ')
    satellite = props.get('satellite_id', 'unknown')
    return acquired, satellite


def run():
    download_dir = Path(cfg.download_path)
    aoi_geom = load_aoi_geometry()

    scene_dirs = sorted([d for d in download_dir.iterdir() if d.is_dir()])
    print(f"[cloud_fraction] Found {len(scene_dirs)} scene folders in {download_dir}")

    records = []
    for scene_dir in scene_dirs:
        scene_id = scene_dir.name
        udm2_files = list(scene_dir.glob('*_udm2.tif'))
        if not udm2_files:
            print(f"  [SKIP] No UDM2 found in {scene_id}")
            continue

        cf = compute_cloud_fraction_for_scene(udm2_files[0], aoi_geom)
        time_str, satellite = parse_scene_metadata(scene_dir)

        records.append({
            'time':               time_str,
            'cloud_fraction_1km': round(cf, 6) if not np.isnan(cf) else '',
            'satellite':          satellite,
            'image_id':           scene_id,
            'scene_path':         str(scene_dir)
        })

    # ── Save CSV ──────────────────────────────────────────
    out_dir = Path(cfg.metadata_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_csv = out_dir / f'{cfg.GAUGE_ID}_cloud_fraction.csv'

    df = pd.DataFrame(records, columns=[
        'time', 'cloud_fraction_1km', 'satellite', 'image_id', 'scene_path'
    ])
    df.to_csv(out_csv, index=False)

    print(f"\n[cloud_fraction] Done. {len(df)} scenes processed.")
    print(f"[cloud_fraction] Output → {out_csv}")

    valid = df['cloud_fraction_1km'].replace('', np.nan).dropna().astype(float)
    if len(valid):
        print(f"[cloud_fraction] Stats:  mean={valid.mean():.3f}  "
              f"min={valid.min():.3f}  max={valid.max():.3f}  n={len(valid)}")


if __name__ == '__main__':
    run()