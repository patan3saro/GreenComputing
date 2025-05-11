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


def set_all_vehicles_data_rate_5g_standard(
        vehicles,
        potenza_dl_dbm,
        avg_data_size=100000,
        banda_tot_mhz=400,
        freq_mhz=6000,
        num_stream=2,
        beamforming_gain_db=5,
        efficienza=0.85,
        sinr_min_db=-5  # soglia minima SINR per essere considerati "in coverage"
):
    """
    Simula throughput e latenza per nodi 5G NR secondo lo standard Release 17–18.
    I nodi con SINR UL o DL inferiore alla soglia sono esclusi.

    Args:
        vehicles: lista di oggetti veicolo
        potenza_dl_dbm: potenza trasmessa dalla BS (dBm)
        banda_tot_mhz: banda totale disponibile (MHz)
        freq_mhz: frequenza portante (MHz)
        num_stream: numero di stream MIMO per utente
        beamforming_gain_db: guadagno medio da beamforming
        efficienza: efficienza fisica (es. 0.85)
        sinr_min_db: soglia minima SINR per la copertura

    Returns:
        Lista di dizionari con: id, distanza, throughput UL/DL, latenza UL/DL
        :param sinr_min_db:
        :param efficienza:
        :param beamforming_gain_db:
        :param num_stream:
        :param freq_mhz:
        :param vehicles:
        :param potenza_dl_dbm:
        :param banda_tot_mhz:
        :param avg_data_size:
    """
    risultati = []
    n = len(vehicles)
    if n == 0:
        return risultati

    noise_dbm = -174 + 10 * np.log10((banda_tot_mhz * 1e6) / n)
    noise_mw = dbm_to_mw(noise_dbm)

    for i, v in enumerate(vehicles):
        distanza_m = np.linalg.norm(np.array([v.position_x, v.position_y]) - [0, 0])

        d_km = max(distanza_m / 1000, 0.01)
        banda_Hz = (banda_tot_mhz / n) * 1e6

        # Fading e path loss
        shadowing_dB = np.random.normal(0, 4)
        fading_dB = 20 * np.log10(np.random.rayleigh(1.0))
        PL = path_loss_db(d_km, freq_mhz) - shadowing_dB - fading_dB

        # === UPLINK ===
        p_rx_ul_dbm = v.ue_power - PL + beamforming_gain_db
        p_rx_ul_mw = dbm_to_mw(p_rx_ul_dbm)

        interferenza_ul = sum(
            dbm_to_mw(vk.ue_power - path_loss_db(max(np.linalg.norm(np.array([vk.position_x, vk.position_y]) - [0, 0]) / 1000, 0.01), freq_mhz))
            for j, vk in enumerate(vehicles) if j != i
        )

        sinr_ul = p_rx_ul_mw / (interferenza_ul + noise_mw)
        sinr_ul_db = 10 * np.log10(sinr_ul)

        # === DOWNLINK ===
        p_rx_dl_dbm = potenza_dl_dbm - PL + beamforming_gain_db
        p_rx_dl_mw = dbm_to_mw(p_rx_dl_dbm)
        interferenza_dl = (n - 1) * p_rx_dl_mw * 0.1

        sinr_dl = p_rx_dl_mw / (interferenza_dl + noise_mw)
        sinr_dl_db = 10 * np.log10(sinr_dl)

        # Esclusione nodi fuori copertura
        if sinr_ul_db < sinr_min_db or sinr_dl_db < sinr_min_db:
            continue

        # Throughput
        rate_ul = efficienza * banda_Hz * np.log2(1 + sinr_ul) * num_stream
        tempo_ul = (avg_data_size * 8 * 1e6) / rate_ul

        rate_dl = efficienza * banda_Hz * np.log2(1 + sinr_dl) * num_stream
        tempo_dl = (avg_data_size * 8 * 1e6) / rate_dl

        # Latenza
        t_propagazione = float(distanza_m) / 3e+8
        t_scheduling = 0.00025
        t_processing = 0.0005
        t_harq = 0.001 if sinr_dl_db < 5 else 0

        lat_ul = round(tempo_ul + t_propagazione + t_scheduling + t_processing + t_harq, 4)
        lat_dl = round(tempo_dl + t_propagazione + t_scheduling + t_processing + t_harq, 4)

        v.set_istantaneous_datarate_pattern(int(rate_ul), int(rate_dl))

        risultati.append(v)

    return risultati
