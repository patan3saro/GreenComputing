"""
Task timing — implements the unified offloading time T_tau of the offloading-time model.

The offloading time has a fixed structure shared by all executor types
(vehicle and cloud), assembled from the following components:

  T_tau = T_prop_radio        # 2 * d_radio / c        (light-speed, both ways)
        + T_ul_radio           # I_tau / R_ul_5G        (UE -> gNB)
        + T_dl_radio           # O_tau / R_dl_5G        (gNB -> UE)
        + T_compute            # W_tau / C_n            (executor CPU time)
        + T_alg                # algorithm overhead     (Controller decision)
        + (cloud only) T_inet  # 2 (d_fiber/c_fib + INET_DELAY)
                               + I_tau/R_inet + O_tau/R_inet
        + (vehicle only) T_prop_vue + T_ul_vue + T_dl_vue
                               # additional radio leg for VCC

This module is decoupled from energy accounting (see `task_energy.py`).
"""

from dataclasses import dataclass
import math

from config import (
    SPEED_LIGHT, SPEED_FIBER,
    PEDESTRIAN_UE_DISTANCE,
    CLOUD_DISTANCE, INET_DELAY,
    DR_INET,
)

# ----------------------------------------------------------------------
#      Service-time moments  (M/G/1 Pollaczek-Khinchine, precomputed once)
# ----------------------------------------------------------------------
# Each executor is a single-server queue. Service time S = W / C_n with C_n
# deterministic per node, so the squared coefficient of variation of the
# service equals that of the workload, Cs^2(S) = Cs^2(W), and is the SAME
# for every node. We precompute E[W], E[W^2] -> Cs^2 -> the Pollaczek-
# Khinchine multiplier ONCE at import (O(k), k = #workload buckets), so the
# per-task wait is a single O(1) multiply-divide.
#
#   M/G/1:  W_q = (1 + Cs^2)/2 * rho/(mu - lam)          [Kleinrock, P-K]
#   Cs^2 = 1 -> M/M/1 (exponential service)   [special case]
#   Cs^2 = 0 -> M/D/1 (deterministic service)
# The automotive workload mix is heavy-tailed (Cs^2 ~ 3.8), so the plain
# M/M/1 would underestimate the wait ~2.4x; M/G/1 is the justified value.
try:
    from config import TASK_WORKLOAD_TUPLE, TASK_WORKLOAD_PROBS
    _w = tuple(float(x) for x in TASK_WORKLOAD_TUPLE)
    _p = tuple(float(x) for x in TASK_WORKLOAD_PROBS)
    W_MEAN = sum(w * pr for w, pr in zip(_w, _p))
    _W2 = sum(w * w * pr for w, pr in zip(_w, _p))
except Exception:                                   # pragma: no cover
    from config import TASK_WORKLOAD
    W_MEAN = float(TASK_WORKLOAD)
    _W2 = W_MEAN * W_MEAN
_EW2 = W_MEAN * W_MEAN
SERVICE_CS2 = max(0.0, (_W2 - _EW2) / _EW2) if _EW2 > 0.0 else 0.0
PK_FACTOR = 0.5 * (1.0 + SERVICE_CS2)               # (1+Cs^2)/2, precomputed
_INV_W_MEAN = (1.0 / W_MEAN) if W_MEAN > 0.0 else float('inf')


def queue_wait_seconds(lam, mu):
    """
    M/G/1 mean waiting time IN QUEUE (Pollaczek-Khinchine) [seconds]:

        W_q = (1 + Cs^2)/2 * rho / (mu - lam),     rho = lam/mu < 1

    Applied UNIFORMLY to every executor (cloud, edge, vehicle): each is a
    single-server queue with service rate mu = C_n / E[W] and offered
    arrival rate lam. Reduces to M/M/1 when Cs^2 = 1. O(1): PK_FACTOR is a
    module constant. Saturation (lam >= mu) or ill-defined mu -> +inf, so
    the deadline is missed and the task fails.
    """
    if mu <= 0.0:
        return float('inf')
    if lam <= 0.0:
        return 0.0
    if lam >= mu:
        return float('inf')
    return PK_FACTOR * lam / (mu * (mu - lam))


# Backwards-compatible alias (M/M/1 is the Cs^2 = 1 special case).
mm1_wait_seconds = queue_wait_seconds


# ----------------------------------------------------------------------
#                       Dwell-time computation
# ----------------------------------------------------------------------
def calculate_dwell_time_and_distance(
    position_x, position_y, speed,
    gnb_position_x=900, gnb_position_y=900, coverage_radius=1000,
):
    """
    Estimate how long a vehicle remains within the gNB coverage circle, given
    its current position and instantaneous speed.

    Returns
    -------
    (dwell_time_ms, distance_to_gnb_m)
        - dwell_time_ms : float
            - +inf if the vehicle is not moving
            - 0    if it is already outside coverage
            - else (remaining_distance / speed) in milliseconds
        - distance_to_gnb_m : Euclidean distance from the gNB [m]
    """
    distance = math.sqrt(
        (position_x - gnb_position_x) ** 2 +
        (position_y - gnb_position_y) ** 2
    )
    if speed <= 0:
        return float('inf'), distance
    if distance > coverage_radius:
        return 0.0, distance
    return ((coverage_radius - distance) / speed) * 1000.0, distance


# ----------------------------------------------------------------------
#                       Time breakdown dataclass
# ----------------------------------------------------------------------
@dataclass
class TimingBreakdown:
    """
    Per-component contribution to the total offloading time of one task.
    All values are in SECONDS.

    The labelling here is unambiguous (no more `energies[3]` confusion):
      - prop_radio_pedestrian : light-speed round-trip from the end-user to the gNB
      - ul_radio              : I_tau / R_ul   (UE uplink delivery to gNB)
      - dl_radio              : O_tau / R_dl   (gNB downlink to UE)
      - compute               : W_tau / C_n
      - alg_overhead          : Controller scheduling time
      - prop_radio_executor   : light-speed round-trip from gNB to the executor
                                 (zero for cloud since cloud is wired, finite for vehicle)
      - inet_prop             : 2 (D_cloud/c_fib + INET_DELAY) (cloud only, 0 for vehicle)
      - inet_ul, inet_dl      : I/R_inet, O/R_inet (cloud only, 0 for vehicle)
    """
    prop_radio_pedestrian: float
    ul_radio: float
    dl_radio: float
    compute: float
    alg_overhead: float

    prop_radio_executor: float = 0.0
    inet_prop: float = 0.0
    inet_ul: float = 0.0
    inet_dl: float = 0.0
    # M/M/1 mean waiting time in the executor's queue (uniform for all node
    # types). Zero when the station is idle -> backward-compatible.
    queue_wait: float = 0.0

    @property
    def total(self):
        return (
            self.prop_radio_pedestrian + self.ul_radio + self.dl_radio
            + self.compute + self.alg_overhead
            + self.prop_radio_executor
            + self.inet_prop + self.inet_ul + self.inet_dl
            + self.queue_wait
        )

    def as_dict(self):
        return {
            'prop_radio_pedestrian': self.prop_radio_pedestrian,
            'ul_radio': self.ul_radio,
            'dl_radio': self.dl_radio,
            'compute': self.compute,
            'alg_overhead': self.alg_overhead,
            'prop_radio_executor': self.prop_radio_executor,
            'inet_prop': self.inet_prop,
            'inet_ul': self.inet_ul,
            'inet_dl': self.inet_dl,
            'queue_wait': self.queue_wait,
            'total': self.total,
        }


# ----------------------------------------------------------------------
#                       Timing computation per task-executor pair
# ----------------------------------------------------------------------
def compute_timing(task, beacon_details, algorithm_overhead):
    """
    Compute the timing breakdown for a (task, executor) pair.

    Parameters
    ----------
    task : dict
        Task descriptor with keys 'I' (input bits), 'O' (output bits),
        'W' (workload in operations), 'D' (deadline in seconds).
    beacon_details : dict
        The `beacon[2]` dict from the controller, with keys:
        'type', 'ul_datarate', 'dl_datarate', 'cpu_capacity',
        'position_x', 'position_y', 'speed'.
    algorithm_overhead : float
        Time spent by the Controller running the allocation algorithm [s].

    Returns
    -------
    TimingBreakdown
    """
    input_size = task['I']
    output_size = task['O']
    workload = task['W']

    dr_ul = beacon_details['ul_datarate']
    dr_dl = beacon_details['dl_datarate']

    # Guard against zero data rate (vehicle below SINR threshold)
    inv_dr_ul = 1.0 / dr_ul if dr_ul and dr_ul > 0 else float('inf')
    inv_dr_dl = 1.0 / dr_dl if dr_dl and dr_dl > 0 else float('inf')
    inv_speed_light = 1.0 / SPEED_LIGHT

    # Shared components (end-user <-> gNB radio leg + executor compute)
    timing = TimingBreakdown(
        prop_radio_pedestrian=2.0 * PEDESTRIAN_UE_DISTANCE * inv_speed_light,
        ul_radio=input_size * inv_dr_ul,
        dl_radio=output_size * inv_dr_dl,
        compute=workload / beacon_details['cpu_capacity'],
        alg_overhead=algorithm_overhead,
    )

    # ---------------- M/M/1 queue wait (UNIFORM for all node types) --------
    # Every executor is a single-server FIFO queue: service rate
    # mu = C_n / E[W] (tasks/s), offered load lam = tasks/s routed to it
    # (injected as 'lambda_tasks_s' by the simulator; absent -> idle -> 0).
    # A misreporter inflates C_n in the NOMINAL beacon -> smaller nominal
    # wait -> looks feasible in Stage 1; in Stage 2 the REALIZED (smaller)
    # C_n yields a larger wait -> the deadline is missed. This ties the
    # queueing model to the misreporting story without any special-casing.
    lam = beacon_details.get('lambda_tasks_s', 0.0) or 0.0
    mu = beacon_details['cpu_capacity'] * _INV_W_MEAN
    timing.queue_wait = queue_wait_seconds(lam, mu)

    node_type = beacon_details['type'].lower()
    if node_type == 'cloud':
        # gNB <-> cloud via wired Internet
        inv_speed_fiber = 1.0 / SPEED_FIBER
        inv_dr_inet = 1.0 / DR_INET
        # Per-node latency override: an EDGE server co-located at the gNodeB
        # has a much smaller Internet delay than a remote cloud. If the
        # beacon carries 'inet_delay_s', use it; otherwise fall back to the
        # global remote-cloud INET_DELAY (paper Table I, Verizon 35 ms).
        node_inet_delay = beacon_details.get('inet_delay_s', INET_DELAY)
        node_distance = beacon_details.get('inet_distance_m', CLOUD_DISTANCE)
        timing.inet_prop = 2.0 * (node_distance * inv_speed_fiber + node_inet_delay)
        timing.inet_ul = input_size * inv_dr_inet
        timing.inet_dl = output_size * inv_dr_inet
    elif node_type == 'vehicle':
        # gNB <-> vehicle additional radio leg (the gNB has already delivered
        # the task to itself; now it forwards to the vehicle).
        # The UL/DL transmission has already been accounted for in
        # ul_radio/dl_radio above (UE leg). The additional leg is the
        # propagation round-trip between gNB and vehicle.
        _, distance = calculate_dwell_time_and_distance(
            beacon_details['position_x'],
            beacon_details['position_y'],
            beacon_details['speed'],
        )
        timing.prop_radio_executor = 2.0 * distance * inv_speed_light
    else:
        raise ValueError(f"Unknown node_type: {node_type}")

    return timing
