"""
comparison_strategies.py
========================
Runs every strategy of the paper on a grid of vehicle densities and seeds
and writes one row per run to results/<out>/ablation_grid.csv.

Strategies:
  - "optimal_dro"   : allocation ILP with the robust admission rule (paper method)
  - "optimal_nodro" : same ILP without admission (ablation)
  - "greedy"        : each task takes the best admissible executor
  - "random"        : each task takes an admissible executor at random
  - "cloud_only"    : remote cloud only
  - "edge_only"     : edge server co-located with the gNodeB
  - "patane"        : Vehicles-first of Patane et al. (Computer Networks 2025)

Regime parameters (defaults reproduce the honest, full-capacity setting):
  --task-rate F            load per user [task/s], default 10
  --vehicle-cf C           spare capacity fraction per vehicle in [0,1];
                           vehicle_cpu_capacity = C * VEHICLE_PEAK_OPS
  --misreporting F         fraction of over-declaring vehicles (psi), default 0
  --misreport-intensity R  over-declaration intensity, default 0

Per run the CSV records tasks generated/processed, failure rate, late
failures, wasted cost, net utility, mean offloading time, mean energy and
the regime parameters. Output path: results/<out>/<strategy>/nv<NV>/seed<SEED>.

Examples:
    python3 comparison_strategies.py --seeds 10 --workers 16 \
        --densities 10,30,60,100,150,200 --sim-ms 30000 --vehicle-cf 0.10 \
        --out comparison_FINAL --resume --slim
    python3 comparison_strategies.py --seeds 10 --workers 16 \
        --vehicle-cf 0.03 --misreporting 0.6 --misreport-intensity 0.6 \
        --out grid_cf03_mf6 --resume --slim
"""

import argparse
import os
import json
import time
import shutil
import itertools
import csv
import multiprocessing as mp
from pathlib import Path
import numpy as np


DEFAULT_DENSITIES = [10, 20, 30, 40, 60, 80, 100, 150, 200]

# Picco HW4 per la conversione --vehicle-cf -> vehicle_cpu_capacity.
# Stesso valore usato in trust_sweep.py per coerenza tra i due sweep.
VEHICLE_PEAK_OPS = 3e14

# Mappa strategia -> (policy, dro_enabled, extra_kwargs)
STRATEGIES = {
    "optimal_dro":   ("optimal",    True,  {}),
    "optimal_nodro": ("optimal",    False, {}),
    "greedy":        ("greedy",     False, {}),
    "random":        ("random",     False, {}),
    "cloud_only":    ("cloud_only", False, {}),
    "edge_only":     ("cloud_only", False, {"_edge": True}),
    "patane":        ("patane",     False, {}),
}


def _mean_offloading_and_energy(run_dir):
    """Media offloading time (s) e energia (J) dalle allocations."""
    ap = run_dir / "allocations.jsonl"
    if not ap.exists():
        return float("nan"), float("nan")
    USD_PER_J = 0.21 / 3.6e6
    times, energies = [], []
    for line in ap.read_text().splitlines():
        if not line.strip():
            continue
        for a in json.loads(line).get("assignments", []):
            t = a.get("time_total_s")
            if t is not None:
                times.append(t)
            c = a.get("cost_dollars", 0) or 0
            if c:
                energies.append(c / USD_PER_J)
    return (float(np.mean(times)) if times else float("nan"),
            float(np.mean(energies)) if energies else float("nan"))


def one_run(task):
    (strat, nv, seed, out_root, edge_latency_ms, sim_ms, resume, slim,
     task_rate, vehicle_cf, mf, mi, users, cap_mean, cap_std, cap_dist) = task
    from main import Simulator

    policy, dro, extra = STRATEGIES[strat]
    rid = f"{strat}/nv{nv}/seed{seed}"          # path invariato (compat. figure)
    run_dir = out_root / rid
    if not resume:
        shutil.rmtree(run_dir, ignore_errors=True)

    # campi di regime, ripetuti in ogni riga per chiarezza nel CSV
    regime = {"task_rate": task_rate, "vehicle_cf": vehicle_cf,
              "misreporting_fraction": mf, "misreport_intensity": mi,
              "users_number": users,
              "cap_mean": cap_mean, "cap_std": cap_std, "cap_dist": cap_dist}

    # resume: se il summary esiste gia, salta (protezione anti-spegnimento)
    summary_path = run_dir / "summary.json"
    if resume and summary_path.exists():
        try:
            s = json.load(open(summary_path))
            mean_t, mean_e = _mean_offloading_and_energy(run_dir)
            gen = s.get("tasks_generated", 0)
            row = {
                "strategy": strat, "num_vehicles": nv, "seed": seed,
                "is_edge": extra.get("_edge", False),
                "tasks_generated": gen,
                "tasks_processed": s.get("tasks_processed", 0),
                "tasks_unassigned": s.get("tasks_unassigned", 0),
                "tasks_lost_stage2": s.get("tasks_lost_stage2", 0),
                "failure_rate_pct": s.get("failure_rate_pct", 0.0),
                "wasted_cost_dollars": s.get("wasted_cost_dollars", 0.0),
                "total_realized_dollars": s.get("total_realized_dollars", 0.0),
                "net_utility_dollars": s.get("net_utility_dollars", 0.0),
                "mean_offloading_s": mean_t, "mean_energy_J": mean_e,
                "_resumed": True,
            }
            row.update(regime)
            return row
        except Exception:
            pass

    kwargs = dict(
        run_id=str(run_dir.relative_to("results")),
        num_vehicles=nv,
        task_rate=task_rate,
        policy=policy,
        dro_enabled=dro,
        seed=seed,
        max_simulation_time_ms=sim_ms,
        verbose=False,
    )
    # numero di UE-requester per cella (se impostato): demanda fissa, alta
    if users is not None:
        kwargs["users_number"] = users
    # eterogeneita' capacita' per-veicolo (None -> default config/main)
    if cap_mean is not None:
        kwargs["cap_mean"] = cap_mean
    if cap_std is not None:
        kwargs["cap_std"] = cap_std
    if cap_dist is not None:
        kwargs["cap_dist"] = cap_dist
    # capacita' spare per veicolo (se richiesta): coerente con trust_sweep
    if vehicle_cf is not None:
        kwargs["vehicle_cpu_capacity"] = vehicle_cf * VEHICLE_PEAK_OPS
    # misreporting (se richiesto): stesso meccanismo del trust_sweep
    if mf:
        kwargs["misreporting_fraction"] = mf
        kwargs["misreport_intensity"] = mi
    # edge_only: riduce il delay Internet del cloud per modellare un MEC
    # co-locato al gNodeB (IEEE 9453495: pochi ms vs 35 ms).
    is_edge = extra.get("_edge", False)
    if is_edge:
        kwargs["cloud_inet_delay_s"] = edge_latency_ms / 1000.0
        # Edge = nodo GPU REALE (A30, 330 TOPS = 3.3e14 OPS/s), non il cloud 1e15.
        # Coda lasciata ampia (default): non rifiuta, ma sotto carico la deadline
        # puo' scadere in coda. Coerente col nodo che prezziamo in ALL_FIGURES.
        kwargs["cloud_cpu_capacity"] = 3.3e14

    try:
        s = Simulator(**kwargs)
        s.run()
    except Exception as e:
        return {"strategy": strat, "num_vehicles": nv, "seed": seed,
                "error": str(e)[:160], **regime}

    mean_t, mean_e = _mean_offloading_and_energy(run_dir)
    gen = s.tasks_generated
    result = {
        "strategy": strat,
        "num_vehicles": nv,
        "seed": seed,
        "is_edge": is_edge,
        "tasks_generated": gen,
        "tasks_processed": s.tasks_processed,
        "tasks_unassigned": getattr(s, "tasks_unassigned", 0),
        "tasks_lost_stage2": getattr(s, "tasks_lost_stage2", 0),
        "failure_rate_pct": 100.0 * (getattr(s, "tasks_unassigned", 0) +
                                     getattr(s, "tasks_lost_stage2", 0))
                            / max(gen, 1),
        "wasted_cost_dollars": getattr(s, "wasted_cost_dollars", 0.0),
        "total_realized_dollars": s.total_realized,
        "net_utility_dollars": s.total_realized -
                               getattr(s, "wasted_cost_dollars", 0.0),
        "mean_offloading_s": mean_t,
        "mean_energy_J": mean_e,
    }
    result.update(regime)
    # --slim: tieni solo summary.json (lo sweep passa da ~30 GB a ~50 MB)
    if slim:
        keep = {"summary.json"}
        try:
            for f in run_dir.iterdir():
                if f.is_file() and f.name not in keep:
                    f.unlink()
        except Exception:
            pass
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--workers", type=int, default=6,
                    help="processi paralleli; basso = PC piu libero")
    ap.add_argument("--nice", type=int, default=10,
                    help="priorita CPU (0-19, alto = cede agli altri)")
    ap.add_argument("--densities", default=None,
                    help="comma-separated, es. 10,30,60,100,200")
    ap.add_argument("--sim-ms", type=int, default=2500,
                    help="durata simulazione in ms (piu lunga = piu mobilita)")
    ap.add_argument("--out", default=None,
                    help="nome cartella output fissa (per --resume)")
    ap.add_argument("--resume", action="store_true",
                    help="salta i run gia completati (riprende dopo stop)")
    ap.add_argument("--slim", action="store_true",
                    help="elimina i file pesanti dopo l'estrazione (solo summary)")
    ap.add_argument("--edge-latency-ms", type=float, default=3.0,
                    help="latenza edge per edge_only (IEEE 9453495: pochi ms)")
    ap.add_argument("--strategies", default=None,
                    help="sottoinsieme, es. optimal_dro,random,cloud_only")
    # --- nuovi parametri di regime ---
    ap.add_argument("--task-rate", type=float, default=10.0,
                    help="carico task/veicolo (default 10 = storico)")
    ap.add_argument("--users", type=int, default=None,
                    help="numero di UE-requester per cella (users_number). "
                         "Default = costante di config (100). Alzalo per "
                         "saturare il sistema: molti requester, pochi veicoli "
                         "spare -> regime dove strategia e DRO contano.")
    ap.add_argument("--cap-mean", type=float, default=None,
                    help="media capacita' spare per veicolo (OPS). "
                         "Default = config (10%% del picco).")
    ap.add_argument("--cap-std", type=float, default=None,
                    help="deviazione std della capacita' spare (OPS) = grado "
                         "di ETEROGENEITA'. 0 -> omogeneo (legacy). Alzala per "
                         "ridurre i veicoli EFFETTIVI (N_eff) a conteggio fisso.")
    ap.add_argument("--cap-dist", default=None, choices=["beta", "truncnorm"],
                    help="distribuzione capacita' su [0, cap_max]: beta | truncnorm.")
    ap.add_argument("--vehicle-cf", type=float, default=None,
                    help="frazione capacita' SPARE per veicolo in [0,1]; "
                         "se assente usa il default del Simulator (capacita' "
                         "piena -> convergenza). Realistico: 0.03-0.10")
    ap.add_argument("--misreporting", type=float, default=0.0,
                    help="frazione veicoli bugiardi (mf); default 0 = onesto")
    ap.add_argument("--misreport-intensity", type=float, default=0.0,
                    help="intensita' bugia (rho); usata se --misreporting>0")
    args = ap.parse_args()

    if args.vehicle_cf is not None and not (0.0 < args.vehicle_cf <= 1.0):
        raise SystemExit("--vehicle-cf deve essere in (0,1]")
    if not (0.0 <= args.misreporting <= 1.0):
        raise SystemExit("--misreporting deve essere in [0,1]")

    # Cede priorita CPU al resto del sistema (il PC resta usabile).
    try:
        os.nice(args.nice)
        print(f"[comparison] nice={args.nice} (priorita CPU ridotta)")
    except (OSError, AttributeError):
        pass

    densities = ([int(x) for x in args.densities.split(",")]
                 if args.densities else DEFAULT_DENSITIES)
    strategies = (args.strategies.split(",") if args.strategies
                  else list(STRATEGIES.keys()))
    for s in strategies:
        if s not in STRATEGIES:
            raise SystemExit(f"strategia sconosciuta: {s}")

    if args.out:
        out_root = Path("results") / args.out
    else:
        out_root = Path("results") / f"comparison_{time.strftime('%Y%m%d_%H%M%S')}"
    out_root.mkdir(parents=True, exist_ok=True)

    tasks = [(strat, nv, seed, out_root, args.edge_latency_ms,
              args.sim_ms, args.resume, args.slim,
              args.task_rate, args.vehicle_cf,
              args.misreporting, args.misreport_intensity, args.users,
              args.cap_mean, args.cap_std, args.cap_dist)
             for strat, nv, seed in itertools.product(
                 strategies, densities, range(1, args.seeds + 1))]

    cf_txt = ("piena (default)" if args.vehicle_cf is None
              else f"{args.vehicle_cf:.3f}*peak")
    print(f"[comparison] {len(tasks)} run "
          f"({len(strategies)} strategie x {len(densities)} densita "
          f"x {args.seeds} seed)")
    users_txt = "config(100)" if args.users is None else str(args.users)
    cap_txt = ("config" if args.cap_std is None
               else f"mean={args.cap_mean} std={args.cap_std} dist={args.cap_dist or 'beta'}")
    print(f"[comparison] regime: users={users_txt}  task_rate={args.task_rate}  "
          f"vehicle_cf={cf_txt}  misreporting={args.misreporting} "
          f"(rho={args.misreport_intensity})")
    print(f"[comparison] capacita': {cap_txt}")
    print(f"[comparison] output {out_root}")

    t0 = time.time()
    results = []
    with mp.Pool(args.workers) as pool:
        done = 0
        for res in pool.imap_unordered(one_run, tasks, chunksize=1):
            results.append(res)
            done += 1
            if done % 20 == 0 or done == len(tasks):
                dt = time.time() - t0
                eta = dt * (len(tasks) - done) / max(done, 1) / 60
                print(f"  [{done}/{len(tasks)}] ETA {eta:.1f} min", flush=True)

    ok = [r for r in results if "error" not in r]
    err = [r for r in results if "error" in r]
    if err:
        print(f"[comparison] {len(err)} run falliti (primo: {err[0].get('error')})")
    if ok:
        grid = out_root / "ablation_grid.csv"
        # union di tutte le chiavi (alcune righe hanno _resumed): evita
        # KeyError nel DictWriter se la prima riga non ha tutte le colonne.
        cols = sorted({k for r in ok for k in r.keys()})
        with open(grid, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(ok)
        print(f"[comparison] csv -> {grid}")
    print(f"[comparison] done in {(time.time()-t0)/60:.1f} min, "
          f"{len(ok)}/{len(results)} ok")
    print(f"\nPath per le figure: {out_root}/ablation_grid.csv")


if __name__ == "__main__":
    main()
