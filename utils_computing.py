from utils_for_covertions import *


def calculate_dwell_time_and_distance(position_x, position_y, speed, gnb_position_x=0, gnb_position_y=0, coverage_radius=1000):
    """
    Calculate dwell time and Euclidean distance based on speed, position relative to GNB, and coverage radius

    Parameters:
    - speed: Vehicle speed (m/s)
    - position_x: X coordinate of the vehicle (m)
    - position_y: Y coordinate of the vehicle (m)
    - gnb_position_x: X coordinate of the GNB (default: 0)
    - gnb_position_y: Y coordinate of the GNB (default: 0)
    - coverage_radius: Radius of the GNB coverage area (m) (default: 1000)

    Returns:
    - Tuple of (dwell_time in milliseconds, euclidean_distance in meters)
    """
    # Calculate Euclidean distance to GNB
    euclidean_distance = math.sqrt((position_x - gnb_position_x) ** 2 +
                                   (position_y - gnb_position_y) ** 2)

    # If speed is zero or negative, dwell time is infinite
    if speed <= 0:
        return float('inf'), euclidean_distance

    # If already outside coverage radius, return 0 dwell time
    if euclidean_distance > coverage_radius:
        return 0, euclidean_distance

    # Calculate remaining distance to edge of coverage
    remaining_distance = coverage_radius - euclidean_distance

    # Calculate time to reach edge of coverage
    dwell_time = (remaining_distance / speed) * 1000  # Convert to milliseconds

    return dwell_time, euclidean_distance


def algorithm_overhead_time():
    pass


def energy_update(energy_available, offloading_energy):
    new_energy = energy_available - offloading_energy
    return new_energy


def offloading_time_energy(task, beacon, algorithm_overhead=0):
    """
    Calculate offloading time and energy for task execution with optimized computations.
    """
    # Extract task parameters with single lookups
    input_size = task['I']
    output_size = task['O']
    workload = task['W']

    # Pre-compute constant conversion factors
    ue_tx_power_watts = dbm_to_watt(UE_TX_POWER)
    gnb_tx_power_5g_watts = dbm_to_watt(GNB_TX_POWER_5G)
    gnb_tx_power_inet_watts = dbm_to_watt(GNB_TX_POWER_INET)
    node_tx_power_watts = dbm_to_watt(beacon[2]['tx_power'])

    # Pre-compute reciprocals for faster calculations
    inv_dr_5g = 1.0 / DR_5G
    inv_speed_light = 1.0 / SPEED_LIGHT

    # Common calculations with multiplication instead of division
    pue_ul_transmission_radio = input_size * inv_dr_5g
    pue_dl_transmission_radio = output_size * inv_dr_5g
    pue_propagation_radio = 2.0 * PEDESTRIAN_UE_DISTANCE * inv_speed_light
    capacity_cpu = beacon[2]['cpu_capacity']
    elaboration = workload / capacity_cpu  # Division needed here

    # Initialize result lists
    times = [
        pue_propagation_radio,
        pue_ul_transmission_radio,
        pue_dl_transmission_radio,
        elaboration,
        algorithm_overhead
    ]

    # Energy calculations
    pue_dl_energy = gnb_tx_power_5g_watts * pue_dl_transmission_radio
    cpu_power = beacon[2]['power']
    elaboration_energy = cpu_power * elaboration
    algorithm_energy = CONTROLLER_CPU_POWER * algorithm_overhead

    energies = [
        pue_dl_energy,
        elaboration_energy,
        algorithm_energy
    ]

    # Type checking using correct isinstance method for safety
    if beacon[2]['type']=='cloud'.lower():
        # Cloud-specific calculations
        inv_speed_fiber = 1.0 / SPEED_FIBER
        inv_dr_inet = 1.0 / DR_INET

        propagation_inet = 2.0 * (CLOUD_DISTANCE * inv_speed_fiber + INET_DELAY)
        ul_transmission_inet = input_size * inv_dr_inet
        dl_transmission_inet = output_size * inv_dr_inet

        # Add cloud-specific components
        times.extend([propagation_inet, ul_transmission_inet, dl_transmission_inet])

        # Cloud-specific energy components
        ul_energy_inet = gnb_tx_power_inet_watts * ul_transmission_inet
        dl_energy_inet = node_tx_power_watts * dl_transmission_inet

        energies.extend([ul_energy_inet, dl_energy_inet])

    elif beacon[2]['type'] == 'vehicle'.lower():

        dwell_time, distance_to_gnb = calculate_dwell_time_and_distance(beacon[2]['position_x'], beacon[2]['position_y'], beacon[2]['speed'], gnb_position_x=0, gnb_position_y=0, coverage_radius=1000)
        # Vehicle-specific calculations
        vue_propagation_radio = 2.0 * distance_to_gnb * inv_speed_light

        # Could reuse common calculations, but keeping separate for clarity
        ul_transmission_vue = input_size * inv_dr_5g
        dl_transmission_vue = output_size * inv_dr_5g

        # Add vehicle-specific components
        times.extend([vue_propagation_radio, ul_transmission_vue, dl_transmission_vue])

        # Vehicle-specific energy components
        ul_energy_vue = gnb_tx_power_inet_watts * ul_transmission_vue
        dl_energy_vue = node_tx_power_watts * dl_transmission_vue

        energies.extend([ul_energy_vue, dl_energy_vue])

    # Calculate totals efficiently using built-in sum (Python optimizes this well)
    offloading_time = sum(times)
    total_energy = sum(energies)

    return offloading_time, times, total_energy, energies
