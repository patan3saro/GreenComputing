"""
Parallelized sweep runner for the VCC simulator (alternative entry point to
comparison_strategies.py, organized by sweep rather than by strategy).

Usage:
    python3 simulations.py --sweep density   --workers 16
    python3 simulations.py --sweep all       --workers 16
    python3 simulations.py --dry-run

Each simulation is CPU-bound (ILP via PuLP/CBC plus the SUMO mobility
cache); use workers ~= min(physical_cores - 1, RAM_GB / 2). Outputs land
under results/<sweep_name>/<param>=<val>/seed=<seed>/.
"""

import argparse
import json
import multiprocessing as mp
import os
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from main import Simulator


# ----------------------------------------------------------------------
# Sweep definitions — targeted to the 4 paper figures (see research_report.md).
#
# Each sweep is sized so that the resulting summary.json + allocations.jsonl
# + realizations.jsonl carry exactly the data needed by `make_figures.py`
# for one figure. Running all four covers the four contributions of
# Sec. 4 of the report.
# ----------------------------------------------------------------------
SEEDS_FULL = list(range(1, 41))            # 40 seeds for production figures
SEEDS_QUICK = list(range(1, 11))           # 10 seeds for sanity / fast iteration

# ----- Fig. 1 — ex-ante / ex-post realization gap -----
# We need (Stage 1 obj, Stage 2 realized) pairs across a wide regime of
# operating points, with DRO ON and DRO OFF so the two regression lines
# can be compared on the same scatter. Density and rate vary to spread
# the points over the (low utility .. high utility) range.
SWEEP_GAP = {
    "name": "gap",
    "factors": {
        "dro_enabled": [True, False],
        "num_vehicles": [20, 50, 100, 150, 200],
        "task_rate": [10],
    },
    "seeds": SEEDS_FULL,
}

# ----- Fig. 2 — feasibility frontier across SLA tiers -----
# We need success rate as a function of (num_vehicles, tier_deadline).
# Tier is implicit in the task distribution (we already sample tasks
# from POSSIBLE_TASK_TYPES (16,100,500) with equal prob), so we just
# vary num_vehicles fine-grained and let make_figures.py stratify the
# allocations.jsonl by tier when plotting.
SWEEP_DENSITY = {
    "name": "density",
    "factors": {
        "task_rate": [10, 1],
        "num_vehicles": [10, 20, 30, 40, 60, 80, 100, 150, 200],
    },
    "seeds": SEEDS_FULL,
}

# ----- Fig. 3 — monetary value of DRO under misreporting -----
# We need the (revenue vs rho) curve with and without DRO, at a fixed
# density that is in the "VCC works" regime (so the comparison is fair).
SWEEP_MISREPORT_DRO = {
    "name": "misreport_dro",
    "factors": {
        "misreporting_fraction": [0.0, 0.1, 0.2, 0.3],
        "dro_enabled": [True, False],
        "num_vehicles": [100],
    },
    "seeds": SEEDS_FULL,
}

# ----- Fig. 4 — empirical core-distance -----
# We need realizations.jsonl with core_in_core / core_corrected fields.
# These are produced by every run. We just need ENOUGH slots, so we
# anchor on one well-sampled density and let make_figures.py pool all
# realized slots across seeds.
SWEEP_CORE = {
    "name": "core",
    "factors": {
        "num_vehicles": [100],
    },
    "seeds": SEEDS_FULL,
}

SWEEPS = {
    "gap": SWEEP_GAP,
    "density": SWEEP_DENSITY,
    "misreport_dro": SWEEP_MISREPORT_DRO,
    "core": SWEEP_CORE,
}


# ----------------------------------------------------------------------
# Run plan generation
# ----------------------------------------------------------------------
def make_run_plan(sweep, base_dir):
    """
    Build the full list of (run_id, kwargs) for a sweep, taking the
    cartesian product of factors x seeds.
    """
    factors = sweep["factors"]
    seeds = sweep["seeds"]
    keys = list(factors.keys())

    def rec(i, current):
        if i == len(keys):
            for s in seeds:
                cfg = dict(current)
                cfg["seed"] = s
                rid_parts = [
                    f"{k}={_fmt(v)}" for k, v in current.items()
                ] + [f"seed={s}"]
                run_id = str(Path(sweep["name"]) / "/".join(rid_parts))
                yield run_id, cfg
            return
        k = keys[i]
        for v in factors[k]:
            current[k] = v
            yield from rec(i + 1, current)
            del current[k]

    return list(rec(0, {}))


def _fmt(v):
    if isinstance(v, float):
        return f"{v:.3g}".replace(".", "_")
    return str(v)


# ----------------------------------------------------------------------
# Worker
# ----------------------------------------------------------------------
def _run_one(args):
    """
    Worker process: instantiate a Simulator and run it.

    Returns a small dict for the main process to log; the heavy artifacts
    (csv, jsonl) are persisted to disk by the Simulator itself.
    """
    run_id, kwargs, base_dir = args
    start = time.time()
    try:
        sim = Simulator(
            run_id=run_id,
            results_dir_base=base_dir,
            verbose=False,
            **kwargs,
        )
        sim.run()
        return {
            "run_id": run_id,
            "status": "ok",
            "elapsed_s": time.time() - start,
            "tasks_generated": sim.tasks_generated,
            "tasks_processed": sim.tasks_processed,
            "total_realized": sim.total_realized,
        }
    except Exception as exc:
        return {
            "run_id": run_id,
            "status": "error",
            "elapsed_s": time.time() - start,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }


# ----------------------------------------------------------------------
# Orchestrator
# ----------------------------------------------------------------------
def execute_sweep(sweep, base_dir, n_workers, dry_run=False):
    """
    Run a sweep in parallel via ProcessPoolExecutor.
    """
    plan = make_run_plan(sweep, base_dir)
    total = len(plan)
    print(f"[sweep:{sweep['name']}] planned {total} runs")
    if dry_run:
        for rid, cfg in plan[:5]:
            print(f"    {rid} -> {cfg}")
        if total > 5:
            print(f"    ... ({total - 5} more)")
        return

    log_path = Path(base_dir) / f"{sweep['name']}_runlog.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    completed = 0
    errors = 0
    t0 = time.time()

    with ProcessPoolExecutor(max_workers=n_workers) as pool:
        futures = {
            pool.submit(_run_one, (rid, cfg, base_dir)): rid
            for rid, cfg in plan
        }
        for fut in as_completed(futures):
            res = fut.result()
            with open(log_path, "a") as f:
                f.write(json.dumps(res) + "\n")
            completed += 1
            if res["status"] != "ok":
                errors += 1
                print(f"  [{completed}/{total}] ERROR {res['run_id']}: {res.get('error')}")
            else:
                rate = completed / (time.time() - t0)
                eta_s = (total - completed) / rate if rate > 0 else 0
                if completed % max(1, total // 50) == 0 or completed == total:
                    print(
                        f"  [{completed}/{total}] OK "
                        f"({rate:.2f} runs/s, ETA {eta_s/60:.1f} min, "
                        f"errors={errors})"
                    )

    print(
        f"[sweep:{sweep['name']}] done in {(time.time()-t0)/60:.1f} min "
        f"({errors} errors, log at {log_path})"
    )


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------
def main_cli():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sweep", default="density",
        choices=list(SWEEPS.keys()) + ["all"],
        help="Which sweep to run (default: density).",
    )
    parser.add_argument(
        "--workers", type=int, default=max(1, mp.cpu_count() - 1),
        help="Parallel worker count (default: cpu_count() - 1).",
    )
    parser.add_argument(
        "--results-dir", default=None,
        help="Override results base directory (default: results/<timestamp>).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the run plan without executing.",
    )
    parser.add_argument(
        "--seeds", type=int, default=None,
        help="Override seed count (use only seeds 1..N).",
    )
    args = parser.parse_args()

    base_dir = args.results_dir or os.path.join(
        "results", datetime.now().strftime("%Y%m%d_%H%M%S"),
    )
    Path(base_dir).mkdir(parents=True, exist_ok=True)
    print(f"[output] {base_dir}")
    print(f"[workers] {args.workers}")

    sweeps_to_run = list(SWEEPS.values()) if args.sweep == "all" else [SWEEPS[args.sweep]]

    if args.seeds:
        for s in sweeps_to_run:
            s = dict(s)
            s["seeds"] = list(range(1, args.seeds + 1))

    for sweep in sweeps_to_run:
        if args.seeds:
            sweep = {**sweep, "seeds": list(range(1, args.seeds + 1))}
        execute_sweep(sweep, base_dir, args.workers, dry_run=args.dry_run)


if __name__ == "__main__":
    # Important on Linux: 'spawn' avoids leaking SUMO/CBC subprocess state
    # across workers. On macOS the default is already 'spawn'.
    if sys.platform.startswith("linux"):
        mp.set_start_method("spawn", force=True)
    main_cli()