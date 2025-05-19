import numpy as np

def dbm_to_mw(dbm):
    """Converte da dBm a milliwatt."""
    return 10 ** (dbm / 10)

def mw_to_dbm(mw):
    """Converte da milliwatt a dBm."""
    return 10 * np.log10(mw)


def path_loss_db(d_km, freq_mhz):
    """
    Calcola il path loss urbano (modello 3GPP NLOS semplificato).
    """
    return 32.4 + 20 * np.log10(freq_mhz) + 30 * np.log10(d_km)


import json

def set_all_vehicles_data_rate_5g_standard(
        vehicles,
        potenza_dl_dbm,
        seed_random,
        avg_data_size=200*8,

        banda_tot_mhz=400,
        freq_mhz=6000,
        num_stream=2,
        beamforming_gain_db=5,
        efficienza=0.85,
        sinr_min_db=-5,
        active_ratio=1.0  # <-- aggiunto per stimare quanti nodi trasmettono
):
    np.random.seed(seed_random)
    risultati = []
    if not vehicles:
        return risultati

    DEFAULT_TRAFFIC = 160000  # bit (I + O attesi)
    vehicle_weights = {v.vehicle_id: DEFAULT_TRAFFIC for v in vehicles}
    total_weight = sum(vehicle_weights.values())
    banda_totale_Hz = banda_tot_mhz * 1e6

    n_eff = max(1, int(len(vehicles) * active_ratio))
    noise_dbm = -174 + 10 * np.log10(banda_totale_Hz / n_eff)
    noise_mw = dbm_to_mw(noise_dbm)

    for i, v in enumerate(vehicles):
        distanza_m = np.linalg.norm(np.array([v.position_x, v.position_y]) - [900, 900])
        d_km = max(distanza_m / 1000, 0.01)

        weight = vehicle_weights.get(v.vehicle_id, DEFAULT_TRAFFIC)
        banda_Hz = (weight / total_weight) * banda_totale_Hz

        shadowing_dB = rng.normal(0, 4)
        fading_dB = 20 * np.log10(rng.rayleigh(1.0))
        PL = path_loss_db(d_km, freq_mhz) - shadowing_dB - fading_dB

        p_rx_ul_dbm = v.ue_power - PL + beamforming_gain_db
        p_rx_ul_mw = dbm_to_mw(p_rx_ul_dbm)
        interferenza_ul = sum(
            dbm_to_mw(vk.ue_power - path_loss_db(max(np.linalg.norm(np.array([vk.position_x, vk.position_y]) - [0, 0]) / 1000, 0.01), freq_mhz))
            for j, vk in enumerate(vehicles) if j != i
        )

        sinr_ul = p_rx_ul_mw / (interferenza_ul + noise_mw)
        sinr_ul_db = 10 * np.log10(sinr_ul)

        p_rx_dl_dbm = potenza_dl_dbm - PL + beamforming_gain_db
        p_rx_dl_mw = dbm_to_mw(p_rx_dl_dbm)
        interferenza_dl = (n_eff - 1) * p_rx_dl_mw * 0.1

        sinr_dl = p_rx_dl_mw / (interferenza_dl + noise_mw)
        sinr_dl_db = 10 * np.log10(sinr_dl)

        if sinr_ul_db < sinr_min_db or sinr_dl_db < sinr_min_db:
            continue

        rate_ul = efficienza * banda_Hz * np.log2(1 + sinr_ul) * num_stream
        rate_dl = efficienza * banda_Hz * np.log2(1 + sinr_dl) * num_stream

        v.set_istantaneous_datarate_pattern(int(rate_ul), int(rate_dl))
        risultati.append(v)

    return risultati


