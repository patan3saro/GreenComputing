"""
Prefetch all SUMO mobility caches sequentially.

Run this ONCE before launching the parallel sweep, to avoid Overpass API
rate-limiting (HTTP 429). After this script finishes, every (num_vehicles,
seed) combination has a fully populated cache directory, and simulations.py
will load it without ever touching the network.

Usage:
    python prefetch_maps.py                 # default: density sweep coverage
    python prefetch_maps.py --seeds 40      # paper full seeds
    python prefetch_maps.py --check         # show cache status, don't fetch
"""

import argparse
import os
import sys
import time
from pathlib import Path

from config import CITY, CITY_BBOX
from mobility_manager import extract_city_traffic


VEHICLE_SET = [10, 20, 30, 40, 60, 80, 100, 150, 200]


def fetch_one(num_vehicles, seed):
    """Build the cache for one (num_vehicles, seed) pair."""
    out_dir, df = extract_city_traffic(
        random_seed=seed,
        city_name=CITY, country_code="it",
        bbox=CITY_BBOX,
        simulation_time=2.5,
        time_step=0.1,
        num_vehicles=num_vehicles,
    )
    return out_dir, df is not None and not df.empty


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=40,
                        help="Number of seeds to prefetch (1..N).")
    parser.add_argument("--vehicles", type=str, default=None,
                        help="Comma-separated vehicle counts. Default: 10,20,30,40,60,80,100,150,200")
    parser.add_argument("--check", action="store_true",
                        help="Only check which caches exist; do not fetch.")
    parser.add_argument("--retry-delay", type=float, default=15.0,
                        help="Sleep seconds after a 429 before retrying (default 15).")
    args = parser.parse_args()

    if args.vehicles:
        vehicle_set = [int(x) for x in args.vehicles.split(",")]
    else:
        vehicle_set = VEHICLE_SET

    seeds = list(range(1, args.seeds + 1))
    total = len(vehicle_set) * len(seeds)

    print(f"[prefetch] coverage: {len(vehicle_set)} vehicle counts x {len(seeds)} seeds = {total} caches")

    ok = 0
    missing = []
    fetched = 0
    skipped = 0
    failures = []

    t0 = time.time()
    for vi, nv in enumerate(vehicle_set):
        for si, sd in enumerate(seeds):
            idx = vi * len(seeds) + si + 1
            cache_dir = Path(
                f"sumo_rome_bb{CITY_BBOX[0]}_{CITY_BBOX[1]}_{CITY_BBOX[2]}_{CITY_BBOX[3]}"
                f"_v{nv}_s{sd}"
            )
            cache_file = cache_dir / "vehicle_data.csv"

            if cache_file.exists():
                ok += 1
                skipped += 1
                if idx % 20 == 0:
                    print(f"  [{idx}/{total}] cached ({skipped} skipped, {fetched} fetched, {len(failures)} failed)")
                continue

            if args.check:
                missing.append((nv, sd))
                continue

            attempts = 0
            success = False
            while attempts < 3 and not success:
                attempts += 1
                try:
                    out_dir, success = fetch_one(nv, sd)
                    if success:
                        ok += 1
                        fetched += 1
                    else:
                        # Returned empty df but no exception: likely a download miss
                        time.sleep(args.retry_delay)
                except Exception as exc:
                    msg = str(exc)
                    if "429" in msg or "Too Many Requests" in msg:
                        print(f"  [{idx}/{total}] rate-limited, sleeping {args.retry_delay}s")
                        time.sleep(args.retry_delay)
                    else:
                        print(f"  [{idx}/{total}] error for v={nv} s={sd}: {msg}")
                        time.sleep(2)
            if not success:
                failures.append((nv, sd))
                print(f"  [{idx}/{total}] FAILED v={nv} s={sd} after 3 attempts")
            elif fetched % 5 == 0 or idx == total:
                elapsed = time.time() - t0
                rate = fetched / elapsed if elapsed > 0 else 0
                eta = (total - idx) / rate if rate > 0 else 0
                print(f"  [{idx}/{total}] fetched v={nv} s={sd} "
                      f"({rate:.2f}/s, ETA {eta/60:.1f} min)")

    if args.check:
        print(f"\n[check] {ok}/{total} cached, {len(missing)} missing")
        if missing:
            print("Missing:")
            for nv, sd in missing[:30]:
                print(f"   v={nv} s={sd}")
            if len(missing) > 30:
                print(f"   ... ({len(missing)-30} more)")
        return

    elapsed = time.time() - t0
    print(f"\n[prefetch done] {ok}/{total} caches ready "
          f"({skipped} skipped, {fetched} fetched, {len(failures)} failed) "
          f"in {elapsed/60:.1f} min")
    if failures:
        print("FAILED (rerun the prefetch later for these):")
        for nv, sd in failures:
            print(f"   v={nv} s={sd}")
        sys.exit(1)


if __name__ == "__main__":
    main()