import os
from pathlib import Path
from datetime import date

#PlanetAPI auth
API_KEY = 'xxxxxxxxxxxxxxxxxxxxxxxxx' # place your Planet API key
planet_email = 'xxxxxxxxxxxxxxxxxx.com' #place your Planet email
planet_password = 'xxxxxxxxxxxxxxxxxxxxxxxxx' #place your Planet password

# ── Gauge site selection ────────────────────────────
# Change GAUGE_ID to match a row in gauges.csv
# Options: 'gauge_1' through 'gauge_10'
GAUGE_ID = 'gauge_1'
 
# Path to the gauges CSV
BASE_PATH = Path(os.environ.get("OneDrive", ""))
if not BASE_PATH:
    raise EnvironmentError("OneDrive environment variable not found")
GAUGES_CSV = BASE_PATH / 'classmaterials' / 'BLab_research_data' / 'Beth research data' / 'Gauges.csv' 
 
# Buffer radius in metres around the gauge point
BUFFER_RADIUS_M = 1000  # 1 km — matches GEE logic
 
# ── Date range ──────────────────────────────────────
# Planet archive starts ~April 2016; end = today
START_DATE = '2016-01-01'
END_DATE   = date.today().strftime('%Y-%m-%d')
 
# ── Cloud cover ─────────────────────────────────────
# Set to 1.0 (100%) to retrieve ALL images for cloud cover study.
# Per-image cloud fraction is computed in compute_cloud_fraction.py.
CLOUD_COVER = 1.0  # 100% — matches GEE logic
 
# ── Item / asset type ───────────────────────────────
ITEM_TYPE  = 'PSScene'
ASSET_TYPE = 'ortho_analytic_4b_sr'   # Surface reflectance, 4-band
 
# ── Run naming (auto-generated from gauge + date) ───
run = f'{GAUGE_ID}_planet_lookup_{date.today().strftime("%Y_%m_%d")}'
 
# ── Output paths ────────────────────────────────────
LOCAL_OUTPUT = Path(r"H:\Research_PhD\Beth_research")
 
aoi_path      = str(LOCAL_OUTPUT / "data" / "aoi" / f"{GAUGE_ID}_1km_buffer.geojson")
lookup_path   = str(LOCAL_OUTPUT / "output" / "lookup"   / run)
order_path    = str(LOCAL_OUTPUT / "output" / "order"    / run)
download_path = str(LOCAL_OUTPUT / "output" / "imgs"     / run)
metadata_path = str(LOCAL_OUTPUT / "output" / "metadata" / run)