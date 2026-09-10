"""
Vehicle node — wireless 5G executor.

Symmetric with `cloud.py`:
  - Wireless UL/DL data rates are set externally by
    `network_manager.set_all_vehicles_data_rate_5g_standard(...)`.
  - Energy accounting uses the EARTH/Auer-Holtkamp model for UE-side
    wireless transmission/reception, via `network_manager.EnergyModel`.

Beacon modes:
  - 'nominal'  -> self-declared parameters (used in Stage 1 allocation).
                  Optionally biased by `misreport_factor`.
  - 'realized' -> ground-truth realization with NV noise (Tab. I, sigma=10%
                  of mean) over the TRUE underlying parameters.
                  This is what the Controller sees ex-post in Stage 2.
"""

import numpy as np

from network_manager import EnergyModel


# Std fraction matching Table I NV notation (sigma = 10% of mean).
NV_STD_FRACTION = 0.10

# Tolleranza di presenza [s]: un veicolo e' "presente" all'istante richiesto
# solo se ha un record di mobilita' entro questa tolleranza. Senza, un veicolo
# uscito di scena verrebbe agganciato alla sua ultima posizione (stale) e
# trattato come server fantasma. La traccia e' a 0.1 s -> un veicolo presente
# ha sempre un record <=0.05 s; uno assente e' molto piu' lontano.
PRESENCE_TOL_S = 0.5


class Vehicle:
    """
    Vehicular compute node.

    Parameters
    ----------
    vehicle_id : int
        Unique vehicle identifier (non-negative).
    cpu_capacity : float [FLOPS]
        True compute capacity available for offloading (already accounts for
        the 10% fraction the paper allocates to offloading, see Tab. I).
    queue_capacity : int
        Maximum number of concurrent tasks the vehicle accepts.
    cpu_power : float [W]
        CPU power draw during computation.
    ue_power : float [dBm]
        UE transmit power for the 5G uplink.
    energy_available : float [J]
        Energy budget dedicated to offloading.
    dollars_per_kwh : float [$/kWh]
        Energy-to-cash conversion rate (lambda_i in the cost model).
    ul_datarate, dl_datarate : float [bps]
        Wireless data rates; updated externally each slot by
        `network_manager.set_all_vehicles_data_rate_5g_standard(...)`.
    position_x, position_y : float
        Current vehicle position (set per-slot from SUMO trace).
    speed : float [m/s]
        Current vehicle speed.
    misreport_factor : float in [0, 1]
        Fraction by which the vehicle inflates its declared CPU capacity in
        nominal beacons (0 = honest, larger = more optimistic).
        Default 0.0. Used in the misreporting sensitivity analysis.
    """

    def __init__(
        self,
        vehicle_id=None,
        cpu_capacity=None,
        queue_capacity=None,
        cpu_power=None,
        ue_power=None,
        energy_available=None,
        dollars_per_kwh=None,
        ul_datarate=None,
        dl_datarate=None,
        position_x=None,
        position_y=None,
        speed=None,
        misreport_factor=0.0,
    ):
        self.vehicle_id = vehicle_id
        self.cpu_capacity = cpu_capacity
        self.cpu_power = cpu_power
        self.ue_power = ue_power
        self.energy_available = energy_available
        self.dollars_per_kwh = dollars_per_kwh
        self.queue_capacity = queue_capacity
        self.ul_datarate = ul_datarate
        self.dl_datarate = dl_datarate
        self.position_x = position_x
        self.position_y = position_y
        self.speed = speed
        self.misreport_factor = float(misreport_factor)
        self.present = True   # aggiornato per-slot da set_istantaneous_mobility_pattern

    # ------------------------------------------------------------------
    #                       Beacon creation
    # ------------------------------------------------------------------
    def create_beacon(self, instant_sec, mode='nominal', rng=None):
        """
        Create a beacon describing the vehicle's state at `instant_sec`.

        Parameters
        ----------
        instant_sec : float
            Beacon timestamp [s].
        mode : {'nominal', 'realized'}
            'nominal'  -> declared parameters (used in Stage 1).
                          Inflated by `self.misreport_factor` if > 0.
            'realized' -> ground-truth realization (used in Stage 2),
                          adds NV noise (sigma = 10% of mean) on top of
                          the TRUE values (NOT of the declared ones, so
                          misreporting cannot hide behind noise).
        rng : np.random.Generator, optional
            Required when mode='realized'.

        Returns
        -------
        tuple
            (instant_sec, vehicle_id, cpu_capacity, queue_capacity,
             cpu_power, ue_power, energy_available, dollars_per_kwh,
             ul_datarate, dl_datarate, position_x, position_y, speed)
        """
        required = [
            'vehicle_id', 'cpu_capacity', 'queue_capacity', 'cpu_power',
            'ue_power', 'energy_available', 'dollars_per_kwh',
            'ul_datarate', 'dl_datarate', 'position_x', 'position_y', 'speed',
        ]
        for attr in required:
            if getattr(self, attr) is None:
                raise ValueError(f"Vehicle {attr} is not defined")

        if mode == 'nominal':
            # Optimistic self-declaration if misreport_factor > 0:
            #   - CPU capacity inflated (faster computation appearance)
            #   - CPU power deflated  (lower energy cost appearance)
            # These two together help the misreporter rank higher in Stage 1.
            rho = self.misreport_factor
            cpu_capacity = self.cpu_capacity * (1.0 + rho)
            cpu_power = self.cpu_power * (1.0 - rho)
            ue_power = self.ue_power
            energy_available = self.energy_available
            dollars_per_kwh = self.dollars_per_kwh
        elif mode == 'realized':
            if rng is None:
                raise ValueError("rng required for mode='realized'")
            # NV noise around TRUE values (not declared ones). This is what
            # the Controller observes ex-post via realized-cost beacons in
            # Sec. III workflow (e), and what feeds the value functions
            # v_z^omega and the deadline indicator 1_{i,tau}^omega.
            cpu_capacity = rng.normal(self.cpu_capacity, abs(self.cpu_capacity) * NV_STD_FRACTION)
            cpu_power = rng.normal(self.cpu_power, abs(self.cpu_power) * NV_STD_FRACTION)
            ue_power = rng.normal(self.ue_power, abs(self.ue_power) * NV_STD_FRACTION)
            energy_available = rng.normal(self.energy_available, abs(self.energy_available) * NV_STD_FRACTION)
            # dollars_per_kwh: contractual, not randomized
            dollars_per_kwh = self.dollars_per_kwh
        else:
            raise ValueError(f"unknown mode: {mode}")

        # queue_capacity is deterministic (system parameter)
        queue_capacity = self.queue_capacity

        # Data rates come from network_manager (set per-slot before beacon)
        ul_datarate = self.ul_datarate
        dl_datarate = self.dl_datarate

        return (
            instant_sec,
            self.vehicle_id,
            cpu_capacity,
            queue_capacity,
            cpu_power,
            ue_power,
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
        Energy consumed by the vehicle UE to transmit `n_bits` over the 5G
        uplink, given its current ul_datarate.
        Used for: vehicle -> Controller (task result return).
        """
        return EnergyModel.tx_energy_wireless_ue(
            p_tx_dbm=self.ue_power, n_bits=n_bits, datarate_bps=self.ul_datarate
        )

    def rx_energy(self, n_bits):
        """
        Energy consumed by the vehicle UE to receive `n_bits` over the 5G
        downlink, given its current dl_datarate.
        Used for: Controller -> vehicle (task input delivery).
        """
        return EnergyModel.rx_energy_wireless_ue(
            n_bits=n_bits, datarate_bps=self.dl_datarate
        )

    def compute_energy(self, workload_ops):
        """
        Energy consumed by the vehicle CPU to execute `workload_ops`.
        First term of the executor energy model:  p_CPU * W / C.
        """
        if self.cpu_capacity <= 0:
            return 0.0
        return self.cpu_power * (workload_ops / self.cpu_capacity)

    def task_energy(self, n_input_bits, n_output_bits, workload_ops):
        """
        Total executor-side energy for one task (the executor energy model):
            E_n = p_CPU * (W / C) + p_tx_ue * (O / R_ul)

        Note: gNB-side and Controller-side energy is accounted via
        `EnergyModel.*_wireless_gnb(...)` outside the Vehicle class.
        """
        return (
            self.compute_energy(workload_ops)
            + self.tx_energy(n_output_bits)
        )

    # ------------------------------------------------------------------
    #                       External per-slot setters
    # ------------------------------------------------------------------
    def set_istantaneous_mobility_pattern(self, instant_sec, mobility_df):
        """
        Update position and speed from the SUMO mobility trace at the
        timestamp closest to `instant_sec`. Marks the vehicle ABSENT
        (self.present=False) if it has no record within PRESENCE_TOL_S of
        instant_sec, so a vehicle off-scene is NOT reused as a phantom server
        with a stale position.
        """
        sub = mobility_df[mobility_df['id'] == self.vehicle_id]
        if sub.empty:
            self.present = False
            return
        idx = sub['time'].sub(instant_sec).abs().idxmin()
        row = mobility_df.loc[idx]
        if abs(float(row['time']) - instant_sec) > PRESENCE_TOL_S:
            self.present = False
            return
        self.present = True
        self.position_x = row['position_x']
        self.position_y = row['position_y']
        self.speed = row['speed']

    def set_istantaneous_datarate_pattern(self, ul_datarate, dl_datarate):
        """
        Set wireless UL/DL data rates for the current slot.
        Called by `network_manager.set_all_vehicles_data_rate_5g_standard`.
        """
        self.ul_datarate = ul_datarate
        self.dl_datarate = dl_datarate
