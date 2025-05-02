from config import *

def seconds_to_ms(time_s):
    return 1000*time_s
def _to_type_of_task(task_deadline, types=POSSIBLE_TASK_TYPES):
    # Iterate through possible_types with their indices
    for idx, deadline_type in enumerate(types):
        if task_deadline < deadline_type:
            return idx

    # If no match is found, return len(possible_types) + 1
    return len(types)


def _to_per_second_amount(monthly_amount):
    """
    Convert a monthly monetary amount to an equivalent per-second rate.

    Args:
        monthly_amount (float): The amount of money per month

    Returns:
        float: The equivalent amount per second
    """
    # Average days in a month (365 / 12)
    avg_days_per_month = 30.4167

    # Seconds in a day
    seconds_per_day = 24 * 60 * 60  # 86,400

    # Seconds in a month
    seconds_per_month = avg_days_per_month * seconds_per_day  # approx. 2,628,000

    # Money per second
    per_second_amount = monthly_amount / seconds_per_month

    return per_second_amount


def to_task_payment(task_deadline, task_rate=TASK_RATE):
    task_type = _to_type_of_task(task_deadline)
    monthly_amount = PRICE_SUBSCRIPTIONS[task_type]
    return _to_per_second_amount(monthly_amount) / task_rate


def dbm_to_watt(dbm):
    """
    Converts power from dBm (decibel-milliwatt) to Watt.

    Formula: P(W) = 10^(dBm/10) / 1000

    Parameters:
    - dbm: Power value in dBm

    Returns:
    - Equivalent power value in Watt

    Examples:
    - 0 dBm = 0.001 W (1 mW)
    - 30 dBm = 1 W
    - 60 dBm = 1000 W (1 kW)
    """
    try:
        # Convert dBm to mW (10^(dBm/10))
        mw = 10 ** (dbm / 10)

        # Convert mW to W (divide by 1000)
        watt = mw / 1000

        return watt
    except Exception as e:
        raise ValueError(f"Error converting from dBm to Watt: {e}")



def dollars_per_kwh_to_dollars_per_joule(dollars_per_kwh):
    """
    Convert $/kWh (dollars per kilowatt-hour) to $/J (dollars per joule).

    Conversion factors:
    - 1 kilowatt-hour (kWh) = 3,600,000 joules (J)
    - This is because: 1 kWh = 1000 watts × 3600 seconds = 3.6 million joules

    Parameters:
    -----------
    dollars_per_kwh : float
        The cost in dollars per kilowatt-hour

    Returns:
    --------
    float
        The cost in dollars per joule

    Example:
    --------
     dollars_per_kwh_to_dollars_per_joule(0.12)  # Typical residential electricity rate
    3.3333333333333335e-08  # Approximately 3.33e-8 $/J
     dollars_per_kwh_to_dollars_per_joule(1)
    2.7777777777777776e-07  # Approximately 2.78e-7 $/J
    """
    # 1 kWh = 3.6 million joules
    joules_per_kwh = 3.6e6

    # Convert $/kWh to $/J
    dollars_per_joule = dollars_per_kwh / joules_per_kwh

    return dollars_per_joule


def dollars_per_joule_to_dollars_per_kwh(dollars_per_joule):
    """
    Convert $/J (dollars per joule) to $/kWh (dollars per kilowatt-hour).

    This is the inverse of the dollars_per_kwh_to_dollars_per_joule function.

    Parameters:
    -----------
    dollars_per_joule : float
        The cost in dollars per joule

    Returns:
    --------
    float
        The cost in dollars per kilowatt-hour

    Example:
    --------
    dollars_per_joule_to_dollars_per_kwh(3.33e-8)  # Approximately 3.33e-8 $/J
    0.11988  # Approximately 0.12 $/kWh
     dollars_per_joule_to_dollars_per_kwh(2.78e-7)  # Approximately 2.78e-7 $/J
    1.0008  # Approximately 1.00 $/kWh
    """
    # 1 kWh = 3.6 million joules
    joules_per_kwh = 3.6e6

    # Convert $/J to $/kWh
    dollars_per_kwh = dollars_per_joule * joules_per_kwh

    return dollars_per_kwh


# Function to format the result in a more readable scientific notation
def format_energy_price(value):
    """
    Format an energy price value in a readable form with appropriate units.

    Parameters:
    -----------
    value : float
        The price value to format

    Returns:
    --------
    str
        Formatted price with appropriate units

    Example:
    --------
     format_energy_price(0.12)
    '0.12'
     format_energy_price(3.33e-8)
    '3.33 × 10⁻⁸'
    """
    if abs(value) >= 0.001:
        return f"{value:.6f}".rstrip('0').rstrip('.')
    else:
        # Convert to scientific notation for very small numbers
        # Extract mantissa and exponent
        mantissa, exponent = f"{value:.2e}".split('e')
        # Convert exponent to superscript
        superscript_map = {'0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴',
                          '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹',
                          '+': '⁺', '-': '⁻'}
        superscript_exponent = ''.join(superscript_map[char] for char in exponent)
        return f"{float(mantissa):.2f} × 10{superscript_exponent}"
