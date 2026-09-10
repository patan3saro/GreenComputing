"""
table2_split.py — utility block of Table II and the incentives of Table III.

Table II (realized utility): total_realized_dollars from ablation_grid.csv,
mean over all seeds with the 95% Student-t half-width, split between
vehicles and cloud with the fraction measured on the seed whose
per-assignment trace (allocations.jsonl) is retained, applied to the
realized total. The allocated-utility split of the same seed is also
printed for reference.

Table III: monthly, yearly and lifetime revenue per vehicle from the
vehicular share, at 160 runs of 30 s per day (1h20 of offloading), converted
to charging hours on a 7 kW wallbox at 0.15 $/kWh and to driving range at
17.5 kWh/100 km.

Usage:  python3 table2_split.py
"""
import glob, json, os
import numpy as np, pandas as pd

ROOT, STRAT = "results/comparison_FINAL", "optimal_dro"
RUNS_PER_DAY, PRICE, WALLBOX, CONS, LIFE_Y = 4800 / 30, 0.15, 7.0, 17.5, 18.4

def seed1_split(nv):
    """(util_veh, util_cloud) allocated and (util_veh_net, util_cloud_net) net of lost tasks, on seed1."""
    run = f"{ROOT}/{STRAT}/nv{nv}/seed1"
    lost = set()
    rp = os.path.join(run, "realizations.jsonl")
    if os.path.exists(rp):
        for line in open(rp):
            for x in (json.loads(line).get("lost_tasks") or []):
                lost.add(x.get("task_id", x.get("id")) if isinstance(x, dict) else x)
    a = dict(veh=0.0, cld=0.0, veh_net=0.0, cld_net=0.0, n_veh=0, n_tot=0)
    ap = os.path.join(run, "allocations.jsonl")
    if not os.path.exists(ap):
        return None
    for line in open(ap):
        for x in json.loads(line).get("assignments", []):
            pay, cost = x.get("payment_dollars", 0.0), x.get("cost_dollars", 0.0)
            u_alloc = x.get("utility_dollars", pay - cost)
            u_net = (0.0 if x["task_id"] in lost else pay) - cost
            k = "cld" if x["node_type"] == "cloud" else "veh"
            a[k] += u_alloc; a[k + "_net"] += u_net
            a["n_tot"] += 1; a["n_veh"] += (k == "veh")
    return a

g = pd.read_csv(os.path.join(ROOT, "ablation_grid.csv"))
b = g[(g.strategy == STRAT) & (g.misreporting_fraction == 0)]
csv_tot = b.groupby("num_vehicles").total_realized_dollars.mean() * 1e6      # micro-dollars
csv_hw = b.groupby("num_vehicles").total_realized_dollars.agg(
    lambda x: 2.262 * x.std(ddof=1) / np.sqrt(len(x))) * 1e6
DENS = list(csv_tot.index)

rows = []
for nv in DENS:
    s = seed1_split(nv)
    if s is None:
        print(f"[skip] nv{nv}: seed1/allocations.jsonl missing"); continue
    frac = s["veh_net"] / (s["veh_net"] + s["cld_net"]) if (s["veh_net"] + s["cld_net"]) else np.nan
    rows.append(dict(nv=nv,
                     paper_veh=s["veh"] * 1e6, paper_cld=s["cld"] * 1e6,
                     s1_veh_net=s["veh_net"] * 1e6, s1_cld_net=s["cld_net"] * 1e6,
                     frac_veh=frac, pct_tasks_veh=100 * s["n_veh"] / s["n_tot"],
                     csv_tot=csv_tot[nv], csv_hw=csv_hw[nv]))
d = pd.DataFrame(rows).set_index("nv")
d["corr_veh"] = d.csv_tot * d.frac_veh
d["corr_cld"] = d.csv_tot * (1 - d.frac_veh)

pd.set_option("display.width", 200)
print("\n[A] allocated utility on seed1 (reference only)")
print((d[["paper_veh", "paper_cld"]] / 1e3).assign(tot=(d.paper_veh + d.paper_cld) / 1e3).round(1).to_string())

print("\n[B] Table II: realized total from the CSV (all seeds) x vehicular fraction of seed1")
print(d[["csv_tot", "csv_hw", "frac_veh", "pct_tasks_veh"]].round(3).to_string())
print((d[["corr_veh", "corr_cld", "csv_tot"]] / 1e3).round(1).to_string())

print("\n[LaTeX] Table II utility block [10^3 micro$]:")
for lab, col in (("Vehicular share", "corr_veh"), ("Cloud share", "corr_cld"), ("\\textbf{Total}", "csv_tot")):
    print(f"    {lab} & " + " & ".join(f"{d.loc[nv, col]/1e3:.1f}" for nv in d.index) + " \\\\")

print("\n[Table III] from the vehicular share of Table II")
for h, days in (("Monthly (30 d)", 30), ("Yearly (365 d)", 365), (f"Lifetime ({LIFE_Y} y)", 365 * LIFE_Y)):
    usd = d.corr_veh / 1e6 / d.index * RUNS_PER_DAY * days
    kwh = usd / PRICE
    T = pd.DataFrame({"Revenue [$]": usd, "Charging [h]": kwh / WALLBOX, "Range [km]": kwh / CONS * 100})
    print(f"\n{h}"); print(T.T.round(2).to_string())
    for m, dec in (("Revenue [$]", 2), ("Charging [h]", 2), ("Range [km]", 0)):
        print("    " + " & ".join([m] + [f"{v:.{dec}f}" for v in T[m]]) + " \\\\")
