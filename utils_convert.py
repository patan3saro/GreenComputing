"""
Conversion utilities.

Payments per task are read from `PRICE_SUBSCRIPTIONS` in one of two modes,
selected by the config flag `PRICE_SUBSCRIPTIONS_UNIT`:
    - "per_task"   -> values are already $/task (Tab. I)
    - "per_month"  -> monthly subscription converted to $/task
The 50/50 inter-block split is applied in Stage 2 (payoff_sharing.py), not
in the payment. Deadlines above the largest reference value fall in the
last bucket.
"""

from config import (
    POSSIBLE_TASK_TYPES,
    PRICE_SUBSCRIPTIONS,
)

# How to interpret PRICE_SUBSCRIPTIONS values:
#   "per_task"  -> they are already $/task (Tab. I convention: 5.7e-6 $, etc.)
#   "per_month" -> legacy: they are monthly subscriptions to be rescaled.
# Default to per_task (paper-compliant). Override by adding to config.py.
try:
    from config import PRICE_SUBSCRIPTIONS_UNIT
except ImportError:
    PRICE_SUBSCRIPTIONS_UNIT = "per_task"


# ----------------------------------------------------------------------
#                       Time conversions
# ----------------------------------------------------------------------
def seconds_to_ms(time_s):
    return 1000.0 * time_s


def ms_to_seconds(time_ms):
    return time_ms * 1e-3


# ----------------------------------------------------------------------
#                       Power conversions
# ----------------------------------------------------------------------
def dbm_to_watt(dbm):
    """
    dBm -> Watt.

    P(W) = 10^(dBm/10) / 1000
    """
    return (10 ** (dbm / 10.0)) / 1000.0


def dollars_per_kwh_to_dollars_per_joule(dollars_per_kwh):
    """
    $/kWh -> $/J  (1 kWh = 3.6e6 J)
    """
    return dollars_per_kwh / 3.6e6


def dollars_per_joule_to_dollars_per_kwh(dollars_per_joule):
    """
    $/J -> $/kWh  (1 kWh = 3.6e6 J)
    """
    return dollars_per_joule * 3.6e6


# ----------------------------------------------------------------------
#                       Task payment (Tab. I)
# ----------------------------------------------------------------------
def _to_type_of_task(task_deadline_s, types=POSSIBLE_TASK_TYPES):
    """
    Bucket a task deadline into one of the POSSIBLE_TASK_TYPES tiers.

    IMPORTANT — units. Task deadlines (`task['D']`) are stored in SECONDS
    throughout the simulator, while POSSIBLE_TASK_TYPES are expressed in
    MILLISECONDS (16, 100, 500). We convert to ms before comparing.

    Semantics (Tab. I): the tier is the SMALLEST bucket whose upper bound
    is >= the deadline. A tighter (smaller) deadline maps to an earlier,
    higher-priced tier:
        D <=  16 ms  -> tier 0  (highest price, most urgent)
        D <= 100 ms  -> tier 1
        D <= 500 ms  -> tier 2  (lowest price, most lax)
        D >  500 ms  -> tier 2  (clamped to the last/cheapest tier)

    Returns an index in [0, len(types)-1].
    """
    deadline_ms = task_deadline_s * 1000.0
    for idx, upper_ms in enumerate(types):
        if deadline_ms <= upper_ms:
            return idx
    return len(types) - 1


def to_task_payment(task_deadline):
    """
    Per-task payment p(D_tau, W_tau) [$/task].

    Per Tab. I of the paper, p_tau is a step function of the deadline:
        D < 16 ms   -> 5.7 uS
        D < 100 ms  -> 3.8 uS
        D < 500 ms  -> 1.9 uS
    The exact values are taken from PRICE_SUBSCRIPTIONS in config.py.

    Note: the 50/50 split between NO and the executor block is NOT applied
    here. It happens in `payoff_sharing.py` (Stage 2). p_tau is the FULL
    revenue collected from the end-user.
    """
    task_type = _to_type_of_task(task_deadline)
    value = PRICE_SUBSCRIPTIONS[task_type]

    if PRICE_SUBSCRIPTIONS_UNIT == "per_task":
        return float(value)
    elif PRICE_SUBSCRIPTIONS_UNIT == "per_month":
        # Legacy: rescale a monthly subscription to a per-task amount,
        # assuming an average task rate (Tab. I: TASK_RATE = 10 tasks/s).
        from config import TASK_RATE
        avg_days_per_month = 30.4167
        seconds_per_day = 86_400
        seconds_per_month = avg_days_per_month * seconds_per_day
        per_second = value / seconds_per_month
        return per_second / TASK_RATE
    else:
        raise ValueError(
            f"Unknown PRICE_SUBSCRIPTIONS_UNIT: {PRICE_SUBSCRIPTIONS_UNIT}"
        )


# ----------------------------------------------------------------------
#                       CO2 conversion
# ----------------------------------------------------------------------
def joules_to_co2_kg(energy_joules, emission_factor_kg_per_kwh=0.233):
    """
    Convert energy [J] to CO2 [kg], given a regional grid emission factor.
    Default 0.233 kg/kWh ~ EU-27 average (cf. EEA2025 in the paper).
    """
    energy_kwh = energy_joules / 3.6e6
    return energy_kwh * emission_factor_kg_per_kwh