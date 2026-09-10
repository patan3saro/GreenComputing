"""
Network Manager — 5G NR Channel and Energy Model
==================================================
Implements:
  - 3GPP TR 38.901 Urban NLOS path loss
  - Log-normal shadowing + Rayleigh fading
  - Dynamic per-vehicle interference computed at gNB position
  - Shannon-based SINR capacity with protocol efficiency
  - Energy consumption: Auer-Holtkamp PA + circuit model (EARTH project)

References
----------
[Auer2011]   Auer et al., "How much energy is needed to run a wireless
             network?", IEEE Wireless Commun., 2011.
[Holtkamp2013] Holtkamp et al., "A parameterized base station power model",
               IEEE Commun. Lett., 2013.
[Mahadevan2009] Mahadevan et al., "A power benchmarking framework for
                network devices", SIGCOMM 2009.
[3GPP38901]   3GPP TR 38.901 v16, "Study on channel model for frequencies
              from 0.5 to 100 GHz", 2020.
"""

import numpy as np


# ----------------------------------------------------------------------
#                     Unit conversions
# ----------------------------------------------------------------------
def dbm_to_mw(dbm):
    """Convert dBm to mW."""
    return 10 ** (dbm / 10)


def mw_to_dbm(mw):
    """Convert mW to dBm."""
    return 10 * np.log10(mw)


def db_to_lin(db):
    """Convert dB to linear ratio."""
    return 10 ** (db / 10)


# ----------------------------------------------------------------------
#                     Path loss model
# ----------------------------------------------------------------------
def path_loss_db(d_km, freq_mhz):
    """
    3GPP TR 38.901 Urban NLOS simplified path loss.

    PL [dB] = 32.4 + 20*log10(f_MHz) + 30*log10(d_km)
    """
    return 32.4 + 20 * np.log10(freq_mhz) + 30 * np.log10(d_km)


# ----------------------------------------------------------------------
#                     Energy model parameters (EARTH project)
# ----------------------------------------------------------------------
class EnergyModel:
    """
    5G NR energy model based on Auer-Holtkamp (EARTH project).

    Total transmit energy for sending `n_bits` over rate `R`:

        E_tx = (P_circuit + P_tx / eta_PA) * (n_bits / R)

    Total receive energy:

        E_rx = P_circuit_rx * (n_bits / R)
    """

    # UE side (vehicle and end-user)
    UE_PA_EFFICIENCY = 0.35           # PA efficiency (Auer 2011 Tab. 2)
    UE_CIRCUIT_TX_W = 0.4             # tx-mode circuit power [W]
    UE_CIRCUIT_RX_W = 0.3             # rx-mode circuit power [W]

    # gNB side (Network Operator base station)
    GNB_PA_EFFICIENCY = 0.31          # PA efficiency (Holtkamp 2013)
    GNB_CIRCUIT_TX_W = 6.8            # per RF chain [W]
    GNB_CIRCUIT_RX_W = 6.8

    # Wired (cloud backhaul) — NIC active power, no RF chain
    WIRED_NIC_TX_W = 0.5              # 10 Gbps NIC active (Mahadevan 2009)
    WIRED_NIC_RX_W = 0.4

    @staticmethod
    def tx_energy_wireless_ue(p_tx_dbm, n_bits, datarate_bps):
        """Energy for UE-side wireless transmission [Joules]."""
        if datarate_bps <= 0 or n_bits <= 0:
            return 0.0
        p_tx_w = dbm_to_mw(p_tx_dbm) * 1e-3                    # dBm -> W
        p_total = EnergyModel.UE_CIRCUIT_TX_W + p_tx_w / EnergyModel.UE_PA_EFFICIENCY
        t_tx = n_bits / datarate_bps
        return p_total * t_tx

    @staticmethod
    def tx_energy_wireless_gnb(p_tx_dbm, n_bits, datarate_bps):
        """Energy for gNB-side wireless transmission [Joules]."""
        if datarate_bps <= 0 or n_bits <= 0:
            return 0.0
        p_tx_w = dbm_to_mw(p_tx_dbm) * 1e-3
        p_total = EnergyModel.GNB_CIRCUIT_TX_W + p_tx_w / EnergyModel.GNB_PA_EFFICIENCY
        t_tx = n_bits / datarate_bps
        return p_total * t_tx

    @staticmethod
    def rx_energy_wireless_ue(n_bits, datarate_bps):
        """Energy for UE-side wireless reception [Joules]."""
        if datarate_bps <= 0 or n_bits <= 0:
            return 0.0
        t_rx = n_bits / datarate_bps
        return EnergyModel.UE_CIRCUIT_RX_W * t_rx

    @staticmethod
    def rx_energy_wireless_gnb(n_bits, datarate_bps):
        """Energy for gNB-side wireless reception [Joules]."""
        if datarate_bps <= 0 or n_bits <= 0:
            return 0.0
        t_rx = n_bits / datarate_bps
        return EnergyModel.GNB_CIRCUIT_RX_W * t_rx

    @staticmethod
    def tx_energy_wired(n_bits, datarate_bps):
        """Energy for wired backhaul transmission [Joules]."""
        if datarate_bps <= 0 or n_bits <= 0:
            return 0.0
        t_tx = n_bits / datarate_bps
        return EnergyModel.WIRED_NIC_TX_W * t_tx

    @staticmethod
    def rx_energy_wired(n_bits, datarate_bps):
        """Energy for wired backhaul reception [Joules]."""
        if datarate_bps <= 0 or n_bits <= 0:
            return 0.0
        t_rx = n_bits / datarate_bps
        return EnergyModel.WIRED_NIC_RX_W * t_rx


# ----------------------------------------------------------------------
#                     Channel / SINR computation
# ----------------------------------------------------------------------
def _bounded_fading_db(rng):
    """
    Rayleigh small-scale fading expressed in dB, bounded to [-20, +10] dB
    to avoid pathological draws that drive PL negative.
    """
    raw = 20 * np.log10(rng.rayleigh(1.0))
    return float(np.clip(raw, -20.0, 10.0))


def _compute_received_power_dbm(
    tx_power_dbm, distance_m, freq_mhz, beamforming_gain_db, shadowing_db, fading_db
):
    """
    Received power [dBm] at the receiver given large + small scale effects.
    """
    d_km = max(distance_m / 1000.0, 0.01)
    pl_db = path_loss_db(d_km, freq_mhz) - shadowing_db - fading_db
    return tx_power_dbm - pl_db + beamforming_gain_db


def set_all_vehicles_data_rate_5g_standard(
    vehicles,
    potenza_dl_dbm,
    rng,
    gnb_position=(900.0, 900.0),
    banda_tot_mhz=400,
    freq_mhz=6000,
    num_stream=2,
    beamforming_gain_db=5,
    efficienza=0.85,
    sinr_min_db=-5,
    active_ratio=1.0,
    shadowing_std_db=4.0,
):
    """
    Assign instantaneous UL/DL data rates to each vehicle based on:
      - 3GPP TR 38.901 Urban NLOS path loss
      - Log-normal shadowing (sigma = shadowing_std_db)
      - Rayleigh small-scale fading
      - Dynamic uplink interference from other vehicles to the same gNB
      - Downlink interference from neighboring beams (ad-hoc 10% factor)
      - Shannon capacity with `efficienza` protocol efficiency and `num_stream` MIMO layers
      - SINR threshold below which UL/DL rate is forced to zero

    Parameters
    ----------
    vehicles : list[Vehicle]
        Vehicles whose position/UE power are already set.
    potenza_dl_dbm : float
        gNB downlink transmit power [dBm].
    rng : np.random.Generator
        External random generator (do NOT seed here).
    gnb_position : tuple
        (x, y) position of the gNB; used for all distance/interference computations.
    Other parameters: see Table I of the paper.

    Returns
    -------
    list[Vehicle]
        Same list with ul_datarate / dl_datarate set.
        Vehicles below SINR threshold get rate = 0 (not silently skipped).

    Notes
    -----
    - The RNG is passed in; there is no internal seeding.
    - The noise floor uses the per-vehicle allocated bandwidth.
    - Interference is computed from the distance to the gNB.
    - Rayleigh fading is clipped to [-20, +10] dB.
    - Vehicles below the SINR threshold get rate = 0 and stay in the list.
    """
    if not vehicles:
        return []

    banda_totale_hz = banda_tot_mhz * 1e6
    n_eff = max(1, int(len(vehicles) * active_ratio))
    banda_hz_per_vehicle = banda_totale_hz / n_eff

    # Noise power on the actual allocated bandwidth per vehicle
    noise_dbm = -174 + 10 * np.log10(banda_hz_per_vehicle)
    noise_mw = dbm_to_mw(noise_dbm)

    gnb_x, gnb_y = gnb_position

    # Pre-compute per-vehicle channel realizations and distances from gNB
    distances_m = np.array([
        np.linalg.norm([v.position_x - gnb_x, v.position_y - gnb_y]) for v in vehicles
    ])
    shadowings_db = rng.normal(0, shadowing_std_db, size=len(vehicles))
    fadings_db = np.array([_bounded_fading_db(rng) for _ in vehicles])

    # Pre-compute UL received powers at gNB for every vehicle (used both for
    # signal and for interference summation, from the same reference point).
    p_rx_ul_mw_all = np.array([
        dbm_to_mw(
            _compute_received_power_dbm(
                tx_power_dbm=v.ue_power,
                distance_m=distances_m[i],
                freq_mhz=freq_mhz,
                beamforming_gain_db=beamforming_gain_db,
                shadowing_db=shadowings_db[i],
                fading_db=fadings_db[i],
            )
        )
        for i, v in enumerate(vehicles)
    ])

    # In 5G NR with OFDMA, vehicles allocated on DISJOINT resource blocks do
    # NOT interfere on uplink. Only vehicles re-using the same RBs (e.g. via
    # aggressive scheduling under heavy load) contribute UL interference.
    # We model this by sampling a small set of "co-channel" interferers from
    # the active subset (size n_eff). The remaining vehicles in the list
    # are *idle* in this slot and contribute zero UL interference.
    active_indices = rng.choice(len(vehicles), size=n_eff, replace=False)
    active_mask = np.zeros(len(vehicles), dtype=bool)
    active_mask[active_indices] = True

    # Co-channel reuse fraction: among the n_eff active, only a small share
    # reuses the same RB as any given vehicle (intra-cell collision).
    ul_reuse_fraction = 0.05
    total_active_ul_mw = p_rx_ul_mw_all[active_mask].sum()

    for i, v in enumerate(vehicles):
        # ---------------- Uplink SINR ----------------
        p_signal_ul = p_rx_ul_mw_all[i]
        # If this vehicle is idle, interference is just the noise floor.
        # If active, see only a fraction `ul_reuse_fraction` of the other
        # active vehicles' UL power as co-channel interference.
        if active_mask[i]:
            interferenza_ul = (total_active_ul_mw - p_signal_ul) * ul_reuse_fraction
        else:
            interferenza_ul = 0.0
        sinr_ul = p_signal_ul / (interferenza_ul + noise_mw)
        sinr_ul_db = 10 * np.log10(sinr_ul)

        # ---------------- Downlink SINR ----------------
        p_rx_dl_dbm = _compute_received_power_dbm(
            tx_power_dbm=potenza_dl_dbm,
            distance_m=distances_m[i],
            freq_mhz=freq_mhz,
            beamforming_gain_db=beamforming_gain_db,
            shadowing_db=shadowings_db[i],
            fading_db=fadings_db[i],
        )
        p_rx_dl_mw = dbm_to_mw(p_rx_dl_dbm)
        # Inter-beam DL interference: 10% leakage from the (n_eff-1) other
        # beams (simplifying assumption — coherent with the original code).
        interferenza_dl = (n_eff - 1) * p_rx_dl_mw * 0.1
        sinr_dl = p_rx_dl_mw / (interferenza_dl + noise_mw)
        sinr_dl_db = 10 * np.log10(sinr_dl)

        # ---------------- Capacity ----------------
        # Do not skip; assign 0 if below threshold (vehicle stays in
        # the list but is effectively non-offloadable for this slot).
        if sinr_ul_db < sinr_min_db or sinr_dl_db < sinr_min_db:
            v.set_istantaneous_datarate_pattern(0, 0)
            continue

        rate_ul = efficienza * banda_hz_per_vehicle * np.log2(1 + sinr_ul) * num_stream
        rate_dl = efficienza * banda_hz_per_vehicle * np.log2(1 + sinr_dl) * num_stream

        v.set_istantaneous_datarate_pattern(int(rate_ul), int(rate_dl))

    return vehicles


# ----------------------------------------------------------------------
#                     Cloud backhaul rate (wired Internet)
# ----------------------------------------------------------------------
def cloud_wired_datarate(cloud_node, rng=None, nominal_rate_bps=1e11, jitter_fraction=0.05):
    """
    Wired backhaul to the cloud: nominal rate ± small jitter.
    The cloud is reached via a fixed-bandwidth Internet link plus a constant
    propagation delay (handled elsewhere in T_unified).
    """
    if rng is None:
        return int(nominal_rate_bps), int(nominal_rate_bps)
    jitter = rng.normal(1.0, jitter_fraction)
    r = max(int(nominal_rate_bps * jitter), int(nominal_rate_bps * 0.5))
    return r, r