"""
DRO admission rule — Stage 1 pre-filtering of (task, executor) pairs.

Paper reference: Definition 1.
Given the nominal beacon estimate of the offloading cost c_hat for executor i
on task tau, with std deviation sigma_hat (NV ~ 10% of mean in Tab. I),
the admission rule keeps the pair only if a CVaR-based cost bound stays
below the per-task revenue p_tau:

  CVaR_alpha[c^off_{i,tau}]
      + epsilon / (1 - alpha)         <=     p_tau

Closed-form Gaussian CVaR:

  CVaR_alpha[X] = mu + sigma * kappa(alpha),
  where kappa(alpha) = phi(Phi^-1(alpha)) / (1 - alpha)

  - alpha   : confidence level (default 0.9)
  - epsilon : Wasserstein ball radius around the empirical distribution
              (epsilon=0 reduces to the classical CVaR rule).
  - kappa   : precomputed table to avoid scipy dependence in hot path.

If DRO_ENABLED is False (default), the rule degenerates into the classical
deterministic admission rule c_hat <= p_tau (i.e. kappa=0, epsilon=0). This
lets you A/B test "no-DRO" vs "DRO-on" without changing call sites.

The cost c_hat used here is the EXECUTOR-side monetary cost (energy of the
executor x its $/kWh rate), plus the NO's energy cost (at NO's $/kWh rate),
because both must be jointly covered by p_tau for the coalition to be
individually rational at the block level (the block-level rationality result in the supplementary material).
"""

from dataclasses import dataclass
from math import sqrt

from config import (
    DRO_ALPHA,
    DRO_EPSILON,
    DRO_KAPPA,
    DRO_ENABLED,
    DRO_LAMBDA_W,
    NV_STD_FRACTION,
    NO_ENERGY_PRICE,
)
from utils_convert import (
    dollars_per_kwh_to_dollars_per_joule,
    to_task_payment,
)


# ----------------------------------------------------------------------
#                       Cost decomposition
# ----------------------------------------------------------------------
@dataclass
class CostBreakdown:
    """
    Per-pair cost decomposition in DOLLARS.
      - c_executor : exec_energy_J * lambda_exec [$/J]
      - c_no       : no_energy_J   * lambda_NO   [$/J]
      - c_total    : c_executor + c_no
    """
    c_executor: float
    c_no: float
    c_total: float


def cost_in_dollars(energy_breakdown, executor_dollars_per_kwh,
                    no_dollars_per_kwh=NO_ENERGY_PRICE):
    """
    Convert an `EnergyBreakdown` into a dollar-denominated CostBreakdown.
    """
    lam_exec = dollars_per_kwh_to_dollars_per_joule(executor_dollars_per_kwh)
    lam_no = dollars_per_kwh_to_dollars_per_joule(no_dollars_per_kwh)
    c_exec = lam_exec * energy_breakdown.exec_total
    c_no = lam_no * energy_breakdown.no_total
    return CostBreakdown(c_executor=c_exec, c_no=c_no, c_total=c_exec + c_no)


# ----------------------------------------------------------------------
#                       DRO admission rule (Def. 1)
# ----------------------------------------------------------------------
@dataclass
class AdmissionResult:
    admitted: bool
    cost_hat: float                  # nominal cost [$]
    cost_std_hat: float              # nominal std [$]
    cvar_bound: float                # DRO upper bound on cost [$]
    payment: float                   # p_tau [$]
    deadline_met_hat: bool           # deadline check on nominal estimate
    reason: str                      # human-readable diagnosis


def admit_pair(task, energy_breakdown, executor_dollars_per_kwh,
               timing_total, deadline,
               alpha=DRO_ALPHA, epsilon=DRO_EPSILON, kappa=DRO_KAPPA,
               enabled=DRO_ENABLED,
               wasserstein_distance=0.0, wasserstein_lambda=None,
               lambda_w_mult=1.0):
    """
    Apply the paper's Stage 1 admission rule to one (task, executor) pair.

    Two hard filters in order:
      1. Deadline: nominal T_tau must be <= D_tau (else 1_{i,tau} = 0).
      2. DRO cost bound (Def. 1):
           CVaR_alpha[c_hat] + epsilon/(1-alpha) + lambda_W * d_W  <= p_tau

         where:
         - CVaR_alpha[c_hat] := c_hat + sigma_hat * kappa
         - sigma_hat = NV_STD_FRACTION * c_hat  (Gaussian NV from Tab. I)
         - d_W is the 1-Wasserstein distance between the executor's
           DECLARED capacity and its EMPIRICAL HISTORY of realized
           capacities. A truthful vehicle has d_W ~= 0; a misreporter
           inflating its capacity by rho has d_W proportional to rho.
           This is what makes the admission see strategic distortion that
           does not directly perturb the nominal energy estimate.
         - lambda_W is the Wasserstein-penalty coefficient (USD per unit
           of normalized distance). When None, defaults to the per-task
           payment scale to keep the penalty dimensionally aligned.

         If enabled=False, all DRO terms collapse: rule becomes c_hat <= p_tau.

    Returns
    -------
    AdmissionResult

    Returns
    -------
    AdmissionResult
    """
    payment = to_task_payment(deadline)
    cost = cost_in_dollars(energy_breakdown, executor_dollars_per_kwh)
    cost_hat = cost.c_total

    # 1. Deadline pre-check
    deadline_met = timing_total <= deadline
    if not deadline_met:
        return AdmissionResult(
            admitted=False, cost_hat=cost_hat, cost_std_hat=0.0,
            cvar_bound=cost_hat, payment=payment,
            deadline_met_hat=False,
            reason=f"deadline_violation: T={timing_total*1000:.2f}ms > D={deadline*1000:.2f}ms",
        )

    # 2. DRO cost bound
    # Sigma_hat: Gaussian NV (10% of mean cost). Use abs() to be sign-safe.
    sigma_hat = NV_STD_FRACTION * abs(cost_hat)

    if enabled:
        cvar = cost_hat + sigma_hat * kappa
        # Wasserstein-based penalty for declaration-vs-history discrepancy
        # (block-level rationality, supplementary material). lambda_W defaults to the payment scale so a unit
        # normalized distance fully blocks the pair; tunable for sensitivity.
        # lambda_w_mult scales the ambiguity radius (adaptive DRO). It is a
        # per-slot scalar g in [0,1]: g=1 -> classical fixed radius (default,
        # bit-identical); g<1 -> lighter admission where the estimated threat
        # is low (few lies and/or low congestion). See optimizer for g.
        if wasserstein_lambda is None:
            lam_w = DRO_LAMBDA_W * payment * float(lambda_w_mult)
        else:
            lam_w = float(wasserstein_lambda) * float(lambda_w_mult)
        wasserstein_term = lam_w * max(0.0, float(wasserstein_distance))
        bound = cvar + epsilon / max(1.0 - alpha, 1e-12) + wasserstein_term
    else:
        cvar = cost_hat
        wasserstein_term = 0.0
        bound = cost_hat

    if bound > payment:
        return AdmissionResult(
            admitted=False, cost_hat=cost_hat, cost_std_hat=sigma_hat,
            cvar_bound=bound, payment=payment,
            deadline_met_hat=True,
            reason=(
                f"dro_violation: CVaR_a={cvar:.3e} + eps/(1-a)={epsilon/max(1-alpha,1e-12):.3e}"
                f" + lambda_W*d_W={wasserstein_term:.3e}"
                f" = {bound:.3e} > p={payment:.3e}"
            ),
        )

    return AdmissionResult(
        admitted=True, cost_hat=cost_hat, cost_std_hat=sigma_hat,
        cvar_bound=bound, payment=payment,
        deadline_met_hat=True,
        reason="ok",
    )


# ----------------------------------------------------------------------
#                       Helpers for Stage 1 optimizer
# ----------------------------------------------------------------------
def filter_admissible(candidate_pairs):
    """
    Given a list of (key, AdmissionResult, ...extras...) tuples, return
    only those with `admitted=True`. Used by the Stage 1 ILP to prune
    its variable domain ahead of solving.
    """
    return [t for t in candidate_pairs if t[1].admitted]


# ----------------------------------------------------------------------
#                       Precomputed kappa for common alphas
# ----------------------------------------------------------------------
# kappa(alpha) = phi(Phi^-1(alpha)) / (1 - alpha)
# Reference values (use scipy.stats.norm to regenerate if needed):
#   alpha   kappa
#   0.50    0.7979
#   0.75    1.2711
#   0.80    1.4002
#   0.85    1.5544
#   0.90    1.7549
#   0.95    2.0628
#   0.99    2.6652
KAPPA_TABLE = {
    0.50: 0.7979,
    0.75: 1.2711,
    0.80: 1.4002,
    0.85: 1.5544,
    0.90: 1.7549,
    0.95: 2.0628,
    0.99: 2.6652,
}


def kappa_for(alpha):
    """Lookup precomputed kappa(alpha) for common alphas, fallback exact."""
    rounded = round(alpha, 2)
    if rounded in KAPPA_TABLE:
        return KAPPA_TABLE[rounded]
    # Fallback: compute exactly via scipy (optional dependency)
    try:
        from scipy.stats import norm
        return norm.pdf(norm.ppf(alpha)) / (1.0 - alpha)
    except ImportError:
        raise ValueError(
            f"alpha={alpha} not in precomputed table; install scipy or "
            f"choose alpha in {sorted(KAPPA_TABLE.keys())}"
        )
