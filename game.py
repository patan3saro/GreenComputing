import itertools
import math
from itertools import combinations
from config import *

# Importa optimize_task_allocation
from value_function import optimize_task_allocation

def is_convex_game(coalition_values, player_ids):
    """
    Verifica se il gioco è convesso.
    Un gioco è convesso se per ogni coppia di coalizioni S e T, vale:
    v(S) + v(T) ≤ v(S∪T) + v(S∩T)

    Args:
        coalition_values: Dictionary mapping coalitions to their values
        player_ids: List of player IDs

    Returns:
        bool: True se il gioco è convesso, False altrimenti
    """
    # Controlla la condizione di convessità per ogni coppia di coalizioni
    for S_list in range(1, len(player_ids)):
        for T_list in range(1, len(player_ids)):
            for S in combinations(player_ids, S_list):
                for T in combinations(player_ids, T_list):
                    S_set = frozenset(S)
                    T_set = frozenset(T)

                    # Calcola S∪T e S∩T
                    union = S_set.union(T_set)
                    intersection = S_set.intersection(T_set)

                    # Controlla la condizione di convessità
                    if coalition_values.get(S_set, 0) + coalition_values.get(T_set, 0) > \
                       coalition_values.get(union, 0) + coalition_values.get(intersection, 0):
                        return False

    return True

def calculate_shapley_values(beacons, tasks, include_NO=True):
    """
    Calcola i valori di Shapley per tutti i giocatori (beacons + eventualmente "NO").
    Verifica se il gioco è convesso e aggiunge 1 ai valori di Shapley solo se il gioco NON è convesso.

    Args:
        beacons: Lista di beacon, dove ogni beacon è una tupla (priorità, id, dettagli, ...)
        tasks: Lista dei task da allocare
        include_NO: Se True, include un giocatore speciale "NO" (Network Operator)

    Returns:
        Tuple: (shapley_values, coalition_values, is_convex)
            - shapley_values: Dictionary mapping each player to their Shapley value
            - coalition_values: Dictionary mapping each coalition to its value
            - is_convex: Boolean indicating if the game is convex
    """
    # Estrai gli ID dei beacon
    player_ids = [str(beacon[1]) for beacon in beacons]

    # Aggiungi il giocatore "NO" se richiesto special ID 250596
    if include_NO:
        player_ids.append(str(NO_ID))

    # Genera tutte le coalizioni e calcola i loro valori
    coalition_values = {}

    # Aggiungi la coalizione vuota
    coalition_values[frozenset()] = 0

    # Genera tutte le possibili combinazioni di giocatori
    for r in range(1, len(player_ids) + 1):
        for combo in combinations(player_ids, r):
            coalition = frozenset(combo)

            # Se "NO" non è nella coalizione, calcola normalmente
            if str(NO_ID) not in coalition:
                coalition_values[coalition] = 0  # Coalizione senza beacon validi
            else:
                # Coalizione che include "NO"
                # Rimuovi "NO" dalla coalizione e utilizza solo i beacon rimanenti
                remaining_players = coalition - {str(NO_ID)}

                if not remaining_players:
                    coalition_values[coalition] = 0  # Solo "NO" nella coalizione
                else:
                    # Filtra i beacon che appartengono alla coalizione senza "NO"
                    coalition_beacons = [b for b in beacons if str(b[1]) in remaining_players]

                    if not coalition_beacons:
                        coalition_values[coalition] = 0
                    else:
                        try:
                            # Esegui l'ottimizzazione con i beacon della coalizione
                            _, _, task_assignments, total_utility, _ = optimize_task_allocation(coalition_beacons, tasks, verbose=False)

                            # Il valore della coalizione con "NO" è l'utilità totale + l'utilità di "NO"
                            coalition_values[coalition] = total_utility
                        except Exception as e:
                            print(f"Errore nell'ottimizzazione per la coalizione {coalition}: {e}")
                            coalition_values[coalition] = 0

    # Verifica se il gioco è convesso
    is_convex = is_convex_game(coalition_values, player_ids)
    print(f"Il gioco è {'convesso' if is_convex else 'non convesso'}")

    # Calcola i valori di Shapley
    n = len(player_ids)
    shapley_values = {player: 0 for player in player_ids}

    for player in player_ids:
        # Per ogni possibile coalizione che non include il giocatore
        for coalition_size in range(n):
            other_players = [p for p in player_ids if p != player]
            for coalition in itertools.combinations(other_players, coalition_size):
                # Calcola il contributo marginale
                coalition_set = frozenset(coalition)
                with_player = frozenset(coalition_set | {player})

                # Contributo marginale
                marginal = coalition_values.get(with_player, 0) - coalition_values.get(coalition_set, 0)

                # Peso per questa dimensione di coalizione
                weight = math.factorial(coalition_size) * math.factorial(n - coalition_size - 1) / math.factorial(n)

                # Aggiungi contributo pesato
                shapley_values[player] += weight * marginal

    # Adjusted shapley value
    if not is_convex:
        raise Exception("THE GAME IS NOT CONVEX")
        #compute new sharing value
        #for player in shapley_values:
        #    shapley_values[player] = phi + incentive + performance
        #this code must implement the performance so it must consider the margin of error between shapley of the realised and shapley expected

    return shapley_values, coalition_values, is_convex

