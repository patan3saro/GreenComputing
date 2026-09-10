#!/usr/bin/env python3
"""
extract_tables3.py — aggregate every summary.json of a campaign into the
tables of the paper (failure rate, late failures, net utility, task fate,
paired no-DRO minus DRO differences), with 95% Student-t intervals over
seeds. The strategy is read from the path component
results/<campaign>/<strategy>/... because the JSON field `policy` is the
same for optimal_dro and optimal_nodro. If two files map to the same cell
(campaign, capacity, psi, strategy, seed) a warning is printed on stderr.

Usage:
    python3 extract_tables3.py > tables/extract.txt 2> tables/extract_warnings.txt
"""

import json, math, os, re, sys
from collections import defaultdict

ROOT = os.path.join(os.getcwd(), "results")

T95 = {1:12.706,2:4.303,3:3.182,4:2.776,5:2.571,6:2.447,7:2.365,8:2.306,
       9:2.262,10:2.228,11:2.201,12:2.179,13:2.160,14:2.145,15:2.131,
       16:2.120,17:2.110,18:2.101,19:2.093,20:2.086,25:2.060,30:2.042}
def t95(df):
    if df <= 0: return float("nan")
    if df in T95: return T95[df]
    for k in sorted(T95):
        if df < k: return T95[k]
    return 1.96

def mean_hw(vals):
    vals = [v for v in vals if v is not None]
    n = len(vals)
    if n == 0: return (float("nan"), float("nan"), 0)
    m = sum(vals)/n
    if n == 1: return (m, float("nan"), 1)
    var = sum((v-m)**2 for v in vals)/(n-1)
    return (m, t95(n-1)*math.sqrt(var/n), n)

KEYS = dict(gen="tasks_generated", proc="tasks_processed",
            unass="tasks_unassigned", lost2="tasks_lost_stage2",
            net="net_utility_dollars")

# dal piu' specifico al piu' generico: l'ordine conta
STRAT_PATTERNS = [
    ("optimal_nodro", "no-DRO"), ("optimal_dro", "DRO"),
    ("nodro", "no-DRO"), ("dro", "DRO"),
    ("vehicles_first", "Vehicles-first"), ("patane", "Vehicles-first"),
    ("greedy", "Greedy"), ("edge_only", "Edge-only"), ("edge", "Edge-only"),
    ("cloud_only", "Cloud-only"), ("cloud", "Cloud-only"),
    ("random", "Random"), ("optimal", "Optimal(?)"),
]

RE_CF = re.compile(r"cf[_-]?(\d+)", re.I)
RE_MF = re.compile(r"(?:mf|mis|psi)[_-]?(\d+)", re.I)
RE_TAIL = re.compile(r"_cf\d+_(?:mf|mis|psi)\d+.*$", re.I)

def parse_campaign(campaign):
    low = campaign.lower()
    cf = mf = None
    m = RE_CF.search(low)
    if m: cf = int(m.group(1))/100.0
    m = RE_MF.search(low)
    if m:
        v = m.group(1)
        mf = int(v)/10.0 if int(v) <= 10 else int(v)/100.0
    return RE_TAIL.sub("", campaign), cf, mf

def strat_from_path(rel):
    parts = rel.lower().split(os.sep)
    for comp in parts[1:]:          # salta la campagna: 'grid_cf03_mf6' contiene 'dro'? no, ma prudenza
        for pat, name in STRAT_PATTERNS:
            if comp == pat or comp.startswith(pat):
                return name
    # fallback: cerca nel path intero
    joined = "/".join(parts[1:])
    for pat, name in STRAT_PATTERNS:
        if pat in joined:
            return name
    return None

records = []
if not os.path.isdir(ROOT):
    print(f"ERRORE: {ROOT} non esiste.", file=sys.stderr); sys.exit(1)

for dirpath, _, filenames in os.walk(ROOT, followlinks=True):
    if "summary.json" not in filenames: continue
    p = os.path.join(dirpath, "summary.json")
    try:
        with open(p) as f: d = json.load(f)
    except Exception as e:
        print(f"WARN skip {p}: {e}", file=sys.stderr); continue
    rel = os.path.relpath(p, ROOT)
    campaign = rel.split(os.sep)[0]
    fam, cf, mf = parse_campaign(campaign)
    strat = strat_from_path(rel)
    seed = d.get("seed")
    m = re.search(r"seed[_-]?(\d+)", rel, re.I)
    if seed is None and m: seed = int(m.group(1))
    records.append(dict(path=rel, family=fam, cf=cf, mf=mf, strategy=strat,
                        seed=int(seed) if seed is not None else None,
                        gen=d.get(KEYS["gen"]), proc=d.get(KEYS["proc"]),
                        unass=d.get(KEYS["unass"]), lost2=d.get(KEYS["lost2"]),
                        net=d.get(KEYS["net"])))

fams = defaultdict(int)
for r in records: fams[r["family"]] += 1
print("="*78)
print("[FAMIGLIE]")
print("="*78)
for f in sorted(fams): print(f"  {f:32s} {fams[f]:5d}")

G = defaultdict(dict)
for r in records:
    if r["strategy"] is None or r["cf"] is None or r["mf"] is None or r["seed"] is None:
        continue
    key = (r["family"], round(r["cf"],3), round(r["mf"],2), r["strategy"])
    if r["seed"] in G[key]:
        print(f"WARN collisione {key} seed={r['seed']}: "
              f"{G[key][r['seed']]['path']}  <-  {r['path']}", file=sys.stderr)
        continue
    G[key][r["seed"]] = r

def series(key, field, pct=False):
    out = {}
    for seed, r in G.get(key, {}).items():
        v = r[field]
        if v is None: continue
        if pct:
            if not r["gen"]: continue
            out[seed] = 100.0*v/r["gen"]
        else:
            out[seed] = float(v)
    return out

def fmt(m, hw, dec=1):
    if isinstance(m,float) and math.isnan(m): return "n/a"
    if isinstance(hw,float) and math.isnan(hw): return f"{m:.{dec}f} (n=1)"
    return f"{m:.{dec}f} (+-{hw:.{dec}f})"

for FAM_SHOW in sorted({k[0] for k in G}):
    print()
    print("="*78)
    print(f"[TABLE_IV] {FAM_SHOW}  — late% del generato, net [µ$], media (+-hw95) sui seed")
    print("="*78)
    keys = sorted(k for k in G if k[0] == FAM_SHOW)
    print(f"{'cf':>5} {'psi':>4} {'strategia':<15} {'late% (+-hw)':>16} "
          f"{'net µ$ (+-hw)':>20} {'gen medio':>10} {'n':>3}")
    for key in keys:
        _, cf, mf, st = key
        lm, lh, ln = mean_hw(list(series(key,"lost2",pct=True).values()))
        nm, nh, _  = mean_hw([v*1e6 for v in series(key,"net").values()])
        gm, _, _   = mean_hw(list(series(key,"gen").values()))
        print(f"{cf:>5} {mf:>4} {st:<15} {fmt(lm,lh):>16} {fmt(nm,nh,0):>20} "
              f"{gm:>10.0f} {ln:>3}")

print()
print("="*78)
print("[TABLE_V] fate of tasks % del generato, psi=0.6")
print("  structural = unass(no-DRO); admission = unass(DRO)-unass(no-DRO) appaiata")
print("="*78)
for fam in sorted({k[0] for k in G}):
    for cf in sorted({k[1] for k in G if k[0]==fam}):
        kD, kN = (fam,cf,0.6,"DRO"), (fam,cf,0.6,"no-DRO")
        if kD not in G or kN not in G: continue
        for st, key in [("DRO",kD), ("no-DRO",kN)]:
            sm, sh, _ = mean_hw(list(series(key,"proc",True).values()))
            um, uh, _ = mean_hw(list(series(key,"unass",True).values()))
            lm, lh, _ = mean_hw(list(series(key,"lost2",True).values()))
            print(f"  {fam} cf={cf} {st:<7} served={fmt(sm,sh)}  "
                  f"unass={fmt(um,uh)}  queue={fmt(lm,lh)}")
        uD = series(kD,"unass",True); uN = series(kN,"unass",True)
        common = sorted(set(uD)&set(uN))
        dm, dh, dn = mean_hw([uD[s]-uN[s] for s in common])
        um, _, _ = mean_hw(list(uN.values()))
        print(f"  {fam} cf={cf} admission (appaiata, n={dn}) = {fmt(dm,dh)}   "
              f"structural = {um:.1f}%")

print()
print("="*78)
print("[FIG3] Delta appaiato: lost2(no-DRO)-lost2(DRO) [task] e in % del generato;")
print("       d_net = net(DRO)-net(no-DRO) [µ$]")
print("="*78)
print(f"{'famiglia':<14} {'cf':>5} {'psi':>4} {'d_lost2 (+-hw)':>18} "
      f"{'d_late% (+-hw)':>16} {'d_net µ$ (+-hw)':>20} {'n':>3}")
for fam in sorted({k[0] for k in G}):
    for cf in sorted({k[1] for k in G if k[0]==fam}):
        for mf in sorted({k[2] for k in G if k[0]==fam and k[1]==cf}):
            kD, kN = (fam,cf,mf,"DRO"), (fam,cf,mf,"no-DRO")
            if kD not in G or kN not in G: continue
            lD, lN = series(kD,"lost2"), series(kN,"lost2")
            pD, pN = series(kD,"lost2",True), series(kN,"lost2",True)
            nD, nN = series(kD,"net"), series(kN,"net")
            c = sorted(set(lD)&set(lN))
            dm, dh, n1 = mean_hw([lN[s]-lD[s] for s in c])
            pm, ph, _  = mean_hw([pN[s]-pD[s] for s in sorted(set(pD)&set(pN))])
            um, uh, _  = mean_hw([(nD[s]-nN[s])*1e6 for s in sorted(set(nD)&set(nN))])
            print(f"{fam:<14} {cf:>5} {mf:>4} {fmt(dm,dh,0):>18} "
                  f"{fmt(pm,ph):>16} {fmt(um,uh,0):>20} {n1:>3}")

print()
print("FINE v3.")
