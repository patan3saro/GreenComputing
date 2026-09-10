#!/usr/bin/env bash
set -u
cd "$(dirname "$0")"
W=18; SIMMS=30000
ALL="optimal_dro,optimal_nodro,greedy,random,patane,cloud_only,edge_only"
DRO="optimal_dro,optimal_nodro"
CAPS=( "01:0.01:1.35e12" "03:0.03:4.0e12" "05:0.05:6.75e12" "08:0.08:1.1e13" "10:0.10:1.35e13" "15:0.15:2.0e13" "20:0.20:2.7e13" )
MFS=( "0.0:0" "0.2:2" "0.4:4" "0.6:6" "0.8:8" )
set_mode(){ sed -i "s/^DRO_ADAPT_MODE = .*/DRO_ADAPT_MODE = \"$1\"/" config.py; }
cell_done(){ [ -f "results/$1/ablation_grid.csv" ]; }
guard(){ FREE=$(df --output=avail -BG / | tail -1 | tr -dc '0-9'); if [ "$FREE" -lt 8 ]; then echo "!!! STOP: <8GB liberi"; exit 1; fi; }

# comparison_FINAL gia' fatto: NON si rilancia.

echo "##### 1/3 GRIGLIA (7 strat, --slim, 3 seed) #####"
set_mode fixed
for cap in "${CAPS[@]}"; do IFS=: read TAG CF CSTD <<< "$cap"
 for mf in "${MFS[@]}"; do IFS=: read MF MT <<< "$mf"
  OUT="grid_cf${TAG}_mf${MT}"; cell_done "$OUT" && { echo "[skip] $OUT"; continue; }; guard
  python3 comparison_strategies.py --seeds 3 --densities 90 --sim-ms $SIMMS --workers $W --slim \
    --strategies "$ALL" --users 100 --vehicle-cf $CF --cap-std $CSTD --cap-dist beta \
    --misreporting $MF --misreport-intensity 0.6 --resume --out "$OUT" 2>&1 | tail -1
 done; done

echo "##### 2/3 ABLATION (dro+nodro, --slim, 3 seed) #####"
for MODE in mis load product; do set_mode $MODE
 for cap in "${CAPS[@]}"; do IFS=: read TAG CF CSTD <<< "$cap"
  for mf in "${MFS[@]}"; do IFS=: read MF MT <<< "$mf"
   OUT="abl_${MODE}_cf${TAG}_mf${MT}"; cell_done "$OUT" && { echo "[skip] $OUT"; continue; }; guard
   python3 comparison_strategies.py --seeds 3 --densities 90 --sim-ms $SIMMS --workers $W --slim \
     --strategies "$DRO" --users 100 --vehicle-cf $CF --cap-std $CSTD --cap-dist beta \
     --misreporting $MF --misreport-intensity 0.6 --resume --out "$OUT" 2>&1 | tail -1
  done; done; done
set_mode fixed

echo "##### 3/3 SENSITIVITY (rho/users/capstd, --slim, 3 seed) #####"
for RHO in 0.2 0.4 0.6 0.8 1.0; do RT=$(echo $RHO|tr -d '.'); OUT="sens_rho_${RT}"
  cell_done "$OUT" && { echo "[skip] $OUT"; continue; }; guard
  python3 comparison_strategies.py --seeds 3 --densities 90 --sim-ms $SIMMS --workers $W --slim \
    --strategies "$DRO" --users 100 --vehicle-cf 0.05 --cap-std 6.75e12 --cap-dist beta \
    --misreporting 0.6 --misreport-intensity $RHO --resume --out "$OUT" 2>&1 | tail -1; done
for U in 25 50 100 150 200; do OUT="sens_users_${U}"
  cell_done "$OUT" && { echo "[skip] $OUT"; continue; }; guard
  python3 comparison_strategies.py --seeds 3 --densities 90 --sim-ms $SIMMS --workers $W --slim \
    --strategies "$DRO" --users $U --vehicle-cf 0.05 --cap-std 6.75e12 --cap-dist beta \
    --misreporting 0.6 --misreport-intensity 0.6 --resume --out "$OUT" 2>&1 | tail -1; done
for CSTD in 25 50 75; do OUT="sens_capstd_${CSTD}"
  cell_done "$OUT" && { echo "[skip] $OUT"; continue; }; guard
  CSTD_V=$(python3 -c "print(${CSTD}/100*1.35e13)")
  python3 comparison_strategies.py --seeds 3 --densities 90 --sim-ms $SIMMS --workers $W --slim \
    --strategies "$DRO" --users 100 --vehicle-cf 0.05 --cap-std $CSTD_V --cap-dist beta \
    --misreporting 0.6 --misreport-intensity 0.6 --resume --out "$OUT" 2>&1 | tail -1; done

echo "##### ROBUSTEZZA COMPLETA #####"
