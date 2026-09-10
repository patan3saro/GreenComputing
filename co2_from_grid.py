#!/usr/bin/env python3
"""
co2_from_grid.py — carbon table (Table VI of the paper) from results/comparison_FINAL/ablation_grid.csv,
plus the paired DRO vs no-DRO check on the honest row.

Recipe:
    kg/year/vehicle = E_task[J] * SEC_PER_DAY * DAYS * TASK_RATE * g[kg/kWh] / 3.6e6
with E_task the seed-mean of mean_energy_J in the cell (strategy, cf, mf=0, users, rate, nv).

Usage:
    python3 co2_from_grid.py                      # default: optimal_dro, cf=0.1, users=100, rate=10
    python3 co2_from_grid.py --fpeak 0.4          # peak-load attribution of the edge footprint
    python3 co2_from_grid.py --recipe measured    # tasks per vehicle measured from the CSV
"""
import argparse, sys
import numpy as np, pandas as pd

SEC_PER_DAY = 4800          # 1h20 of offloading per day
DAYS        = 365
HOURS_5Y_KWH = 13100.0      # edge server, 300 W x 5 years
EMBODIED_KG  = 925.0        # (900+1250)/2 - (50+100)/2
GRID = {"France": 19.6, "EU-27": 242.0, "USA": 369.0, "China": 581.0}   # g CO2 / kWh
T95 = {2:12.706,3:4.303,4:3.182,5:2.776,6:2.571,7:2.447,8:2.365,9:2.306,10:2.262}

ap = argparse.ArgumentParser()
ap.add_argument("--csv", default="results/comparison_FINAL/ablation_grid.csv")
ap.add_argument("--strategy", default="optimal_dro")
ap.add_argument("--cf", type=float, default=0.1)
ap.add_argument("--users", type=int, default=100)
ap.add_argument("--rate", type=float, default=10.0)
ap.add_argument("--recipe", choices=["stream", "measured"], default="stream",
                help="stream: TASK_RATE tasks/s per vehicle (paper recipe); measured: tasks_processed/num_vehicles from the CSV")
ap.add_argument("--ref-density", type=int, default=60)
ap.add_argument("--fpeak", type=float, default=1.0, help="peak share attributed to offloading (Sec. IX-C); 1.0 = full attribution")
a = ap.parse_args()

g = pd.read_csv(a.csv)
base = g[(g.misreporting_fraction == 0) & (g.users_number == a.users) & (g.task_rate == a.rate)]
if base.empty:
    sys.exit("no rows with mf=0, users=%d, rate=%g" % (a.users, a.rate))

# ---------------- Table VI: annual VCC emissions per vehicle -----------------
sel = base[(base.strategy == a.strategy) & (np.isclose(base.vehicle_cf, a.cf))]
if sel.empty:
    print("available cells (strategy, cf):");
    print(base.groupby(["strategy", "vehicle_cf"]).size().to_string()); sys.exit(1)

rows = []
for nv, d in sel.groupby("num_vehicles"):
    E = d.mean_energy_J.mean()
    if a.recipe == "stream":
        tasks_per_veh_year = SEC_PER_DAY * DAYS * a.rate
    else:
        runs_per_year = SEC_PER_DAY * DAYS / 30.0          # 30 s runs
        tasks_per_veh_year = (d.tasks_processed / d.num_vehicles).mean() * runs_per_year
    kwh = E * tasks_per_veh_year / 3.6e6
    rows.append(dict(nv=nv, seeds=len(d), E_J=E, kWh=kwh,
                     **{r: kwh * gi / 1000 for r, gi in GRID.items()}))
T = pd.DataFrame(rows).set_index("nv")

print(f"\n[Table VI] annual VCC emissions per vehicle [kg]  strategy={a.strategy} cf={a.cf} recipe={a.recipe}")
print(f"  recipe: E_task x {SEC_PER_DAY} s/day x {DAYS} days x "
      + (f"{a.rate:g} tasks/s" if a.recipe == "stream" else "measured tasks per vehicle") + " x g/kWh")
print(T[["seeds", "E_J", "kWh"] + list(GRID)].round(4).to_string())

# ---------------- edge 5-year footprint and saving ----------------
print(f"\n[Table VI] edge 5-year footprint = f_peak({a.fpeak:g}) x ({EMBODIED_KG:.0f} kg embodied + {HOURS_5Y_KWH:.0f} kWh x g); saving at density {a.ref_density}")
if a.ref_density in T.index:
    for r, gi in GRID.items():
        edge = a.fpeak * (EMBODIED_KG + HOURS_5Y_KWH * gi / 1000)
        vcc5 = 5 * T.loc[a.ref_density, r]
        print(f"  {r:8s} edge {edge:7.0f} kg   VCC 5y {vcc5:6.3f} kg   saving {100*(1-vcc5/edge):.2f}%   avoided {edge/1000:.1f} t")
else:
    print("  reference density not present:", list(T.index))

# LaTeX rows
print("\n[LaTeX] table rows:")
for r in GRID:
    cells = " & ".join(f"{T.loc[nv, r]:.2f}" for nv in T.index)
    edge = a.fpeak * (EMBODIED_KG + HOURS_5Y_KWH * GRID[r] / 1000)
    sav = 100 * (1 - 5 * T.loc[a.ref_density, r] / edge) if a.ref_density in T.index else float("nan")
    print(f"  {r:7s} & {cells} & {edge:.0f} & {sav:.2f}\\% \\\\")

# ---------------- honest row: |Delta| DRO vs no-DRO, per cf ----------------
print("\n[Honest row] DRO vs no-DRO, mf=0, per capacity (paired by seed and density)")
d1 = base[base.strategy == "optimal_dro"]; d0 = base[base.strategy == "optimal_nodro"]
key = ["vehicle_cf", "num_vehicles", "seed"]
m = d1.merge(d0, on=key, suffixes=("_dro", "_nodro"))
for cf, d in m.groupby("vehicle_cf"):
    dl = d.tasks_lost_stage2_dro - d.tasks_lost_stage2_nodro
    dp = d.tasks_processed_dro - d.tasks_processed_nodro
    n = len(d); t = T95.get(n, 1.96)
    hw = lambda x: t * x.std(ddof=1) / np.sqrt(n) if n > 1 else float("nan")
    print(f"  cf={cf:<5g} n={n:3d}  late: max|D|={dl.abs().max():4.0f}  mean {dl.mean():+.1f} ±{hw(dl):.1f}   "
          f"processed: max|D|={dp.abs().max():4.0f}  mean {dp.mean():+.1f} ±{hw(dp):.1f}")
