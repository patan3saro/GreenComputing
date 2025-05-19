from utils_for_covertions import *
import math

def calculate_dwell_time_and_distance(position_x, position_y, speed, gnb_position_x=900, gnb_position_y=900, coverage_radius=1000):
    euclidean_distance = math.sqrt((position_x - gnb_position_x) ** 2 +
                                   (position_y - gnb_position_y) ** 2)

    if speed <= 0:
        return float('inf'), euclidean_distance

    if euclidean_distance > coverage_radius:
        return 0, euclidean_distance

    remaining_distance = coverage_radius - euclidean_distance
    dwell_time = (remaining_distance / speed) * 1000  # in ms

    return dwell_time, euclidean_distance

def energy_update(energy_available, offloading_energy):
    return energy_available - offloading_energy

def offloading_time_energy(task, beacon, algorithm_overhead):
    input_size = task['I']
    output_size = task['O']
    workload = task['W']

    gnb_tx_power_5g_watts = dbm_to_watt(GNB_TX_POWER_5G)
    gnb_tx_power_inet_watts = dbm_to_watt(GNB_TX_POWER_INET)
    node_tx_power_watts = dbm_to_watt(beacon[2]['tx_power'])

    dr_5G_ul = beacon[2]['ul_datarate']
    dr_5G_dl = beacon[2]['dl_datarate']

    inv_dr_5g_ul = 1.0 / dr_5G_ul if dr_5G_ul > 0 else float('inf')
    inv_dr_5g_dl = 1.0 / dr_5G_dl if dr_5G_dl > 0 else float('inf')

    inv_speed_light = 1.0 / SPEED_LIGHT

    pue_ul_transmission_radio = input_size * inv_dr_5g_ul
    pue_dl_transmission_radio = output_size * inv_dr_5g_dl
    pue_propagation_radio = 2.0 * PEDESTRIAN_UE_DISTANCE * inv_speed_light
    capacity_cpu = beacon[2]['cpu_capacity']
    elaboration = workload / capacity_cpu

    times = [
        pue_propagation_radio,
        pue_ul_transmission_radio,
        pue_dl_transmission_radio,
        elaboration,
        algorithm_overhead
    ]

    pue_dl_energy = gnb_tx_power_5g_watts * pue_dl_transmission_radio
    cpu_power = beacon[2]['cpu_power']
    elaboration_energy = cpu_power * elaboration
    algorithm_energy = CONTROLLER_CPU_POWER * algorithm_overhead

    energies = [
        pue_dl_energy,
        elaboration_energy,
        algorithm_energy
    ]

    node_type = beacon[2]['type'].lower()

    if node_type == 'cloud':
        inv_speed_fiber = 1.0 / SPEED_FIBER
        inv_dr_inet = 1.0 / DR_INET

        propagation_inet = 2.0 * (CLOUD_DISTANCE * inv_speed_fiber + INET_DELAY)
        ul_transmission_inet = input_size * inv_dr_inet
        dl_transmission_inet = output_size * inv_dr_inet

        times.extend([propagation_inet, ul_transmission_inet, dl_transmission_inet])

        ul_energy_inet = gnb_tx_power_inet_watts * ul_transmission_inet
        dl_energy_inet = node_tx_power_watts * dl_transmission_inet

        energies.extend([ul_energy_inet, dl_energy_inet])

    elif node_type == 'vehicle':
        dwell_time, distance_to_gnb = calculate_dwell_time_and_distance(
            beacon[2]['position_x'], beacon[2]['position_y'], beacon[2]['speed'],
            gnb_position_x=900, gnb_position_y=900, coverage_radius=1000)

        vue_propagation_radio = 2.0 * distance_to_gnb * inv_speed_light
        ul_transmission_vue = input_size * inv_dr_5g_ul
        dl_transmission_vue = output_size * inv_dr_5g_dl

        times.extend([vue_propagation_radio, ul_transmission_vue, dl_transmission_vue])

        ul_energy_vue = gnb_tx_power_inet_watts * ul_transmission_vue
        dl_energy_vue = node_tx_power_watts * dl_transmission_vue

        energies.extend([ul_energy_vue, dl_energy_vue])

    offloading_time = sum(times)
    energy_tot = sum(energies)

    return offloading_time, times, energy_tot, energies
