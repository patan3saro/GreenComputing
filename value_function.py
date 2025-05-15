import pulp
import utils_for_covertions as convert
import utils_computing as compute
from config import NO_ENERGY_PRICE, VERBOSE
from collections import defaultdict

def verbose_print(*args, **kwargs):
    if VERBOSE:
        print(*args, **kwargs)

def calculate_algorithm_overhead(num_nodes, num_tasks, compute_capacity_tflops=13):
    operations_per_node_task_pair = 100
    pre_calc_operations = num_nodes * num_tasks * operations_per_node_task_pair
    solver_base_operations = 1000
    solver_operations_per_var = 10000
    solver_operations = solver_base_operations + (solver_operations_per_var * num_nodes * num_tasks)
    total_operations = pre_calc_operations + solver_operations
    operations_per_second = compute_capacity_tflops * (10 ** 12)
    theoretical_time = total_operations / operations_per_second
    efficiency_factor = 0.01
    estimated_time = theoretical_time / efficiency_factor
    return estimated_time

def _calculate_utility_nodes(beacon, task, algorithm_overhead, task_rate):
    offloading_time, times, energy_tot, energies = compute.offloading_time_energy(task, beacon, algorithm_overhead)
    energy_price_joule = convert.dollars_per_kwh_to_dollars_per_joule(beacon[2]['dollars_per_kwh'])

    energy_costs = {
        'uplink_energy_cost': energy_price_joule * energies[0],
        'elab_energy_cost': energy_price_joule * energies[1],
        'alg_energy_cost': energy_price_joule * energies[2],
        'ul_bs_energy_cost': energy_price_joule * energies[3],
        'dl_bs_energy_cost': energy_price_joule * energies[4],

    }
    energy_NO =energies[0]+energies[2]+energies[3]
    energy_NO_cost = convert.dollars_per_kwh_to_dollars_per_joule(NO_ENERGY_PRICE) * energy_NO

    deadline_met = offloading_time <= task["D"]

    if not deadline_met:
        utility = 0
    else:
        energy_consumed = energies[1] + energies[4]
        task_payment = convert.to_task_payment(task["D"], task_rate)
        utility = task_payment - energy_price_joule * energy_consumed

    detailed_info = {
        'offloading_time': offloading_time,
        'deadline': task["D"],
        'deadline_met': deadline_met,
        'times': {
            'uplink_time': times[0]+times[1]+times[6]+times[5],
            'downlink_time': times[0]+ times[2] + times[5] + times[7] ,
            'computation_time': times[3],
            'queueing_time': 0,
            'algorithm overhead': times[4],
        },
        'energies': {
            'uplink_energy': energies[3],
            'downlink_energy': energies[0]+energies[4],
            'algorithm energy': energies[2],
            'computation_energy': energies[1],
            'uplink_bs_energy': energies[3],
            'downlink_bs_energy': energies[4],
            'total_energy': energy_tot,
            'device_energy': energies[1] + energies[4],
            'network_operator_energy': energy_NO,
        },
        'costs': energy_costs,
        'energy_NO_cost': energy_NO_cost,
        'task_payment': task_payment if deadline_met else 0,
        'utility': utility

    }
    return utility, energy_NO, detailed_info

def real_value_function(real_beacons, task_assignments, algorithm_overhead, task_rate, verbose=False):
    from collections import defaultdict

    tot_utility = 0
    infos = []

    if verbose:
        verbose_print(f"[REAL] Calcolo della funzione di valore reale per {len(task_assignments)} assegnazioni...")

    for t in task_assignments:
        task = t['task']
        node_id = int(t['node'][1])

        # Cerca il beacon reale corrispondente
        matched_beacons = [b for b in real_beacons if int(b[1]) == node_id]
        if not matched_beacons:
            continue  # Nodo non attivo → task fallito

        beacon = list(matched_beacons[0])  # tupla → lista (mutabile)
        beacon_data = beacon[2]

        # Lascia la datarate reale intatta — NON modificarla artificialmente

        try:
            utility, _, detailed_info = _calculate_utility_nodes(beacon, task, algorithm_overhead, task_rate)
        except Exception:
            continue  # Skip in caso di errore

        if not detailed_info['deadline_met']:
            if verbose:
                verbose_print(f"[REAL] Task {task.get('id')} PERSO: deadline violata nella realtà")
            continue

        tot_utility += utility + detailed_info['energy_NO_cost']
        infos.append({
            'task': t,
            'node': beacon,
            'utility': utility,
            'other': detailed_info
        })

        if verbose:
            verbose_print(f"[REAL] Task {task.get('id')} → Utilità = {utility:.2e}")

    if verbose:
        verbose_print(f"[REAL] Utilità totale reale calcolata: {tot_utility:.2e}")

    return tot_utility, infos



def optimize_task_allocation(beacons, tasks, task_rate, verbose=None):
        prob = pulp.LpProblem("Task_Node_Assignment", pulp.LpMaximize)
        task_ids = [f"T{i}" for i in range(len(tasks))]
        task_map = {task_id: task for task_id, task in zip(task_ids, tasks)}
        node_ids = [f"N{i[1]}" for i in beacons]
        node_map = {node_id: beacon for node_id, beacon in zip(node_ids, beacons)}
        x = {(n, t): pulp.LpVariable(f"Assign_{n}_{t}", cat=pulp.LpBinary) for n in node_ids for t in task_ids}
        y = {n: pulp.LpVariable(f"Use_{n}", cat=pulp.LpBinary) for n in node_ids}
        node_capacities = {n: node_map[n][2]['queue_capacity'] for n in node_ids}

        utilities = {}
        energy_NO_values_price = {}
        detailed_task_node_info = {}

        algorithm_overhead = calculate_algorithm_overhead(len(beacons), len(tasks))

        BIG_M = -10000
        for n in node_ids:
            for t in task_ids:
                try:
                    utility, energy_NO, detailed_info = _calculate_utility_nodes(node_map[n], task_map[t], algorithm_overhead, task_rate)
                    utilities[(n, t)] = utility if detailed_info['deadline_met'] else BIG_M
                    energy_NO_values_price[(n, t)] = -convert.dollars_per_kwh_to_dollars_per_joule(NO_ENERGY_PRICE) * energy_NO
                    detailed_task_node_info[(n, t)] = detailed_info
                except Exception:
                    utilities[(n, t)] = BIG_M
                    energy_NO_values_price[(n, t)] = 0
                    detailed_task_node_info[(n, t)] = None

        prob += pulp.lpSum([
            (utilities[(n, t)] + energy_NO_values_price[(n, t)]) * x[(n, t)]
            for n in node_ids for t in task_ids
        ])

        for t in task_ids:
            prob += pulp.lpSum([x[(n, t)] for n in node_ids]) <= 1
        for n in node_ids:
            prob += pulp.lpSum([x[(n, t)] for t in task_ids]) <= node_capacities[n]
        for n in node_ids:
            for t in task_ids:
                prob += x[(n, t)] <= y[n]
                if utilities[(n, t)] < 0 or (detailed_task_node_info[(n, t)] and not detailed_task_node_info[(n, t)]['deadline_met']):
                    prob += x[(n, t)] == 0
        solver = pulp.PULP_CBC_CMD(msg=VERBOSE)
        status = prob.solve(solver)
        total_utility = pulp.value(prob.objective)
        assigned_node_ids = [n for n in node_ids if y[n].value() > 0.5]
        assigned_nodes = [node_map[n] for n in assigned_node_ids]
        tasks_per_node = {}
        for n in node_ids:
            task_count = sum(1 for t in task_ids if x[(n, t)].value() > 0.5)
            if task_count > 0:
                tasks_per_node[n] = {'beacon': node_map[n], 'count': task_count}
        task_assignments = []
        for t in task_ids:
            for n in node_ids:
                if x[(n, t)].value() > 0.5:
                    task_assignments.append({
                        'task': task_map[t],
                        'node': node_map[n],
                        'utility': utilities[(n, t)],
                        'details': detailed_task_node_info[(n, t)],
                        'NO_utility': energy_NO_values_price[(n, t)]
                    })
        return assigned_nodes, tasks_per_node, task_assignments, total_utility, algorithm_overhead