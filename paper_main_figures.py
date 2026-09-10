#!/usr/bin/env python3
"""
paper_main_figures.py — the three figures of the main paper from the raw simulation output.

  Fig. 2a  final_combined_plot.png       offloading split + mean offloading time  T-bar
  Fig. 2b  energy_cost_with_ci_area.png  per-task energy + cost per country
  Fig. 3   mm1_heatmap_qos.png           late failures avoided by DRO (no-DRO - DRO)

Data sources:
  results/comparison_FINAL/ablation_grid.csv                 curves, mean over all seeds
  results/comparison_FINAL/<strategy>/nv*/seed1/allocations.jsonl   split and energy split
  results/grid_cf{CC}_mf{M}/<strategy>/nv90/**/summary.json  heatmap cells, mean over seeds

Every plotted value is also written to <out>/paper_figure_values.csv.

Usage:  python3 paper_main_figures.py [--root results] [--out figures]
"""
import argparse, csv, glob, json, os, re
from collections import defaultdict
import numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ------------------------------------------------------------------ style
FS_LABEL, FS_TICK, FS_LEG = 15, 13, 12
plt.rcParams.update({
    "font.family": "serif", "font.serif": ["DejaVu Serif"], "mathtext.fontset": "dejavuserif",
    "axes.labelsize": FS_LABEL, "axes.labelweight": "bold",
    "xtick.labelsize": FS_TICK, "ytick.labelsize": FS_TICK,
    "legend.fontsize": FS_LEG, "legend.frameon": False, "legend.handlelength": 2.0,
    "legend.columnspacing": 1.0, "legend.handletextpad": 0.5, "legend.borderaxespad": 0.2,
    "axes.linewidth": 1.0, "lines.linewidth": 2.0, "lines.markersize": 7,
    "grid.color": "0.85", "grid.linewidth": 0.6, "grid.linestyle": ":",
    "figure.dpi": 200, "savefig.dpi": 400, "savefig.bbox": "tight", "savefig.pad_inches": 0.02})
K, G = "black", "0.45"
PRICES_KWH = {"France": 0.22, "EU": 0.26, "USA": 0.17, "China": 0.078}   # national electricity prices [$/kWh]
DRO, NODRO, GREEDY, CLOUD, EDGE = "optimal_dro", "optimal_nodro", "greedy", "cloud_only", "edge_only"
VALUES = []   # every plotted value, written to paper_figure_values.csv


def rec(fig, series, x, y, lo=np.nan, hi=np.nan):
    VALUES.append(dict(figure=fig, series=series, x=x, y=y, ci_low=lo, ci_high=hi))


def mci(v):
    v = np.array([t for t in v if t == t], dtype=float)
    if len(v) == 0: return (np.nan, np.nan, np.nan)
    m = float(v.mean()); ci = 1.96 * v.std(ddof=1) / np.sqrt(len(v)) if len(v) > 1 else 0.0
    return (m, m - ci, m + ci)


# ------------------------------------------------------------ loaders
def csv_curves(root, strategy):
    """per nv: (mean, lo, hi) of mean_offloading_s and mean_energy_J over all seeds."""
    path = os.path.join(root, "comparison_FINAL", "ablation_grid.csv")
    rows = [r for r in csv.DictReader(open(path)) if r.get("strategy") == strategy]
    by = defaultdict(list)
    for r in rows:
        by[int(float(r["num_vehicles"]))].append(r)
    out = {}
    for nv in sorted(by):
        f = lambda col: mci([float(r[col]) for r in by[nv] if r.get(col) not in (None, "", "nan")])
        out[nv] = dict(ot=f("mean_offloading_s"), en=f("mean_energy_J"))
    return out


def alloc_split(root, strategy, seed="seed1"):
    """per nv from seed1 allocations.jsonl: % tasks to vehicles, mean vehicle offloading time,
    mean vehicle exec energy (exec_total), mean system energy (grand_total)."""
    out = {}
    for ap in glob.glob(os.path.join(root, "comparison_FINAL", strategy, "nv*", seed, "allocations.jsonl")):
        nv = next((int(p[2:]) for p in ap.split(os.sep) if p.startswith("nv")), None)
        if nv is None: continue
        otv, env, entot = [], [], []; nveh = ntot = 0
        for line in open(ap):
            line = line.strip()
            if not line: continue
            try: obj = json.loads(line)
            except json.JSONDecodeError: continue
            for a in obj.get("assignments", []):
                nid = a.get("node_id", 0)
                cloud = (a.get("node_type") == "cloud") or (isinstance(nid, (int, float)) and nid < 0)
                e = a.get("energy") or {}
                ntot += 1
                if not cloud:
                    nveh += 1
                    if isinstance(a.get("time_total_s"), (int, float)): otv.append(a["time_total_s"])
                    if isinstance(e.get("exec_total"), (int, float)): env.append(e["exec_total"])
                if isinstance(e.get("grand_total"), (int, float)): entot.append(e["grand_total"])
        if ntot:
            out[nv] = dict(pct_veh=100.0 * nveh / ntot,
                           ot_veh=np.mean(otv) if otv else np.nan,
                           en_veh=np.mean(env) if env else np.nan,
                           en_total=np.mean(entot) if entot else np.nan)
    return out


def grid_scan(root):
    rx = re.compile(r"grid_cf(\d+)_mf(\d+)")
    caps, mfs = set(), set()
    for d in glob.glob(os.path.join(root, "grid_cf*_mf*")):
        m = rx.search(os.path.basename(d))
        if m: caps.add(int(m.group(1))); mfs.add(int(m.group(2)))
    return sorted(caps), sorted(mfs)


def grid_lost2(root, cc, mm, st):
    v = []
    for sd in glob.glob(os.path.join(root, f"grid_cf{cc:02d}_mf{mm}", st, "nv90", "**", "summary.json"),
                        recursive=True):
        try: v.append(json.load(open(sd)).get("tasks_lost_stage2", 0))
        except Exception: pass
    return (float(np.mean(v)), len(v)) if v else (None, 0)


# --------------------------------------------------------------- helpers
def finish(ax, xt, last=False):
    ax.grid(True); ax.set_axisbelow(True)
    for s in ("top", "right"): ax.spines[s].set_visible(False)
    ax.set_xticks(range(len(xt))); ax.set_xticklabels(xt if last else [])
    ax.set_xlim(-0.45, len(xt) - 0.55)


# --------------------------------------------------------------- Fig. 2a
def fig2a(root, out):
    C = {s: csv_curves(root, s) for s in (DRO, GREEDY, CLOUD, EDGE)}
    S = alloc_split(root, DRO)
    dens = sorted(C[DRO]); xt = [str(v) for v in dens]; x = np.arange(len(dens))
    tot = np.array([C[DRO][v]["ot"][0] for v in dens]); lo = np.array([C[DRO][v]["ot"][1] for v in dens])
    hi = np.array([C[DRO][v]["ot"][2] for v in dens])
    grd = np.array([C[GREEDY].get(v, {}).get("ot", (np.nan,) * 3)[0] for v in dens])
    cld = np.array([C[CLOUD].get(v, {}).get("ot", (np.nan,) * 3)[0] for v in dens])
    edg = np.array([C[EDGE].get(v, {}).get("ot", (np.nan,) * 3)[0] for v in dens])
    split = np.array([S.get(v, {}).get("pct_veh", np.nan) for v in dens])
    vhc = np.array([S.get(v, {}).get("ot_veh", np.nan) for v in dens])
    for i, v in enumerate(dens):
        rec("2a", "pct_vehicles", v, split[i]); rec("2a", "T_dro_total", v, tot[i], lo[i], hi[i])
        rec("2a", "T_dro_vehicles_seed1", v, vhc[i]); rec("2a", "T_greedy", v, grd[i])
        rec("2a", "T_cloud_only", v, cld[i]); rec("2a", "T_edge_only", v, edg[i])

    fig, (a0, a1) = plt.subplots(2, 1, figsize=(4.6, 3.1), sharex=True,
                                 gridspec_kw={"height_ratios": [1, 2.0], "hspace": 0.10})
    a0.bar(x, split, .72, color="0.35", edgecolor=K, lw=.8, label="Vehicles", zorder=3)
    a0.bar(x, 100 - split, .72, bottom=split, color="0.85", edgecolor=K, lw=.8, hatch="//",
           label="Cloud", zorder=3)
    a0.set_ylabel("Offloaded\n[%]", fontsize=13); a0.set_ylim(0, 104); a0.set_yticks([0, 50, 100])
    a0.legend(ncol=2, loc="lower center", bbox_to_anchor=(0.5, 1.00)); finish(a0, xt)
    a1.fill_between(x, lo, hi, color="0.88", zorder=1)
    a1.plot(x, grd, "-", color=G, lw=4.5, solid_capstyle="round", zorder=2)
    a1.plot(x, grd, "^", color=G, ms=7, ls="none", label="Greedy", zorder=3)
    a1.plot(x, tot, "-o", color=K, mfc="white", mew=1.6, label="DRO total", zorder=5)
    a1.plot(x, vhc, "--s", color=K, label="DRO vehicles", zorder=5)
    a1.plot(x, cld, "--", color=G, label="Cloud-only", zorder=2)
    a1.plot(x, edg, "-.", color=G, marker="+", ms=9, mew=1.6, label="Edge-only", zorder=2)
    a1.set_ylabel(r"$\overline{T}$ [s]"); a1.set_xlabel("Vehicles in scenario")
    ymax = np.nanmax(np.concatenate([tot, cld])) * 1.28
    a1.set_ylim(0, ymax)
    a1.legend(ncol=2, loc="upper right", fontsize=FS_LEG - 2, handlelength=1.7, columnspacing=.7)
    finish(a1, xt, last=True); fig.align_ylabels([a0, a1])
    fig.savefig(os.path.join(out, "final_combined_plot.png")); plt.close(fig)
    return dens


# --------------------------------------------------------------- Fig. 2b
def fig2b(root, out, dens):
    Cd, Cc = csv_curves(root, DRO), csv_curves(root, CLOUD)
    S = alloc_split(root, DRO)
    xt = [str(v) for v in dens]; x = np.arange(len(dens))
    e_veh = np.array([S.get(v, {}).get("en_veh", np.nan) for v in dens])
    e_cld = np.array([Cc.get(v, {}).get("en", (np.nan,) * 3)[0] for v in dens])
    e_tot = np.array([S.get(v, {}).get("en_total", np.nan) for v in dens])
    if np.all(np.isnan(e_tot)):
        e_tot = np.array([Cd[v]["en"][0] for v in dens]); print("[2b] grand_total absent, cost from CSV energy")
    for i, v in enumerate(dens):
        rec("2b", "E_vehicle_exec_seed1", v, e_veh[i]); rec("2b", "E_cloud_only", v, e_cld[i])
        for c in PRICES_KWH: rec("2b", f"cost_{c}_microdollar", v, e_tot[i] * PRICES_KWH[c] / 3.6e6 * 1e6)

    fig, (b0, b1) = plt.subplots(2, 1, figsize=(4.6, 3.0), sharex=True,
                                 gridspec_kw={"height_ratios": [1, 1.15], "hspace": 0.10})
    b0.plot(x, e_veh, "-o", color=K, mfc="white", mew=1.6, label="Vehicle")
    b0.plot(x, e_cld, "--s", color=K, label="Cloud-only")
    b0.set_ylabel("Energy [J]", fontsize=13); b0.set_yticks([.05, .10])
    b0.legend(ncol=1, loc="center right", fontsize=FS_LEG - 1); finish(b0, xt)
    styles = {"France": ("-", "o", K), "EU": ("--", "s", G), "USA": ("-.", "^", G), "China": (":", "D", G)}
    for c, (ls, mk, col) in styles.items():
        b1.plot(x, e_tot * PRICES_KWH[c] / 3.6e6 * 1e6, ls, marker=mk, color=col, label=c, ms=6)
    b1.set_ylabel("Cost/task\n[$\\mu$\\$]", fontsize=13); b1.set_xlabel("Vehicles in scenario")
    b1.set_yticks([.002, .004, .006])
    b1.legend(ncol=4, loc="upper center", bbox_to_anchor=(0.5, 1.05), fontsize=FS_LEG - 2,
              handlelength=1.4, columnspacing=.5, handletextpad=.3)
    finish(b1, xt, last=True); fig.align_ylabels([b0, b1])
    fig.savefig(os.path.join(out, "energy_cost_with_ci_area.png")); plt.close(fig)


# --------------------------------------------------------------- Fig. 3
def fig3(root, out):
    caps, mfs = grid_scan(root)
    if not caps: print("[3] no grid_cf*_mf* under", root); return
    mfs = [m for m in mfs if m != 0]                       # honest row omitted (stated in caption)
    D = np.full((len(mfs), len(caps)), np.nan); nseed = None
    for i, mm in enumerate(mfs):
        for j, cc in enumerate(caps):
            d, nd = grid_lost2(root, cc, mm, DRO); n, nn = grid_lost2(root, cc, mm, NODRO)
            if d is not None and n is not None:
                D[i, j] = n - d; nseed = nseed or min(nd, nn)
                rec("3", "late_failures_avoided", f"cf={cc}%,psi={mm/10:.1f}", D[i, j])
    fig, ax = plt.subplots(figsize=(9.0, 4.0))
    im = ax.imshow(D, cmap="Greys", origin="lower", aspect="auto", vmin=np.nanmin(D), vmax=np.nanmax(D))
    ax.set_xticks(range(len(caps)), [f"{c}%" for c in caps], fontsize=15)
    ax.set_yticks(range(len(mfs)), [f"{m/10:.1f}" for m in mfs], fontsize=15)
    ax.set_xlabel("Spare capacity fraction", fontsize=17, fontweight="bold")
    ax.set_ylabel(r"Misreporting fraction $\psi$", fontsize=17, fontweight="bold")
    ax.set_title("Late failures avoided by DRO", fontsize=15, fontweight="bold", pad=8)
    for s in ax.spines.values(): s.set_visible(False)
    thr = np.nanmin(D) + .60 * (np.nanmax(D) - np.nanmin(D))
    for i in range(len(mfs)):
        for j in range(len(caps)):
            v = D[i, j]
            if np.isnan(v): continue
            ax.text(j, i, f"{int(round(v)):+,}".replace(",", "\u2009").replace("-", "\u2212"),
                    ha="center", va="center", fontsize=13, fontweight="bold",
                    color="white" if v > thr else "black")
    cb = fig.colorbar(im, ax=ax, pad=.06, fraction=.025, aspect=18)
    cb.set_label("no-DRO $-$ DRO  [tasks]", fontsize=15, fontweight="bold"); cb.ax.tick_params(labelsize=14)
    cb.outline.set_visible(False)
    fig.savefig(os.path.join(out, "mm1_heatmap_qos.png")); plt.close(fig)
    print(f"[3] grid {len(caps)}x{len(mfs)} cells, {nseed} seeds per cell (min)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="results"); ap.add_argument("--out", default="figures")
    a = ap.parse_args(); os.makedirs(a.out, exist_ok=True)
    dens = fig2a(a.root, a.out); fig2b(a.root, a.out, dens); fig3(a.root, a.out)
    with open(os.path.join(a.out, "paper_figure_values.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(VALUES[0])); w.writeheader(); w.writerows(VALUES)
    print("written:", a.out)
