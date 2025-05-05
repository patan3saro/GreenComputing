#!/usr/bin/env python3
import subprocess
import numpy as np

# 1) I 10 seed da iterare
seeds = list(range(1, 11))

# 2) Numero di users
user_counts = (1, 2, 5, 10, 15, 20, 25, 30, 40, 50, 60, 80, 100)

# 3) Workload: da 100 M a 10 000 M con step 100 M
workloads = [i * 100_000_000 for i in range(1, 101)]

# 4) Task‐rate per utenti fissi a 50
task_rates = (1, 5, 10, 20)

# 5) Numero di veicoli
vehicle_counts = (1, 2, 3, 4, 5, 10, 20, 30, 40, 50, 60, 70, 80, 100)

# 6) CPU capacity dei veicoli: 0.1 → 1.0 step 0.1
cpu_caps = np.arange(0.1, 1.01, 0.1)

# 7) Queue capacity dei veicoli: 1 → 10
queue_caps = range(1, 11)

# 8) window_task_collection: 2 ms → 10 ms step 1
window_tc = range(2, 11)

def run_main(**kwargs):
    """
    Costruisce e invoca:
      python main.py --param1 val1 --param2 val2 ...
    """
    cmd = ["python", "main.py"]
    for k, v in kwargs.items():
        cmd += [f"--{k}", str(v)]
    print("RUN:", " ".join(cmd))
    subprocess.run(cmd, check=True)

# ───────────────────────────────────────────────────────────────────────────
# A) Esperimento Users × Workload (task_rate fisso a 50)
for seed in seeds:
    for users in user_counts:
        for wl in workloads:
            run_main(
                seed=seed,
                num_users=users,
                workload=wl,
                task_rate=50
            )

# ───────────────────────────────────────────────────────────────────────────
# B) Esperimento Task‐rate per num_users=50 (workload fissato, es: 100 M)
for seed in seeds:
    for tr in task_rates:
        run_main(
            seed=seed,
            num_users=50,
            workload=100_000_000,
            task_rate=tr
        )

# ───────────────────────────────────────────────────────────────────────────
# C) Esperimento Numero di veicoli (users=50, wl=100 M, tr=50)
for seed in seeds:
    for nv in vehicle_counts:
        run_main(
            seed=seed,
            num_users=50,
            workload=100_000_000,
            task_rate=50,
            num_vehicles=nv
        )

# ───────────────────────────────────────────────────────────────────────────
# D) Esperimento CPU capacity (users=50, wl=100 M, tr=50, nv=10)
for seed in seeds:
    for cpu in cpu_caps:
        run_main(
            seed=seed,
            num_users=50,
            workload=100_000_000,
            task_rate=50,
            num_vehicles=10,
            cpu_capacity=cpu
        )

# ───────────────────────────────────────────────────────────────────────────
# E) Esperimento Queue capacity (users=50, wl=100 M, tr=50, nv=10, cpu=0.5)
for seed in seeds:
    for qc in queue_caps:
        run_main(
            seed=seed,
            num_users=50,
            workload=100_000_000,
            task_rate=50,
            num_vehicles=10,
            cpu_capacity=0.5,
            queue_capacity=qc
        )

# ───────────────────────────────────────────────────────────────────────────
# F) Esperimento window_task_collection (users=50, wl=100 M, tr=50, nv=10, cpu=0.5, qc=5)
for seed in seeds:
    for wc in window_tc:
        run_main(
            seed=seed,
            num_users=50,
            workload=100_000_000,
            task_rate=50,
            num_vehicles=10,
            cpu_capacity=0.5,
            queue_capacity=5,
            window_task_collection=wc
        )
