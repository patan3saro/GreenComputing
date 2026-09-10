#!/usr/bin/env bash
# Regenerates every figure and table of the paper and of the supplementary
# material. If results/ is absent, the raw simulation output is downloaded
# first (DATA_URL below).
#
#   pip install -r requirements.txt
#   ./reproduce.sh
set -euo pipefail
cd "$(dirname "$0")"

# Raw simulation output: one archive, unpacked as results/ next to this script.
DATA_URL="https://github.com/patan3saro/GreenComputing/releases/download/v1.0-data/GreenComputing_results_v1.tar.gz"
ARCHIVE="$(basename "${DATA_URL%%\?*}")"

if [ ! -d results ]; then
  echo "[0/7] downloading raw output from ${DATA_URL}"
  curl -L --fail -o "$ARCHIVE" "$DATA_URL"
  tar -xzf "$ARCHIVE" && rm -f "$ARCHIVE"
  [ -d results ] || { echo "archive did not contain results/"; exit 1; }
fi

mkdir -p figures tables
echo "[1/7] figures 2a, 2b, 3            -> figures/"
python3 paper_main_figures.py --root results --out figures
echo "[2/7] tables II (failure), V, S1   -> tables/extract.txt"
python3 extract_tables3.py > tables/extract.txt 2> tables/extract_warnings.txt
echo "[3/7] tables II (utility), III     -> tables/table2_table3.txt"
python3 table2_split.py > tables/table2_table3.txt
echo "[4/7] table IV                     -> tables/table4.txt"
python3 cost_per_task_table.py > tables/table4.txt
echo "[5/7] table VI                     -> tables/table6.txt"
python3 co2_from_grid.py > tables/table6.txt
echo "[6/7] table S1                     -> tables/table_s1.txt"
python3 loss_attribution.py > tables/table_s1.txt
echo "[7/7] table S2                     -> tables/table_s2.txt"
python3 sensitivity_table.py > tables/table_s2.txt
echo "done: figures/ and tables/"
