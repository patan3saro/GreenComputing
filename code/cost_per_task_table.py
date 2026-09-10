#!/usr/bin/env python3
"""
cost_per_task_table.py — cost per served task of an edge server versus VCC
(Table IV of the paper).

The edge server amortizes a three-year total cost of ownership (capital,
technician, rack, energy, maintenance, spares) over the tasks it serves at a
given sustained load; VCC recovers no capital and pays only the marginal
energy cost. Constants are those of the cost model used throughout the
campaign post-processing.

Usage:  python3 cost_per_task_table.py
"""
PUE       = 1.3
PRICE_KWH = 0.21
ALPHA     = 15 * 3600 * 365          # task-seconds per year at the amortization duty cycle
TASK3     = 5 * 100 * ALPHA * 3      # tasks served over the 3-year horizon
ORE       = ALPHA * 3 / 3600         # operating hours over 3 years
P_PICCO   = 1.829e14                 # peak offered load [OP/s]
VCC_COST    = 0.0039e-6              # VCC marginal cost per task [$] (energy only, no capital)
EDGE_ENERGY = 0.0069e-6              # edge energy per task [$]

EDGES = {                            # name: (capacity [OP/s], price [$], TDP [kW])
    "A30 (330 TOPS, baseline)": (3.3e14,  5000,  0.165),
    "A100 (624 TOPS)":          (6.24e14, 10000, 0.300),
}
LOADS = [1.0, 0.5, 0.1, 0.01]        # fraction of peak load


def tco(C, price, tdp):
    """Three-year total cost of ownership [$] of an edge server."""
    f = min(P_PICCO / C, 1.0)
    return (price * f + (5000 * 12 * 3 / 50) * f + 150 * 12 * 3 * f
            + tdp * PUE * ORE * PRICE_KWH * f + 0.12 * price * 3 * f + 0.04 * price * 3 * f)


if __name__ == "__main__":
    print(f"{'Load [% of peak]':28s}" + "".join(f"{int(l*100):>9d}" for l in LOADS))
    rows = {}
    for name, (C, price, tdp) in EDGES.items():
        rows[name] = [(tco(C, price, tdp) / (TASK3 * l) + EDGE_ENERGY) * 1e6 for l in LOADS]
        print(f"{name:28s}" + "".join(f"{v:9.2f}" for v in rows[name]))
    print(f"{'VCC (zero capital)':28s}" + "".join(f"{VCC_COST*1e6:9.4f}" for _ in LOADS))
    base = rows["A30 (330 TOPS, baseline)"]
    print(f"{'A30 / VCC ratio':28s}" + "".join(f"{v/(VCC_COST*1e6):8.0f}x" for v in base))
    print("\n[LaTeX]")
    for name, vals in rows.items():
        print(f"    {name} & " + " & ".join(f"{v:.2f}" for v in vals) + r" \\")
    print(r"    \textbf{VCC (zero capital)} & \multicolumn{4}{c}{\textbf{" + f"{VCC_COST*1e6:.3f}" + r" at every load}} \\")
    print(r"    A30 / VCC ratio & " + " & ".join(f"${v/(VCC_COST*1e6):.0f}\\times$" for v in base) + r" \\")
