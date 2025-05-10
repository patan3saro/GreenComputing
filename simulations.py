#!/usr/bin/env python3

import os
# Disable parallelism: force single-threaded execution
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
from datetime import datetime
from itertools import product
from main import main
import seeds as sds


# 1) Random seeds
def get_seeds():
    return list(range(1))

# 2) Number of users
def get_users():
    return (1, 2, 5, 10, 15, 20, 25, 30, 40, 50, 60, 80, 100)

# 3) Workload: 100M to 10_000M step 100M
def get_workloads():
    return [i * 100_000_000 for i in range(1, 101)]

# 4) Task-rates for scenario B
def get_task_rates():
    return (1, 5, 10, 20)

# 5) Number of vehicles
def get_vehicle_counts():
    return (1, 2, 3, 4, 5, 10, 20, 30, 40, 50, 60, 70, 80, 100)

# 6) Queue capacities
def get_queue_caps():
    return range(1, 11)

# 7) Window for task collection
def get_window_tc():
    return range(2, 11)

# 8) CPU capacity factors (0.1 to 2.0 step 0.1)
def get_cpu_factors():
    return [round(i * 0.1, 1) for i in range(1, 21)]


# Constant multiplier for vehicle CPU capacity
VEHICLE_CPU_CAPACITY_BASE = 1.3e13


def generate_param_sets():
    seeds = get_seeds()
    users = get_users()
    workloads = get_workloads()
    task_rates = get_task_rates()
    vehicles = get_vehicle_counts()
    queue_caps = get_queue_caps()
    windows = get_window_tc()
    cpu_factors = get_cpu_factors()

    sets = []
    # A1) Varying users, fixed workload=100M
    for seed, u in product(seeds, users):

        sds.seed_random = seed
        sets.append({'scenario': 'A1', 'seed_random': seed,
                     'users_number': u,
                     'task_workload': 100_000_000,
                     'task_rate': 500})
    # A2) Varying workload, fixed users=50
    for seed, wl in product(seeds, workloads):
        sds.seed_random = seed
        sets.append({'scenario': 'A2', 'seed_random': seed,
                     'users_number': 50,
                     'task_workload': wl,
                     'task_rate': 50})

    # B) Task-rate for users=50, workload=100M
    for seed, tr in product(seeds, task_rates):
        sds.seed_random = seed
        sets.append({'scenario': 'B', 'seed_random': seed,
                     'users_number': 50,
                     'task_workload': 100_000_000,
                     'task_rate': tr})

    # C) Number of vehicles
    for seed, nv in product(seeds, vehicles):
        sets.append({'scenario': 'C', 'seed_random': seed,
                     'users_number': 50,
                     'task_workload': 100_000_000,
                     'task_rate': 50,
                     'num_vehicles': nv})

    # D) Queue capacity
    for seed, qc in product(seeds, queue_caps):
        sds.seed_random = seed
        sets.append({'scenario': 'D', 'seed_random': seed,
                     'users_number': 50,
                     'task_workload': 100_000_000,
                     'task_rate': 50,
                     'num_vehicles': 50,
                     'queue_capacity_vehicle': qc})

    # E) Window for task collection × Workload
    for seed, wc, in product(seeds, windows):
        sds.seed_random = seed
        sets.append({'scenario': 'E', 'seed_random': seed,
                     'users_number': 50,
                     'task_workload': 100_000_000,
                     'task_rate': 50,
                     'num_vehicles': 50,
                     'queue_capacity_vehicle': 5,
                     'window_task_collection': wc})

    # F) CPU capacity: factor × VEHICLE_CPU_CAPACITY_BASE
    for seed, cf in product(seeds, cpu_factors):
        sds.seed_random = seed
        capacity = cf * VEHICLE_CPU_CAPACITY_BASE
        sets.append({'scenario': 'F', 'seed_random': seed,
                     'users_number': 50,
                     'task_workload': 100_000_000,
                     'task_rate': 50,
                     'num_vehicles': 50,
                     'queue_capacity_vehicle': 5,
                     'vehicle_cpu_capacity': capacity})

    return sets


def main_run():
    # create base results folder with timestamp
    timestamp = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
    base_folder = os.path.join("results", timestamp)
    os.makedirs(base_folder, exist_ok=True)

    params_list = generate_param_sets()
    total = len(params_list)
    for idx, params in enumerate(params_list, start=1):
        scenario = params.pop('scenario')

        # Define folder structure per scenario
        if scenario == 'A1':
            subfolder = os.path.join('A1_users', f"users_{params['users_number']}")
        elif scenario == 'A2':
            subfolder = os.path.join('A2_workloads', f"workload_{params['task_workload']}")
        elif scenario == 'B':
            subfolder = os.path.join('B_rates', f"rate_{params['task_rate']}")
        elif scenario == 'C':
            subfolder = os.path.join('C_vehicles', f"vehicles_{params['num_vehicles']}")
        elif scenario == 'D':
            subfolder = os.path.join('D_queue_caps', f"queue_{params['queue_capacity_vehicle']}")
        elif scenario == 'E':
            subfolder = os.path.join('E_windows', f"window_{params['window_task_collection']}",
                                     f"workload_{params['task_workload']}")
        elif scenario == 'F':
            subfolder = os.path.join('F_cpu_caps', f"cpu_{params['vehicle_cpu_capacity']}")
        else:
            subfolder = ''

        run_folder = os.path.join(base_folder, subfolder)
        os.makedirs(run_folder, exist_ok=True)

        print(f"[{idx}/{total}] Scenario {scenario}: running with params {params}")
        main(run_folder, **params)


if __name__ == "__main__":
    main_run()
