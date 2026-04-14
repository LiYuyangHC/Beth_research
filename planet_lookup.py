# Planet API image query before orders and downloads
# Adapted for gauge-site cloud cover study (Beth_research)
#
# Changes from original:
#   - Loads AOI from GeoJSON buffer (generate_aoi.py) instead of shapefile
#   - Removed cloud_cover, haze filters (CLOUD_COVER=1.0 — all images wanted)
#   - Single gauge feature instead of loop over river reaches
#
# Original updates:
# 04-27-2022 - updated for filters
# 10-16-2022 - update for new PSScene API filters
# 03-11-2023 - modify for unit reach lookups, api winter filters, clipping bounds

import os
import sys
import json
import time
import glob
import requests
import numpy as np
import geopandas as gpd
from requests.auth import HTTPBasicAuth
from shapely.geometry import Polygon
from config import *


def authenticate():
    try:
        PLANET_API_KEY = API_KEY
    except Exception as e:
        print("Failed to get Planet Key: Try planet init or install Planet Command line tool")
        sys.exit()

    payload = json.dumps({
        "email": planet_email,
        "password": planet_password
    })

    headers = {'Content-Type': 'application/json'}

    response = requests.post(
        "https://api.planet.com/auth/v1/experimental/public/users/authenticate",
        headers=headers,
        data=payload,
    )
    if response.status_code == 200:
        bearer_token = f"Bearer {response.json()['token']}"
    else:
        sys.exit(f"Failed with status code {response.status_code}")
    return PLANET_API_KEY, payload, headers, response


def search_payload(geom):

    geojson_geometry = {
        "type": "Polygon",
        "coordinates": [geom]
    }

    geometry_filter = {
        "type": "GeometryFilter",
        "field_name": "geometry",
        "config": geojson_geometry
    }

    date_range_filter = {
        "type": "DateRangeFilter",
        "field_name": "acquired",
        "config": {
            "gte": f"{START_DATE}T00:00:00.000Z",
            "lte": f"{END_DATE}T23:59:59.000Z"
        }
    }

    # ── Cloud/haze filters REMOVED for cloud cover study ──────────────
    # Original pipeline filtered to cloud_cover <= 0.1 and haze = 0.
    # For this study we want ALL images regardless of cloud cover.
    # Cloud fraction is computed post-download in compute_cloud_fraction.py

    qual_filter = {
        "type": "StringInFilter",
        "field_name": "quality_category",
        "config": ["standard"]
    }

    pub_filter = {
        "type": "StringInFilter",
        "field_name": "publishing_stage",
        "config": ["finalized"]
    }

    asset_filter = {
        "type": "AssetFilter",
        "config": ["ortho_analytic_4b_sr"]
    }

    perm_filter = {
        "type": "PermissionFilter",
        "config": ["assets:download"]
    }

    combined_filter = {
        "type": "AndFilter",
        "config": [
            geometry_filter,
            date_range_filter,
            qual_filter,
            asset_filter,
            perm_filter
        ]
    }

    search_request = {
        "item_types": ["PSScene"],
        "filter": combined_filter
    }
    return search_request


def yield_features(url, auth, payload):
    page = requests.post(url, auth=auth, data=json.dumps(payload), headers=headers)
    if response.status_code == 200:
        if page.json()['features']:
            for feature in page.json()['features']:
                yield feature

            while True:
                url = page.json()['_links']['_next']
                page = requests.get(url, auth=auth)

                for feature in page.json()['features']:
                    yield feature

                if page.json()['_links'].get('_next') is None:
                    break


def ft_iterate(geom):
    search_json = search_payload(geom)

    all_features = list(
        yield_features('https://api.planet.com/data/v1/quick-search',
                       HTTPBasicAuth(PLANET_API_KEY, ''), search_json))

    for feature in all_features:
        try:
            if True:
                img_bbox = feature['geometry']['coordinates'][0]
                overlap = Polygon(geom).intersection(Polygon(img_bbox)).area / Polygon(geom).area

                # Keep images with at least 10% overlap with AOI
                if overlap >= 0.1:
                    id_master.append(feature['id'])
                    feat.append(feature)
        except Exception as e:
            print(e)


def load_gauge_aoi():
    """
    Load the 1km buffer GeoJSON created by generate_aoi.py.
    Returns a dict with 'fid' and 'bounds' matching original pipeline format.
    """
    with open(aoi_path) as f:
        geojson = json.load(f)

    coords = geojson['coordinates'][0]
    bounds = {
        "type": "Polygon",
        "coordinates": [coords]
    }
    return {'fid': GAUGE_ID, 'bounds': bounds}


def export_reachimgs(out_folder, reach_id, good):
    os.makedirs(f'{out_folder}', exist_ok=True)
    goodfile = f"{out_folder}/{reach_id}.npy"
    np.save(goodfile, good)


if __name__ == "__main__":

    print('Starting...')
    start_time = time.time()
    PLANET_API_KEY, payload, headers, response = authenticate()

    # ── Load gauge AOI (replaces shapefile loop) ──────────────────────
    riv_geom = load_gauge_aoi()
    print(f"[lookup] Gauge: {GAUGE_ID}  |  AOI: {aoi_path}")

    # Check if already done
    done = [os.path.basename(x)[:-4] for x in glob.glob(lookup_path + "/*.npy")]

    if riv_geom['fid'] not in done:
        id_master, feat, good_geom = [], [], {}
        ft_iterate(riv_geom['bounds']['coordinates'][0])
        good_geom[riv_geom['fid']] = {v['id']: v for v in feat}
        good_geom['bounds'] = riv_geom['bounds']
        print(f"\t{GAUGE_ID}: {len(feat)} images found")
        export_reachimgs(lookup_path, riv_geom['fid'], good_geom)
    else:
        print(f'\t{GAUGE_ID}: Already done.')

    print(f'Time elapsed: {(time.time() - start_time) / 60:.2f} min')