"""
Task energy — per-stakeholder energy accounting for one offloaded task,
using the EnergyModel of `network_manager.py` (EARTH/Auer-Holtkamp).

Stakeholder breakdown:
  - device_energy        : end-user UE compute + UL/DL toward the gNB.
                          Energy paid by the requesting device. NOT used
                          in the Stage 1 utility (it's the user's, not the
                          NO's nor the executor's).
  - executor_energy      : energy that the chosen executor (vehicle or
                          cloud) spends on compute + tx of the result.
                          Charged against the executor's payoff.
  - network_operator_energy : energy the NO spends on
                          gNB tx + gNB rx + Controller CPU (algorithm) +
                          (cloud only) wired backhaul tx/rx.
                          Charged against the NO payoff (the outer-game split.
"""

from dataclasses import dataclass

from network_manager import EnergyModel
from config import (
    GNB_TX_POWER_5G, GNB_TX_POWER_INET,
    CONTROLLER_CPU_POWER,
    DR_INET,
    INTERNET_ENERGY_PER_BIT,
    VEHICLE_ENERGY_PER_OP, CLOUD_ENERGY_PER_OP,
)


# ----------------------------------------------------------------------
#                       Energy breakdown dataclass
# ----------------------------------------------------------------------
@dataclass
class EnergyBreakdown:
    """
    Per-component energy accounting for one (task, executor) pair.
    All values are in JOULES.

    Three logical owners:
      - NO  (Network Operator) : gNB RF chains, Controller CPU, cloud backhaul
      - Exec (Executor)         : the selected node's CPU + UL of the result
      - User                    : the end-user device's UE energy
    """
    # Network Operator side
    no_gnb_ul_rx: float           # gNB receives UL from end-user UE
    no_gnb_dl_tx: float           # gNB transmits DL of result to end-user UE
    no_alg: float                 # Controller CPU for the algorithm
    no_gnb_to_exec_tx: float = 0.0   # gNB transmits task to vehicle exec
    no_gnb_to_exec_rx: float = 0.0   # gNB receives result from vehicle exec
    no_inet_tx: float = 0.0          # gNB sends task over wired backhaul to cloud
    no_inet_rx: float = 0.0          # gNB receives result over wired backhaul

    # Executor side
    exec_compute: float = 0.0     # executor CPU running the task
    exec_tx: float = 0.0          # executor transmits result back

    # End-user device side (kept for accounting, NOT used in payoffs)
    user_ue_tx: float = 0.0       # end-user UE uploads task input
    user_ue_rx: float = 0.0       # end-user UE downloads result

    @property
    def no_total(self):
        return (
            self.no_gnb_ul_rx + self.no_gnb_dl_tx + self.no_alg
            + self.no_gnb_to_exec_tx + self.no_gnb_to_exec_rx
            + self.no_inet_tx + self.no_inet_rx
        )

    @property
    def exec_total(self):
        return self.exec_compute + self.exec_tx

    @property
    def user_total(self):
        return self.user_ue_tx + self.user_ue_rx

    @property
    def grand_total(self):
        return self.no_total + self.exec_total + self.user_total

    def as_dict(self):
        return {
            'no_gnb_ul_rx': self.no_gnb_ul_rx,
            'no_gnb_dl_tx': self.no_gnb_dl_tx,
            'no_alg': self.no_alg,
            'no_gnb_to_exec_tx': self.no_gnb_to_exec_tx,
            'no_gnb_to_exec_rx': self.no_gnb_to_exec_rx,
            'no_inet_tx': self.no_inet_tx,
            'no_inet_rx': self.no_inet_rx,
            'no_total': self.no_total,
            'exec_compute': self.exec_compute,
            'exec_tx': self.exec_tx,
            'exec_total': self.exec_total,
            'user_ue_tx': self.user_ue_tx,
            'user_ue_rx': self.user_ue_rx,
            'user_total': self.user_total,
            'grand_total': self.grand_total,
        }


# ----------------------------------------------------------------------
#                       Energy computation per task-executor pair
# ----------------------------------------------------------------------
def compute_energy(task, beacon_details, timing, algorithm_overhead):
    """
    Compute the full per-stakeholder energy breakdown for one task.

    Parameters
    ----------
    task : dict
        Task descriptor with 'I', 'O', 'W' fields (the offloading-time model.
    beacon_details : dict
        Executor beacon `details` dict (with 'type', 'cpu_power',
        'cpu_capacity', 'tx_power', 'ul_datarate', 'dl_datarate', ...).
    timing : TimingBreakdown
        Output of `task_timing.compute_timing(...)`. Used to read tx/rx
        times consistently with the timing model.
    algorithm_overhead : float
        Time the Controller spent running the allocation algorithm [s].

    Returns
    -------
    EnergyBreakdown
    """
    input_size = task['I']
    output_size = task['O']
    workload = task['W']

    # ----- End-user UE energy (carried by the user; informational only) -----
    # User uploads task to gNB and downloads result from gNB. We model the
    # user device as a generic UE with the same power-model parameters as
    # vehicles, transmitting at a similar power. The user data rates are
    # not separately modelled here -> reuse the executor's UL/DL as a
    # proxy (they share the same gNB).
    dr_ul = beacon_details['ul_datarate']
    dr_dl = beacon_details['dl_datarate']
    # Use a default UE power (23 dBm) for the user side
    user_tx_power_dbm = 23

    user_ue_tx = EnergyModel.tx_energy_wireless_ue(
        p_tx_dbm=user_tx_power_dbm, n_bits=input_size, datarate_bps=dr_ul,
    )
    user_ue_rx = EnergyModel.rx_energy_wireless_ue(
        n_bits=output_size, datarate_bps=dr_dl,
    )

    # ----- NO side: gNB RX (UL from user) + gNB TX (DL to user) -----
    no_gnb_ul_rx = EnergyModel.rx_energy_wireless_gnb(
        n_bits=input_size, datarate_bps=dr_ul,
    )
    no_gnb_dl_tx = EnergyModel.tx_energy_wireless_gnb(
        p_tx_dbm=GNB_TX_POWER_5G, n_bits=output_size, datarate_bps=dr_dl,
    )

    # ----- NO Controller CPU energy for the algorithm -----
    no_alg = CONTROLLER_CPU_POWER * algorithm_overhead

    # ----- Executor compute energy -----
    # Modelled per-operation (J/OP), the physically correct way for AI
    # accelerators: a short inference does not draw the full chip TDP for
    # its entire duration. energy = workload[OPS] * energy_per_op[J/OP].
    node_type_for_energy = beacon_details['type'].lower()
    if node_type_for_energy == 'cloud':
        energy_per_op = CLOUD_ENERGY_PER_OP
    else:
        energy_per_op = VEHICLE_ENERGY_PER_OP
    exec_compute = workload * energy_per_op

    breakdown = EnergyBreakdown(
        no_gnb_ul_rx=no_gnb_ul_rx,
        no_gnb_dl_tx=no_gnb_dl_tx,
        no_alg=no_alg,
        exec_compute=exec_compute,
        user_ue_tx=user_ue_tx,
        user_ue_rx=user_ue_rx,
    )

    node_type = beacon_details['type'].lower()
    if node_type == 'cloud':
        # gNB <-> cloud over the Internet. We account for THREE distinct
        # contributions:
        #   (a) the two NIC endpoints (gNB egress and cloud ingress) using
        #       the wired NIC power model;
        #   (b) the END-TO-END Internet path (routers, switches, transit,
        #       core, edge, DC fabric), modelled as a constant energy
        #       intensity per bit (Aslan et al. 2018).
        #   (c) the cloud executor sending the result back, also charged
        #       at INTERNET_ENERGY_PER_BIT (covers transit) PLUS its own
        #       NIC tx energy.
        #
        # Counting only (a) would underestimate cloud offloading energy by
        # several orders of magnitude relative to measured Internet
        # electricity intensity.
        nic_in_tx = EnergyModel.tx_energy_wired(input_size, DR_INET)
        nic_in_rx = EnergyModel.rx_energy_wired(input_size, DR_INET)
        nic_out_tx = EnergyModel.tx_energy_wired(output_size, DR_INET)
        nic_out_rx = EnergyModel.rx_energy_wired(output_size, DR_INET)

        inet_path_in = INTERNET_ENERGY_PER_BIT * input_size
        inet_path_out = INTERNET_ENERGY_PER_BIT * output_size

        # gNB-side wired transmission (task -> cloud) and reception
        # (result <- cloud) charged to the NO, plus the share of the
        # end-to-end Internet path proportional to bits crossing it.
        breakdown.no_inet_tx = nic_in_tx + inet_path_in
        breakdown.no_inet_rx = nic_out_rx + inet_path_out
        # Cloud-side NIC for sending the result back is charged to the
        # executor (it is its own outbound traffic).
        breakdown.exec_tx = nic_out_tx
    elif node_type == 'vehicle':
        # gNB transmits task to vehicle, vehicle uploads result back. Both
        # use the wireless wireless ue/gnb model. The C6 bug (UL energy
        # of the vehicle using gnb_tx_power instead of ue_power) is fixed
        # here: the vehicle UL uses `tx_power` (its own UE power).
        breakdown.no_gnb_to_exec_tx = EnergyModel.tx_energy_wireless_gnb(
            p_tx_dbm=GNB_TX_POWER_5G, n_bits=input_size, datarate_bps=dr_dl,
        )
        breakdown.no_gnb_to_exec_rx = EnergyModel.rx_energy_wireless_gnb(
            n_bits=output_size, datarate_bps=dr_ul,
        )
        breakdown.exec_tx = EnergyModel.tx_energy_wireless_ue(
            p_tx_dbm=beacon_details['tx_power'],
            n_bits=output_size, datarate_bps=dr_ul,
        )
    else:
        raise ValueError(f"Unknown node_type: {node_type}")

    return breakdown 