import numpy as np


def dbm_to_mw(dbm):
    """Converte da dBm a milliwatt."""
    return 10 ** (dbm / 10)


def mw_to_dbm(mw):
    """Converte da milliwatt a dBm."""
    return 10 * np.log10(mw)


def path_loss_db(d_km, freq_MHz):
    """
    Calcola il path loss urbano (modello 3GPP NLOS semplificato).
    """
    return 32.4 + 20 * np.log10(freq_MHz) + 30 * np.log10(d_km)


def vehicles_to_nodes(vehicles, current_time_sec, data_len=8000000):
    """
    Converte una lista di veicoli in nodi con distanza dalla BS e potenza UL.
    """
    res = []
    for v in vehicles:
        pos_x, pos_y, _ = v.get_position_and_speed(current_time_sec)
        distance = np.linalg.norm(np.array([pos_x, pos_y]) - [0, 0])
        res.append((v.id, distance, v.ue_power, data_len))
    return res


def calcola_data_rate_5g_standard(
        vehicles,
        current_time_sec,
        potenza_dl_dbm,
        banda_tot_MHz=200,
        freq_MHz=6000,
        num_stream=2,
        beamforming_gain_dB=5,
        efficienza=0.85,
        sinr_min_db=-5  # soglia minima SINR per essere considerati "in coverage"
):
    """
    Simula throughput e latenza per nodi 5G NR secondo lo standard Release 17–18.
    I nodi con SINR UL o DL inferiore alla soglia sono esclusi.

    Args:
        vehicles: lista di oggetti veicolo
        current_time_sec: tempo corrente (in secondi)
        potenza_dl_dbm: potenza trasmessa dalla BS (dBm)
        banda_tot_MHz: banda totale disponibile (MHz)
        freq_MHz: frequenza portante (MHz)
        num_stream: numero di stream MIMO per utente
        beamforming_gain_dB: guadagno medio da beamforming
        efficienza: efficienza fisica (es. 0.85)
        sinr_min_db: soglia minima SINR per la copertura

    Returns:
        Lista di dizionari con: id, distanza, throughput UL/DL, latenza UL/DL
    """
    nodi = vehicles_to_nodes(vehicles, current_time_sec)
    risultati = []
    N = len(nodi)

    if N == 0:
        return risultati

    noise_dbm = -174 + 10 * np.log10((banda_tot_MHz * 1e6) / N)
    noise_mw = dbm_to_mw(noise_dbm)

    for i, (id_nodo, distanza_m, pot_ul_dbm, dati_MB) in enumerate(nodi):
        d_km = max(distanza_m / 1000, 0.01)
        banda_Hz = (banda_tot_MHz / N) * 1e6

        # Fading e path loss
        shadowing_dB = np.random.normal(0, 4)
        fading_dB = 20 * np.log10(np.random.rayleigh(1.0))
        PL = path_loss_db(d_km, freq_MHz) - shadowing_dB - fading_dB

        # === UPLINK ===
        p_rx_ul_dbm = pot_ul_dbm - PL + beamforming_gain_dB
        p_rx_ul_mw = dbm_to_mw(p_rx_ul_dbm)

        interferenza_ul = sum(
            dbm_to_mw(p - path_loss_db(max(d / 1000, 0.01), freq_MHz))
            for j, (_, d, p, _) in enumerate(nodi) if j != i
        )

        sinr_ul = p_rx_ul_mw / (interferenza_ul + noise_mw)
        sinr_ul_db = 10 * np.log10(sinr_ul)

        # === DOWNLINK ===
        p_rx_dl_dbm = potenza_dl_dbm - PL + beamforming_gain_dB
        p_rx_dl_mw = dbm_to_mw(p_rx_dl_dbm)
        interferenza_dl = (N - 1) * p_rx_dl_mw * 0.1

        sinr_dl = p_rx_dl_mw / (interferenza_dl + noise_mw)
        sinr_dl_db = 10 * np.log10(sinr_dl)

        # Esclusione nodi fuori copertura
        if sinr_ul_db < sinr_min_db or sinr_dl_db < sinr_min_db:
            continue

        # Throughput
        rate_ul = efficienza * banda_Hz * np.log2(1 + sinr_ul) * num_stream
        tempo_ul = (dati_MB * 8 * 1e6) / rate_ul

        rate_dl = efficienza * banda_Hz * np.log2(1 + sinr_dl) * num_stream
        tempo_dl = (dati_MB * 8 * 1e6) / rate_dl

        # Latenza
        t_propagazione = distanza_m / 3e8
        t_scheduling = 0.00025
        t_processing = 0.0005
        t_harq = 0.001 if sinr_dl_db < 5 else 0

        lat_ul = round(tempo_ul + t_propagazione + t_scheduling + t_processing + t_harq, 4)
        lat_dl = round(tempo_dl + t_propagazione + t_scheduling + t_processing + t_harq, 4)

        risultati.append({
            'id': id_nodo,
            'distanza_m': distanza_m,
            'useful_throughput_ul': int(rate_ul),
            'useful_throughput_dl': int(rate_dl),
            'Latenza_UL_s': lat_ul,
            'Latenza_DL_s': lat_dl
        })

    return risultati


def extend_beacon_with_datarate(beacon, datarate_by_id):
    """
    Estende un beacon aggiungendo ul/dl datarate.
    """
    ul = datarate_by_id['useful_throughput_ul']
    dl = datarate_by_id['useful_throughput_dl']
    return beacon + (ul, dl)


def extend_cloud_beacon(beacon, cloud_dr):
    """
    Estende un beacon cloud con un datarate identico per UL e DL.
    """
    return beacon + (cloud_dr, cloud_dr)
