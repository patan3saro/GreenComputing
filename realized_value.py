"""
Stage 2 — Ex-post realized value processing.

It:

  - Uses REALIZED beacons (ground-truth NV draws) instead of nominal ones.
  - Recomputes timing + energy + cost through the `task_timing` and
    `task_energy` modules (which use the EnergyModel + Internet end-to-end).
  - Builds realized records, applies the 50/50 + c_i sharing (the sharing rule),
    aggregates per-stakeholder payoffs, and runs the core check + LP
    correction from `core_check.py` (Theorem 1).

Payoffs are defined as
    Pi = p - c_NO - c_exec
    pi_NO = pi_exec_block = Pi / 2
so the NO cost is already accounted for inside Pi via c_NO.
"""

from collections import defaultdict

from task_timing import compute_timing
from task_energy import compute_energy
from utils_convert import to_task_payment, dollars_per_kwh_to_dollars_per_joule
from payoff_sharing import share_single_task, share_block
from value_function import (
    RealizedTaskRecord,
    v_coalition,
)
from core_check import verify_and_correct
from config import NO_ENERGY_PRICE, VERBOSE


def _verbose(*args, **kwargs):
    if VERBOSE:
        print(*args, **kwargs)


# ----------------------------------------------------------------------
#   DIAGNOSTICA TEMPORANEA (attiva solo con GC_DIAG=1 nell'ambiente).
#   Serve a capire PERCHE' un task finisce in lost_tasks:
#     - ramo A: nessun beacon realizzato per l'esecutore  -> non e' un
#               fallimento di deadline, e' contabilita' mancante;
#     - ramo B: deadline realmente mancata -> stampa QUALE componente
#               del timing esplode (coda / internet / compute).
#   Da rimuovere (o lasciare spenta) una volta chiusa la diagnosi.
# ----------------------------------------------------------------------
import os as _os
import sys as _sys

_DIAG = _os.environ.get("GC_DIAG") == "1"


def _diag_nobeacon(assignment, executor_id):
    if not _DIAG:
        return
    ntype = "cloud" if (isinstance(executor_id, int) and executor_id < 0) else "vehicle"
    print(f"[LOST:nobeacon] type={ntype} exec={executor_id}", file=_sys.stderr)


def _diag_deadline(task, real_details, timing):
    if not _DIAG:
        return
    print(
        f"[LOST:deadline] type={real_details.get('type')} "
        f"D={task['D'] * 1e3:.0f}ms T={timing.total * 1e3:.1f}ms "
        f"queue={timing.queue_wait * 1e3:.1f} "
        f"inet={timing.inet_prop * 1e3:.1f} "
        f"comp={timing.compute * 1e3:.1f}",
        file=_sys.stderr,
    )


def realized_value_function(real_beacons, task_assignments,
                            algorithm_overhead,
                            run_core_check=True,
                            no_dollars_per_kwh=NO_ENERGY_PRICE,
                            verbose=False):
    """
    Stage 2: process the realized outcome of `task_assignments` returned
    by Stage 1, using the realized beacons stored at the Controller.

    Parameters
    ----------
    real_beacons : list of legacy-format tuples (priority, id, details, t)
        i.e., `controller.real_beacons`.
    task_assignments : list of dicts
        Output of `optimizer.optimize_task_allocation`.
    algorithm_overhead : float
        Allocation algorithm time [s] used for energy/time accounting.
    run_core_check : bool
        If True, verify the core and apply LP correction when needed
        (Theorem 1). Set to False for very tight slot budgets in early
        sanity runs.
    no_dollars_per_kwh : float
    verbose : bool

    Returns
    -------
    dict with keys:
        'total_payoff'           : sum over all tasks of Pi
        'pi_NO_total'             : aggregated NO payoff [$]
        'pi_per_executor'         : {executor_id: total payoff $}
        'task_payoffs'            : list of TaskPayoff (per task)
        'lost_tasks'              : list of task_id whose realized deadline
                                     was missed (no revenue collected)
        'core_check'              : CoreCheckResult or None
        'core_corrected'          : bool, True if LP correction was applied
        'imputation'              : final imputation {player_id: $}
        'realized_records'        : list of RealizedTaskRecord
    """
    # Index realized beacons by executor id for O(1) lookup
    real_by_id = {b[1]: b[2] for b in real_beacons}

    task_payoffs = []
    realized_records = []
    lost_tasks = []
    pi_no_total = 0.0
    pi_per_exec = defaultdict(float)

    lam_no = dollars_per_kwh_to_dollars_per_joule(no_dollars_per_kwh)

    for a in task_assignments:
        task = a['task']
        executor_id = a['node'][1]

        real_details = real_by_id.get(executor_id)
        if real_details is None:
            # No realized beacon for this executor -> treat as failed task
            _diag_nobeacon(a, executor_id)
            lost_tasks.append(task.get('id', None))
            continue

        # Recompute timing + energy on REALIZED parameters
        timing = compute_timing(task, real_details, algorithm_overhead)
        energy = compute_energy(task, real_details, timing, algorithm_overhead)

        deadline_met = timing.total <= task['D']
        if not deadline_met:
            _diag_deadline(task, real_details, timing)
            lost_tasks.append(task.get('id', None))
            # Still record the realized cost (executor and NO incurred energy
            # even though no revenue was collected). This is what keeps the
            # value function honest when a vehicle misreports and then fails.
            payment = 0.0
        else:
            payment = to_task_payment(task['D'])

        lam_exec = dollars_per_kwh_to_dollars_per_joule(real_details['dollars_per_kwh'])
        c_exec = lam_exec * energy.exec_total
        c_no = lam_no * energy.no_total

        # Build the realized record for the value function and core check
        rec = RealizedTaskRecord(
            task_id=task.get('id', -1),
            executor_id=executor_id,
            payment=payment,
            indicator_executor=1 if deadline_met else 0,
            # Indicator for the "NO alone" alternative path is approximated
            # as 1 (the cloud-only baseline always meets the deadline in
            # this paper's parameter regime; if needed it can be made more
            # precise by recomputing the cloud-only timing here).
            indicator_no=1 if deadline_met else 0,
            cost_executor=c_exec,
            cost_no=c_no,
        )
        realized_records.append(rec)

        # Apply 50/50 sharing per-task
        payoff = share_single_task(
            realized_payment=payment,
            realized_cost_no=c_no,
            realized_cost_executor=c_exec,
            task_id=rec.task_id,
            executor_id=executor_id,
        )
        task_payoffs.append(payoff)
        pi_no_total += payoff.pi_no
        pi_per_exec[executor_id] += payoff.pi_executor

    total_payoff = sum(p.Pi for p in task_payoffs)

    # -------------------- Core check (Theorem 1) --------------------
    core_check_result = None
    core_corrected = False
    imputation = {'NO': pi_no_total, **dict(pi_per_exec)}

    if run_core_check and realized_records:
        players = ['NO'] + list(pi_per_exec.keys())

        # In the 50/50 + c_i deployment, beta^i = 1/2 for the executor's own
        # served tasks. The inner-game weights w_i act WITHIN the executor
        # block's half of Pi, but at the task level each task's revenue
        # already goes to its unique executor (the one-executor-per-task constraint, at most one per task).
        executor_ids = list(pi_per_exec.keys())
        beta_per_executor = {i: 0.5 for i in executor_ids}

        def v_func(S):
            return v_coalition(realized_records, S, NO_label='NO',
                              beta_per_executor=beta_per_executor)

        imputation, core_check_result, core_corrected = verify_and_correct(
            imputation, v_func, players, NO_label='NO', verbose=verbose,
        )

        if core_corrected:
            # Refresh aggregate payoffs from the corrected imputation
            pi_no_total = imputation.get('NO', pi_no_total)
            pi_per_exec = defaultdict(float)
            for k, v in imputation.items():
                if k != 'NO':
                    pi_per_exec[k] = v

    return {
        'total_payoff': total_payoff,
        'pi_NO_total': pi_no_total,
        'pi_per_executor': dict(pi_per_exec),
        'task_payoffs': task_payoffs,
        'lost_tasks': lost_tasks,
        'core_check': core_check_result,
        'core_corrected': core_corrected,
        'imputation': imputation,
        'realized_records': realized_records,
    }
