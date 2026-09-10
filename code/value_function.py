"""
Coalition value function — paper the value function.

Implements v_z^omega(S) for all coalitions S of N_z = {NO} U S_z.
This is the value function over which Theorem 1 (Bondareva-Shapley
balancedness) is verified ex-post by the Controller.

Three cases (paper Sec. VI):

  Case A:  S = {NO}                              (the value function, case A
      v(S) = sum_{tau in T_z^N} ( beta_NO * p_tau * 1_{NO,tau} - c_NO_tau )

  Case B:  NO not in S                            (the value function, case B
      v(S) = sum_{i in S} sum_{tau in T^{i}_z} ( beta_i * p_tau * 1_{i,tau} - c_i_tau )

  Case C:  NO in S, |S| > 1                       (the value function, case C
      v(S) = v({NO}) + v(S minus NO)

In our 50/50 deployment (the sharing rule, beta_NO = 1/2 and the executor block
inherits 1/2 distributed via w_i, so for the verification step we set:
    beta^NO = 1/2
    beta^i  = w_i = c_i / sum_j c_j  (across the executors in S)

This matches the deployed sharing rule and ensures the imputation
x = (pi_NO, pi_i)_i lies in the core (Theorem 1).
"""

from dataclasses import dataclass
from typing import Iterable


@dataclass
class RealizedTaskRecord:
    """
    Realized outcome for one task at slot z under realization omega.

    All quantities are in $ (or J converted via lambda^i e^i_tau).
    """
    task_id: int
    executor_id: int                  # id of the executor that served tau
    payment: float                    # p_tau
    indicator_executor: int           # 1 if executor met deadline, else 0
    indicator_no: int                 # 1 if the NO-served-alone path also met deadline
    cost_executor: float              # c_i^omega
    cost_no: float                    # c_NO^omega


def beta_no_default():
    """Outer-game share of the NO (50/50 split)."""
    return 0.5


def weights_inner(realized_records, executor_ids):
    """
    Compute the inner-game weights w_i (the inner-game weights:
        w_i = c_i / sum_{j in executors} c_j   if sum > 0
        else equal split.

    The sum is over the cost realizations of the executor block of S.
    """
    cost_by_id = {}
    for r in realized_records:
        if r.executor_id in executor_ids:
            cost_by_id[r.executor_id] = cost_by_id.get(r.executor_id, 0.0) + r.cost_executor
    total = sum(cost_by_id.values())
    if total > 0:
        return {i: cost_by_id.get(i, 0.0) / total for i in executor_ids}
    elif executor_ids:
        return {i: 1.0 / len(executor_ids) for i in executor_ids}
    return {}


# ----------------------------------------------------------------------
#                       Value function v_z^omega(S)
# ----------------------------------------------------------------------
def v_NO_alone(realized_records):
    """
    the value function, case A: v({NO}) under the assumption that the NO could in principle
    serve all tasks alone via its cloud.
    Here we approximate it as the NO-keeps-half-of-revenue minus NO cost,
    over the tasks that DID complete successfully (1_{NO,tau} = 1).
    """
    beta_NO = beta_no_default()
    s = 0.0
    for r in realized_records:
        s += beta_NO * r.payment * r.indicator_no - r.cost_no
    return s


def v_executors(realized_records, coalition_executor_ids,
                beta_per_executor=None):
    """
    the value function, case B of the paper: NO not in S.

    The set T_z^{S} is the union of tasks served by executors in S. Each
    task tau in T_z^{S} contributes:
        beta_i_tau * p_tau * 1_{i,tau} - c_i_tau
    where `i = i(tau)` is the unique executor that served tau (the one-executor-per-task constraint:
    at most one executor per task), and `beta_i_tau` is the share of the
    payment that flows to executor i for task tau.

    In the 50/50 + c_i deployment, beta_i_tau = 1/2 deterministically
    because the inner game splits the executor block's half of Pi
    via weights w_i that sum to 1: when summed across executors in S
    the total flow back to the block equals 1/2 of Pi exactly.

    For SUB-coalitions S' subset S_z, only the tasks served by i in S'
    are counted (so a sub-coalition cannot claim revenue from tasks it
    did not execute).
    """
    if not coalition_executor_ids:
        return 0.0
    coal_records = [r for r in realized_records if r.executor_id in coalition_executor_ids]

    if beta_per_executor is None:
        # Self-contained default: each executor in the coalition gets 1/2
        # of its own served-task payment.
        beta_eff = {i: 0.5 for i in coalition_executor_ids}
    else:
        beta_eff = beta_per_executor

    s = 0.0
    for r in coal_records:
        beta_i = beta_eff.get(r.executor_id, 0.5)
        s += beta_i * r.payment * r.indicator_executor - r.cost_executor
    return s


def v_coalition(realized_records, coalition_ids, NO_label='NO',
                beta_per_executor=None):
    """
    the value function dispatcher.

    Parameters
    ----------
    realized_records : list[RealizedTaskRecord]
        All realized records for the slot (across executors and tasks).
    coalition_ids : iterable of player ids (executor ids OR NO_label).
        The coalition S whose value we want to compute.
    NO_label : object
    beta_per_executor : dict {executor_id: beta_i} or None
        FIXED weights (paper Sec. VI). If None, falls back to the
        within-coalition self-contained mode.

    Returns
    -------
    float
        v_z^omega(S).
    """
    coalition_ids = set(coalition_ids)
    no_in = NO_label in coalition_ids
    executor_ids = coalition_ids - {NO_label}

    # Case A: S = {NO}
    if no_in and not executor_ids:
        return v_NO_alone(realized_records)

    # Case B: NO not in S
    if not no_in:
        return v_executors(realized_records, executor_ids,
                           beta_per_executor=beta_per_executor)

    # Case C: NO in S and |S| > 1
    return v_NO_alone(realized_records) + v_executors(
        realized_records, executor_ids,
        beta_per_executor=beta_per_executor,
    )