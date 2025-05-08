import datetime
import os
import random, numpy as np
import math

import pandas as pd
from datetime import datetime

import utils_computing as compute
import utils_for_covertions as convert

from config import *
from vehicle import Vehicle
from cloud import Cloud
from controller import Controller
from value_function import *
import game
from mobility_manager import extract_city_traffic
from network_manager import *

import seeds
import random
import numpy as np



def is_node_busy(node_id, busy_nodes_id):
    return any(node['busy_id'] == node_id for node in busy_nodes_id)

def filter_tasks_by_arrival_time(tasks, start_time, end_time):
    start_time /= 1000
    end_time /= 1000

    filtered_tasks=[task for task in tasks if "arrival_time" in task and start_time <= task["arrival_time"] <= end_time]
    return filtered_tasks

def generate_exponential_tasks(rate, task_input_size, task_output_size, task_workload,
                               num_users, max_sim_time_ms,
                               task_type_tuple, possible_task_types):


    start_time, end_time = (0, max_sim_time_ms)
    start_time_sec = start_time / 1000
    end_time_sec = end_time / 1000

    total_rate = rate * num_users
    window_duration_sec = end_time_sec - start_time_sec
    n_tasks = np.random.poisson(lam=total_rate * window_duration_sec)

    arrival_times_sec = np.random.uniform(start_time_sec, end_time_sec, size=n_tasks)
    arrival_times_sec.sort()

    # Scelta dei valori base secondo le probabilità
    scelte = np.random.choice(possible_task_types, size=n_tasks, p=task_type_tuple)

    # Applichiamo una normale centrata sul valore scelto
    # con deviazione standard di 0.1
    deadlines = [random.normalvariate(v, 0.1) for v in scelte]
    deadlines_seconds = np.array(deadlines)/ 1000

    tasks = [{
        "id": i,
        "arrival_time": arrival_time,  # in secondi
        "I": task_input_size,  # bit
        "O": task_output_size,  # bit
        "W": task_workload,  # 500 Mcycles
        "D": deadline  # in secondi
    } for i, (arrival_time, deadline) in enumerate(zip(arrival_times_sec, deadlines_seconds))]

    print(
        f"Generati {len(tasks)} task per {num_users} utenti a tasso {rate}/sec nella finestra [{start_time_sec}-{end_time_sec}]sec")
    return tasks


def create_vehicles(num, city, bbox, sim_time_ms, cpu_cap, cpu_power, ue_tx, energy, price, queue_capacity):
    output_dir, df = extract_city_traffic(city, "it", bbox, sim_time_ms / 1000, 0.1, num)
    if df is None or df.empty:
        raise RuntimeError(f"Nessun dato di traffico estratto da {output_dir}")
    # Se la colonna non si chiama 'id', rinominala
    if 'id' not in df.columns:
        if 'vehicle_id' in df.columns:
            df = df.rename(columns={'vehicle_id': 'id'})
        else:
            df = df.rename(columns={df.columns[0]: 'id'})  # fallback generico
    # Ora è sicuro ordinare
    df = df.sort_values(by=['id', 'time'], ascending=[True, False])
    return [
        Vehicle(id=vid,
                cpu_capacity=cpu_cap,
                queue_capacity=queue_capacity,
                cpu_power=cpu_power,
                ue_power=ue_tx,
                energy_available=energy,
                dollars_per_kwh=price,
                mobility_df=g)
        for vid, g in df.groupby('id')
    ]


def create_cloud_nodes(num, cloud_id, cpu_cap, cloud_queue_capacity,  tx_power, energy, price):
    return [Cloud(id=cloud_id - i, cpu_capacity=cpu_cap, cloud_queue_capacity=cloud_queue_capacity, cpu_power=cpu_cap,
                  tx_power=tx_power, energy_available=energy, dollars_per_kwh=price)
            for i in range(num)]

def main(results_folder, task_input_size=TASK_INPUT_SIZE,
    task_output_size=TASK_OUTPUT_SIZE,
    task_workload=TASK_WORKLOAD,
    city=CITY, city_bbox=CITY_BBOX, seed_random=SEED_RANDOM, no_id=NO_ID, verbose=VERBOSE,
    dr_5g=DR_5G, inet_dr=DR_INET, inet_delay=INET_DELAY,
    gnb_tx_power_5g=GNB_TX_POWER_5G, gnb_tx_power_inet=GNB_TX_POWER_INET, ue_tx_power=UE_TX_POWER,
    coverage_radius=COVERAGE_RADIUS, pedestrian_ue_distance=PEDESTRIAN_UE_DISTANCE,
    cloud_distance=CLOUD_DISTANCE, cloud_cpu_capacity=CLOUD_CPU_CAPACITY,
    vehicle_cpu_capacity=VEHICLE_CPU_CAPACITY, queue_capacity_vehicle=VEHICLE_QUEUE_CAPACITY,
    cloud_queue_capacity=CLOUD_QUEUE_CAPACITY, controller_cpu_power=CONTROLLER_CPU_POWER,
    vehicle_cpu_power=VEHICLE_CPU_POWER, energy_available=ENERGY_AVAILABLE,
    price_kwh=PRICE_KWH, price_kwh_cloud=PRICE_KWH_CLOUD, no_energy_price=NO_ENERGY_PRICE,
    possible_task_types=POSSIBLE_TASK_TYPES, task_type_tuple=TASK_TYPE_TUPLE, task_rate=TASK_RATE,
    window_task_collection=WINDOW_TASK_COLLECTION, price_subscriptions=PRICE_SUBSCRIPTIONS,
    start_time=START_TIME, max_simulation_time_ms=MAX_SIMULATION_TIME_MS, time_step_ms=TIME_STEP_MS,
    algorithm_time_overhead=ALGORITHM_TIME_OVERHEAD,
    vehicle_beacon_interval_ms=VEHICLE_BEACON_INTERVAL_MS,
    cloud_beacon_interval_ms=CLOUD_BEACON_INTERVAL_MS,
    num_vehicles=NUM_VEHICLES, users_number=USERS_NUMBER, num_clouds=NUM_CLOUDS,
    cloud_id=CLOUD_ID, network_operators=NETWORK_OPERATORS):

    seeds.seed_random = seed_random

    random.seed(seeds.seed_random)
    np.random.seed(seeds.seed_random)

    print("=== Avvio Simulazione ===")

    vehicles = create_vehicles(num_vehicles, city, city_bbox, max_simulation_time_ms,
                               vehicle_cpu_capacity, vehicle_cpu_power,
                               ue_tx_power, energy_available, price_kwh, queue_capacity_vehicle)

    clouds = create_cloud_nodes(num_clouds, cloud_id, cloud_cpu_capacity, cloud_queue_capacity,
                                gnb_tx_power_inet, energy_available, price_kwh)

    controller = Controller(gnb_position_x=0, gnb_position_y=0)
    tasks =  generate_exponential_tasks(task_rate, task_input_size, task_output_size, task_workload, users_number, max_simulation_time_ms, task_type_tuple, possible_task_types)


    last_v_beacon = {v.id: -vehicle_beacon_interval_ms for v in vehicles}
    last_v_real = last_v_beacon.copy()
    last_c_beacon = {c.id: -cloud_beacon_interval_ms for c in clouds}

    beacon_df = pd.DataFrame(columns=[
        'timestamp', 'node_id', 'beacon_cpu_capacity', 'queue_capacity', 'beacon_cpu_power', 'beacon_ue_power',
        'beacon_energy', 'beacon_dollars_per_kwh', 'pos_x', 'pos_y', 'speed', 'distance_gNB', 'dwell',
        'useful_throughput_ul', 'useful_throughput_dl'
    ])

    beacon_df_real = beacon_df.copy()


    tasks_df = pd.DataFrame(columns=["id", "arrival_time", "I", "O", "W", "D"])
    busy_nodes_id = []

    current_time_ms = start_time
    task_allocation_count = total_tasks_processed = total_utility = count_all_tasks = 0

    while current_time_ms <= max_simulation_time_ms:
        current_time_sec = current_time_ms / 1000

        datarates = calcola_data_rate_5g_standard(vehicles, current_time_sec, potenza_dl_dbm=gnb_tx_power_5g)
        valid_ids = {d['id'] for d in datarates}

        for v in vehicles:
            # escludi subito i veicoli il cui id non è in datarates
            if v.id not in valid_ids:
                continue

            if current_time_ms - last_v_beacon[v.id] >= vehicle_beacon_interval_ms and not is_node_busy(v.id,
                                                                                                        busy_nodes_id):
                beacon = v.create_communication_beacon(current_time_sec)
                beacon_real = v.create_real_beacon(beacon)

                dwell, dist = compute.calculate_dwell_time_and_distance(
                    beacon[6]['position_x'], beacon[6]['position_y'], beacon[6]['speed']
                )

                dwell_r, dist_r = compute.calculate_dwell_time_and_distance(
                    beacon[6]['position_x'], beacon[6]['position_y'], beacon[6]['speed']
                )

                if int(beacon[0])>=0:
                    datarate_by_id = [d for d in datarates if int(d.get('id')) == int(beacon[0])]
                    datarate_by_id= datarate_by_id[0]

                    #  Estendi i beacon con i datarate prima di passarli al controller

                    beacon_with_rates = extend_beacon_with_datarate(beacon, datarate_by_id)
                    beacon_real_with_rates = extend_beacon_with_datarate(beacon_real, datarate_by_id)

                    controller.receive_vehicle_beacon(beacon_with_rates, current_time_ms, dwell )
                    controller.receive_vehicle_real_beacon(beacon_real_with_rates, current_time_ms, dwell_r)

                    last_v_beacon[v.id] = last_v_real[v.id] = current_time_ms

                    beacon_df.loc[len(beacon_df)] = [
                        current_time_sec,
                        beacon_with_rates[0],  # node_id
                        beacon_with_rates[1],  # beacon_cpu_capacity
                        beacon_with_rates[6],  # queue_capacity
                        beacon_with_rates[2],  # beacon_cpu_power
                        beacon_with_rates[3],  # beacon_ue_power
                        beacon_with_rates[4],  # energy
                        beacon_with_rates[5],  # dollars_per_kwh
                        beacon[6]['position_x'],
                        beacon[6]['position_y'],
                        beacon[6]['speed'],
                        dist,
                        dwell,
                        beacon_with_rates[-2],  # useful_throughput_ul
                        beacon_with_rates[-1]  # useful_throughput_dl
                    ]

                    beacon_df_real.loc[len(beacon_df_real)] = [
                        current_time_sec,
                        beacon_real_with_rates[0],  # node_id
                        beacon_real_with_rates[1],  # beacon_cpu_capacity
                        beacon_real_with_rates[6],  # queue_capacity
                        beacon_real_with_rates[2],  # beacon_cpu_power
                        beacon_real_with_rates[3],  # beacon_ue_power
                        beacon_real_with_rates[4],  # energy
                        beacon_real_with_rates[5],  # dollars_per_kwh
                        beacon_real[6]['position_x'],
                        beacon_real[6]['position_y'],
                        beacon_real[6]['speed'],
                        dist_r,
                        dwell_r,
                        beacon_real_with_rates[-2],  # useful_throughput_ul
                        beacon_real_with_rates[-1]  # useful_throughput_dl
                    ]

        for c in clouds:
            if current_time_ms - last_c_beacon[c.id] >= cloud_beacon_interval_ms:
                beacon = extend_cloud_beacon(c.create_communication_beacon(), inet_dr)
                beacon_real = extend_cloud_beacon(c.create_real_beacon(), inet_dr)

                beacon_df.loc[len(beacon_df)] = [current_time_sec] + list(beacon[:-1]) + [0, 0, 0, CLOUD_DISTANCE, 0, cloud_queue_capacity]
                beacon_df_real.loc[len(beacon_df_real)] = [current_time_sec] + list(beacon_real[:-1]) + [0, 0, 0, CLOUD_DISTANCE, 0, cloud_queue_capacity]

                controller.receive_cloud_beacon(beacon, current_time_ms)
                print(f"[LOG] Beacon inviato - ID: {c.id}, Time: {current_time_sec:.2f}s")

                controller.receive_cloud_real_beacon(beacon_real, current_time_ms)
                print(f"[LOG] Cloud beacon inviato - ID: {c.id}, Time: {current_time_sec:.2f}s")

                last_c_beacon[c.id] = current_time_ms

        controller.clean_expired_beacons(current_time_ms)

        if current_time_ms % window_task_collection == 0:
            filtered = filter_tasks_by_arrival_time(tasks, current_time_ms, current_time_ms + window_task_collection)
            count_all_tasks += len(filtered)
            if filtered:
                new_tasks_df = pd.DataFrame(filtered)

                if not new_tasks_df.empty:
                    tasks_df = pd.concat([tasks_df, new_tasks_df], ignore_index=True)

                beacons = controller.beacons

                if beacons:
                    assigned_nodes, tasks_per_node, task_assignments, total_utility_allocation, algo_overhead = optimize_task_allocation(beacons, filtered, task_rate)

                    busy_nodes_id += [{'busy_id': int(t['node'][1]), 'time': math.ceil(convert.seconds_to_ms(t['details']['offloading_time']))}
                                      for t in task_assignments if int(t['node'][1]) >= 0]

                    # nome ricco di info
                    alloc_filename = (
                            f"allocations.txt"
                    )
                    alloc_path = os.path.join(results_folder, alloc_filename)

                    with open(alloc_path, 'w') as f:
                        f.write(f"{current_time_sec}\t{task_assignments}\n")

                    task_allocation_count += 1
                    total_tasks_processed += sum(1 for t in task_assignments if t is not None)
                    total_utility += total_utility_allocation

                    real_beacons = controller.real_beacons
                    tot_utility_real, infos = real_value_function(real_beacons, task_assignments, algo_overhead, task_rate)

                    real_fn = (
                            f"realization.txt"
                            )

                    with open(os.path.join(results_folder, real_fn), 'w') as f:
                             f.write(f"{current_time_sec}\t{tot_utility_real}\n{infos}\n")

                busy_nodes_id = [n for n in busy_nodes_id if n['time'] > 1]
                for n in busy_nodes_id: n['time'] -= 1

        current_time_ms += time_step_ms

    print("\n=== Simulazione completata ===")
    print(f"Tempo totale: {max_simulation_time_ms} ms | Task generati: {count_all_tasks} | Processati: {total_tasks_processed} | Utilit\u00e0: {total_utility}")

    beacon_df.to_csv(
        os.path.join(
        results_folder,
        f"beacons.csv"
        ),
        index = False
        )
      # nuovo filename con parametri
    tasks_fn = (
        f"tasks.csv"
        )
    tasks_path = os.path.join(results_folder, tasks_fn)
    tasks_df.to_csv(tasks_path, index=False)

if __name__ == "__main__":
    main(results_folder='results')
