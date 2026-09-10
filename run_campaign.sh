#!/usr/bin/env bash
# =====================================================================
#  CAMPAGNA COMPLETA REVIEW-PROOF — VCC vs Edge
#  M/G/1 uniforme, edge=A30, coda reale, DRO adattivo, copertura 500m,
#  ottimo ILP esatto (HiGHS+scala). 3 seed, 30s run (warmup 30s in traccia).
#  DISCO-SMART: tracce COMPLETE su griglia+sensitivity (per latency/CVaR/
#  Gini/violin), --slim su ablation (basta l'aggregato). ~15 GB totali.
#  Checkpoint: salta celle gia' fatte. Anti-standby via systemd-inhibit.
# =====================================================================
set -u
cd "$(dirname "$0")"

SEEDS=3
SIMMS=30000
WORKERS=18
STRAT_ALL="optimal_dro,optimal_nodro,greedy,random,patane,cloud_only,edge_only"
STRAT_DRO="optimal_dro,optimal_nodro"
CENTER_CF=0.05; CENTER_CSTD=6.75e12; CENTER_MF=0.6; CENTER_RHO=0.6

GRID_CAPS=( "01:0.01:1.35e12" "03:0.03:4.0e12" "05:0.05:6.75e12" \
            "08:0.08:1.1e13" "10:0.10:1.35e13" "15:0.15:2.0e13" "20:0.20:2.7e13" )
GRID_MFS=( "0.0:0" "0.2:2" "0.4:4" "0.6:6" "0.8:8" )

set_mode(){ sed -i "s/^DRO_ADAPT_MODE = .*/DRO_ADAPT_MODE = \"$1\"/" config.py; }
done_cell(){ [ -f "results/$1/ablation_grid.csv" ]; }

echo "############ 1/4  GRIGLIA PRINCIPALE (fixed, 7 strat, TRACCE COMPLETE) ############"
set_mode fixed
for cap in "${GRID_CAPS[@]}"; do
  IFS=: read TAG CF CSTD <<< "$cap"
  for mf in "${GRID_MFS[@]}"; do
    IFS=: read MF MT <<< "$mf"
    OUT="grid_cf${TAG}_mf${MT}"; done_cell "$OUT" && { echo "[skip] $OUT"; continue; }
    echo "grid cap=$CF mf=$MF"
    python comparison_strategies.py --seeds $SEEDS --densities 90 --sim-ms $SIMMS --workers $WORKERS \
      --strategies "$STRAT_ALL" --users 100 --vehicle-cf $CF --cap-std $CSTD --cap-dist beta \
      --misreporting $MF --misreport-intensity $CENTER_RHO --out "$OUT" 2>&1 | tail -1
  done
done

echo "############ 2/4  ABLATION DRO (mis/load/product, dro+nodro, --slim) ############"
for MODE in mis load product; do
  set_mode $MODE; echo "=== MODE=$MODE ==="
  for cap in "${GRID_CAPS[@]}"; do
    IFS=: read TAG CF CSTD <<< "$cap"
    for mf in "${GRID_MFS[@]}"; do
      IFS=: read MF MT <<< "$mf"
      OUT="abl_${MODE}_cf${TAG}_mf${MT}"; done_cell "$OUT" && { echo "[skip] $OUT"; continue; }
      python comparison_strategies.py --seeds $SEEDS --densities 90 --sim-ms $SIMMS --workers $WORKERS --slim \
        --strategies "$STRAT_DRO" --users 100 --vehicle-cf $CF --cap-std $CSTD --cap-dist beta \
        --misreporting $MF --misreport-intensity $CENTER_RHO --out "$OUT" 2>&1 | tail -1
    done
  done
done
set_mode fixed

echo "############ 3/4  SENSITIVITY (centro cap5%/mf0.6, TRACCE COMPLETE) ############"
for RHO in 0.2 0.4 0.6 0.8 1.0; do
  RT=$(echo $RHO | tr -d '.'); OUT="sens_rho_${RT}"; done_cell "$OUT" && { echo "[skip] $OUT"; continue; }
  python comparison_strategies.py --seeds $SEEDS --densities 90 --sim-ms $SIMMS --workers $WORKERS \
    --strategies "$STRAT_ALL" --users 100 --vehicle-cf $CENTER_CF --cap-std $CENTER_CSTD --cap-dist beta \
    --misreporting $CENTER_MF --misreport-intensity $RHO --out "$OUT" 2>&1 | tail -1
done
for FRAC in 0:0 25:3.75e12 45:6.75e12 65:9.75e12 85:1.275e13; do
  IFS=: read PT CSTD <<< "$FRAC"; OUT="sens_capstd_${PT}"; done_cell "$OUT" && { echo "[skip] $OUT"; continue; }
  python comparison_strategies.py --seeds $SEEDS --densities 90 --sim-ms $SIMMS --workers $WORKERS \
    --strategies "$STRAT_ALL" --users 100 --vehicle-cf $CENTER_CF --cap-std $CSTD --cap-dist beta \
    --misreporting $CENTER_MF --misreport-intensity $CENTER_RHO --out "$OUT" 2>&1 | tail -1
done
for U in 25 50 100 150 200; do
  OUT="sens_users_${U}"; done_cell "$OUT" && { echo "[skip] $OUT"; continue; }
  python comparison_strategies.py --seeds $SEEDS --densities 90 --sim-ms $SIMMS --workers $WORKERS \
    --strategies "$STRAT_ALL" --users $U --vehicle-cf $CENTER_CF --cap-std $CENTER_CSTD --cap-dist beta \
    --misreporting $CENTER_MF --misreport-intensity $CENTER_RHO --out "$OUT" 2>&1 | tail -1
done

echo "############ 4/4  DISCO USATO ############"
du -sh results/ 2>/dev/null
echo "CAMPAGNA COMPLETA. (sensitivity densita' nv = batch separato, servono tracce nv=30,60,120)"
