import os
import pandas as pd
import random

from config import *
from vehicle import Vehicle
from cloud import Cloud
from controller import Controller
from value_function import *
from mobility_manager import extract_city_traffic
from network_manager import *

def is_node_busy(node_id, busy_nodes_id):
    return any(node['busy_id'] == node_id for node in busy_nodes_id)

def filter_tasks_by_arrival_time(tasks, start_time_ms, end_time_ms):
    start_time = start_time_ms/1000
    end_time = end_time_ms/1000

    filtered_tasks=[task for task in tasks if "arrival_time" in task and start_time <= task["arrival_time"] <= end_time]
    return filtered_tasks

def generate_exponential_tasks(rate, task_input_size, task_output_size, task_workload,
                               num_users, max_sim_time_ms,
                               task_type_tuple, task_type_probability):


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


#vedi se tutto funziona secondo la nuova logca e ordine implementati in cloud e vehicle

def create_vehicles_and_mobility(num_vehicles, city, city_bbox, max_simulation_time_ms, vehicle_cpu_capacity, vehicle_queue_capacity,vehicle_cpu_power, ue_power, energy_available, dollars_per_kwh):
    max_simulation_time_seconds = convert.ms_to_seconds(max_simulation_time_ms)
    output_dir, mobility_df = extract_city_traffic(city, "it", city_bbox, max_simulation_time_seconds, 0.1, num_vehicles)
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

    import random
    import seeds
    import numpy as np
    seeds.seed_random = seed_random
    random.seed(seeds.seed_random)
    np.random.seed(seeds.seed_random)

    print("=== Avvio simulazione ===")

    print("=== Creazione veicoli e mobilità ===")
    vehicles, mobility_df = create_vehicles_and_mobility(num_vehicles, city, city_bbox, max_simulation_time_ms,#
                               vehicle_cpu_capacity, vehicle_queue_capacity, vehicle_cpu_power,
                               ue_tx_power, energy_available, price_kwh)

    print("=== Creazione cloud ===")
    clouds = create_cloud_nodes(num_clouds, cloud_cpu_capacity, cloud_queue_capacity, controller_cpu_power,
                                gnb_tx_power_inet, energy_available, price_kwh, ul_datarate=inet_dr, dl_datarate=inet_dr)

    controller = Controller(gnb_position_x=0, gnb_position_y=0)
    tasks =  generate_exponential_tasks(task_rate, task_input_size, task_output_size, task_workload, users_number, max_simulation_time_ms, task_type_tuple, possible_task_types)


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
        vehicles_with_datarates = set_all_vehicles_data_rate_5g_standard(vehicles_with_mobility, potenza_dl_dbm=gnb_tx_power_5g)
        for v in vehicles_with_datarates:

            if current_time_ms - last_v_beacon[v.vehicle_id] >= vehicle_beacon_interval_ms and not is_node_busy(v.vehicle_id,
                                                                                                        busy_nodes_id):
                beacon = v.create_beacon(current_time_sec, randomize=False)
                beacon_real = v.create_beacon(current_time_sec, randomize=True)
                dwell, dist = compute.calculate_dwell_time_and_distance(v.position_x, v.position_y, v.speed)

                controller.receive_vehicle_beacon(beacon, current_time_ms, dwell)
                controller.receive_vehicle_real_beacon(beacon_real, current_time_ms, dwell)

                last_v_beacon[v.vehicle_id] = last_v_real[v.vehicle_id] = current_time_ms

                beacon_df = pd.concat([beacon_df, pd.DataFrame([beacon])], ignore_index=True)
                beacon_df_real = pd.concat([beacon_df_real, pd.DataFrame([beacon_real])], ignore_index=True)

        for c in clouds:
            if current_time_ms - last_c_beacon[c.cloud_id] >= cloud_beacon_interval_ms:
                cloud_beacon = c.create_beacon(current_time_sec, randomize=False)
                cloud_beacon_real = c.create_beacon(current_time_sec, randomize=True)
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
    main(results_folder='tests')
