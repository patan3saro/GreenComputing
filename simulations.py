import os
from datetime import datetime
from main import main

# === Parametri di Default ===
def get_defaults():
    return {
        'users_number': 50,
        'task_workload': 5e8,
        'task_rate': 10,
        'num_vehicles': 20,
        'vehicle_queue_capacity': 1,
        'vehicle_cpu_capacity': 1.3e13,
        'vehicle_cpu_power': 200,
        'ue_tx_power': 23,
        'window_task_collection': 5,
        'cloud_cpu_capacity': 1e15,
        'price_kwh': 0.15,
        'task_type_tuple': (0.33, 0.33, 0.34),
    }

SEEDS = [x for x in range(20)]

PARAM_SPACE = {
    'users_number': [10, 30, 50, 80, 100],
    'task_workload': [1e8, 3e8, 5e8, 7e8, 1e9],
    'task_rate': [1, 5, 10, 15, 20],
    'num_vehicles': [10, 30, 50, 80, 100],
    'vehicle_queue_capacity': [1, 3, 5, 7, 10],
    'vehicle_cpu_capacity': [0.5, 0.75, 1.0, 1.5, 2.0],  # moltiplicatore
    'vehicle_cpu_power': [100, 150, 200, 250, 300],
    'ue_tx_power': [20, 21, 23, 24, 26],
    'window_task_collection': [2, 4, 6, 8, 10],
    'cloud_cpu_capacity': [1e14, 3e14, 5e14, 8e14, 1e15],
    'price_kwh': [0.05, 0.10, 0.15, 0.20, 0.25],
    'task_type_tuple': [(0.8,0.1,0.1), (0.1,0.8,0.1), (0.1,0.1,0.8), (0.33,0.33,0.34)],
}

BASE_CPU = 1.3e13

def run_all():
    timestamp = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
    base_folder = os.path.join("results_simplified", timestamp)
    os.makedirs(base_folder, exist_ok=True)

    for param, values in PARAM_SPACE.items():
        for val in values:
            for seed in SEEDS:
                config = get_defaults()
                config[param] = val
                config['seed_random'] = seed

                # adattamenti speciali
                if param == 'vehicle_cpu_capacity':
                    config[param] = val * BASE_CPU

                if param == 'window_task_collection':
                    config['max_simulation_time_ms'] = val * 10 + 200

                folder = os.path.join(base_folder, param, f"val_{str(val).replace('.', '_')}", f"seed_{seed}")
                os.makedirs(folder, exist_ok=True)

                print(f"[RUN] {param}={val}, seed={seed}")
                main(folder, **config)

if __name__ == "__main__":
    run_all()
