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

Planet download folder structure:
  download_path/gauge_1/batch_id/PSScene/
    ├── 20260101_164834_10_24f6_3B_AnalyticMS_SR_clip.tif
    ├── 20260101_164834_10_24f6_3B_udm2_clip.tif
    ├── 20260101_164834_10_24f6_metadata.json
    └── ...

Run after downloading images:
    python compute_cloud_fraction.py

Requires: rasterio, numpy, pandas, shapely
    pip install rasterio numpy pandas shapely
"""

import json
import numpy as np
import pandas as pd
import rasterio
import rasterio.mask
from rasterio.warp import transform_geom
from datetime import datetime
from pathlib import Path
from shapely.geometry import mapping, shape

import config as cfg

# UDM2 band indices (1-based, as in rasterio)
# Planet UDM2 band layout:
#   1: clear  2: snow  3: shadow  4: light haze  5: heavy haze  6: cloud
UDM2_SHADOW_BAND = 3
UDM2_LIGHT_HAZE_BAND = 4
UDM2_CLOUD_BAND  = 6
UDM2_CIRRUS_BAND = 5  # heavy haze — closest to Landsat cirrus

# Beth's Landsat code uses shadow + cloud + cirrus. Planet has heavy haze
# rather than cirrus, so heavy haze is included by default as the closest
# equivalent. Light haze is left off by default to stay closer to that logic;
# set this to True for a stricter "any haze/cloud impairment" sensitivity test.
INCLUDE_LIGHT_HAZE = True


def load_aoi_geometry():
    with open(cfg.aoi_path) as f:
        return shape(json.load(f))


def geometry_for_dataset(dataset, aoi_geom):
    geom = mapping(aoi_geom)
    if dataset.crs:
        return transform_geom('EPSG:4326', dataset.crs, geom)
    return geom


def read_masked_band(dataset, aoi_geom, band_index: int, dataset_geom=None):
    geom = dataset_geom or geometry_for_dataset(dataset, aoi_geom)
    band = rasterio.mask.mask(
        dataset, [geom], crop=True,
        indexes=band_index, filled=True
    )[0]
    if band.ndim == 3:
        return band[0]
    return band


def compute_cloud_fraction_for_scene(udm2_path: Path, aoi_geom) -> float:
    try:
        # Find matching SR image
        sr_files = list(udm2_path.parent.glob(
            udm2_path.name.replace('_udm2_clip.tif', '_AnalyticMS_SR_clip.tif')
        ))
        
        with rasterio.open(udm2_path) as src:
            udm2_geom = geometry_for_dataset(src, aoi_geom)
            shadow = read_masked_band(
                src, aoi_geom, UDM2_SHADOW_BAND, dataset_geom=udm2_geom
            )
            cirrus = read_masked_band(
                src, aoi_geom, UDM2_CIRRUS_BAND, dataset_geom=udm2_geom
            )
            light_haze = read_masked_band(
                src, aoi_geom, UDM2_LIGHT_HAZE_BAND, dataset_geom=udm2_geom
            )
            cloud = read_masked_band(
                src, aoi_geom, UDM2_CLOUD_BAND, dataset_geom=udm2_geom
            )

        # Use SR image to determine valid pixels (not blackfill corners)
        if sr_files:
            with rasterio.open(sr_files[0]) as sr_src:
                sr_geom = geometry_for_dataset(sr_src, aoi_geom)
                sr_band = read_masked_band(
                    sr_src, aoi_geom, 1, dataset_geom=sr_geom
                )
            valid = (sr_band != 0)  # 0 = nodata corners in SR
        else:
            # Fallback: use Band 1 clear + cloud flags
            with rasterio.open(udm2_path) as src:
                udm2_geom = geometry_for_dataset(src, aoi_geom)
                clear = read_masked_band(
                    src, aoi_geom, 1, dataset_geom=udm2_geom
                )
            valid = (clear == 1) | (shadow == 1) | (cirrus == 1) | (cloud == 1)
            if INCLUDE_LIGHT_HAZE:
                valid = valid | (light_haze == 1)

        n_valid = valid.sum()
        if n_valid == 0:
            return float('nan')

        cloudy = (shadow == 1) | (cirrus == 1) | (cloud == 1)
        if INCLUDE_LIGHT_HAZE:
            cloudy = cloudy | (light_haze == 1)
        cloudy = cloudy & valid
        return float(cloudy.sum()) / float(n_valid)

    except Exception as e:
        print(f"  [WARN] Could not process {udm2_path.name}: {e}")
        return float('nan')


def find_psscene_folders(download_dir: Path):
    """
    Find all PSScene folders within the download directory.
    Planet structure: download_path / gauge_id / batch_id / PSScene / *.tif
    """
    return sorted(download_dir.rglob('PSScene'))


def extract_scene_id(filename: str) -> str:
    """
    Extract scene ID from Planet filename.
    e.g. '20260101_164834_10_24f6_3B_udm2_clip.tif' → '20260101_164834_10_24f6'
    """
    for suffix in (
        '_3B_udm2_clip.tif',
        '_udm2_clip.tif',
        '_3B_udm2.tif',
        '_udm2.tif',
    ):
        if filename.endswith(suffix):
            return filename[:-len(suffix)]
    return Path(filename).stem


def parse_scene_id_time(scene_id: str) -> str | None:
    """
    Recover acquisition time from Planet scene IDs that start with
    YYYYMMDD_HHMMSS.
    """
    parts = scene_id.split('_')
    if len(parts) < 2:
        return None
    try:
        return datetime.strptime(
            f'{parts[0]}_{parts[1]}', '%Y%m%d_%H%M%S'
        ).strftime('%Y-%m-%d %H:%M:%S')
    except ValueError:
        return None


def parse_scene_id_satellite(scene_id: str) -> str | None:
    """Recover the satellite/platform token from the end of a scene ID."""
    parts = scene_id.split('_')
    if len(parts) >= 3:
        return parts[-1]
    return None


def read_scene_metadata(ps_dir: Path, scene_id: str):
    """Return acquisition time and satellite id for a scene."""
    time_str = parse_scene_id_time(scene_id)
    satellite = parse_scene_id_satellite(scene_id)

    meta_files = list(ps_dir.glob(f'{scene_id}_metadata.json'))
    if not meta_files:
        meta_files = [
            p for p in ps_dir.glob(f'{scene_id}*_metadata.json')
            if 'AnalyticMS' not in p.name
        ]

    if meta_files:
        try:
            with open(meta_files[0]) as f:
                meta = json.load(f)
            props = meta.get('properties', {})
            acquired = props.get('acquired')
            if acquired:
                time_str = acquired[:19].replace('T', ' ')
            satellite = props.get('satellite_id') or satellite or 'unknown'
        except Exception as e:
            print(f"  [WARN] Could not read metadata for {scene_id}: {e}")

    return time_str, satellite


def run():
    download_dir = Path(cfg.download_path)
    aoi_geom = load_aoi_geometry()

    # Find all PSScene folders
    psscene_dirs = find_psscene_folders(download_dir)
    if not psscene_dirs:
        print(f"[cloud_fraction] No PSScene folders found in {download_dir}")
        print(f"  Check that images have been downloaded.")
        return

    # Collect all UDM2 files across all PSScene folders
    udm2_files = []
    for ps_dir in psscene_dirs:
        udm2_files.extend(sorted(ps_dir.glob('*_udm2_clip.tif')))

    print(f"[cloud_fraction] Found {len(udm2_files)} UDM2 files across "
          f"{len(psscene_dirs)} PSScene folder(s)")

    records = []
    for udm2_path in udm2_files:
        scene_id = extract_scene_id(udm2_path.name)
        ps_dir = udm2_path.parent

        # Compute cloud fraction
        cf = compute_cloud_fraction_for_scene(udm2_path, aoi_geom)

        # Find matching metadata JSON. If unavailable, fall back to the Planet
        # scene ID so time and satellite are not left blank.
        time_str, satellite = read_scene_metadata(ps_dir, scene_id)

        records.append({
            'time':               time_str,
            'cloud_fraction_1km': round(cf, 6) if not np.isnan(cf) else '',
            'satellite':          satellite,
            'image_id':           scene_id,
            'scene_path':         str(ps_dir)
        })

        # Progress
        if not np.isnan(cf):
            print(f"  {scene_id}: cloud_fraction={cf:.3f}")
        else:
            print(f"  {scene_id}: cloud_fraction=NaN")

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
