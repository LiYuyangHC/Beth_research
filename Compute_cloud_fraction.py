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
    try:
        with rasterio.open(udm2_path) as src:
            shadow = src.read(3)
            cloud  = src.read(6)
            cirrus = src.read(5)  # heavy haze
            clear  = src.read(1)

        # Valid = any pixel that has data (clear=1 OR any flag set)
        # Exclude pixels where all bands are 0 (no data)
        valid = (clear == 1) | (shadow == 1) | (cloud == 1) | (cirrus == 1)
        n_valid = valid.sum()
        if n_valid == 0:
            return float('nan')

        cloudy = (shadow == 1) | (cloud == 1) | (cirrus == 1)
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
    parts = filename.split('_')
    if len(parts) >= 4:
        return '_'.join(parts[:4])
    return filename


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

        # Find matching metadata JSON
        meta_files = list(ps_dir.glob(f'{scene_id}_metadata.json'))
        time_str, satellite = None, None
        if meta_files:
            try:
                with open(meta_files[0]) as f:
                    meta = json.load(f)
                props = meta.get('properties', {})
                time_str = props.get('acquired', '')[:19].replace('T', ' ')
                satellite = props.get('satellite_id', 'unknown')
            except Exception as e:
                print(f"  [WARN] Could not read metadata for {scene_id}: {e}")

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