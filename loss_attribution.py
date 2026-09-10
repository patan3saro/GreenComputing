#!/usr/bin/env python3
"""
loss_attribution.py — attributes every generated task to one of four fates
(served, structural loss, admission loss, queue loss) for DRO and no-DRO,
so that rows sum to 100% (Table S1 of the supplementary material).

no-DRO runs the same optimizer as DRO without the admission rule, so it is
the paired control: its unassigned tasks cannot be attributed to
robustness. Hence
    L_struct = unassigned(no-DRO)          no feasible executor at all
    L_admis  = unassigned(DRO) - unassigned(no-DRO)   price of admission
    L_queue  = late failures at execution
Reads results/grid_cf<CC>_mf<M>/<strategy>/nv90/**/summary.json.
"""

import json
import glob
import sys
import numpy as np

CELLE = [(1, 6), (3, 0), (3, 6), (5, 6), (8, 0), (8, 6), (10, 6), (20, 6)]
STRAT = ["optimal_dro", "optimal_nodro", "greedy", "patane", "edge_only"]
NOMI = {"optimal_dro": "DRO", "optimal_nodro": "no-DRO", "greedy": "Greedy",
        "patane": "VF", "edge_only": "Edge"}


def carica(cc, mt, st):
    """Media sui seed dei contatori di summary.json. None se cella assente."""
    g = u = l = 0.0
    n = 0
    for p in glob.glob(f"results/grid_cf{cc:02d}_mf{mt}/{st}/nv90/**/summary.json",
                       recursive=True):
        try:
            s = json.load(open(p))
        except Exception:
            continue
        g += s.get("tasks_generated", 0)
        u += s.get("tasks_unassigned", 0)
        l += s.get("tasks_lost_stage2", 0)
        n += 1
    if n == 0:
        return None
    return {"gen": g / n, "unass": u / n, "lost2": l / n, "n": n}


def tabella_console():
    print("\n" + "=" * 100)
    print("  ATTRIBUZIONE DELLE PERDITE  (% dei task generati; le righe sommano a 100)")
    print("=" * 100)
    print(f"{'cella':>14} {'strat':>8} | {'servito':>8} {'struttura':>10} "
          f"{'ammissione':>11} {'coda':>8} | {'gen':>7} {'seed':>5}")
    print("-" * 100)
    righe = []
    for cc, mt in CELLE:
        base = carica(cc, mt, "optimal_nodro")
        if base is None:
            continue
        for st in STRAT:
            d = carica(cc, mt, st)
            if d is None:
                continue
            gen = max(d["gen"], 1.0)
            struct = min(d["unass"], base["unass"])
            admis = d["unass"] - struct
            served = gen - d["unass"] - d["lost2"]
            r = dict(cella=f"cap{cc}% phi{mt/10:.1f}", strat=NOMI[st],
                     served=100 * served / gen, struct=100 * struct / gen,
                     admis=100 * admis / gen, queue=100 * d["lost2"] / gen,
                     gen=gen, n=d["n"])
            righe.append(r)
            print(f"{r['cella']:>14} {r['strat']:>8} | {r['served']:7.1f}% "
                  f"{r['struct']:9.1f}% {r['admis']:10.1f}% {r['queue']:7.1f}% "
                  f"| {gen:7.0f} {d['n']:5d}")
        print("-" * 100)
    return righe


def tabella_latex(righe):
    print("\n\n% ---- tabella pronta da incollare -------------------------------")
    print(r"\begin{table}[t]")
    print(r"  \centering\footnotesize\setlength{\tabcolsep}{4pt}")
    print(r"  \caption{Fate of every generated task, as a percentage of the")
    print(r"  offered load. \emph{Structural} losses admit no feasible executor")
    print(r"  and are independent of the policy; \emph{admission} losses are the")
    print(r"  extra rejections imputable to Def.~1, measured against \textsf{no-DRO}")
    print(r"  as the control; \emph{queue} losses are tasks admitted in Stage~1")
    print(r"  that miss the deadline at execution. Rows sum to 100\%.}")
    print(r"  \label{tab:loss_attribution}")
    print(r"  \begin{tabular}{llrrrr}")
    print(r"    \toprule")
    print(r"    Regime & Policy & Served & Structural & Admission & Queue \\")
    print(r"    \midrule")
    prev = None
    for r in righe:
        if prev is not None and r["cella"] != prev:
            print(r"    \midrule")
        prev = r["cella"]
        et = r["cella"].replace("%", r"\%").replace("phi", r"$\phi$=")
        print(f"    {et} & {r['strat']} & {r['served']:.1f} & {r['struct']:.1f} "
              f"& {r['admis']:.1f} & {r['queue']:.1f} \\\\")
    print(r"    \bottomrule")
    print(r"  \end{tabular}")
    print(r"\end{table}")


def analisi_tier():
    """Quale tier di deadline viene sacrificato: confronta la ripartizione
    dei generati (~1/3 ciascuno) con quella degli assegnati."""
    print("\n\n" + "=" * 78)
    print("  QUALE TIER DI DEADLINE VIENE SERVITO  (un seed per cella)")
    print("=" * 78)
    print(f"{'cella':>14} {'strat':>8} | {'D=16ms':>9} {'D=100ms':>9} "
          f"{'D=500ms':>9} | {'assegnati':>10}")
    print("-" * 78)
    for cc, mt in [(3, 6), (8, 6)]:
        for st in ("optimal_dro", "optimal_nodro"):
            f = sorted(glob.glob(
                f"results/grid_cf{cc:02d}_mf{mt}/{st}/nv90/seed*/allocations.jsonl"))
            if not f:
                continue
            t = [0, 0, 0]
            for line in open(f[0]):
                try:
                    a = json.loads(line)
                except Exception:
                    continue
                for x in a.get("assignments", []):
                    d = x.get("deadline_s") or x.get("task_deadline_s")
                    if d is None:
                        continue
                    ms = float(d) * 1000.0
                    t[0 if ms < 50 else (1 if ms < 300 else 2)] += 1
            tot = max(sum(t), 1)
            print(f"{'cap%d%% phi%.1f' % (cc, mt/10):>14} {NOMI[st]:>8} | "
                  + " ".join(f"{100*x/tot:8.1f}%" for x in t)
                  + f" | {tot:10d}")
        print("-" * 78)
    print("\n  Riferimento: i generati sono ~33/33/34%. Uno scostamento forte")
    print("  indica che quel tier non trova esecutori fattibili.")


if __name__ == "__main__":
    righe = tabella_console()
    if righe:
        tabella_latex(righe)
    if "--tiers" in sys.argv:
        analisi_tier()
