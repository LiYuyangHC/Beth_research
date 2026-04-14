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
        print(f'Failed with response code {response.status_code}')

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
    else:
        print(f'Failed with Exception code: {response.status_code}')


def download_results(order_url, folder, overwrite=False):
    r = requests.get(order_url, auth=(PLANET_API_KEY, ""))
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
                r = requests.get(url, allow_redirects=True)
                path.parent.mkdir(parents=True, exist_ok=True)
                open(path, 'wb').write(r.content)
            else:
                print(f'  already exists, skipping {name}')
    else:
        print(f'Failed with response {r.status_code}')


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
            for i, link in enumerate(left):
                download_results(url_dc[link], dl_path)
                print(f'\tBatch {i} done. Time elapsed: {(time.time() - start) / 60:.2f} min')
        else:
            print('\tAll batches already downloaded.')