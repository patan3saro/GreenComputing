"""
Consolidated configuration — paper Tab. I + 2026 calibration.

All parameters used across the codebase live here. The grouping mirrors
Tab. I of the paper for easy cross-referencing. Values reflect the
operational regime targeted by the paper:

  - Mid-band 5G FR1 (n78) commercial deployment (3GPP TS 38.101-1).
  - Reference market: France 2026 (stable, decarbonized, well-documented).
  - In-vehicle automotive AI compute: NVIDIA DRIVE AGX Orin tier
    (Volvo EX90, JLR 2026), 254 TOPS INT8, 10% reserved for offloading.
  - Currency: USD throughout. Sources in EUR are converted at 1.07 EUR/USD
    (ECB reference rate, 2026 average).

NV notation = "Normally distributed Variable" (Tab. I):
    realized value ~ N(mean, sigma=NV_STD_FRACTION * mean)

For sweep experiments, override these values per-run via the
`Simulator(**kwargs)` constructor.
"""

# Architecture and Mobility
CITY = "Rome"
# Bbox SUMO ~2.5x2.5 km, PIU' GRANDE della copertura BS (raggio 1 km, vedi
# COVERAGE_RADIUS) e con la BS al centro: i veicoli scorrono attraverso la
# cella, solo quelli entro COVERAGE_RADIUS sono server usabili -> il pool
# cambia mentre attraversano. Centro ~ (12.4790, 41.8985). Richiede SUMO
# aggiornato (>=1.19): su SUMO 1.18 netconvert abortisce su questo bbox.
CITY_BBOX = (12.4640, 41.8870, 12.4940, 41.9100)   # ~2.5 km
VEHICLE_AVG_SPEED_KMH = 13.1
NUM_VEHICLES = 100
NUM_CLOUDS = 1
USERS_NUMBER = 100

# General
MAX_SIMULATION_TIME_MS = 2500
TIME_STEP_MS = 1
WINDOW_TASK_COLLECTION = 5
TASK_RATE = 10
SEEDS = list(range(1, 41))
SEED_RANDOM = 100
START_TIME = 0

# Warm-up SUMO: i veicoli entrano gradualmente da rete vuota. Misurare da t=0
# conta solo i pochi iniziali (transitorio). WARMUP_MS scarta il transitorio:
# la traccia viene generata per (WARMUP_MS + run), e la misura parte a t=WARMUP_MS
# quando la rete e' a regime. 0 = comportamento legacy (nessun warm-up).
# Tara il valore con la diagnostica del conteggio concorrente (dove il plateau).
WARMUP_MS = 30000

# Computation
# Cloud: hyperscale datacenter, abstracted as "infinite".
CLOUD_CPU_CAPACITY = 1e15

# In-vehicle AI compute: Tesla Hardware 4 (AI4) full-self-driving computer,
# shipping in production vehicles (Model S/X/Y, Cybertruck) since 2023.
# Tesla does NOT publish official TOPS figures for HW4. Independent
# estimates from teardown analyses span 232-500 TOPS for the system
# (e.g., PimpMyEV 2024 reports 232 TOPS based on Dojo D1; AutoPilotReview
# 2024 cites "5x HW3" implying ~720 TOPS). We adopt a CONSERVATIVE 300 TOPS
# system value (mid-range, below the highest claims, above the lowest).
# We reserve only 10% of this peak for opportunistic offloading; the
# remaining 90% stays committed to the vehicle's own perception/ADAS
# workload (paper Sec. III, frugality assumption).
VEHICLE_PEAK_OPS = 3.0e14              # 300 TOPS (HW4 conservative)
VEHICLE_COMPUTE_FRACTION = 0.10        # paper Sec. III
VEHICLE_CPU_CAPACITY = VEHICLE_PEAK_OPS * VEHICLE_COMPUTE_FRACTION
                                       # = 3.0e13 OPS for offloading

# Heterogeneous per-vehicle spare capacity (paper Sec. III).
# c_i ~ bounded distribution on [0, CAP_MAX]; CAP_MEAN default = 10% of peak,
# CAP_MAX = 30% ceiling (rest reserved for safety-critical ADAS),
# CAP_STD = heterogeneity (0 -> homogeneous), CAP_DIST = "beta" | "truncnorm".
CAP_MEAN = VEHICLE_CPU_CAPACITY        # 3.0e13 OPS — mean spare (10% of peak)
CAP_MAX  = 0.30 * VEHICLE_PEAK_OPS     # 9.0e13 OPS — ceiling (30% of peak)
CAP_STD  = 0.0                         # 0 -> homogeneous (legacy)
CAP_DIST = "beta"                      # "beta" | "truncnorm"

VEHICLE_QUEUE_CAPACITY = 1
CLOUD_QUEUE_CAPACITY = 1e12

# Tasks
TASK_WORKLOAD = 500e6
# Realistic per-task workload distribution for automotive AI inference.
# Each task picks one of these workload values with the matching prob.
# All values come from published OPS/FLOPs counts of automotive perception/
# planning networks (citations below). The mix is intentionally shifted
# toward heavy workloads to make the resource bottleneck visible.
#
#   1.0e8  (100 MOPS) : MobileNet-tiny / lane detection
#                        (Sandler et al., MobileNetV2, CVPR 2018)
#   1.0e9  (1 GOPS)   : YOLO-nano / small classifier
#                        (Ultralytics, 2020-2024)
#   1.0e10 (10 GOPS)  : YOLOv5-S object detection (19.4 GFLOPs measured)
#                        (Liu et al., ScienceDirect 2024)
#                       YOLOP panoptic (50 GFLOPs joint det+seg)
#                        (Wu et al., arXiv 2108.11250)
#   1.0e11 (100 GOPS) : BEVFormer 3D multi-camera (150-250 GFLOPs)
#                        (Li et al., ECCV 2022, arXiv 2203.17270)
#                       PointPillars LiDAR detection (~50-100 GFLOPs)
#                        (Lang et al., CVPR 2019)
#   1.0e12 (1 TOPS-s) : End-to-end DriveTransformer / BETAV (>200 GFLOPs)
#                        (Jia et al., arXiv 2503.07656; Zhao et al., Sensors 2025)
#
# When `TASK_WORKLOAD_TUPLE` and `TASK_WORKLOAD_PROBS` are None, all tasks
# use the scalar TASK_WORKLOAD (legacy mode).
TASK_WORKLOAD_TUPLE = (1.0e8, 1.0e9, 1.0e10, 1.0e11, 1.0e12)
TASK_WORKLOAD_PROBS = (0.10, 0.20, 0.30, 0.25, 0.15)
TASK_INPUT_SIZE = 8000
TASK_OUTPUT_SIZE = 8000
POSSIBLE_TASK_TYPES = (16, 100, 500)
TASK_TYPE_TUPLE = (0.33, 0.33, 0.34)
# Per-task payments, SLA-tiered, anchored to AWS Lambda 2026 pricing
# ($0.20/1M req + $1.66667e-5/GB-s standard; Lambda@Edge $0.60/1M req for
# latency-critical code near the user). Each offloaded task ~ one
# serverless invocation (~1 GB working set, representative billed
# duration). The latency tier sets a request-charge premium, giving a
# monotone schedule (more urgent -> higher price):
#   tier 0 (D <=  16 ms): 2.63 uUSD/task
#   tier 1 (D <= 100 ms): 1.43 uUSD/task
#   tier 2 (D <= 500 ms): 1.03 uUSD/task
PRICE_SUBSCRIPTIONS = (2.63e-6, 1.43e-6, 1.03e-6)  # USD/task (AWS-anchored)
PRICE_SUBSCRIPTIONS_UNIT = "per_task"

# Energy (France 2026)
# Vehicle / NO retail electricity: France Tarif Bleu Base, May 2026
# 0.194 EUR/kWh -> 0.207 USD/kWh @ 1.07 EUR/USD
PRICE_KWH = 0.21                       # USD/kWh
NO_ENERGY_PRICE = 0.21                 # USD/kWh

# Grid carbon intensity: France 2025, 19.6 gCO2eq/kWh (RTE Annual Review).
CO2_FACTOR_KG_PER_KWH = 0.0196

CONTROLLER_CPU_POWER = 200             # W — Controller CPU
VEHICLE_CPU_POWER = 80                 # W — Orin TDP (kept for reference)
ENERGY_AVAILABLE = 1e13

# Compute energy is modelled per-operation (J/OP), not as power*time.
# Modern AI accelerators are rated in TOPS/W (operations per joule); a short
# inference does NOT draw the full TDP for its whole duration. Using
# power*TDP*time over-charges a small task by ~4 orders of magnitude.
#
# Vehicle: Tesla HW4 system, ~300 TOPS (conservative) at a system power
# envelope of ~130 W (FSD computer) -> ~2.3e12 OPS/W.
#   energy_per_op = 1 / 2.3e12 = 4.3e-13 J/OP
# Cloud: datacenter GPU (H100-class), ~1979 TFLOPS @ 700 W incl. PUE 1.2
#   -> ~2.36e12 OPS/W effective. Cloud compute energy is dominated by the
#   Internet transport anyway.
VEHICLE_TOPS_PER_WATT = 2.30e12        # Tesla HW4 efficiency, conservative
CLOUD_TOPS_PER_WATT = 2.36e12          # datacenter GPU incl. PUE (OPS/W)
VEHICLE_ENERGY_PER_OP = 1.0 / VEHICLE_TOPS_PER_WATT   # J/OP
CLOUD_ENERGY_PER_OP = 1.0 / CLOUD_TOPS_PER_WATT       # J/OP

# Internet end-to-end electricity intensity (fixed network + DC share).
# Aslan et al. 2018, J. Industrial Ecology: ~0.06 kWh/GB for fixed-line
# networks in 2015, halving roughly every 2 years (corroborated by IEA
# 2022, which reports fixed-network intensity halving every ~2 years in
# developed countries). Extrapolated to 2024: ~0.006 kWh/GB.
#   0.006 kWh/GB = 0.006 * 3.6e6 J / 8e9 bit = 2.7e-6 J/bit
# This is a CONSERVATIVE (low) estimate of the cloud transport footprint,
# so it does not artificially favor the VCC path.
INTERNET_ENERGY_PER_BIT = 2.7e-6       # J/bit, Aslan 2018 extrapolated to 2024

# Network (5G NR FR1, n78 mid-band)
CARRIER_FREQUENCY = 3.5e9              # n78 center
TOTAL_BANDWIDTH = 100e6                # single n78 carrier
GNB_TX_POWER_5G = 23
GNB_TX_POWER_INET = 23
UE_TX_POWER = 23
N_SPATIAL_STREAMS = 2
BEAMFORMING_GAIN_DB = 5
SHADOWING_STD_DB = 4
PROTOCOL_EFFICIENCY = 0.85
SINR_MIN_DB = -5

COVERAGE_RADIUS = 500
INET_DELAY = 0.035
DR_INET = 10.0e10

SPEED_LIGHT = 2.998e8
SPEED_FIBER = (2.0 / 3.0) * SPEED_LIGHT
CLOUD_DISTANCE = 10_000
PEDESTRIAN_UE_DISTANCE = 100

# Beacons (ETSI CAM)
VEHICLE_BEACON_INTERVAL_MS = 100
CLOUD_BEACON_INTERVAL_MS = 900_000
BEACON_EXPIRATION_MS = 500

# Stochasticity (NV)
NV_STD_FRACTION = 0.10

# Misreporting
MISREPORTING_FRACTION = 0.0

# DRO admission rule (Def. 1)
# alpha    : CVaR confidence level
# kappa    : Gaussian quantile factor phi(Phi^-1(alpha))/(1-alpha), precomputed
# epsilon  : Wasserstein ball radius for the cost distribution itself
# lambda_W : multiplicative scale that turns the Wasserstein discrepancy
#            between DECLARED and REALIZED-HISTORICAL capacity into a
#            cost penalty. lambda_W * payment is the per-unit penalty;
#            with the default 5.0 a vehicle that inflates its capacity
#            by 20% (d_W ~ 0.2) sees its admission bound saturated.
DRO_ALPHA = 0.90
DRO_EPSILON = 0.0
DRO_KAPPA = 1.7549
DRO_LAMBDA_W = 5.0
DRO_ENABLED = True

# --- Adaptive DRO radius (data-driven Wasserstein radius) -------------------
# The fixed radius (DRO_LAMBDA_W) is blind to the operating regime, so it
# over-rejects where lying is harmless. We scale it by a per-slot multiplier
#   g = g_mis(d_bar_W) * g_load(rho_bar),   each factor saturating in [0,1):
#     g_mis  = d_bar_W / (d_bar_W + D0)     -> "how much are they lying?"
#     g_load = rho_bar / (rho_bar + RHO0)   -> "how much does it hurt, given load?"
# The PRODUCT is a logical AND: the radius grows only when there is BOTH
# misreporting AND congestion, i.e. only where lies actually cause failures.
#   g=1 recovers the classical fixed radius; g->0 makes DRO a no-op.
# Mode selects the ablation variant.
DRO_ADAPT_MODE = "fixed"
DRO_ADAPT_D0   = 0.30           # misreporting half-scale (g_mis=0.5 at d_bar_W=D0)
DRO_ADAPT_RHO0 = 0.50           # congestion half-scale  (g_load=0.5 at rho_bar=RHO0)

# IDs and misc
CLOUD_ID = -1
NO_ID = 19_250_596
VERBOSE = False
ALGORITHM_TIME_OVERHEAD = 0
RESULTS_DIR_BASE = "results"
