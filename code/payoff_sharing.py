"""
Stage 2 — Payoff sharing (paper Sec. VI, the sharing rule).

Decomposes the realized payoff Pi^omega_tau = p_tau - sum_j c^j_tau(theta^omega)
into:
  - Outer game (inter-block): 50/50 split between NO and the executor
    superplayer, derived from the canonical two-player unanimity Shapley.
  - Inner game (intra-block):  proportional to c_i^omega (sign-robust),
    i.e., w_i = c_i / sum_j c_j among the executors of S_z.

Sign-robust property: when Pi > 0 each executor receives a share of the
surplus proportional to its effort; when Pi < 0 each executor absorbs a
share of the deficit proportional to the same effort. The NO absorbs
exactly half of the deficit too -- the operator cannot offload its loss
to the executors, which is the property that incentivizes participation.

Identity check (S = S_z, the slot coalition):
    pi_NO + sum_{i in S minus NO} pi_i  ==  Pi  identically in omega
    sum_{i in S minus NO} pi_i          ==  Pi/2 identically in omega
This is verified in unit tests; it follows from sum w_i = 1.

Output objects are typed dataclasses, NOT raw dicts indexed by integers,
so downstream code (logging, plotting, core_check) reads from named
attributes rather than positional offsets.
"""

from dataclasses import dataclass, field
from typing import Optional

from utils_convert import dollars_per_kwh_to_dollars_per_joule
from config import NO_ENERGY_PRICE


# ----------------------------------------------------------------------
#                       Per-task realized payoff
# ----------------------------------------------------------------------
@dataclass
class TaskPayoff:
    r"""
    Realized payoff and per-player share for one (task, executor) outcome.

    All values are in DOLLARS.
        Pi      = p_tau - c_NO - c_exec      (realized total payoff)
        pi_NO   = 0.5 * Pi                    (outer game, the outer-game split
        pi_exec = 0.5 * Pi * w_exec           (inner game, the inner-game weights

    For a single executor coalition (|S\NO| = 1), w_exec = 1 trivially.
    For multi-executor coalitions, w_exec aggregates across the block.
    """
    task_id: int
    executor_id: int
    payment: float
    cost_no: float
    cost_executor: float
    Pi: float                # realized total payoff
    pi_no: float             # NO share (outer game)
    pi_executor: float       # this executor's share (inner game)
    weight: float            # inner-game weight w_i

    def check_identity(self, tol=1e-12):
        """Sanity: pi_NO + pi_exec == Pi (for single-executor case)."""
        return abs(self.pi_no + self.pi_executor - self.Pi) <= tol * max(1.0, abs(self.Pi))


# ----------------------------------------------------------------------
#                       Single-executor sharing (per-task)
# ----------------------------------------------------------------------
def share_single_task(realized_payment, realized_cost_no, realized_cost_executor,
                      task_id=-1, executor_id=-1):
    """
    Sharing for a task served by exactly one executor (the common case in
    Stage 1, since the one-executor-per-task constraint gives at most one executor per task).

    The inner game collapses trivially to w_executor = 1.
    """
    Pi = realized_payment - realized_cost_no - realized_cost_executor
    pi_no = 0.5 * Pi
    pi_exec = 0.5 * Pi
    return TaskPayoff(
        task_id=task_id,
        executor_id=executor_id,
        payment=realized_payment,
        cost_no=realized_cost_no,
        cost_executor=realized_cost_executor,
        Pi=Pi,
        pi_no=pi_no,
        pi_executor=pi_exec,
        weight=1.0,
    )


# ----------------------------------------------------------------------
#                       Multi-executor block sharing (per-slot)
# ----------------------------------------------------------------------
@dataclass
class BlockPayoff:
    """
    Aggregate payoff at the slot level when multiple executors are active.

    the inner-game weights: w_i = c_i / sum_j c_j among executors. The NO always receives
    1/2 of the slot-aggregate Pi; each executor gets w_i * (Pi/2).
    """
    slot_total_payment: float
    slot_total_cost_no: float
    slot_total_cost_executors: float
    Pi: float
    pi_no: float
    pi_per_executor: dict     # {executor_id: pi_i}
    weight_per_executor: dict # {executor_id: w_i}

    @property
    def total_executor_share(self):
        return sum(self.pi_per_executor.values())

    def check_identity(self, tol=1e-9):
        s = self.pi_no + self.total_executor_share
        return abs(s - self.Pi) <= tol * max(1.0, abs(self.Pi))


def share_block(per_executor_payments, per_executor_cost_no,
                per_executor_cost_exec):
    """
    Apply the outer 50/50 + inner c_i sharing across an entire executor
    block in one slot.

    Parameters
    ----------
    per_executor_payments : dict {executor_id: p_tau} aggregated by executor
        (i.e., the sum of p_tau for the tasks that this executor served
        successfully -- 1_{i,tau}^omega = 1 -- under realization omega).
    per_executor_cost_no : dict {executor_id: c_NO of NO for serving this
        executor's tasks} (the NO incurs a per-task cost via the executor energy model.
    per_executor_cost_exec : dict {executor_id: c_exec for this executor's
        tasks} (the cost model.

    Returns
    -------
    BlockPayoff
    """
    ids = list(per_executor_payments.keys())

    P_total = sum(per_executor_payments.values())
    C_NO = sum(per_executor_cost_no.values())
    C_exec = sum(per_executor_cost_exec.get(i, 0.0) for i in ids)
    Pi = P_total - C_NO - C_exec

    # Inner weights: w_i = c_i / sum_j c_j. Sign-robust. If all c_i == 0
    # (no work done), distribute equally to keep the identity sum w = 1.
    sum_c = sum(per_executor_cost_exec.get(i, 0.0) for i in ids)
    if sum_c > 0:
        weights = {i: per_executor_cost_exec.get(i, 0.0) / sum_c for i in ids}
    elif ids:
        weights = {i: 1.0 / len(ids) for i in ids}
    else:
        weights = {}

    pi_no = 0.5 * Pi
    pi_per_exec = {i: 0.5 * Pi * weights[i] for i in ids}

    return BlockPayoff(
        slot_total_payment=P_total,
        slot_total_cost_no=C_NO,
        slot_total_cost_executors=C_exec,
        Pi=Pi,
        pi_no=pi_no,
        pi_per_executor=pi_per_exec,
        weight_per_executor=weights,
    )


# ----------------------------------------------------------------------
#                       Helper: derive payoff from a task_assignment
# ----------------------------------------------------------------------
def derive_realized_payoff_for_assignment(realized_timing, realized_energy,
                                           task, executor_details,
                                           no_dollars_per_kwh=NO_ENERGY_PRICE):
    """
    Convenience function: from realized timing + energy + executor info,
    compute the realized monetary payoff for one task, then apply the
    single-task 50/50 share. Returns a `TaskPayoff`.

    Returns None if the deadline was not met (no payment collected).
    """
    from utils_convert import to_task_payment

    deadline_met = realized_timing.total <= task['D']
    if not deadline_met:
        return None

    payment = to_task_payment(task['D'])
    lam_exec = dollars_per_kwh_to_dollars_per_joule(executor_details['dollars_per_kwh'])
    lam_no = dollars_per_kwh_to_dollars_per_joule(no_dollars_per_kwh)

    c_exec = lam_exec * realized_energy.exec_total
    c_no = lam_no * realized_energy.no_total

    return share_single_task(
        realized_payment=payment,
        realized_cost_no=c_no,
        realized_cost_executor=c_exec,
        task_id=task.get('id', -1),
        executor_id=executor_details.get('beacon_id', -1),
    )