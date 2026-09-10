#!/usr/bin/env python3
"""
sensitivity_table.py — late failures of DRO and no-DRO when one factor is
varied around the reference cell (Table S2 of the supplementary material).

Families read from results/sens_*: sens_rho_<intensity> (misreporting
intensity), sens_capstd_<k> (spread of vehicle capacities; the ratio
cap_std/cap_mean is read from summary.json), sens_users_<n> (end-users).
Late failures are tasks_lost_stage2 / tasks_generated, mean over seeds with
the 95% Student-t half-width.

Usage:  python3 sensitivity_table.py
"""
import glob, json, os
import numpy as np

T95 = {10: 2.262, 9: 2.306, 8: 2.365, 7: 2.447, 6: 2.571, 5: 2.776, 4: 3.182, 3: 4.303, 2: 12.706}

def family_stats(fam):
    name = os.path.basename(fam); out = {}; par = None
    for st in ("optimal_dro", "optimal_nodro"):
        late = []
        for f in glob.glob(f"{fam}/{st}/nv*/seed*/summary.json"):
            d = json.load(open(f))
            g = d.get("tasks_generated") or 1
            late.append(100 * d.get("tasks_lost_stage2", 0) / g)
            if par is None:
                if "capstd" in name and d.get("cap_mean"):
                    par = ("Capacity CV", f"{d['cap_std'] / d['cap_mean']:.2f}")
                elif "users" in name:
                    par = ("End-users", str(d.get("users_number", name.split("_")[-1])))
                elif "rho" in name:
                    par = ("Intensity", f"{d.get('misreport_intensity', int(name.split('_')[-1]) / 10):.1f}")
        n = len(late)
        m = float(np.mean(late)) if n else float("nan")
        hw = T95.get(n, 1.96) * np.std(late, ddof=1) / np.sqrt(n) if n > 1 else 0.0
        out[st] = (m, hw, n)
    return name, par, out

if __name__ == "__main__":
    rows = [family_stats(f) for f in sorted(glob.glob("results/sens_*"))]
    order = {"Intensity": 0, "Capacity CV": 1, "End-users": 2}
    rows.sort(key=lambda r: (order.get(r[1][0], 9), float(r[1][1])))
    print(f"{'family':16s} {'factor':12s} {'value':>6s}   {'DRO':>16s}   {'no-DRO':>16s}")
    for name, (fac, val), o in rows:
        d, nd = o["optimal_dro"], o["optimal_nodro"]
        print(f"{name:16s} {fac:12s} {val:>6s}   {d[0]:5.1f} (+-{d[1]:.1f}) n={d[2]:<2d}   {nd[0]:5.1f} (+-{nd[1]:.1f}) n={nd[2]:<2d}")
    print("\n[LaTeX]")
    for name, (fac, val), o in rows:
        d, nd = o["optimal_dro"], o["optimal_nodro"]
        print(f"    {fac} & {val} & {d[0]:.1f} ($\\pm${d[1]:.1f}) & {nd[0]:.1f} ($\\pm${nd[1]:.1f}) \\\\")
