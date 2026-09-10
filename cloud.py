"""
Cloud node — wired backhaul executor.

The cloud is reached over a fixed-bandwidth Internet link, so its data rate
is governed by `network_manager.cloud_wired_datarate(rng)` (called from the
simulator each slot), and its energy consumption uses the wired NIC model
in `network_manager.EnergyModel`.

Beacon scheme is symmetric with `vehicle.py`:
  - mode='nominal'   -> self-declared parameters (used in Stage 1 allocation)
  - mode='realized'  -> ground-truth realization (used in Stage 2 sharing)
"""

import numpy as np

from network_manager import EnergyModel


# Std fraction matching Table I NV notation (sigma = 10% of mean).
NV_STD_FRACTION = 0.10


class Cloud:
    """
    Cloud compute node.

    Parameters
    ----------
    cloud_id : int
        Unique cloud identifier (typically negative, e.g. -1, to distinguish
        from vehicle ids).
    cpu_capacity : float [FLOPS]
        Total compute capacity (Tab. I: 1e15 FLOPS).
    queue_capacity : int
        Maximum number of concurrent tasks (deterministic system parameter).
    cpu_power : float [W]
        Server CPU power draw during computation.
    tx_power : float [dBm]
        Backhaul transmit power (unused in energy model, kept for symmetry
        with vehicle beacon schema).
    energy_available : float [J]
        Available energy budget (effectively infinite for the cloud).
    dollars_per_kwh : float [$/kWh]
        Energy-to-cash conversion rate (lambda_i in the cost model).
    ul_datarate, dl_datarate : float [bps]
        Wired backhaul data rates; updated externally each slot by
        `network_manager.cloud_wired_datarate(rng)`.
    position_x, position_y : float
        Geographical position (used for distance/propagation in the
        offloading time model). The cloud is static.
    speed : float
        Always 0 for a static cloud.
    """

    def __init__(
        self,
        cloud_id=None,
        cpu_capacity=None,
        queue_capacity=None,
        cpu_power=None,
        tx_power=None,
        energy_available=None,
        dollars_per_kwh=None,
        ul_datarate=None,
        dl_datarate=None,
        position_x=None,
        position_y=None,
        speed=0.0,
    ):
        self.cloud_id = cloud_id
        self.cpu_capacity = cpu_capacity
        self.cpu_power = cpu_power
        self.tx_power = tx_power
        self.energy_available = energy_available
        self.dollars_per_kwh = dollars_per_kwh
        self.queue_capacity = queue_capacity
        self.ul_datarate = ul_datarate
        self.dl_datarate = dl_datarate
        self.position_x = position_x
        self.position_y = position_y
        self.speed = speed

    # ------------------------------------------------------------------
    #                       Beacon creation
    # ------------------------------------------------------------------
    def create_beacon(self, instant_sec, mode='nominal', rng=None):
        """
        Create a beacon describing the cloud's state at `instant_sec`.

        Parameters
        ----------
        instant_sec : float
            Timestamp of the beacon [s].
        mode : {'nominal', 'realized'}
            - 'nominal'  -> declared parameters (used in Stage 1).
            - 'realized' -> ground-truth realization (used in Stage 2),
                            adds NV noise (sigma = 10% of mean) to compute
                            and energy-related fields. Data rates are NOT
                            re-randomized here because they are already set
                            from `network_manager.cloud_wired_datarate(rng)`.
        rng : np.random.Generator, optional
            Required when mode='realized'. Pass the simulator's external
            generator to avoid PRNG state collisions.

        Returns
        -------
        tuple
            (instant_sec, cloud_id, cpu_capacity, queue_capacity, cpu_power,
             tx_power, energy_available, dollars_per_kwh,
             ul_datarate, dl_datarate, position_x, position_y, speed)
        """
        # Validate required attributes
        required = [
            'cloud_id', 'cpu_capacity', 'queue_capacity', 'cpu_power',
            'tx_power', 'energy_available', 'dollars_per_kwh',
            'ul_datarate', 'dl_datarate', 'position_x', 'position_y', 'speed',
        ]
        for attr in required:
            if getattr(self, attr) is None:
                raise ValueError(f"Cloud {attr} is not defined")

        if mode == 'nominal':
            cpu_capacity = self.cpu_capacity
            cpu_power = self.cpu_power
            tx_power = self.tx_power
            energy_available = self.energy_available
            dollars_per_kwh = self.dollars_per_kwh
        elif mode == 'realized':
            if rng is None:
                raise ValueError("rng required for mode='realized'")
            # NV: gaussian noise with sigma = 10% mean (Tab. I)
            cpu_capacity = rng.normal(self.cpu_capacity, abs(self.cpu_capacity) * NV_STD_FRACTION)
            cpu_power = rng.normal(self.cpu_power, abs(self.cpu_power) * NV_STD_FRACTION)
            tx_power = rng.normal(self.tx_power, abs(self.tx_power) * NV_STD_FRACTION)
            energy_available = rng.normal(self.energy_available, abs(self.energy_available) * NV_STD_FRACTION)
            # dollars_per_kwh: contractual, NOT randomized
            dollars_per_kwh = self.dollars_per_kwh
        else:
            raise ValueError(f"unknown mode: {mode}")

        # queue_capacity is deterministic (system parameter), not randomized
        queue_capacity = self.queue_capacity

        # Data rates come from network_manager (wired backhaul); kept as-is
        ul_datarate = self.ul_datarate
        dl_datarate = self.dl_datarate

        return (
            instant_sec,
            self.cloud_id,
            cpu_capacity,
            queue_capacity,
            cpu_power,
            tx_power,
            energy_available,
            dollars_per_kwh,
            ul_datarate,
            dl_datarate,
            self.position_x,
            self.position_y,
            self.speed,
        )

    # ------------------------------------------------------------------
    #                       Energy accounting
    # ------------------------------------------------------------------
    def tx_energy(self, n_bits):
        """
        Energy consumed by the cloud to transmit `n_bits` over the wired
        backhaul, given its current dl_datarate.
        Used for: cloud -> Controller (result return path).
        """
        return EnergyModel.tx_energy_wired(n_bits=n_bits, datarate_bps=self.dl_datarate)

    def rx_energy(self, n_bits):
        """
        Energy consumed by the cloud to receive `n_bits` over the wired
        backhaul, given its current ul_datarate.
        Used for: Controller -> cloud (task input).
        """
        return EnergyModel.rx_energy_wired(n_bits=n_bits, datarate_bps=self.ul_datarate)

    def compute_energy(self, workload_ops):
        """
        Energy consumed by the cloud CPU to execute `workload_ops` operations
        on its `cpu_capacity` FLOPS hardware.
        the executor energy model of the paper, first term:  p_CPU * W / C.
        """
        if self.cpu_capacity <= 0:
            return 0.0
        return self.cpu_power * (workload_ops / self.cpu_capacity)

    def task_energy(self, n_input_bits, n_output_bits, workload_ops):
        """
        Total executor-side energy for one task (the executor energy model):
            E_n = p_CPU * (W / C) + p_tx_wired * (O / R_dl)

        Note: the NO-side energy (gNB tx/rx and Controller CPU) is accounted
        elsewhere via `EnergyModel.*_wireless_gnb(...)` and not here.
        """
        return (
            self.compute_energy(workload_ops)
            + self.tx_energy(n_output_bits)
        )

    # ------------------------------------------------------------------
    #                       External datarate setter
    # ------------------------------------------------------------------
    def set_istantaneous_datarate_pattern(self, ul_datarate, dl_datarate):
        """
        Set wired backhaul data rates for the current slot.
        Called by `network_manager.cloud_wired_datarate(...)` in the loop.
        """
        self.ul_datarate = ul_datarate
        self.dl_datarate = dl_datarate