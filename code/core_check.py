"""
Core check and LP correction — paper Sec. VI, Theorem 1.

After Stage 2 has computed the candidate imputation x = (pi_NO, pi_i),
the Controller verifies that x lies in the core of the realized TU-game
G_z^omega = (N_z, v_z^omega).

A vector x is in the core iff:
    (efficiency)             sum_i x_i == v(N)
    (coalitional rationality) sum_{i in S} x_i >= v(S)  for every S ⊆ N

If a violation is detected, we solve a small LP that projects the candidate
imputation onto the core while keeping it as close as possible (L1 norm) to
the original 50/50 + c_i imputation. Theorem 1 guarantees the LP is
feasible (core is non-empty).

Operationally:
  - For each slot, |N_z| is at most a few tens of players (NO + selected
    executors), so enumerating 2^|N_z| coalitions is fine.
  - LP correction has complexity O((n+m)^3) under interior-point methods
    (n = #players, m = #constraints). For coalition sizes on the order
    of tens, this stays well within the slot budget.

This module never modifies the original imputation in place: it returns
either the same imputation (if already in the core) or a corrected one,
plus a diagnostic explaining what was wrong.
"""

from dataclasses import dataclass, field
from itertools import combinations
from typing import Optional

import pulp


# Tolerance for floating-point comparisons when checking core constraints
CORE_TOL = 1e-10


@dataclass
class CoreCheckResult:
    in_core: bool
    n_violations: int
    worst_violation: float                # max( v(S) - sum_{i in S} x_i, 0 )
    violating_coalitions: list = field(default_factory=list)
    efficiency_gap: float = 0.0           # v(N) - sum_i x_i
    diagnostic: str = ""


def check_core(imputation, v_func, players, NO_label='NO',
               rel_tol=1e-6, abs_tol=1e-12):
    """
    Verify whether `imputation` (dict {player_id: x_i}) lies in the core
    of the game defined by `v_func(coalition)` over `players`.

    Tolerance is relative to v(N) (scale-aware): a violation is reported
    only if it exceeds max(rel_tol * |v(N)|, abs_tol).

    Parameters
    ----------
    imputation : dict
        Candidate payoff vector.
    v_func : callable
        v_func(coalition_set) -> float.
    players : iterable
    NO_label : object
    rel_tol : float
        Relative tolerance vs |v(N)|. 1e-6 = 0.0001%.
    abs_tol : float
        Absolute floor when v(N) is near zero.

    Returns
    -------
    CoreCheckResult
    """
    players = list(players)
    grand = set(players)

    v_grand = v_func(grand)
    sum_x = sum(imputation.get(p, 0.0) for p in players)
    eff_gap = v_grand - sum_x

    # Scale-aware tolerance
    tol = max(rel_tol * abs(v_grand), abs_tol)

    violations = []
    worst = 0.0
    for size in range(1, len(players)):
        for S in combinations(players, size):
            S_set = set(S)
            v_S = v_func(S_set)
            x_S = sum(imputation.get(p, 0.0) for p in S_set)
            slack = x_S - v_S
            if slack < -tol:
                violations.append((tuple(sorted(S_set, key=str)), slack))
                if -slack > worst:
                    worst = -slack

    in_core = (abs(eff_gap) <= tol) and not violations
    diag = "core" if in_core else (
        f"{len(violations)} violations; eff_gap={eff_gap:.3e}; worst={worst:.3e}; tol={tol:.3e}"
    )
    return CoreCheckResult(
        in_core=in_core,
        n_violations=len(violations),
        worst_violation=worst,
        violating_coalitions=violations,
        efficiency_gap=eff_gap,
        diagnostic=diag,
    )


# ----------------------------------------------------------------------
#                       LP correction
# ----------------------------------------------------------------------
def correct_to_core(imputation, v_func, players, NO_label='NO', verbose=False):
    """
    Project the imputation onto the core by minimizing the L1 distance
    from the original imputation, subject to:
        - efficiency: sum_i x_i == v(N)
        - coalitional rationality: sum_{i in S} x_i >= v(S) for all S
    Returns a new imputation dict.

    The LP is feasible by Theorem 1 (Robust Core Non-Emptiness).
    """
    players = list(players)
    n = len(players)

    prob = pulp.LpProblem("core_projection", pulp.LpMinimize)

    # Decision variables (one x per player, free in sign)
    x = {p: pulp.LpVariable(f"x_{str(p)}", lowBound=None) for p in players}

    # Auxiliary variables for L1 deviation from the original imputation
    dev_pos = {p: pulp.LpVariable(f"dpos_{str(p)}", lowBound=0) for p in players}
    dev_neg = {p: pulp.LpVariable(f"dneg_{str(p)}", lowBound=0) for p in players}

    # Constraints encoding |x_p - x0_p| = dev_pos - dev_neg
    for p in players:
        x0 = imputation.get(p, 0.0)
        prob += x[p] - x0 == dev_pos[p] - dev_neg[p], f"dev_eq_{str(p)}"

    # Objective: minimize sum |x_p - x0_p|
    prob += pulp.lpSum(dev_pos[p] + dev_neg[p] for p in players)

    # Efficiency
    v_grand = v_func(set(players))
    prob += pulp.lpSum(x[p] for p in players) == v_grand, "efficiency"

    # Coalitional rationality
    for size in range(1, n):
        for S in combinations(players, size):
            S_set = set(S)
            v_S = v_func(S_set)
            prob += pulp.lpSum(x[p] for p in S) >= v_S, f"rat_{str(S)}"

    solver = pulp.PULP_CBC_CMD(msg=False)
    status = prob.solve(solver)

    if pulp.LpStatus[status] != 'Optimal':
        # Should not happen if Theorem 1 holds; return original for safety
        return dict(imputation), False

    return {p: x[p].value() for p in players}, True


# ----------------------------------------------------------------------
#                       Convenience wrapper
# ----------------------------------------------------------------------
def verify_and_correct(imputation, v_func, players, NO_label='NO', verbose=False):
    """
    One-shot: check the core, correct if needed, return (final_imputation,
    CoreCheckResult, was_corrected).
    """
    check = check_core(imputation, v_func, players, NO_label=NO_label)
    if check.in_core:
        return dict(imputation), check, False

    corrected, ok = correct_to_core(imputation, v_func, players,
                                     NO_label=NO_label, verbose=verbose)
    return corrected, check, ok