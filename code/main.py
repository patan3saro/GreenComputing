"""
Main simulator — orchestrator of Stage 1 (real-time allocation) and Stage 2
(ex-post sharing) over the simulation horizon.

The pipeline at each slot z is:

    Stage 1
    1. Update vehicle positions from the SUMO mobility trace.
    2. Compute instantaneous 5G data rates per vehicle.
    3. Emit periodic beacons (nominal + realized) and ingest into the Controller.
    4. Clean expired beacons.
    5. Allocate via `optimizer.optimize_task_allocation`.

    Stage 2 (off the critical path)
    6. Recompute realized timing/energy/cost on realized beacons.
    7. Apply 50/50 + c_i sharing (the sharing rule.
    8. Verify the core and project onto it if needed (Theorem 1).

Outputs go to `RESULTS_DIR_BASE / run_id /`:
    - tasks.csv
    - beacons.csv, beacons_real.csv
    - allocations.jsonl
    - realizations.jsonl
    - lost_tasks.jsonl
    - summary.json
"""

import json
import math
import os
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from config import (
    CITY, CITY_BBOX,
    NUM_VEHICLES, NUM_CLOUDS, USERS_NUMBER,
    MAX_SIMULATION_TIME_MS, TIME_STEP_MS, WINDOW_TASK_COLLECTION,
    TASK_RATE, SEED_RANDOM, START_TIME, WARMUP_MS,
    CLOUD_CPU_CAPACITY, VEHICLE_CPU_CAPACITY,
    CAP_MAX, CAP_STD, CAP_DIST,
    VEHICLE_QUEUE_CAPACITY, CLOUD_QUEUE_CAPACITY,
    TASK_WORKLOAD, TASK_INPUT_SIZE, TASK_OUTPUT_SIZE,
    POSSIBLE_TASK_TYPES, TASK_TYPE_TUPLE,
    PRICE_KWH, NO_ENERGY_PRICE,
    CONTROLLER_CPU_POWER, VEHICLE_CPU_POWER, ENERGY_AVAILABLE,
    GNB_TX_POWER_5G, GNB_TX_POWER_INET, UE_TX_POWER,
    DR_INET,
    COVERAGE_RADIUS, PEDESTRIAN_UE_DISTANCE, CLOUD_DISTANCE,
    VEHICLE_BEACON_INTERVAL_MS, CLOUD_BEACON_INTERVAL_MS,
    BEACON_EXPIRATION_MS,
    MISREPORTING_FRACTION,
    CLOUD_ID, VERBOSE, RESULTS_DIR_BASE,
)
from vehicle import Vehicle, PRESENCE_TOL_S
from cloud import Cloud
from controller import Controller
from network_manager import (
    set_all_vehicles_data_rate_5g_standard,
    cloud_wired_datarate,
)
from mobility_manager import extract_city_traffic
from optimizer import optimize_task_allocation
from realized_value import realized_value_function
from utils_convert import ms_to_seconds, seconds_to_ms
from task_timing import calculate_dwell_time_and_distance


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _is_busy(node_id, busy_nodes):
    return any(b['busy_id'] == node_id for b in busy_nodes)


def _filter_tasks_in_window(tasks, t0_ms, t1_ms):
    t0_s = ms_to_seconds(t0_ms)
    t1_s = ms_to_seconds(t1_ms)
    return [t for t in tasks if t0_s <= t['arrival_time'] <= t1_s]


def _safe_serialize(obj):
    """Best-effort JSON serializer for dataclasses, ndarrays, etc."""
    if hasattr(obj, 'as_dict'):
        return obj.as_dict()
    if hasattr(obj, '__dict__'):
        return obj.__dict__
    return str(obj)


# ----------------------------------------------------------------------
# Heterogeneous per-vehicle spare capacity
# ----------------------------------------------------------------------
def _sample_vehicle_capacities(n, mean, std, c_max, dist, rng):
    """Sample n per-vehicle spare capacities on the bounded support [0, c_max],
    with EXACT target (mean, std). std<=0 -> homogeneous (all = mean), which
    reproduces the legacy single-scalar behavior.

      - "beta"      : Beta rescaled to [0, c_max]. Bounded both sides, exact
                      moments, no normalization constant to handle by hand.
      - "truncnorm" : Gaussian truncated to [0, c_max]; the normalization
                      constant Z = Phi(beta)-Phi(alpha) is handled and the
                      pre-truncation (mu0, sig0) solved so the POST-truncation
                      moments match (mean, std).
    """
    mean = float(mean)
    std = float(std)
    c_max = float(c_max)
    if std <= 0.0:
        return np.full(n, mean)                       # homogeneous (legacy)
    if not (0.0 < mean < c_max):
        raise ValueError(
            f"heterogeneous capacity needs 0 < cap_mean({mean:.4g}) "
            f"< cap_max({c_max:.4g})")
    if dist == "beta":
        m = mean / c_max
        v = (std / c_max) ** 2
        v_max = m * (1.0 - m)
        if v >= v_max:
            raise ValueError(
                f"cap_std={std:.4g} too large for cap_mean={mean:.4g}, "
                f"cap_max={c_max:.4g}: max std ~ {c_max * math.sqrt(v_max):.4g}. "
                f"Lower cap_std or raise cap_max.")
        common = m * (1.0 - m) / v - 1.0
        a, b = m * common, (1.0 - m) * common
        caps = c_max * rng.beta(a, b, size=n)
    elif dist == "truncnorm":
        from scipy import stats
        from scipy.optimize import fsolve
        lo, hi = 0.0, c_max
        def _moments(mu0, sig0):
            al, be = (lo - mu0) / sig0, (hi - mu0) / sig0
            Z = stats.norm.cdf(be) - stats.norm.cdf(al)   # normalization const
            if Z <= 0:
                return float('nan'), float('nan')
            pa, pb = stats.norm.pdf(al), stats.norm.pdf(be)
            mm = mu0 + sig0 * (pa - pb) / Z
            vv = sig0 ** 2 * (1.0 + (al * pa - be * pb) / Z - ((pa - pb) / Z) ** 2)
            return mm, math.sqrt(max(vv, 0.0))
        def _eqs(p):
            mu0, sig0 = p
            sig0 = max(sig0, 1e-12)
            mm, ss = _moments(mu0, sig0)
            if not np.isfinite(mm):
                return [1e9, 1e9]
            return [mm - mean, ss - std]
        mu0, sig0 = fsolve(_eqs, [mean, std])
        sig0 = max(sig0, 1e-12)
        m_hat, s_hat = _moments(mu0, sig0)
        if not (abs(m_hat - mean) < 1e-3 * c_max and abs(s_hat - std) < 1e-3 * c_max):
            raise ValueError(
                f"(cap_mean={mean:.4g}, cap_std={std:.4g}) not realizable as a "
                f"truncated normal on [0, {c_max:.4g}] (max std ~ "
                f"{c_max / math.sqrt(12):.4g}). Lower cap_std or raise cap_max.")
        caps = stats.truncnorm((lo - mu0) / sig0, (hi - mu0) / sig0,
                               loc=mu0, scale=sig0).rvs(size=n, random_state=rng)
    else:
        raise ValueError("cap_dist must be 'beta' or 'truncnorm'")
    return np.clip(caps, 0.0, c_max)


def _compute_n_eff(caps):
    """Effective number of servers N_eff = (sum c)^2 / sum c^2.
    Equals N for homogeneous capacity, < N for heterogeneous (~ N/(1+CV^2))."""
    c = np.asarray(caps, dtype=float)
    s = c.sum()
    return float(s * s / np.sum(c * c)) if np.any(c) else 0.0


# ----------------------------------------------------------------------
# Task generation
# ----------------------------------------------------------------------
def generate_exponential_tasks(rate, input_size, output_size, workload,
                                num_users, max_sim_time_ms,
                                task_type_probs, task_type_deadlines, rng,
                                workload_tuple=None, workload_probs=None):
    """
    Poisson task arrivals over the simulation window.

    Returns a list of dicts with keys: id, arrival_time [s], I, O, W, D [s].

    If `workload_tuple` and `workload_probs` are supplied, each task draws
    its W from that categorical distribution (modelling the realistic mix
    of automotive AI inference workloads, from lightweight classifiers
    ~1e8 OPS to planning transformers ~1e12 OPS). Otherwise all tasks use
    the scalar `workload`.
    """
    end_time_s = ms_to_seconds(max_sim_time_ms)
    total_rate = rate * num_users
    n_tasks = int(rng.poisson(total_rate * end_time_s))

    arrivals = rng.uniform(0.0, end_time_s, size=n_tasks)
    arrivals.sort()

    base_deadlines = rng.choice(task_type_deadlines, size=n_tasks, p=task_type_probs)
    # NV noise around each chosen bucket
    deadlines = np.array([rng.normal(v, v * 0.1) for v in base_deadlines]) / 1000.0

    if workload_tuple is not None and workload_probs is not None:
        workloads = rng.choice(np.asarray(workload_tuple, dtype=float),
                               size=n_tasks, p=workload_probs)
    else:
        workloads = np.full(n_tasks, workload)

    tasks = [
        {
            'id': i,
            'arrival_time': float(at),
            'I': input_size,
            'O': output_size,
            'W': float(w),
            'D': float(max(d, 0.001)),     # clamp positive
        }
        for i, (at, d, w) in enumerate(zip(arrivals, deadlines, workloads))
    ]
    return tasks


# ----------------------------------------------------------------------
# Simulator
# ----------------------------------------------------------------------
class Simulator:
    """
    End-to-end simulator orchestrating Stage 1 and Stage 2.
    """

    def __init__(self,
                 # Identification
                 run_id="default",
                 results_dir_base=RESULTS_DIR_BASE,
                 # Mobility
                 city=CITY, city_bbox=CITY_BBOX,
                 num_vehicles=NUM_VEHICLES, num_clouds=NUM_CLOUDS,
                 users_number=USERS_NUMBER,
                 # Time
                 max_simulation_time_ms=MAX_SIMULATION_TIME_MS,
                 time_step_ms=TIME_STEP_MS,
                 window_task_collection=WINDOW_TASK_COLLECTION,
                 start_time_ms=START_TIME,
                 warmup_ms=WARMUP_MS,
                 # Tasks
                 task_rate=TASK_RATE,
                 task_input_size=TASK_INPUT_SIZE,
                 task_output_size=TASK_OUTPUT_SIZE,
                 task_workload=TASK_WORKLOAD,
                 # Beacons
                 vehicle_beacon_interval_ms=VEHICLE_BEACON_INTERVAL_MS,
                 cloud_beacon_interval_ms=CLOUD_BEACON_INTERVAL_MS,
                 beacon_expiration_ms=BEACON_EXPIRATION_MS,
                 # Hardware
                 vehicle_cpu_capacity=VEHICLE_CPU_CAPACITY,
                 # Heterogeneous per-vehicle spare capacity (paper Sec. III).
                 # cap_mean: mean spare. None -> falls back to
                 #   vehicle_cpu_capacity (so existing sweeps that set
                 #   vehicle_cpu_capacity keep working unchanged).
                 # cap_std : heterogeneity std. 0 -> homogeneous (legacy).
                 # cap_max : physical ceiling [0, cap_max] (30% of peak).
                 # cap_dist: "beta" | "truncnorm".
                 cap_mean=None,
                 cap_std=CAP_STD,
                 cap_max=CAP_MAX,
                 cap_dist=CAP_DIST,
                 cloud_cpu_capacity=CLOUD_CPU_CAPACITY,
                 vehicle_cpu_power=VEHICLE_CPU_POWER,
                 vehicle_queue_capacity=VEHICLE_QUEUE_CAPACITY,
                 cloud_queue_capacity=CLOUD_QUEUE_CAPACITY,
                 ue_power=UE_TX_POWER,
                 # Energy
                 price_kwh=PRICE_KWH,
                 energy_available=ENERGY_AVAILABLE,
                 # Strategic behavior
                 misreporting_fraction=MISREPORTING_FRACTION,
                 misreport_intensity=0.3,    # rho used by the chosen liars
                 # Allocation policy (paper method and baselines)
                 policy="optimal",           # optimal|cloud_only|greedy|random
                 # DRO admission toggle (None -> use config default)
                 dro_enabled=None,
                 # Cloud Internet delay override [s]. None keeps the global
                 # remote-cloud value (config.INET_DELAY, 35 ms, Verizon).
                 # Set to a few ms to model an EDGE/MEC server co-located at
                 # the gNodeB (IEEE MEC latency studies) for the edge_only
                 # ablation baseline.
                 cloud_inet_delay_s=None,
                 # M/M/1 queueing (uniform for cloud, edge, vehicles).
                 #   mm1_queue : master switch. False -> no queue wait
                 #               (lambda stays 0 -> bit-identical to the
                 #               pre-M/M/1 model, for A/B verification).
                 #   mm1_tau_ms: time constant of the per-node arrival-rate
                 #               EWMA [ms]. ~1 s smooths the per-slot spikes so
                 #               a single task in a 5 ms slot is not read as a
                 #               huge instantaneous rate.
                 mm1_queue=True,
                 mm1_tau_ms=1000.0,
                 # Reproducibility
                 seed=SEED_RANDOM,
                 verbose=VERBOSE,
                 ):
        self.run_id = run_id
        self.results_dir = Path(results_dir_base) / run_id
        self.results_dir.mkdir(parents=True, exist_ok=True)

        # Single RNG shared by all stochastic modules (M1 fix)
        self.rng = np.random.default_rng(seed)
        self.seed = seed

        # Persist config knobs
        self.city = city
        self.city_bbox = city_bbox
        self.num_vehicles = num_vehicles
        self.num_clouds = num_clouds
        self.users_number = users_number
        self.max_sim_ms = max_simulation_time_ms
        self.dt_ms = time_step_ms
        self.window_ms = window_task_collection
        self.start_ms = start_time_ms
        self.warmup_ms = int(warmup_ms)
        self._warmup_s = ms_to_seconds(self.warmup_ms)
        self.task_rate = task_rate
        self.task_I = task_input_size
        self.task_O = task_output_size
        self.task_W = task_workload
        self.v_beacon_ms = vehicle_beacon_interval_ms
        self.c_beacon_ms = cloud_beacon_interval_ms
        self.beacon_expiry_ms = beacon_expiration_ms
        self.vehicle_cpu_capacity = vehicle_cpu_capacity
        # Heterogeneous spare capacity config. cap_mean defaults to the
        # (possibly overridden) homogeneous vehicle_cpu_capacity, so legacy
        # runs and sweeps that only set vehicle_cpu_capacity are unaffected.
        self.cap_mean = vehicle_cpu_capacity if cap_mean is None else float(cap_mean)
        self.cap_std = float(cap_std)
        self.cap_max = float(cap_max)
        self.cap_dist = cap_dist
        self._n_eff = 0.0                # set in _build_vehicles_and_mobility
        self._concurrent_mean = 0.0      # media veicoli concorrenti per-slot
        self.cloud_cpu_capacity = cloud_cpu_capacity
        self.vehicle_cpu_power = vehicle_cpu_power
        self.vehicle_queue_capacity = vehicle_queue_capacity
        self.cloud_queue_capacity = cloud_queue_capacity
        self.ue_power = ue_power
        self.price_kwh = price_kwh
        self.energy_available = energy_available
        self.misreporting_fraction = misreporting_fraction
        self.misreport_intensity = misreport_intensity
        self.policy = policy
        self.dro_enabled = dro_enabled
        # Edge-latency override for the edge_only baseline. Patching the
        # task_timing module global is process-local; under multiprocessing
        # each worker process handles runs sequentially, so this is safe and
        # does not leak across parallel runs. None -> keep remote-cloud delay.
        self.cloud_inet_delay_s = cloud_inet_delay_s

        # --- M/G/1 queueing state (uniform for all executors) ------------
        self._mm1_enabled = bool(mm1_queue)
        self._mm1_tau_ms = float(mm1_tau_ms)
        # Precompute the EWMA constants ONCE (avoid per-slot divisions):
        #   alpha      = window / tau          (EWMA weight)
        #   inv_win_s  = 1 / window_seconds    (instantaneous-rate scale)
        _w_ms = float(window_task_collection)
        self._mm1_inv_win_s = 1000.0 / _w_ms
        self._mm1_alpha = min(1.0, _w_ms / max(self._mm1_tau_ms, _w_ms))
        self._mm1_floor = 1e-3            # prune idle nodes below this rate
        # EWMA of arrival rate lambda [tasks/s] per node id; empty at start
        # -> zero wait on the first slots -> warmup-safe. Pruned when idle
        # so memory stays O(#actively-loaded executors), not O(#ids ever).
        self._node_lambda = {}
        self._lambda_counts = {}         # reused per-slot scratch (no realloc)
        # With M/G/1 ON every node is a REAL queue: tasks WAIT rather than
        # being turned away, and the queue wait (not an external busy lock)
        # is what serializes a node. So (i) lift the per-slot ILP backlog cap
        # for vehicles from 1 to a large finite value, letting tasks queue,
        # and (ii) disable the vehicle busy-exclusion (redundant with, and
        # double-counting, the M/G/1 wait). Both revert automatically when
        # mm1_queue=False (legacy queue=1 + busy behaviour).
        if self._mm1_enabled:
            self.vehicle_queue_capacity = max(self.vehicle_queue_capacity, 256)
        if cloud_inet_delay_s is not None:
            import task_timing
            task_timing.INET_DELAY = float(cloud_inet_delay_s)
        self.verbose = verbose

        # Lazily-created entities
        self.vehicles = []
        self.clouds = []
        self.controller = None
        self.mobility_df = None
        self.tasks = []

        # Tracing buffers (M4 fix: list-of-dicts, single DataFrame at the end)
        self._nom_beacon_rows = []
        self._real_beacon_rows = []
        self._task_rows = []

        # Counters
        self.task_allocation_count = 0
        self.tasks_processed = 0         # assigned AND deadline met (Stage 2)
        self.tasks_generated = 0
        # A task that arrives in a slot is either:
        #   (a) assigned by Stage-1 ILP and meets its deadline -> processed
        #   (b) assigned but fails realization in Stage 2       -> lost_stage2
        #   (c) never assigned (no executor can meet the firm
        #       deadline, or DRO admission rejected it)          -> unassigned
        # (b)+(c) together are the FAILURES per the paper's definition
        # ("a task for which no node completes within the firm deadline").
        self.tasks_unassigned = 0        # case (c)
        self.tasks_lost_stage2 = 0       # case (b)
        self.wasted_cost_dollars = 0.0   # energy cost spent on tasks later lost
        self.total_objective = 0.0       # Stage 1 sum of objectives
        self.total_realized = 0.0        # Stage 2 sum of Pi
        # DRO detection confusion matrix (vs ground-truth liar labels):
        #   tp = liar correctly rejected, fp = honest wrongly rejected,
        #   tn = honest correctly kept,   fn = liar wrongly kept.
        # Accumulated over all slots and all evaluated vehicles.
        self._trust_tp = 0
        self._trust_fp = 0
        self._trust_tn = 0
        self._trust_fn = 0
        # Per-executor history of REALIZED cpu_capacity, for the
        # Wasserstein-based misreporting detector (robust admission).
        # Maps vehicle_id (or cloud_id) -> list of realized capacities.
        self.capacity_history = {}

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------
    def _build_vehicles_and_mobility(self):
        # Genera la traccia per (warmup + run) secondi: il warm-up serve a
        # riempire la rete (i veicoli entrano da rete vuota). La MISURA poi
        # parte a t=warmup, dove la rete e' a regime (vedi run()).
        warmup_s = ms_to_seconds(self.warmup_ms)
        run_s = ms_to_seconds(self.max_sim_ms)
        sim_time_s = warmup_s + run_s
        out_dir, df = extract_city_traffic(
            random_seed=self.seed,
            city_name=self.city, country_code="it",
            bbox=self.city_bbox,
            simulation_time=sim_time_s,
            time_step=0.1,
            num_vehicles=self.num_vehicles,
        )
        if df is None or df.empty:
            raise RuntimeError(f"[mobility] no traffic extracted from {out_dir}")
        df = df.sort_values(by=['id', 'time'], ascending=[True, True])

        # La traccia resta INTERA [0, warmup+run] (il lookup nel loop usa
        # current_s + warmup). Veicoli, N_eff e liar vengono pero' contati sulla
        # sola finestra a REGIME [warmup, warmup+run], non sul transitorio.
        if self.warmup_ms > 0:
            win = df[(df['time'] >= warmup_s) & (df['time'] <= warmup_s + run_s)]
            if win.empty:
                raise RuntimeError(
                    f"[mobility] finestra a regime [{warmup_s},{warmup_s+run_s}]s vuota: "
                    f"warmup troppo lungo per la traccia. Riduci WARMUP_MS.")
        else:
            win = df

        # Decide which vehicles are misreporters
        unique_vids = sorted(win['id'].unique())
        n_liars = int(round(self.misreporting_fraction * len(unique_vids)))
        liars = set(self.rng.choice(unique_vids, size=n_liars, replace=False)) if n_liars > 0 else set()
        # Store ground-truth liar identities for trust/detection accounting:
        # this lets us later compare DRO admission decisions against the
        # true honest/liar label (confusion matrix, detection rate).
        self.liar_ids = set(int(v) for v in liars)

        # Heterogeneous per-vehicle spare capacity on [0, cap_max].
        # cap_std=0 reproduces the legacy homogeneous vehicle_cpu_capacity.
        # Drawn from the shared RNG for reproducibility. N_eff = (sum c)^2 /
        # sum c^2 is logged: it reads heterogeneity as an "effective" vehicle
        # count, while the actual count (network load) stays unchanged.
        caps = _sample_vehicle_capacities(
            len(unique_vids),
            mean=self.cap_mean, std=self.cap_std,
            c_max=self.cap_max, dist=self.cap_dist, rng=self.rng,
        )
        # n_eff e concurrent_mean sul POOL CONCORRENTE reale (veicoli PRESENTI
        # a ogni istante della finestra), non sugli unici della traccia.
        cap_by_id = {int(v): float(c) for v, c in zip(unique_vids, caps)}
        neffs, counts = [], []
        for _, grp in win.groupby('time'):
            ids = grp['id'].unique()
            counts.append(len(ids))
            cs = np.array([cap_by_id[int(i)] for i in ids if int(i) in cap_by_id], dtype=float)
            if cs.size and cs.sum() > 0:
                neffs.append((cs.sum() ** 2) / np.sum(cs ** 2))
        self._n_eff = float(np.mean(neffs)) if neffs else _compute_n_eff(caps)
        self._concurrent_mean = float(np.mean(counts)) if counts else float(len(unique_vids))

        self.vehicles = [
            Vehicle(
                vehicle_id=int(vid),
                cpu_capacity=float(caps[i]),
                queue_capacity=self.vehicle_queue_capacity,
                cpu_power=self.vehicle_cpu_power,
                ue_power=self.ue_power,
                energy_available=self.energy_available,
                dollars_per_kwh=self.price_kwh,
                ul_datarate=0,
                dl_datarate=0,
                position_x=0, position_y=0, speed=0,
                misreport_factor=(self.misreport_intensity if vid in liars else 0.0),
            )
            for i, vid in enumerate(unique_vids)
        ]
        self.mobility_df = df
        # OTTIMIZZAZIONE (bit-identica): pre-indicizza la traccia per id in
        # array ordinati per tempo. Il lookup per-slot passa da un filtro
        # pandas sull'INTERA traccia (O(righe) per chiamata, 84% del runtime
        # nel profiler) a np.searchsorted O(log n). Stesso record "piu' vicino"
        # (con tie -> tempo minore, come idxmin sul df ordinato per tempo) e
        # stessa tolleranza di presenza.
        self._mob_index = {}
        for vid, grp in df.groupby('id'):
            self._mob_index[int(vid)] = (
                grp['time'].to_numpy(),
                grp['position_x'].to_numpy(),
                grp['position_y'].to_numpy(),
                grp['speed'].to_numpy(),
            )
        # Base station al CENTRO della rete (centro del bounding box delle
        # posizioni della traccia). Serve perche' la COPERTURA abbia senso:
        # in uno scenario piu' grande del raggio, solo i veicoli entro
        # COVERAGE_RADIUS dalla BS sono usabili, e il pool cambia mentre i
        # veicoli attraversano la cella.
        self._bs_xy = (
            0.5 * (float(df['position_x'].min()) + float(df['position_x'].max())),
            0.5 * (float(df['position_y'].min()) + float(df['position_y'].max())),
        )
        if self.verbose:
            cv = (np.std(caps) / np.mean(caps)) if np.mean(caps) > 0 else 0.0
            print(f"[setup] {len(self.vehicles)} vehicles, {len(liars)} misreporters "
                  f"(rho={self.misreport_intensity}); cap mean={np.mean(caps):.3g} "
                  f"std={np.std(caps):.3g} CV={cv:.2f} N_eff={self._n_eff:.1f}")

    def _build_clouds(self):
        self.clouds = [
            Cloud(
                cloud_id=CLOUD_ID - i,
                cpu_capacity=self.cloud_cpu_capacity,
                queue_capacity=self.cloud_queue_capacity,
                cpu_power=CONTROLLER_CPU_POWER,
                tx_power=GNB_TX_POWER_INET,
                energy_available=self.energy_available,
                dollars_per_kwh=NO_ENERGY_PRICE,
                ul_datarate=int(DR_INET),
                dl_datarate=int(DR_INET),
                position_x=CLOUD_DISTANCE, position_y=CLOUD_DISTANCE,
                speed=0,
            )
            for i in range(self.num_clouds)
        ]

    def _build_controller(self):
        self.controller = Controller(gnb_position_x=self._bs_xy[0], gnb_position_y=self._bs_xy[1])

    def _generate_tasks(self):
        # Pull the realistic workload mix from config if available, falling
        # back to the scalar TASK_WORKLOAD otherwise. This way old runs that
        # set Simulator(task_workload=X) still get uniform W=X tasks.
        from config import TASK_WORKLOAD_TUPLE, TASK_WORKLOAD_PROBS
        self.tasks = generate_exponential_tasks(
            rate=self.task_rate,
            input_size=self.task_I, output_size=self.task_O, workload=self.task_W,
            num_users=self.users_number,
            max_sim_time_ms=self.max_sim_ms,
            task_type_probs=TASK_TYPE_TUPLE,
            task_type_deadlines=POSSIBLE_TASK_TYPES,
            rng=self.rng,
            workload_tuple=TASK_WORKLOAD_TUPLE,
            workload_probs=TASK_WORKLOAD_PROBS,
        )
        if self.verbose:
            print(f"[setup] {len(self.tasks)} tasks generated")

    def setup(self):
        self._build_vehicles_and_mobility()
        self._build_clouds()
        self._build_controller()
        self._generate_tasks()

    # ------------------------------------------------------------------
    # Beacon emission
    # ------------------------------------------------------------------
    def _emit_vehicle_beacons(self, current_ms, busy_nodes,
                               last_beacon_ms):
        """Emit nominal+realized beacons for vehicles that are due."""
        for v in self.vehicles:
            if not getattr(v, 'present', True):   # assente in questo istante -> niente beacon
                continue
            if _is_busy(v.vehicle_id, busy_nodes):
                continue
            if current_ms - last_beacon_ms[v.vehicle_id] < self.v_beacon_ms:
                continue
            if v.ul_datarate is None or v.dl_datarate is None:
                continue

            current_s = ms_to_seconds(current_ms)

            beacon_nom = v.create_beacon(current_s, mode='nominal')
            beacon_real = v.create_beacon(current_s, mode='realized', rng=self.rng)

            dwell_ms, _ = calculate_dwell_time_and_distance(
                v.position_x, v.position_y, v.speed,
            )

            self.controller.receive_vehicle_beacon(beacon_nom, current_ms, dwell_ms)
            self.controller.receive_vehicle_real_beacon(beacon_real, current_ms, dwell_ms)

            # Update per-vehicle realized-capacity history (for DRO Wasserstein).
            # beacon_real is a tuple; cpu_capacity sits at index 2 by convention
            # (see Vehicle.create_beacon documented return signature).
            try:
                vid = v.vehicle_id
                cap_real = float(beacon_real[2])
                self.capacity_history.setdefault(vid, []).append(cap_real)
                # Cap the history to the last 50 realizations to keep memory bounded.
                if len(self.capacity_history[vid]) > 50:
                    self.capacity_history[vid].pop(0)
            except (IndexError, TypeError, ValueError):
                pass

            last_beacon_ms[v.vehicle_id] = current_ms

            self._nom_beacon_rows.append(self._beacon_row(beacon_nom, current_ms, 'vehicle'))
            self._real_beacon_rows.append(self._beacon_row(beacon_real, current_ms, 'vehicle'))

    def _emit_cloud_beacons(self, current_ms, last_beacon_ms):
        for c in self.clouds:
            if current_ms - last_beacon_ms[c.cloud_id] < self.c_beacon_ms:
                continue
            # Refresh the wired backhaul rate with light jitter
            ul, dl = cloud_wired_datarate(c, rng=self.rng)
            c.set_istantaneous_datarate_pattern(ul, dl)

            current_s = ms_to_seconds(current_ms)
            beacon_nom = c.create_beacon(current_s, mode='nominal')
            beacon_real = c.create_beacon(current_s, mode='realized', rng=self.rng)

            self.controller.receive_cloud_beacon(beacon_nom, current_ms)
            self.controller.receive_cloud_real_beacon(beacon_real, current_ms)

            last_beacon_ms[c.cloud_id] = current_ms

            self._nom_beacon_rows.append(self._beacon_row(beacon_nom, current_ms, 'cloud'))
            self._real_beacon_rows.append(self._beacon_row(beacon_real, current_ms, 'cloud'))

    @staticmethod
    def _beacon_row(beacon_tuple, current_ms, node_type):
        """Flatten a beacon tuple into a serializable row."""
        (instant_s, bid, cpu_cap, queue_cap, cpu_pow, tx_pow,
         energy_av, dpkwh, ul_dr, dl_dr, px, py, speed) = beacon_tuple
        return {
            'timestamp_ms': current_ms,
            'node_id': bid,
            'node_type': node_type,
            'cpu_capacity': cpu_cap,
            'queue_capacity': queue_cap,
            'cpu_power': cpu_pow,
            'tx_power': tx_pow,
            'energy_available': energy_av,
            'dollars_per_kwh': dpkwh,
            'ul_datarate': ul_dr,
            'dl_datarate': dl_dr,
            'pos_x': px,
            'pos_y': py,
            'speed': speed,
        }

    # ------------------------------------------------------------------
    # Per-slot allocation
    # ------------------------------------------------------------------
    def _inject_lambda(self, beacon_list):
        """Write the current per-node arrival-rate estimate into each beacon's
        details dict (index 2 of the legacy tuple) so compute_timing can build
        the M/G/1 wait uniformly. No-op when queueing is disabled."""
        if not self._mm1_enabled:
            return beacon_list
        nl = self._node_lambda                          # localize lookup
        for b in beacon_list:
            b[2]['lambda_tasks_s'] = nl.get(b[1], 0.0)
        return beacon_list

    def _update_node_lambda(self, assignments):
        """EWMA update of per-node arrival rate lambda [tasks/s].
        O(N + A), no set allocation: decay every tracked node IN PLACE, fold
        in this slot's counts, then add the few brand-new nodes. Idle nodes
        whose rate decays below the floor are pruned so memory stays bounded
        to the actively-loaded executors. (Was set(a)|set(b) per slot.)"""
        if not self._mm1_enabled:
            return
        alpha = self._mm1_alpha
        one_minus = 1.0 - alpha
        rate_scale = alpha * self._mm1_inv_win_s       # alpha * (1/window_s)
        floor = self._mm1_floor
        nl = self._node_lambda
        counts = self._lambda_counts
        counts.clear()
        for a in assignments:
            nid = int(a['node'][1])
            counts[nid] = counts.get(nid, 0) + 1
        dead = None
        for nid, prev in nl.items():
            c = counts.pop(nid, 0)                       # consume matched
            val = one_minus * prev + (rate_scale * c if c else 0.0)
            if c == 0 and val < floor:
                if dead is None:
                    dead = (nid,)
                else:
                    dead += (nid,)
            else:
                nl[nid] = val                            # value-only update
        for nid, c in counts.items():                    # brand-new nodes
            nl[nid] = rate_scale * c
        if dead:
            for nid in dead:
                del nl[nid]

    def _run_slot_allocation(self, current_ms, busy_nodes):
        """
        Stage 1 + Stage 2 over the tasks arriving in [current_ms, current_ms+window).
        Returns (n_processed, total_obj, total_realized, busy_added).
        """
        slot_tasks = _filter_tasks_in_window(self.tasks, current_ms, current_ms + self.window_ms)
        if not slot_tasks:
            return 0, 0, 0, 0.0, 0.0, 0.0, []

        beacons = self.controller.beacons       # nominal store, legacy tuple view
        if not beacons:
            return 0, 0, 0, 0.0, 0.0, 0.0, []
        # M/M/1: inject the current per-node arrival rate so Stage-1 feasibility
        # accounts for queue wait (uniform for cloud/edge/vehicles).
        self._inject_lambda(beacons)

        # Track task generation
        for t in slot_tasks:
            self._task_rows.append({
                'id': t['id'], 'arrival_time': t['arrival_time'],
                'I': t['I'], 'O': t['O'], 'W': t['W'], 'D': t['D'],
            })

        # ---------------- Stage 1 ----------------
        dro_audit = []
        assigned, tasks_per_node, assignments, total_obj, alg = optimize_task_allocation(
            beacons=beacons, tasks=slot_tasks,
            policy=self.policy, rng=self.rng,
            dro_enabled=self.dro_enabled,
            capacity_history=self.capacity_history,
            audit_sink=dro_audit,
        )
        self.task_allocation_count += 1

        # ---- Trust audit: label each evaluated vehicle honest/liar and
        # cross-reference with the DRO decision, to later build a detection
        # confusion matrix (true/false positives/negatives of the DRO rule).
        if dro_audit:
            tp = fp = tn = fn = 0
            for row in dro_audit:
                nid = row['node_id']
                if isinstance(nid, int) and nid < 0:
                    continue                      # skip cloud
                is_liar = nid in self.liar_ids
                rejected = row['dro_rejected'] or row['rejected_all']
                if is_liar and rejected:
                    tp += 1
                elif is_liar and not rejected:
                    fn += 1
                elif not is_liar and rejected:
                    fp += 1
                else:
                    tn += 1
                row['is_liar'] = is_liar
            self._dump_jsonl('dro_trust.jsonl', {
                'timestamp_ms': current_ms,
                'tp': tp, 'fp': fp, 'tn': tn, 'fn': fn,
                'per_vehicle': dro_audit,
            })
            self._trust_tp += tp
            self._trust_fp += fp
            self._trust_tn += tn
            self._trust_fn += fn

        # ---- Tracciabilità: quali task NON sono stati assegnati? ----
        # Lo Stage-1 ILP omette dall'output i task che nessun executor
        # puo' completare entro la deadline firm, o che il pre-filtro DRO
        # (Def. 1) ha rifiutato. Questi sono FAILURES e vanno tracciati,
        # altrimenti il bilancio generated = processed + lost non torna.
        slot_ids = {t['id'] for t in slot_tasks}
        assigned_ids = set()
        for a in assignments:
            t = a.get('task')
            tid = t.get('id') if isinstance(t, dict) else a.get('task_id', t)
            if tid is not None:
                assigned_ids.add(tid)
        unassigned_ids = sorted(slot_ids - assigned_ids)

        # --- stato del sistema in questo slot (tracce complete) ---
        veh_in_cov = None
        for _holder in (self, getattr(self, 'controller', None)):
            _vs = getattr(_holder, 'vehicles', None) if _holder is not None else None
            if _vs:
                try:
                    veh_in_cov = sum(1 for v in _vs if getattr(v, 'present', False))
                    break
                except Exception:
                    pass
        try:
            beacons_now = len(self.controller.real_beacons or [])
        except Exception:
            beacons_now = None
        used_vehicles = len({a['node'][1] for a in assignments if int(a['node'][1]) >= 0})

        self._dump_jsonl('allocations.jsonl', {
            'timestamp_ms': current_ms,
            'n_tasks': len(slot_tasks),
            'n_assigned': len(assignments),
            'n_unassigned': len(unassigned_ids),
            'objective_dollars': float(total_obj or 0.0),
            'alg_overhead_s': float(alg),
            'vehicles_in_coverage': veh_in_cov,
            'beacons_active': beacons_now,
            'vehicles_used': used_vehicles,
            'active_users': self.users_number,
            'num_vehicles_scenario': self.num_vehicles,
            'assignments': [self._slim_assignment(a) for a in assignments],
        })

        if unassigned_ids:
            self._dump_jsonl('unassigned_tasks.jsonl', {
                'timestamp_ms': current_ms,
                'task_ids': unassigned_ids,
                'reason': 'infeasible_deadline_or_dro_rejected',
            })

        # M/M/1: the arrival rate seen by each node this slot is known once the
        # allocation is decided -> refresh the EWMA BEFORE Stage 2 so the
        # realized deadline check uses the up-to-date queue state.
        self._update_node_lambda(assignments)

        # ---------------- Stage 2 ----------------
        real_beacons = self.controller.real_beacons
        self._inject_lambda(real_beacons)       # realized C_n -> realized wait
        result = realized_value_function(
            real_beacons=real_beacons,
            task_assignments=assignments,
            algorithm_overhead=alg,
            run_core_check=True,
            verbose=self.verbose,
        )
        self._dump_jsonl('realizations.jsonl', {
            'timestamp_ms': current_ms,
            'total_realized_dollars': result['total_payoff'],
            'pi_NO': result['pi_NO_total'],
            'pi_per_executor': result['pi_per_executor'],
            'core_in_core': result['core_check'].in_core if result['core_check'] else None,
            'core_corrected': result['core_corrected'],
            'lost_tasks': result['lost_tasks'],
        })

        lost_stage2 = result['lost_tasks'] or []
        if lost_stage2:
            self._dump_jsonl('lost_tasks.jsonl', {
                'timestamp_ms': current_ms,
                'task_ids': lost_stage2,
            })

        # Wasted cost: energy-cost spent on tasks that were assigned (so the
        # executor burned energy) but then failed in Stage 2. Under
        # misreporting this is the money the system throws away, and it is
        # exactly what the DRO admission rule (Def. 1) is meant to prevent.
        lost_set = set(lost_stage2)
        wasted = 0.0
        if lost_set:
            for a in assignments:
                t = a.get('task')
                tid = t.get('id') if isinstance(t, dict) else a.get('task_id', t)
                if tid in lost_set:
                    cost = a.get('details', {}).get('cost', {})
                    if isinstance(cost, dict):
                        wasted += cost.get('total_dollars', 0.0)

        # Mark assigned executors as busy for their realized offloading time
        # Mark assigned vehicle executors as busy for their realized time.
        # With M/G/1 ON the queue wait already serializes each node, so the
        # external busy-lock is disabled (keeping it would double-count the
        # waiting time). With M/G/1 OFF we keep the legacy busy exclusion.
        busy_added = []
        if not self._mm1_enabled:
            for a in assignments:
                nid = int(a['node'][1])
                if nid < 0:
                    continue                          # cloud has no exclusion
                busy_ms = math.ceil(seconds_to_ms(a['details']['offloading_time']))
                busy_added.append({'busy_id': nid, 'time_ms': busy_ms})

        # processed = assigned MINUS those that failed in Stage 2
        n_processed = len(assignments) - len(lost_set)
        return (
            n_processed,
            len(unassigned_ids),
            len(lost_set),
            float(wasted),
            float(total_obj or 0.0),
            float(result['total_payoff']),
            busy_added,
        )

    @staticmethod
    def _slim_assignment(a):
        """Full per-assignment record: everything derivable is logged
        (tracce complete, nessuna compressione)."""
        det = a.get('details', {}) or {}
        cost = det.get('cost', {}) or {}
        task = a.get('task', {}) or {}
        nid = a['node'][1]
        return {
            'task_id': task.get('id'),
            'node_id': nid,
            'node_type': 'cloud' if int(nid) < 0 else 'vehicle',
            'utility_dollars': float(a['utility']),
            'time_total_s': det.get('offloading_time'),
            'deadline_s': det.get('deadline'),
            'deadline_met': det.get('deadline_met'),
            'payment_dollars': det.get('payment_dollars'),
            'cost_dollars': (cost.get('total_dollars') if isinstance(cost, dict) else cost),
            'cost_breakdown': cost,                       # dict costo INTERO
            'energy': det.get('energy'),                  # ENERGIA in joule (esatta, da task_energy)
            'timing': det.get('timing'),                  # breakdown timing completo
            'admission': det.get('admission'),            # dict ammissione INTERO (non solo reason)
            'queue_wait_s': det.get('queue_wait', det.get('wait_s')),
            'task_workload_ops': (task.get('W') or task.get('workload')),
            'task_deadline_s': task.get('deadline'),
        }

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    def _apply_mobility(self, v, t):
        """Versione veloce, bit-identica, di set_istantaneous_mobility_pattern:
        usa l'indice pre-costruito (np.searchsorted, O(log n)) invece di
        filtrare il DataFrame (O(righe) per chiamata). Stessa scelta del record
        piu' vicino (tie -> tempo minore, come idxmin sulla traccia ordinata per
        tempo) e stessa tolleranza di presenza PRESENCE_TOL_S."""
        rec = self._mob_index.get(v.vehicle_id)
        if rec is None:
            v.present = False
            return
        times, xs, ys, sp = rec
        n = times.shape[0]
        if n == 0:
            v.present = False
            return
        i = int(np.searchsorted(times, t))
        if i <= 0:
            j = 0
        elif i >= n:
            j = n - 1
        else:
            j = i - 1 if abs(times[i - 1] - t) <= abs(times[i] - t) else i
        if abs(float(times[j]) - t) > PRESENCE_TOL_S:
            v.present = False
            return
        v.present = True
        v.position_x = xs[j]
        v.position_y = ys[j]
        v.speed = sp[j]

    def run(self):
        if not self.vehicles:
            self.setup()

        last_v_beacon = {v.vehicle_id: -self.v_beacon_ms for v in self.vehicles}
        last_c_beacon = {c.cloud_id: -self.c_beacon_ms for c in self.clouds}
        busy_nodes = []

        # Il loop (e quindi task/slot) resta su [start, start+run]: cambia solo
        # da DOVE si campiona la mobilita' (vedi offset warmup nel lookup sotto),
        # cosi' i veicoli sono a regime senza disallineare i task.
        current_ms = self.start_ms
        sim_end_ms = self.start_ms + self.max_sim_ms

        while current_ms <= sim_end_ms:
            current_s = ms_to_seconds(current_ms)

            # 1. Refresh vehicle mobility
            for v in self.vehicles:
                # offset warmup: a loop t -> traccia (t + warmup), cioe' la
                # finestra a regime [warmup, warmup+run].
                self._apply_mobility(v, current_s + self._warmup_s)

            # 2. Refresh 5G data rates for non-busy vehicles
            # FILTRO COPERTURA: BS al centro; un veicolo in scena ma oltre
            # COVERAGE_RADIUS dalla BS non e' un server usabile (lo escludo come
            # assente). Rivalutato a ogni slot dopo l'update di mobilita': genera
            # il ricambio del pool mentre i veicoli attraversano la cella.
            _bsx, _bsy = self._bs_xy
            _r2 = float(COVERAGE_RADIUS) * float(COVERAGE_RADIUS)
            for _v in self.vehicles:
                if _v.present and ((_v.position_x - _bsx) ** 2 + (_v.position_y - _bsy) ** 2) > _r2:
                    _v.present = False
            active_vehicles = [v for v in self.vehicles if getattr(v, 'present', True) and not _is_busy(v.vehicle_id, busy_nodes)]
            if active_vehicles:
                ar = (self.users_number * self.task_rate) / (1000.0 / self.window_ms) / max(self.num_vehicles, 1)
                active_ratio = float(np.clip(2.0 * ar, 0.01, 1.0))   # M3 clamp
                set_all_vehicles_data_rate_5g_standard(
                    active_vehicles,
                    potenza_dl_dbm=GNB_TX_POWER_5G,
                    rng=self.rng,
                    active_ratio=active_ratio,
                    gnb_position=self._bs_xy,
                )

            # 3. Beacons
            self._emit_vehicle_beacons(current_ms, busy_nodes, last_v_beacon)
            self._emit_cloud_beacons(current_ms, last_c_beacon)

            # 4. Expiry
            self.controller.clean_expired_beacons(
                current_ms,
                vehicle_expiry_ms=self.beacon_expiry_ms,
            )

            # 5. Slot allocation (every WINDOW_TASK_COLLECTION ms)
            if current_ms % self.window_ms == 0:
                (n, n_unassigned, n_lost2, wasted, obj, real,
                 busy_added) = self._run_slot_allocation(current_ms, busy_nodes)
                self.tasks_processed += n
                self.tasks_unassigned += n_unassigned
                self.tasks_lost_stage2 += n_lost2
                self.wasted_cost_dollars += wasted
                self.total_objective += obj
                self.total_realized += real
                busy_nodes.extend(busy_added)

                # M9: decrement busy timers by the slot length, not by 1
                busy_nodes = [b for b in busy_nodes if b['time_ms'] > self.window_ms]
                for b in busy_nodes:
                    b['time_ms'] -= self.window_ms

            current_ms += self.dt_ms

        self.tasks_generated = len(self.tasks)
        self._finalize()

    # ------------------------------------------------------------------
    # Finalization
    # ------------------------------------------------------------------
    def _dump_jsonl(self, fname, record):
        path = self.results_dir / fname
        with open(path, 'a') as f:
            f.write(json.dumps(record, default=_safe_serialize) + "\n")

    def _finalize(self):
        # Beacon CSVs (single materialization)
        if self._nom_beacon_rows:
            pd.DataFrame(self._nom_beacon_rows).to_csv(
                self.results_dir / "beacons.csv", index=False,
            )
        if self._real_beacon_rows:
            pd.DataFrame(self._real_beacon_rows).to_csv(
                self.results_dir / "beacons_real.csv", index=False,
            )
        if self._task_rows:
            pd.DataFrame(self._task_rows).to_csv(
                self.results_dir / "tasks.csv", index=False,
            )

        # Summary
        summary = {
            'run_id': self.run_id,
            'seed': self.seed,
            'num_vehicles': self.num_vehicles,
            'num_clouds': self.num_clouds,
            'n_eff': self._n_eff,
            'concurrent_mean': self._concurrent_mean,
            'cap_mean': self.cap_mean,
            'cap_std': self.cap_std,
            'cap_max': self.cap_max,
            'cap_dist': self.cap_dist,
            'task_rate': self.task_rate,
            'misreporting_fraction': self.misreporting_fraction,
            'policy': self.policy,
            'dro_enabled': self.dro_enabled,
            'sim_time_ms': self.max_sim_ms,
            'tasks_generated': self.tasks_generated,
            'tasks_processed': self.tasks_processed,
            'tasks_unassigned': self.tasks_unassigned,
            'tasks_lost_stage2': self.tasks_lost_stage2,
            'tasks_failed_total': self.tasks_unassigned + self.tasks_lost_stage2,
            'failure_rate_pct': (
                100.0 * (self.tasks_unassigned + self.tasks_lost_stage2)
                / max(self.tasks_generated, 1)
            ),
            'wasted_cost_dollars': self.wasted_cost_dollars,
            'net_utility_dollars': self.total_realized - self.wasted_cost_dollars,
            # DRO detection performance vs ground-truth liar labels
            'dro_trust_tp': self._trust_tp,
            'dro_trust_fp': self._trust_fp,
            'dro_trust_tn': self._trust_tn,
            'dro_trust_fn': self._trust_fn,
            'dro_precision': (
                self._trust_tp / max(self._trust_tp + self._trust_fp, 1)
            ),
            'dro_recall': (
                self._trust_tp / max(self._trust_tp + self._trust_fn, 1)
            ),
            'dro_false_positive_rate': (
                self._trust_fp / max(self._trust_fp + self._trust_tn, 1)
            ),
            'slots_run': self.task_allocation_count,
            'total_objective_dollars': self.total_objective,
            'total_realized_dollars': self.total_realized,
        }
        with open(self.results_dir / "summary.json", 'w') as f:
            json.dump(summary, f, indent=2)

        if self.verbose:
            print("\n=== Simulation complete ===")
            for k, v in summary.items():
                print(f"  {k}: {v}")


# ----------------------------------------------------------------------
# CLI entry point
# ----------------------------------------------------------------------
def main(run_id="default", **kwargs):
    sim = Simulator(run_id=run_id, **kwargs)
    sim.run()
    return sim


if __name__ == "__main__":
    main(run_id="default", verbose=True)
