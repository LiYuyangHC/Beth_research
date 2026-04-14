# Beth_research — PlanetScope Cloud Cover Study

PlanetScope image extraction pipeline for 10 gauge sites in NC/VA.
Extracts all available images (2016–present) and computes per-image
cloud fraction to mirror the GEE Landsat cloud cover analysis.

---

## Folder Structure

```
Beth_research/
├── config_gauges.py          ← ⚙️  Edit this first (API key + gauge selection)
├── gauges.csv                ← 10 gauge site coordinates
├── generate_aoi.py           ← creates 1km buffer GeoJSON around gauge
├── compute_cloud_fraction.py ← computes cloud fraction from UDM2 masks
├── run_gauge1.py             ← runs the full pipeline for one gauge
│
│   (copied from original pipeline)
├── planet_lookup.py          ← queries Planet API for available scenes
├── planet_order.py           ← places orders and downloads
├── check_order_status.py     ← polls order until ready
│
└── output/
    ├── lookup/               ← scene metadata from API query
    ├── order/                ← order URLs
    ├── imgs/                 ← downloaded scene folders
    └── metadata/             ← ⭐ cloud fraction CSVs (main output)
```

---

## Quick Start

### 1. Install dependencies
```bash
pip install geopandas shapely rasterio numpy pandas requests
```

### 2. Edit `config.py`
```python
API_KEY      = 'your-planet-api-key-here'   # get from planet.com
planet_email = 'your@email.com'
GAUGE_ID     = 'gauge_1'                    # change to run other gauges
LOCAL_OUTPUT = Path(r"C:\your\path\here")   # update to your machine's path
```

### 3. Test with a dry run (no quota used)
```bash
python run_gauge1.py --dry-run
```

### 4. Full run (place order + download)
```bash
python run_gauge1.py
```

---

## Output

Each gauge produces a CSV in `output/metadata/` with these columns:

| Column | Description |
|--------|-------------|
| `time` | Scene acquisition datetime (YYYY-MM-DD HH:MM:SS) |
| `cloud_fraction_1km` | Fraction of pixels flagged as cloud/shadow/cirrus (0–1) |
| `satellite` | Planet satellite ID |
| `image_id` | Planet scene ID |
| `scene_path` | Local path to downloaded scene folder |

This matches the column structure of the GEE Landsat export
(`GEE_L89_gaugeexport_cc.txt`) for direct comparison.

---

## Cloud Fraction Method

Mirrors GEE `QA_PIXEL` logic using Planet's **UDM2** mask:

| GEE QA_PIXEL bit | Planet UDM2 band |
|-----------------|-----------------|
| Bit 3 — shadow  | Band 3 — shadow |
| Bit 5 — cloud   | Band 6 — cloud  |
| Bit 7 — cirrus  | Band 5 — heavy haze |

All images are downloaded regardless of cloud cover (`CLOUD_COVER = 1.0`).
Cloud fraction is computed post-download from the UDM2 asset.

---

## Gauge Sites

| ID | Longitude | Latitude |
|----|-----------|----------|
| gauge_1 | -79.493889 | 35.061111 |
| gauge_2 | -78.293611 | 34.404444 |
| gauge_3 | -78.548333 | 34.095000 |
| gauge_4 | -81.406944 | 36.393333 |
| gauge_5 | -82.405278 | 35.653056 |
| gauge_6 | -83.618611 | 35.127500 |
| gauge_7 | -77.025556 | 36.370833 |
| gauge_8 | -77.372778 | 35.616667 |
| gauge_9 | -78.674167 | 35.838056 |
| gauge_10 | -79.782500 | 36.097778 |

---

## Notes

- Planet quota is **3,000 km²/month** on standard plan. Each 1km gauge
  buffer is ~3.14 km², so 10 gauges ≈ 31.4 km² per order — well within
  monthly quota once it resets.
- For large multi-year pulls, consider applying for
  **NASA CSDA access**: https://csdap.earthdata.nasa.gov
- Never commit `config_gauges.py` to GitHub (contains API key).