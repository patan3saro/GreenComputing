"""
Stage 1 — Real-time task allocation (paper Sec. V).

Solves the ILP of the allocation ILP on NOMINAL beacon estimates, after pre-filtering
the (task, executor) candidate domain via the DRO admission rule of Def. 1.

Inputs:
    beacons : list of legacy-format tuples (priority, beacon_id, details, t)
              as returned by `controller.beacons` (nominal store)
    tasks   : list of task dicts with keys 'I', 'O', 'W', 'D', 'arrival_time'

Outputs (paper-compatible):
    assigned_nodes      : list of executor details that received at least one task
    tasks_per_node      : dict {executor_id: {'beacon': details, 'count': k}}
    task_assignments    : list of dicts {task, executor_details, utility,
                                          timing, energy, cost, admission}
    total_utility       : objective value of the ILP [$]
    algorithm_overhead  : estimated decision time [s]

Design notes:
  - Deadline and admission (Def. 1) are applied as a pre-filter that
    shrinks the variable domain before the ILP, rather than as penalty
    terms or inequality constraints inside it.
  - Objective: max sum_{i,tau} ( p_tau - c^off_{i,tau} ) s^i_tau y^i_{tau,z},
    with the NO cost inside c^off.

The returned dictionaries carry typed timing, energy and admission
breakdowns for every evaluated pair.
"""

import math
import pulp

from config import VERBOSE
from config import DRO_ADAPT_MODE, DRO_ADAPT_D0, DRO_ADAPT_RHO0
from utils_convert import to_task_payment
from task_timing import compute_timing, W_MEAN as _W_MEAN
from task_energy import compute_energy
from admission import admit_pair, cost_in_dollars


def verbose_print(*args, **kwargs):
    if VERBOSE:
        print(*args, **kwargs)


# ----------------------------------------------------------------------
#                       Algorithm overhead estimate
# ----------------------------------------------------------------------
def calculate_algorithm_overhead(num_nodes, num_tasks, compute_capacity_tflops=13):
    """
    Coarse estimate of the time the Controller spends solving the ILP.
    Used to charge a CPU-energy term to the NO via `task_energy.no_alg`.

    It is not used as a hard deadline by the optimizer; it only feeds the
    energy/cost accounting and the offloading-time model.
    """
    operations_per_node_task_pair = 100
    pre_calc_operations = num_nodes * num_tasks * operations_per_node_task_pair
    solver_base_operations = 1000
    solver_operations_per_var = 10000
    solver_operations = solver_base_operations + (solver_operations_per_var * num_nodes * num_tasks)
    total_operations = pre_calc_operations + solver_operations
    operations_per_second = compute_capacity_tflops * (10 ** 12)
    theoretical_time = total_operations / operations_per_second
    efficiency_factor = 0.01
    return theoretical_time / efficiency_factor


# ----------------------------------------------------------------------
#                       Pair pre-computation
# ----------------------------------------------------------------------
def _evaluate_pair(task, beacon_details, algorithm_overhead,
                   no_dollars_per_kwh=None, dro_enabled=None,
                   d_w=0.0, lambda_w_mult=1.0):
    """
    For one (task, executor) pair, compute timing, energy, dollar costs,
    and run the admission rule. Returns a dict ready to be fed to the ILP.

    OTTIMIZZAZIONE: d_w (distanza di Wasserstein dichiarato-vs-storia) dipende
    SOLO dal nodo, non dal task -> viene calcolato UNA volta per nodo dal
    chiamante e passato qui, invece di essere ricalcolato per ogni coppia
    (era O(N*T*H), ora O(N*H)). `lambda_w_mult` (default 1.0) scala il raggio
    DRO in modo adattivo; 1.0 -> comportamento classico bit-identico.
    """
    timing = compute_timing(task, beacon_details, algorithm_overhead)
    energy = compute_energy(task, beacon_details, timing, algorithm_overhead)

    cost = cost_in_dollars(
        energy_breakdown=energy,
        executor_dollars_per_kwh=beacon_details['dollars_per_kwh'],
    ) if no_dollars_per_kwh is None else cost_in_dollars(
        energy_breakdown=energy,
        executor_dollars_per_kwh=beacon_details['dollars_per_kwh'],
        no_dollars_per_kwh=no_dollars_per_kwh,
    )

    admit_kwargs = {'wasserstein_distance': d_w, 'lambda_w_mult': lambda_w_mult}
    if dro_enabled is not None:
        admit_kwargs['enabled'] = bool(dro_enabled)

    admission = admit_pair(
        task=task,
        energy_breakdown=energy,
        executor_dollars_per_kwh=beacon_details['dollars_per_kwh'],
        timing_total=timing.total,
        deadline=task['D'],
        **admit_kwargs,
    )

    payment = to_task_payment(task['D'])
    # L'ILP deve VEDERE la coda. `timing.total` include l'attesa M/G/1 stimata
    # sul nodo: se il tempo totale sfora la deadline, la coppia non ha valore
    # per l'obiettivo di the allocation ILP. Senza questo test l'ottimizzatore accatasta i
    # task sul nodo piu' economico (il vincolo di capacita' e' lasco quando la
    # coda e' attiva) e li fa morire ex-post in attesa, mentre i veicoli liberi
    # in copertura restano inutilizzati. Non e' un vincolo nuovo: e' il vincolo
    # di deadline gia' dichiarato in the allocation ILP, applicato sul tempo REALE.
    feasible = admission.admitted and (timing.total <= task['D'])
    # L'obiettivo di the allocation ILP pesa il margine netto per lo SLACK residuo sulla
    # deadline. Il costo reale di un'assegnazione non e' solo energia: occupare
    # quasi tutto il budget temporale (attesa M/G/1 inclusa) espone il task al
    # fallimento e congestiona il nodo per i task successivi. Il fattore e'
    # costante per coppia -> l'ILP resta lineare nelle y (Teoremi 1-2 invariati).
    slack_frac = (task['D'] - timing.total) / task['D'] if task['D'] > 0 else 0.0
    utility = (payment - cost.c_total) * max(slack_frac, 0.0) if feasible else 0.0

    return {
        'utility': utility,
        'feasible': feasible,
        'timing': timing,
        'energy': energy,
        'cost': cost,
        'admission': admission,
        'payment': payment,
        'd_w': d_w,
    }


def _wasserstein_by_node(node_ids, node_details, capacity_history):
    """Calcola d_w UNA volta per nodo (dichiarato vs media storia realizzata).
    Ritorna {node_str: d_w}. Complessita' O(N*H), non O(N*T*H)."""
    out = {}
    if capacity_history is None:
        return {n: 0.0 for n in node_ids}
    for n in node_ids:
        det = node_details[n]
        nid = _extract_id(det)
        hist = capacity_history.get(nid, ())
        d_w = 0.0
        if hist:
            mean_real = sum(hist) / len(hist)
            if mean_real > 0:
                declared = float(det.get('cpu_capacity', 0.0))
                d_w = max(0.0, (declared - mean_real) / mean_real)
        out[n] = d_w
    return out


# ----------------------------------------------------------------------
#                       Main optimization entry point
# ----------------------------------------------------------------------
def _adaptive_lambda_mult(node_ids, node_details, d_bar_W):
    """Per-slot multiplier g in [0,1] for the DRO ambiguity radius.
    g = g_mis(d_bar_W) * g_load(rho_bar), each saturating; mode selects the
    ablation variant. rho_bar = mean over executors of rho = lambda / mu,
    with mu = C_n / E[W] and lambda from the M/G/1 beacon field. 'fixed' -> 1
    (classical radius, bit-identical)."""
    mode = DRO_ADAPT_MODE
    if mode == "fixed":
        return 1.0
    # g_mis: misreporting factor
    g_mis = d_bar_W / (d_bar_W + DRO_ADAPT_D0) if d_bar_W > 0 else 0.0
    # g_load: congestion factor from per-node rho = lambda / (C/E[W])
    rho_vals = []
    for n in node_ids:
        det = node_details[n]
        lam = float(det.get('lambda_tasks_s', 0.0) or 0.0)
        C = float(det.get('cpu_capacity', 0.0))
        if C > 0.0 and lam > 0.0:
            mu = C / _W_MEAN
            if mu > 0.0:
                rho_vals.append(min(lam / mu, 1.0))
    rho_bar = (sum(rho_vals) / len(rho_vals)) if rho_vals else 0.0
    g_load = rho_bar / (rho_bar + DRO_ADAPT_RHO0) if rho_bar > 0 else 0.0
    if mode == "mis":
        return g_mis
    if mode == "load":
        return g_load
    # "product": logical AND of the two complementary signals
    return g_mis * g_load


def optimize_task_allocation(beacons, tasks, task_rate=None, verbose=None,
                             policy="optimal", rng=None, dro_enabled=None,
                             capacity_history=None, audit_sink=None):
    """
    Stage 1 allocation under a selectable policy (paper Sec. V + baselines).

    Policies
    --------
    "optimal"    : solve the ILP of the allocation ILP over DRO-admissible pairs (the
                   paper's method).
    "cloud_only" : restrict the candidate set to cloud executors (id < 0);
                   models the pure cloud-offloading baseline.
    "greedy"     : no ILP; each task independently picks the admissible
                   executor with the highest per-pair utility, subject to
                   per-executor queue capacity, processed in task order.
    "random"     : each task picks a uniformly random admissible executor
                   (respecting capacity); needs `rng`.

    All policies share the SAME per-pair pre-computation (timing, energy,
    admission, cost), so the downstream realized-value pipeline and the
    output schema are identical. Only the SELECTION of pairs differs.

    Parameters
    ----------
    beacons, tasks : see module docstring.
    task_rate : ignored (legacy).
    verbose : optional bool.
    policy : one of {"optimal","cloud_only","greedy","random"}.
    rng : np.random.Generator, required for policy="random".

    Returns
    -------
    assigned_nodes, tasks_per_node, task_assignments, total_utility,
    algorithm_overhead
    """
    if not beacons or not tasks:
        return [], {}, [], 0.0, 0.0

    task_ids = [f"T{i}" for i in range(len(tasks))]
    task_map = {tid: t for tid, t in zip(task_ids, tasks)}

    node_ids = [f"N{b[1]}" for b in beacons]
    node_details = {nid: b[2] for nid, b in zip(node_ids, beacons)}

    # cloud_only: drop non-cloud candidates up front
    if policy == "cloud_only":
        node_ids = [n for n in node_ids
                    if str(node_details[n].get('type', '')).lower() == 'cloud']
        node_details = {n: node_details[n] for n in node_ids}
        if not node_ids:
            return [], {}, [], 0.0, 0.0

    algorithm_overhead = calculate_algorithm_overhead(len(beacons), len(tasks))

    # --- d_w UNA volta per nodo (ottimizzazione + base per l'adattivita') ---
    d_w_by_node = _wasserstein_by_node(node_ids, node_details, capacity_history)
    # d_bar_W: misreporting medio di sistema stimato (media dei d_w sui nodi con
    # storia). Aggregato una volta per slot: usato per il raggio DRO adattivo.
    _dw_hist = [d_w_by_node[n] for n in node_ids if capacity_history is not None]
    d_bar_W = (sum(_dw_hist) / len(_dw_hist)) if _dw_hist else 0.0
    # Moltiplicatore del raggio (1.0 = comportamento fisso, bit-identico).
    # In modalita' adattiva scala con misreporting stimato x congestione.
    lambda_w_mult = _adaptive_lambda_mult(node_ids, node_details, d_bar_W)

    # --- Pre-compute every (n, t) pair + costruisci gli ammissibili in un colpo ---
    pair_info = {}
    admissible = {}
    for n in node_ids:
        d_w_n = d_w_by_node[n]
        for t in task_ids:
            try:
                info = _evaluate_pair(
                    task=task_map[t],
                    beacon_details=node_details[n],
                    algorithm_overhead=algorithm_overhead,
                    dro_enabled=dro_enabled,
                    d_w=d_w_n,
                    lambda_w_mult=lambda_w_mult,
                )
                pair_info[(n, t)] = info
                if info['feasible']:
                    admissible[(n, t)] = info
            except Exception as exc:
                verbose_print(f"[opt] pair ({n},{t}) failed: {exc}")
                pair_info[(n, t)] = None

    # --- Trust audit: record per-vehicle DRO decision (d_W, admitted) ---
    # d_W depends only on the executor's declared-vs-realized capacity, not
    # on the task, so we summarize one row per executor. "admitted_any" is
    # True if at least one (executor, task) pair passed admission; a vehicle
    # rejected on every task was effectively filtered out by the DRO rule.
    if audit_sink is not None:
        for n in node_ids:
            nid = int(n[1:]) if n[1:].lstrip('-').isdigit() else n
            d_w_vals = [pair_info[(n, t)]['d_w']
                        for t in task_ids
                        if pair_info.get((n, t)) is not None]
            adm_flags = [pair_info[(n, t)]['admission'].admitted
                         for t in task_ids
                         if pair_info.get((n, t)) is not None]
            dropped_dro = [
                ('dro' in (pair_info[(n, t)]['admission'].reason or '').lower())
                for t in task_ids
                if pair_info.get((n, t)) is not None
            ]
            if not d_w_vals:
                continue
            audit_sink.append({
                'node_id': nid,
                'd_w': max(d_w_vals),
                'admitted_any': any(adm_flags),
                'rejected_all': not any(adm_flags),
                'dro_rejected': any(dropped_dro),
            })

    # --- Patane et al. VCCFirst (Computer Networks 2025, arXiv:2507.15670) ---
    # Faithful reproduction of their Section 4 "VCCFirst" strategy, using OUR
    # system parameters (not theirs):
    #   * Candidates are ONLY vehicles that currently broadcast a beacon and
    #     have free capacity (Sec. 3.3: a busy or out-of-range vehicle does
    #     not appear in the Controller's list). We therefore restrict to
    #     vehicles whose pair is computable AND reachable (finite offloading
    #     time, i.e. data rate > 0 at beacon time).
    #   * Among those, ONE is selected uniformly at RANDOM (they are treated
    #     as equivalent), with no deadline optimization and no DRO.
    #   * If no vehicle is available, the task goes to the CLOUD as backup
    #     (assumed to always have resources).
    #   * One task at a time per vehicle (queue_capacity gate).
    # Mobility-induced failures are NOT engineered here: they emerge ex-post
    # when a selected vehicle leaves coverage during execution (their Fig. 7
    # red bar), which our Stage-2 realized check captures as a lost task.
    if policy == "patane":
        if rng is None:
            import numpy as _np
            rng = _np.random.default_rng()
        cloud_ids = [n for n in node_ids
                     if str(node_details[n].get('type', '')).lower() == 'cloud']
        veh_ids = [n for n in node_ids
                   if str(node_details[n].get('type', '')).lower() != 'cloud']
        remaining_cap = {n: node_details[n].get('queue_capacity', 1)
                         for n in node_ids}
        all_pairs = {(n, t): pair_info[(n, t)]
                     for n in node_ids for t in task_ids
                     if pair_info.get((n, t)) is not None}

        def _reachable(n, t):
            # A vehicle that broadcasts a usable beacon has a finite
            # offloading time (data rate > 0). Unreachable vehicles would
            # not be in the Controller's list, so we exclude them here.
            info = all_pairs.get((n, t))
            if info is None:
                return False
            ot = info['timing'].total
            return math.isfinite(ot)

        selected = []
        for t in task_ids:
            v_cands = [n for n in veh_ids
                       if remaining_cap.get(n, 0) > 0 and _reachable(n, t)]
            if v_cands:
                pick = v_cands[int(rng.integers(len(v_cands)))]
            else:
                c_cands = [n for n in cloud_ids
                           if remaining_cap.get(n, 0) > 0 and (n, t) in all_pairs]
                if not c_cands:
                    continue
                pick = c_cands[int(rng.integers(len(c_cands)))]
            selected.append((pick, t))
            remaining_cap[pick] -= 1
        total_utility = sum(all_pairs[(n, t)]['utility'] for (n, t) in selected)
        return _build_outputs(
            selected, all_pairs, task_map, node_details, algorithm_overhead,
            total_utility,
        )

    if not admissible:
        verbose_print("[opt] no admissible (task, executor) pair; empty allocation")
        return [], {}, [], 0.0, algorithm_overhead

    # --- Selection of pairs depends on the policy ---
    if policy in ("greedy", "random"):
        selected = _heuristic_select(
            admissible, task_ids, node_ids, node_details,
            policy=policy, rng=rng,
        )
        total_utility = sum(admissible[(n, t)]['utility'] for (n, t) in selected)
        return _build_outputs(
            selected, admissible, task_map, node_details, algorithm_overhead,
            total_utility,
        )

    # --- Otherwise (optimal / cloud_only): solve the ILP ---
    prob = pulp.LpProblem("Stage1_TaskAllocation", pulp.LpMaximize)

    x = {(n, t): pulp.LpVariable(f"Assign_{n}_{t}", cat=pulp.LpBinary)
         for (n, t) in admissible}

    # Objective: sum_{(n,t) admissible} utility_{n,t} * x_{n,t}
    # SCALA NUMERICA: le utilita' sono ~1e-6 dollari, pericolosamente vicine
    # alle tolleranze interne dei solver MIP (verificato via brute-force: a
    # scala 1e-6 sia CBC che HiGHS restituiscono occasionalmente ottimi
    # SBAGLIATI; a scala x1e6 entrambi sono esatti). Moltiplicare l'obiettivo
    # per una costante positiva NON cambia l'insieme delle soluzioni ottime
    # (argmax invariato) -> matematicamente identico, numericamente robusto.
    # Il valore riportato viene ri-diviso per la scala (unita' invariate).
    _OBJ_SCALE = 1.0e6
    prob += pulp.lpSum(
        (_OBJ_SCALE * pair_info[(n, t)]['utility']) * x[(n, t)] for (n, t) in x
    )

    # Constraints
    # the one-executor-per-task constraint: at most one executor per task
    for t in task_ids:
        terms = [x[(n, t)] for n in node_ids if (n, t) in x]
        if terms:
            prob += pulp.lpSum(terms) <= 1, f"OneExec_{t}"

    # the executor quota constraint: executor queue capacity
    for n in node_ids:
        cap = node_details[n].get('queue_capacity', 1)
        terms = [x[(n, t)] for t in task_ids if (n, t) in x]
        if terms:
            prob += pulp.lpSum(terms) <= cap, f"Cap_{n}"

    # Solve.
    # HiGHS IN-PROCESS al posto di CBC-subprocess: il profiler mostrava che il
    # 37% del runtime era posix.waitpid (fork/exec di CBC ad OGNI slot, 1193
    # volte/run). HiGHS gira dentro il processo Python -> zero overhead di
    # processo. EQUIVALENZA GARANTITA:
    #   - il MODELLO (variabili/obiettivo/vincoli) e' costruito identico sopra;
    #   - gapRel=0 forza l'ottimo PROVATO (HiGHS di default userebbe gap 1e-4);
    #   - threads=1 -> deterministico e coerente coi worker paralleli dello
    #     sweep (niente oversubscription con --workers N);
    #   - fallback automatico a CBC se highspy non e' installato.
    # NOTA onesta: su soluzioni OTTIME MULTIPLE (pareggi di utilita') i due
    # solver possono selezionare allocazioni diverse a parita' di obiettivo.
    prob.solve(_make_solver(verbose))

    total_utility = (pulp.value(prob.objective) or 0.0) / _OBJ_SCALE

    selected = [(n, t) for (n, t), var in x.items()
                if var.value() is not None and var.value() > 0.5]

    return _build_outputs(
        selected, admissible, task_map, node_details, algorithm_overhead,
        total_utility,
    )


def _heuristic_select(admissible, task_ids, node_ids, node_details,
                      policy, rng=None):
    """
    Greedy or random per-task selection respecting per-executor queue
    capacity. Returns a list of selected (node_id, task_id) pairs.
    """
    remaining_cap = {n: node_details[n].get('queue_capacity', 1) for n in node_ids}
    selected = []
    for t in task_ids:
        cands = [(n, t) for n in node_ids
                 if (n, t) in admissible and remaining_cap.get(n, 0) > 0]
        if not cands:
            continue
        if policy == "greedy":
            best = max(cands, key=lambda nt: admissible[nt]['utility'])
        else:  # random
            if rng is None:
                import numpy as _np
                rng = _np.random.default_rng()
            best = cands[int(rng.integers(len(cands)))]
        selected.append(best)
        remaining_cap[best[0]] -= 1
    return selected


def _build_outputs(selected, admissible, task_map, node_details,
                   algorithm_overhead, total_utility):
    """
    Assemble the (assigned_nodes, tasks_per_node, task_assignments,
    total_utility, algorithm_overhead) tuple from a list of selected
    (node_id, task_id) pairs. Shared by all policies.
    """
    task_assignments = []
    tasks_per_node = {}
    selected_node_ids = set()

    for (n, t) in selected:
        info = admissible[(n, t)]
        assignment = {
            'task': task_map[t],
            'node': (None, _extract_id(node_details[n]), node_details[n], None),
            'utility': info['utility'],
            'details': {
                'offloading_time': info['timing'].total,
                'deadline': task_map[t]['D'],
                'deadline_met': info['timing'].total <= task_map[t]['D'],
                'timing': info['timing'].as_dict(),
                'energy': info['energy'].as_dict(),
                'cost': {
                    'executor_dollars': info['cost'].c_executor,
                    'no_dollars': info['cost'].c_no,
                    'total_dollars': info['cost'].c_total,
                },
                'payment_dollars': info['payment'],
                'admission': {
                    'cvar_bound': info['admission'].cvar_bound,
                    'cost_hat': info['admission'].cost_hat,
                    'cost_std_hat': info['admission'].cost_std_hat,
                    'reason': info['admission'].reason,
                },
            },
            'NO_utility': 0.0,
        }
        task_assignments.append(assignment)
        tasks_per_node.setdefault(n, {'beacon': node_details[n], 'count': 0})
        tasks_per_node[n]['count'] += 1
        selected_node_ids.add(n)

    assigned_nodes = [node_details[n] for n in selected_node_ids]
    return assigned_nodes, tasks_per_node, task_assignments, total_utility, algorithm_overhead


# ----------------------------------------------------------------------
#                       Solver selection (HiGHS in-process)
# ----------------------------------------------------------------------
# Rilevato UNA volta all'import. HiGHS (highspy) gira in-process: elimina il
# fork/exec+waitpid di CBC ad ogni slot. Fallback: CBC identico allo storico.
try:                                             # pragma: no cover
    import highspy as _highspy                   # noqa: F401
    _HIGHS_OK = True
except ImportError:                              # pragma: no cover
    _HIGHS_OK = False


def _make_solver(verbose):
    """Solver per l'ILP di Stage 1. HiGHS in-process (gapRel=0 -> ottimo
    provato, threads=1 -> deterministico e coerente coi worker paralleli);
    fallback CBC-subprocess se highspy manca."""
    msg = bool(verbose) if verbose is not None else False
    if _HIGHS_OK:
        try:
            return pulp.HiGHS(msg=msg, gapRel=0, threads=1)
        except TypeError:
            # versioni pulp piu' vecchie senza 'threads' kwarg
            return pulp.HiGHS(msg=msg, gapRel=0)
    return pulp.PULP_CBC_CMD(msg=msg)


def _extract_id(details):
    """Robust id extraction from a beacon details dict."""
    return details.get('beacon_id') if 'beacon_id' in details else details.get('id', None)
