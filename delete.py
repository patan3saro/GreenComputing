import numpy as np


def generate_exponential_tasks(rate, num_users, optimization_window=None):

    # Finestra di default di 1 secondo se non specificata
    start_time, end_time = (0, MAX_SIMULATION_TIME_MS) if optimization_window is None else optimization_window

    # Converti da millisecondi a secondi per calcoli più semplici
    start_time_sec = start_time / 1000
    end_time_sec = end_time / 1000
    window_duration_sec = end_time_sec - start_time_sec

    # Calcola il tasso totale
    total_rate = rate * num_users  # task per secondo

    # Genera il numero di task usando la distribuzione di Poisson
    n_tasks = np.random.poisson(lam=total_rate * window_duration_sec)

    # Genera tempi di arrivo casuali uniformi all'interno della finestra e li ordina
    arrival_times_sec = np.random.uniform(start_time_sec, end_time_sec, size=n_tasks)

    arrival_times_sec.sort()  # Ordina per mantenere l'ordine cronologico
    # Crea dizionari task in modo efficiente
    tasks = [{
        "id": i,
        "arrival_time": arrival_time,  # in secondi
        "I": 1000000 * 8,  # bit - input data size
        "O": 1000000 * 8,  # bit - output data size
        "W": 500000000,  # 500 Mcycles - workload
        "D": 0.010  # deadline in secondi
    } for i, arrival_time in enumerate(arrival_times_sec)]

    print(
        f"Generati {len(tasks)} task per {num_users} utenti a tasso {rate}/sec nella finestra [{start_time_sec}-{end_time_sec}]sec")
    return tasks




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

    tasks = [{
        "id": i,
        "arrival_time": arrival_time,  # in secondi
        "I": task_input_size,  # bit
        "O": task_output_size,  # bit
        "W": task_workload,  # 500 Mcycles
        "D": deadline  # in secondi
    } for i, (arrival_time, deadline) in enumerate(zip(arrival_times_sec, deadlines))]

    print(
        f"Generati {len(tasks)} task per {num_users} utenti a tasso {rate}/sec nella finestra [{start_time_sec}-{end_time_sec}]sec")
    return tasks

