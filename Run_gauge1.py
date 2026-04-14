"""
run_gauge1.py
──────────────
Orchestrates the full Planet image extraction pipeline for gauge_1.
Edit GAUGE_ID in config_gauges.py to run a different site.

Steps:
  1. generate_aoi.py            — create 1km buffer GeoJSON
  2. planet_lookup.py           — query Planet API for available scenes
  3. planet_order.py --order    — place order (uses quota!)
  4. check_order_status.py      — poll until order is ready
  5. planet_order.py --download — download scenes
  6. compute_cloud_fraction.py  — compute per-image cloud fraction CSV

Usage:
    # Dry-run: lookup only, no order placed (safe to run anytime)
    python run_gauge1.py --dry-run

    # Full run: place order + download (only when quota is available)
    python run_gauge1.py

⚠️  QUOTA WARNING: Check quota status before placing orders.
    Use --dry-run to test lookup without consuming quota.
"""

import subprocess
import sys
import time
import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--dry-run', action='store_true',
                    help='Run lookup only — no order placed')
args = parser.parse_args()

PIPELINE_DIR = Path(__file__).parent
PYTHON = sys.executable


def run_step(label: str, cmd: list, abort_on_fail: bool = True):
    print(f"\n{'─'*60}")
    print(f"▶  {label}")
    print(f"{'─'*60}")
    result = subprocess.run(cmd, cwd=PIPELINE_DIR)
    if result.returncode != 0:
        print(f"\n✗  FAILED: {label} (exit {result.returncode})")
        if abort_on_fail:
            sys.exit(result.returncode)
        return False
    print(f"✓  Done: {label}")
    return True


def main():
    print("\n" + "═"*60)
    print("  Planet Gauge Image Extraction — Gauge 1 Test Run")
    if args.dry_run:
        print("  MODE: DRY RUN (lookup only, no order placed)")
    print("═"*60)

    run_step("Step 1/6 — Generate 1km buffer AOI",
             [PYTHON, str(PIPELINE_DIR / 'generate_aoi.py')])

    run_step("Step 2/6 — Query Planet API (lookup available scenes)",
             [PYTHON, str(PIPELINE_DIR / 'planet_lookup.py')])

    if args.dry_run:
        print("\n[DRY RUN] Stopping after lookup.")
        print("Review lookup results, then run without --dry-run to order.")
        sys.exit(0)

    print("\n⚠️  About to place a Planet order — this uses quota.")
    print("    Press Ctrl+C within 5 seconds to abort...\n")
    time.sleep(5)

    run_step("Step 3/6 — Place Planet order",
             [PYTHON, str(PIPELINE_DIR / 'planet_order.py'), '--order'])

    run_step("Step 4/6 — Check order status (polls until success)",
             [PYTHON, str(PIPELINE_DIR / 'check_order_status.py')])

    run_step("Step 5/6 — Download images",
             [PYTHON, str(PIPELINE_DIR / 'planet_order.py'), '--download'])

    run_step("Step 6/6 — Compute per-image cloud fraction",
             [PYTHON, str(PIPELINE_DIR / 'compute_cloud_fraction.py')])

    print("\n" + "═"*60)
    print("  ✓  Pipeline complete for gauge_1")
    print("  Check output/metadata/ for the cloud fraction CSV")
    print("═"*60 + "\n")


if __name__ == '__main__':
    main()