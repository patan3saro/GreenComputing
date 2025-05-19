import os
import pandas as pd
import math
import json
from config import *
from vehicle import Vehicle
from cloud import Cloud
from controller import Controller
from value_function import *
from mobility_manager import extract_city_traffic
from network_manager import *
from collections import defaultdict
import numpy as np


def simplify_real_info(info):
    return {
        "task_id": info["task"]["task"]["id"],
        "node_id": info["node"][1],
        "utility": float(info["utility"]),
        "deadline_met": bool(info["other"]["deadline_met"])
    }


def simplify_assignment(assignment):
    return {
        "task": assignment["task"],
        "node_id": assignment["node"][1],
        "utility": float(assignment["utility"]),
        "deadline_met": bool(assignment["details"]["deadline_met"])
    }


def is_node_busy(node_id, busy_nodes_id):
    return any(node['busy_id'] == node_id for node in busy_nodes_id)

def filter_tasks_by_arrival_time(tasks, start_time_ms, end_time_ms):
    start_time = start_time_ms/1000
    end_time = end_time_ms/1000

    filtered_tasks=[task for task in tasks if "arrival_time" in task and start_time <= task["arrival_time"] <= end_time]
    return filtered_tasks

def generate_exponential_tasks(rate, task_input_size, task_output_size, task_workload,
                               num_users, max_sim_time_ms,
                               task_type_tuple, task_type_probability, seed_random):

    np.random.seed(seed_random)

    start_time_ms, end_time_ms = (0, max_sim_time_ms)
    start_time_sec = convert.ms_to_seconds(start_time_ms)
    end_time_sec = convert.ms_to_seconds(end_time_ms)

    total_rate = rate * num_users
    window_duration_sec = end_time_sec - start_time_sec
    n_tasks = np.random.poisson(lam=total_rate * window_duration_sec)

    arrival_times_sec = np.random.uniform(start_time_sec, end_time_sec, size=n_tasks)
    arrival_times_sec.sort()

    # Scelta delle deadline valori base secondo le probabilità
    scelte = np.random.choice(task_type_probability, size=n_tasks, p=task_type_tuple)

    # Applichiamo una normale centrata sul valore scelto
    # con deviazione standard di 0.1
    deadlines = [np.random.normal(v, v*0.1) for v in scelte]
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


#vedi se tutto funziona secondo la nuova logca e ordine implementati in cloud e vehicle

def create_vehicles_and_mobility(random_seed, num_vehicles, city, city_bbox, max_simulation_time_ms, vehicle_cpu_capacity, vehicle_queue_capacity,vehicle_cpu_power, ue_power, energy_available, dollars_per_kwh):
    max_simulation_time_seconds = convert.ms_to_seconds(max_simulation_time_ms)
    output_dir, mobility_df = extract_city_traffic(random_seed, city, "it", city_bbox, max_simulation_time_seconds, 0.1, num_vehicles)
    if mobility_df is None or mobility_df.empty:
        raise RuntimeError(f"Nessun dato di traffico estratto da {output_dir}, None or Empty")
    # Ora è sicuro ordinare
    mobility_df = mobility_df.sort_values(by=['id', 'time'], ascending=[True, False])
    return [
        Vehicle(vehicle_id=vid,
                cpu_capacity=vehicle_cpu_capacity,
                queue_capacity=vehicle_queue_capacity,
                cpu_power=vehicle_cpu_power,
                ue_power=ue_power,
                energy_available=energy_available,
                dollars_per_kwh=dollars_per_kwh,
                ul_datarate = None,
                dl_datarate = None,
                position_x = None,
                position_y = None,
                speed = None)
        for vid, _ in mobility_df.groupby('id')
    ], mobility_df




def create_cloud_nodes(num_clouds, cpu_capacity, queue_capacity, cpu_power,
tx_power, energy_available, dollars_per_kwh, ul_datarate, dl_datarate, position_x=0, position_y=0, speed=0):
    cloud_id_base = -1
    return [Cloud(cloud_id=cloud_id_base - i, cpu_capacity=cpu_capacity, queue_capacity=queue_capacity, cpu_power=cpu_power,
                  tx_power=tx_power, energy_available=energy_available, dollars_per_kwh=dollars_per_kwh, ul_datarate=ul_datarate, dl_datarate=dl_datarate, position_x=position_x, position_y=position_y, speed=speed)
            for i in range(num_clouds)]


def main(results_folder, task_input_size=TASK_INPUT_SIZE,
    task_output_size=TASK_OUTPUT_SIZE,
    task_workload=TASK_WORKLOAD,
    city=CITY, city_bbox=CITY_BBOX, seed_random=SEED_RANDOM, no_id=NO_ID, verbose=VERBOSE,
    dr_5g=DR_5G, inet_dr=DR_INET, inet_delay=INET_DELAY,
    gnb_tx_power_5g=GNB_TX_POWER_5G, gnb_tx_power_inet=GNB_TX_POWER_INET, ue_tx_power=UE_TX_POWER,
    coverage_radius=COVERAGE_RADIUS, pedestrian_ue_distance=PEDESTRIAN_UE_DISTANCE,
    cloud_distance=CLOUD_DISTANCE, cloud_cpu_capacity=CLOUD_CPU_CAPACITY,
    vehicle_cpu_capacity=VEHICLE_CPU_CAPACITY, vehicle_queue_capacity=VEHICLE_QUEUE_CAPACITY,
    cloud_queue_capacity=CLOUD_QUEUE_CAPACITY, controller_cpu_power=CONTROLLER_CPU_POWER,
    vehicle_cpu_power=VEHICLE_CPU_POWER, energy_available=ENERGY_AVAILABLE,
    price_kwh=PRICE_KWH, no_energy_price=NO_ENERGY_PRICE,
    possible_task_types=POSSIBLE_TASK_TYPES, task_type_tuple=TASK_TYPE_TUPLE, task_rate=TASK_RATE,
    window_task_collection=WINDOW_TASK_COLLECTION, price_subscriptions=PRICE_SUBSCRIPTIONS,
    start_time=START_TIME, max_simulation_time_ms=MAX_SIMULATION_TIME_MS, time_step_ms=TIME_STEP_MS,
    vehicle_beacon_interval_ms=VEHICLE_BEACON_INTERVAL_MS,
    cloud_beacon_interval_ms=CLOUD_BEACON_INTERVAL_MS,
    num_vehicles=NUM_VEHICLES, users_number=USERS_NUMBER, num_clouds=NUM_CLOUDS,
    cloud_id=CLOUD_ID):



    print("=== Avvio simulazione ===")

    print("=== Creazione veicoli e mobilità ===")
    vehicles, mobility_df = create_vehicles_and_mobility(seed_random, num_vehicles, city, city_bbox, max_simulation_time_ms,#
                               vehicle_cpu_capacity, vehicle_queue_capacity, vehicle_cpu_power,
                               ue_tx_power, energy_available, price_kwh)

    print("=== Creazione cloud ===")
    clouds = create_cloud_nodes(num_clouds, cloud_cpu_capacity, cloud_queue_capacity, controller_cpu_power,
                                gnb_tx_power_inet, energy_available, price_kwh, ul_datarate=inet_dr, dl_datarate=inet_dr)

    controller = Controller(gnb_position_x=0, gnb_position_y=0)
    tasks =  generate_exponential_tasks(task_rate, task_input_size, task_output_size, task_workload, users_number, max_simulation_time_ms, task_type_tuple, possible_task_types, seed_random)


    last_v_beacon = {v.vehicle_id: -vehicle_beacon_interval_ms for v in vehicles}
    last_v_real = last_v_beacon.copy()
    last_c_beacon = {c.cloud_id: -cloud_beacon_interval_ms for c in clouds}

    # for beacon tracing
    beacon_df = pd.DataFrame(columns=[
        'timestamp', 'node_id', 'node_cpu_capacity', 'queue_capacity', 'cpu_power', 'tx_power',
        'energy_available', 'dollars_per_kwh','ul_datarate', 'dl_datarate', 'pos_x', 'pos_y', 'speed'
    ])

    beacon_df_real = beacon_df.copy()

    #for task tracing
    tasks_df = pd.DataFrame(columns=["id", "arrival_time", "I", "O", "W", "D"])

    #to keep track of the nodes busy for offloading
    busy_nodes_id = []


    current_time_ms = start_time

    #initialize counts
    task_allocation_count = 0
    total_tasks_processed = 0
    total_utility = 0
    count_all_tasks = 0

    while current_time_ms <= max_simulation_time_ms:
        current_time_sec = convert.ms_to_seconds(current_time_ms)

        #assign current position to vehicles
        for vs in vehicles:
            vs.set_istantaneous_mobility_pattern(current_time_sec, mobility_df)

        vehicles_with_mobility = vehicles

        #assign datarates to vehicles
        active_vehicles = [v for v in vehicles_with_mobility if not is_node_busy(v.vehicle_id, busy_nodes_id)]
        # Calcolo datarate iniziale con x% attivi solo nel primo step
        if current_time_ms == start_time:
            vehicles_with_datarates = set_all_vehicles_data_rate_5g_standard(
                active_vehicles,
                seed_random=seed_random,
                potenza_dl_dbm=gnb_tx_power_5g,
                active_ratio=0.7  # <-- x% attivi all'inizio
            )
        else:
            vehicles_with_datarates = set_all_vehicles_data_rate_5g_standard(
                active_vehicles,
                seed_random=seed_random,
                potenza_dl_dbm=gnb_tx_power_5g,
                active_ratio=1.0  # <-- tutti potenzialmente attivi nei passi successivi
            )

        # Beacon asincroni: ogni veicolo ha offset sfasato nel tempo
        for v in vehicles_with_datarates:
            if current_time_ms - last_v_beacon[v.vehicle_id] >= vehicle_beacon_interval_ms and not is_node_busy(
                    v.vehicle_id, busy_nodes_id):
                # Invia beacon con ritardo sfasato (offset = vehicle_id % 100 ms)
                offset = v.vehicle_id % 100
                if current_time_ms % vehicle_beacon_interval_ms != offset:
                    continue

                beacon = v.create_beacon(current_time_sec, randomize=False, seed_random=seed_random)
                beacon_real = v.create_beacon(current_time_sec, randomize=True,seed_random=seed_random)
                dwell, dist = compute.calculate_dwell_time_and_distance(v.position_x, v.position_y, v.speed)

                controller.receive_vehicle_beacon(beacon, current_time_ms, dwell)
                controller.receive_vehicle_real_beacon(beacon_real, current_time_ms, dwell)

                last_v_beacon[v.vehicle_id] = last_v_real[v.vehicle_id] = current_time_ms

                beacon_df = pd.concat([beacon_df, pd.DataFrame([beacon])], ignore_index=True)
                beacon_df_real = pd.concat([beacon_df_real, pd.DataFrame([beacon_real])], ignore_index=True)

        for c in clouds:
            if current_time_ms - last_c_beacon[c.cloud_id] >= cloud_beacon_interval_ms:
                cloud_beacon = c.create_beacon(current_time_sec, randomize=False, seed_random=seed_random)
                cloud_beacon_real = c.create_beacon(current_time_sec, randomize=True, seed_random=seed_random)
                beacon_df = pd.concat([beacon_df, pd.DataFrame([cloud_beacon])], ignore_index=True)
                beacon_df_real = pd.concat([beacon_df_real, pd.DataFrame([cloud_beacon_real])], ignore_index=True)

                controller.receive_cloud_beacon(cloud_beacon, current_time_ms)
                print(f"[LOG] Beacon inviato - ID: {c.cloud_id}, Time: {current_time_sec:.2f}s")

                controller.receive_cloud_real_beacon(cloud_beacon_real, current_time_ms)
                print(f"[LOG] Cloud beacon inviato - ID: {c.cloud_id}, Time: {current_time_sec:.2f}s")

                last_c_beacon[c.cloud_id] = current_time_ms

        controller.clean_expired_beacons(current_time_ms)

        #END OF BEACON MANAGING

        #loose tasks if out after calculation and register in a file
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


                    traffic_map = defaultdict(lambda: {'I': 0, 'O': 0})
                    for t in task_assignments:
                        nid = int(t['node'][1])
                        traffic_map[nid]['I'] += t['task']['I']
                        traffic_map[nid]['O'] += t['task']['O']

                    # Aggiorna datarate in beacon con traffico reale
                    for b in controller.beacons:
                        nid = int(b[1])
                        if nid in traffic_map:
                            b[2]['ul_datarate'] = traffic_map[nid]['I'] / 0.1  # 100ms
                            b[2]['dl_datarate'] = traffic_map[nid]['O'] / 0.1

                    # Traccia log per ogni nodo
                    log_path = os.path.join(results_folder, "datarate_debug.jsonl")
                    with open(log_path, "a") as log_file:
                        for nid, traffic in traffic_map.items():
                            log_file.write(json.dumps({
                                "timestamp": current_time_sec,
                                "node_id": nid,
                                "traffic_I": traffic['I'],
                                "traffic_O": traffic['O'],
                                "ul_datarate": traffic['I'] / 0.1,
                                "dl_datarate": traffic['O'] / 0.1
                            }) + "\n")

                    busy_nodes_id += [{'busy_id': int(t['node'][1]), 'time': math.ceil(convert.seconds_to_ms(t['details']['offloading_time']))}
                                      for t in task_assignments if int(t['node'][1]) >= 0]

                    # nome ricco di info
                    assignments_serializable = [simplify_assignment(t) for t in task_assignments]

                    alloc_path = os.path.join(results_folder, "allocations.txt")
                    with open(alloc_path, 'a') as f:
                        f.write(json.dumps({
                            "timestamp": current_time_sec,
                            "assignments": task_assignments  # <-- tutto l'oggetto completo
                        }, default=str) + "\n")

                    task_allocation_count += 1
                    total_tasks_processed += sum(1 for t in task_assignments if t is not None)
                    total_utility += total_utility_allocation

                    real_beacons = controller.real_beacons
                    tot_utility_real, infos = real_value_function(real_beacons, task_assignments, algo_overhead,
                                                                  task_rate)

                    # Traccia task persi (deadline non rispettata)
                    lost_tasks = [
                        {
                            "timestamp": current_time_sec,
                            "task_id": t['task']['id'],
                            "node_id": int(t['node'][1]),
                            "deadline": t['task']['D']
                        }
                        for t in task_assignments
                        if not any(info['task']['task']['id'] == t['task']['id'] for info in infos)
                    ]

                    if lost_tasks:
                        lost_path = os.path.join(results_folder, "lost_tasks.jsonl")
                        with open(lost_path, "a") as f_lost:
                            for lost in lost_tasks:
                                f_lost.write(json.dumps(lost) + "\n")

                    real_path = os.path.join(results_folder, "realization.txt")
                    with open(real_path, 'a') as f:
                        f.write(json.dumps({
                            "timestamp": current_time_sec,
                            "real_total_utility": tot_utility_real,
                            "details": infos  # <-- dettagli completi
                        }, default=str) + "\n")

                busy_nodes_id = [n for n in busy_nodes_id if n['time'] > 1]
                for n in busy_nodes_id: n['time'] -= 1

        current_time_ms += time_step_ms

    # Salvataggi finali già presenti
    print("\n=== Simulazione completata ===")
    print(f"Tempo totale: {max_simulation_time_ms} ms | Task generati: {count_all_tasks} | Processati: {total_tasks_processed} | Utilità: {total_utility}")

    beacon_df.to_csv(os.path.join(results_folder, "beacons.csv"), mode='w', index=False)
    beacon_df_real.to_csv(os.path.join(results_folder, "beacons_real.csv"), mode='w', index=False)

    tasks_path = os.path.join(results_folder, "tasks.csv")
    tasks_df.to_csv(tasks_path, index=False)

if __name__ == "__main__":
    main(results_folder='tests')
