#!/usr/bin/env python3

import os
from datetime import datetime
from itertools import product
from main import main

# 1) Random seeds
def get_seeds():
    return list(range(2))

# 2) Number of users
def get_users():
    return (1, 2, 5, 10, 15, 20, 25, 30, 40, 50, 60, 80, 100)

# 3) Workload: 100M to 10_000M step 100M
def get_workloads():
    return [i * 100_000_000 for i in range(1, 101)]

# 4) Task‑rates for scenario B
def get_task_rates():
    return (1, 5, 10, 20)

# 5) Number of vehicles
def get_vehicle_counts():
    return (1, 2, 3, 4, 5, 10, 20, 30, 40, 50, 60, 70, 80, 100)

# 6) CPU capacities
def get_cpu_caps():
    return [round(i * 0.1, 1) for i in range(1, 11)]

# 7) Queue capacities
def get_queue_caps():
    return range(1, 11)

# 8) Window for task collection
def get_window_tc():
    return range(2, 11)


def generate_param_sets():
    seeds = get_seeds()
    users = get_users()
    workloads = get_workloads()
    task_rates = get_task_rates()
    vehicles = get_vehicle_counts()
    cpu_caps = get_cpu_caps()
    queue_caps = get_queue_caps()
    windows = get_window_tc()

    sets = []
    # A) Users × Workload (fixed task_rate=50)
    for seed in seeds:
        # varying users, fixed workload=100M
        for u in users:
            sets.append({'seed_random': seed,
                         'users_number': u,
                         'task_workload': 100_000_000,
                         'task_rate': 50})
        # varying workload, fixed users=50
        for wl in workloads:
            sets.append({'seed_random': seed,
                         'users_number': 50,
                         'task_workload': wl,
                         'task_rate': 50})

    # B) Task‑rate for users=50, workload=100M
    for seed, tr in product(seeds, task_rates):
        sets.append({'seed_random': seed,
                     'users_number': 50,
                     'task_workload': 100_000_000,
                     'task_rate': tr})

    # C) Number of vehicles
    for seed, nv in product(seeds, vehicles):
        sets.append({'seed_random': seed,
                     'users_number': 50,
                     'task_workload': 100_000_000,
                     'task_rate': 50,
                     'num_vehicles': nv})

    # D) CPU capacity of vehicles
    for seed, cpu in product(seeds, cpu_caps):
        sets.append({'seed_random': seed,
                     'users_number': 50,
                     'task_workload': 100_000_000,
                     'task_rate': 50,
                     'num_vehicles': 50,
                     'vehicle_cpu_capacity': cpu})

    # E) Queue capacity
    for seed, qc in product(seeds, queue_caps):
        sets.append({'seed_random': seed,
                     'users_number': 50,
                     'task_workload': 100_000_000,
                     'task_rate': 50,
                     'num_vehicles': 50,
                     'vehicle_cpu_capacity': 0.5,
                     'queue_capacity_vehicle': qc})

    # F) Window for task collection
    for seed, wc in product(seeds, windows):
        sets.append({'seed_random': seed,
                     'users_number': 50,
                     'task_workload': 100_000_000,
                     'task_rate': 50,
                     'num_vehicles': 50,
                     'vehicle_cpu_capacity': 0.5,
                     'queue_capacity_vehicle': 5,
                     'window_task_collection': wc})

    return sets


def main_run():
    # create results folder with timestamp
    timestamp = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
    results_folder = os.path.join("results", timestamp)
    os.makedirs(results_folder, exist_ok=True)

    params_list = generate_param_sets()
    total = len(params_list)
    for idx, params in enumerate(params_list, start=1):
        print(f"[{idx}/{total}] Running with params: {params}")
        main(results_folder, **params)


if __name__ == "__main__":
    main_run()
