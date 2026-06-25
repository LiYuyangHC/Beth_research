# Order and download Planet images based on API image query results
# Adapted for gauge-site cloud cover study (Beth_research)
#
# Changes from original:
#   - config import → config_gauges
#   - Download runs locally (SLURM parallel removed — single gauge, single machine)
#   - feature_id is string (GAUGE_ID) instead of integer reach ID
#
# Original updates:
# 04-30-2022 - batch downloading, functionized
# 11-13-2022 - updated for PSScene4band asset deprecation
# 03-12-2023 - modified for parallel run per unit feature

import os
import glob
import time
import requests
import json
import sys
import pathlib
import numpy as np
import argparse
from shapely.geometry import shape, Polygon, mapping
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from config import *


def authenticate_order():
    try:
        PLANET_API_KEY = API_KEY
    except Exception:
        print("Failed to get Planet Key")
        sys.exit(1)

    headers = {'Content-Type': 'application/json'}

    response = requests.get(
        'https://api.planet.com/compute/ops/orders/v2',
        auth=(PLANET_API_KEY, "")
    )
    if response.status_code == 200:
        print('Setup OK: API key valid')
    else:
        msg = response.text.strip()
        raise RuntimeError(
            f'Planet API key check failed with status {response.status_code}: {msg}'
        )

    return PLANET_API_KEY, headers, response


def order_now(order_payload):
    orders_url = 'https://api.planet.com/compute/ops/orders/v2'
    response = requests.post(
        orders_url,
        data=json.dumps(order_payload),
        auth=(PLANET_API_KEY, ""),
        headers=headers
    )
    if response.status_code == 202:
        order_id = response.json()['id']
        url = f"https://api.planet.com/compute/ops/orders/v2/{order_id}"
        feature_check = requests.get(url, auth=(PLANET_API_KEY, ""))
        if feature_check.status_code == 200:
            print(f"Order URL: {url}")
            return url
        msg = feature_check.text.strip()
        raise RuntimeError(
            f'Planet order was accepted but status lookup failed with '
            f'status {feature_check.status_code}: {msg}'
        )
    else:
        msg = response.text.strip()
        raise RuntimeError(
            f'Planet order failed with status {response.status_code}: {msg}'
        )


def build_download_session():
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        status=5,
        backoff_factor=2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def download_file(session, url, path):
    tmp_path = path.with_suffix(path.suffix + ".part")
    with session.get(url, allow_redirects=True, stream=True, timeout=(20, 120)) as r:
        r.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
    os.replace(tmp_path, path)


def download_results(order_url, folder, overwrite=False, session=None):
    if session is None:
        session = build_download_session()

    r = session.get(order_url, auth=(PLANET_API_KEY, ""), timeout=(20, 120))
    if r.status_code == 200:
        response = r.json()
        results = response['_links']['results']
        results_urls = [r['location'] for r in results]
        results_names = [r['name'] for r in results]
        print(f'{len(results_urls)} items to download')

        for url, name in zip(results_urls, results_names):
            path = pathlib.Path(os.path.join(folder, name))
            if overwrite or not path.exists():
                print(f'  downloading {name}')
                download_file(session, url, path)
                time.sleep(0.2)
            else:
                print(f'  already exists, skipping {name}')
    else:
        msg = r.text.strip()
        raise RuntimeError(f'Failed to read order results {r.status_code}: {msg}')


def order_url(feature_id, ids, json_bound, batchid=0):
    payload = {
        "name": f'{feature_id}_{batchid}',
        "order_type": "partial",
        "notifications": {"email": False},
        "products": [{
            "item_ids": ids,
            "item_type": "PSScene",
            "product_bundle": "analytic_sr_udm2"   # includes UDM2 for cloud fraction
        }],
        "tools": [{
            "clip": {"aoi": json_bound}
        }]
    }
    return order_now(payload)


def riv_lookup(lookup_folder, feature):
    riv = f'{lookup_folder}/{feature}.npy'
    file = np.load(riv, allow_pickle=True).tolist()
    imlist = []
    for key in file.keys():
        if key != 'bounds':
            imlist.append(list(file[key].keys()))
    imlist = [x for y in imlist for x in y]
    riv_bounds = file['bounds']
    if len(riv_bounds['coordinates'][0]) > 500:
        riv_bounds = simplify_bounds(riv_bounds)
    return {'imids': sorted(imlist), 'bounds': riv_bounds}


def simplify_bounds(polygon_dict, target_vertices=450, preserve_topology=True):
    """Simplify polygon to <500 vertices (Planet Order API requirement)."""
    poly = shape(polygon_dict)
    if not isinstance(poly, Polygon):
        raise ValueError("Input geometry must be a single Polygon.")

    def vertex_count(p):
        return max(0, len(p.exterior.coords) - 1)

    if target_vertices >= vertex_count(poly):
        return polygon_dict

    low, high = 0.0, 1e-6
    while vertex_count(poly.simplify(high, preserve_topology=preserve_topology)) > target_vertices and high < 1.0:
        high *= 2

    for _ in range(50):
        mid = (low + high) / 2
        simplified = poly.simplify(mid, preserve_topology=preserve_topology)
        if vertex_count(simplified) > target_vertices:
            low = mid
        else:
            high = mid

    return mapping(poly.simplify(high, preserve_topology=preserve_topology))


def imgs_downloaded(im_path, feature):
    fold = f'{im_path}/{feature}'
    batch = glob.glob(fold + '/*')
    batch = [os.path.basename(x) for x in batch]
    all_imgs = []
    for dl_fold in batch:
        path = f"{fold}/{dl_fold}/PSScene"
        imgs = glob.glob(path + "/*.tif")
        imgs = [x for x in imgs if x[-11:] == 'SR_clip.tif']
        all_imgs.append(imgs)
    return [os.path.basename(x)[:-26] for y in all_imgs for x in y]


if __name__ == "__main__":

    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--order", action='store_true',
                    help="order Planet images")
    ap.add_argument("-d", "--download", action='store_true',
                    help="download Planet images (check order status is 'success' first)")
    args = vars(ap.parse_args())

    PLANET_API_KEY, headers, response = authenticate_order()

    # ── Feature ID is gauge string, e.g. 'gauge_1' ───────────────────
    feature = GAUGE_ID

    if args["order"]:
        start = time.time()
        os.makedirs(order_path, exist_ok=True)

        # Check if already ordered
        urls_done = [os.path.basename(x)[:-5] for x in glob.glob(order_path + "/*.json")]
        if feature in urls_done:
            print(f'{feature}: already ordered.')
            sys.exit(0)

        try:
            riv_info = riv_lookup(lookup_path, feature)
            bounds = riv_info['bounds']
            ids = riv_info['imids']

            # Remove already-downloaded images
            imgs_done = imgs_downloaded(download_path, feature)
            ids = sorted(list(set(ids) - set(imgs_done)))
            print(f'\nOrdering {len(ids)} images for {feature}')

            if len(ids) == 0:
                print('\tNo images to order — all already downloaded.')
                sys.exit(0)

            # Batch if >450 images (Planet API limit per order)
            if len(ids) > 450:
                order_urls = []
                nbatch = int(np.ceil(len(ids) / 450))
                for batch in range(nbatch):
                    ids_batch = ids[batch * 450:450 * (batch + 1)]
                    print(f'\n  Batch {batch}: {len(ids_batch)} images')
                    order_urls.append(order_url(feature, ids_batch, bounds, batch))
            else:
                order_urls = [order_url(feature, ids, bounds)]

            with open(f'{order_path}/{feature}.json', 'w') as f:
                json.dump(order_urls, f)

            print(f'\nOrder placed. Time elapsed: {(time.time() - start) / 60:.2f} min')

        except Exception as e:
            print(f'Error ordering {feature}: {e}')

    elif args["download"]:
        start = time.time()

        # ── SLURM removed: runs directly on local machine ─────────────
        print(f'\nDownloading images for {feature}...')
        dl_path = f'{download_path}/{feature}'
        os.makedirs(dl_path, exist_ok=True)

        urlp = f'{order_path}/{feature}.json'
        if not os.path.exists(urlp):
            print(f'No order file found at {urlp}. Run --order first.')
            sys.exit(1)

        with open(urlp, 'r') as f:
            urls = json.load(f)

        url_dc = {}
        for url in urls:
            url_dc[url[45:]] = url

        dl_done = [os.path.basename(x) for x in glob.glob(dl_path + "/*")]
        left = list(set(list(url_dc.keys())) - set(dl_done))

        if len(left) > 0:
            with build_download_session() as session:
                for i, link in enumerate(left):
                    download_results(url_dc[link], dl_path, session=session)
                    print(f'\tBatch {i} done. Time elapsed: {(time.time() - start) / 60:.2f} min')
        else:
            print('\tAll batches already downloaded.')
