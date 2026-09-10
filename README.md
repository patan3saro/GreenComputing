# GreenComputing

Simulator and reproduction scripts for *Reusing Spare Vehicle Computing
Capacity: Is It Viable, Profitable and Sustainable?* (submitted to IEEE
Transactions on Mobile Computing).

## Reproduce the paper

```
pip install -r requirements.txt
./reproduce.sh
```

`reproduce.sh` downloads the raw simulation output on first run (20 MB), then writes the three figures to `figures/` and
every table to `tables/`. The post-processing itself runs in under a minute.

| Paper item | Script | Input |
|---|---|---|
| Fig. 2a, 2b, 3 | `paper_main_figures.py` | `results/comparison_FINAL/ablation_grid.csv`, `results/comparison_FINAL/optimal_dro/nv*/seed1/allocations.jsonl`, `results/grid_cf*_mf*/*/nv90/*/summary.json` |
| Table II (failure rates), Table V | `extract_tables3.py` | all `summary.json` |
| Table II (utility), Table III | `table2_split.py` | `ablation_grid.csv`, seed-1 `allocations.jsonl` |
| Table IV | `cost_per_task_table.py` | constants only |
| Table VI | `co2_from_grid.py` (`--fpeak` for peak-load attribution) | `ablation_grid.csv` |
| Table S1 | `loss_attribution.py` | grid `summary.json` |
| Table S2 | `sensitivity_table.py` | `results/sens_*/*/nv*/seed*/summary.json` |

`paper_main_figures.py` also writes `figures/paper_figure_values.csv` with
every plotted value.

## Data

The raw output of the campaign (one `summary.json` per run, plus
`ablation_grid.csv` and the per-assignment `allocations.jsonl` and
`realizations.jsonl` of the first seed of each density) is attached to the
release `v1.0-data` of this repository. `reproduce.sh` fetches it
automatically; to do it by hand, download the archive from the release page
and unpack it as `results/` in this directory. The families `abl_load_*`,
`abl_mis_*` and `abl_product_*` are the adaptive-penalty variants of
Sec. S3 of the supplementary material; `cap_dens_05` is exploratory and not
used in the paper.

## Re-run the simulation

The simulator is in Python; the mobility traces are generated with
[SUMO](https://eclipse.dev/sumo/) from OpenStreetMap data of downtown Rome
(`SUMO_HOME` must be set). Prefetch the traces once, then run the campaign:

```
python3 prefetch_maps.py
./run_campaign.sh
```

`run_campaign.sh` runs the density sweep (`comparison_FINAL`), the
capacity × misreporting grid (`grid_cf*_mf*`) and the sensitivity
families (`sens_*`) with 10 seeds each; it takes several days on a
16-core machine. Single configurations can be run with
`comparison_strategies.py` (see its docstring for the parameters).

Entry points and modules:

- `comparison_strategies.py` — runs one configuration for every strategy
- `main.py` — one simulation (Stage 1 allocation, Stage 2 sharing)
- `optimizer.py`, `admission.py` — allocation ILP and robust admission rule
- `payoff_sharing.py`, `value_function.py`, `core_check.py`, `realized_value.py` — coalitional game
- `task_timing.py`, `task_energy.py`, `network_manager.py` — delay, energy and 5G channel models
- `vehicle.py`, `cloud.py`, `controller.py`, `mobility_manager.py` — nodes and mobility
- `config.py` — every parameter of Table I

## License

MIT, see `LICENSE`.
