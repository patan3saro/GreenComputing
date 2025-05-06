import math

DR_5G = 1.5e+10  # bps
DR_INET = 10.0e+10
SPEED_LIGHT = 2.998e+8  # m/s In free space
SPEED_FIBER = (
                          2 / 3) * SPEED_LIGHT  # m/s 66.666666% https://www.fastweb.it/fastweb-plus/digital-magazine/dati-e-velocita-di-trasmissione-scenari-futuri-per-la-rete/
CLOUD_DISTANCE = 10000  # meters
PEDESTRIAN_UE_DISTANCE = 100  # meters

CLOUD_CPU_CAPACITY = 10.0e+14  # OPS
VEHICLE_CPU_CAPACITY = 1.3e+13  # OPS NVIDIA V100

CLOUD_ID = -1
GNB_TX_POWER_5G = 23  # dbm
GNB_TX_POWER_INET = 23
UE_TX_POWER = 23
CONTROLLER_CPU_POWER = 200  # watt
VEHICLE_CPU_POWER = 200  # watt
PRICE_KWH_CLOUD = 0.1
PRICE_KWH = 0.15  # $/KWh
POSSIBLE_TASK_TYPES = (16, 100, 500)  # milliseconds
TASK_TYPE_TUPLE = (0, 0, 1) #alpha breta gamma it defines the task type percentage we have

PRICE_SUBSCRIPTIONS = (10, 15, 20, 25)

TASK_RATE = 10  # task requests per use per second

VEHICLE_QUEUE_CAPACITY = 1
CLOUD_QUEUE_CAPACITY = 10.0e+12

NUM_VEHICLES = 40
MAX_SIMULATION_TIME_MS =  215
TIME_STEP_MS = 1  # millisecond time step
USERS_NUMBER = 100
NUM_CLOUDS = 1

CITY = "Rome"
CITY_BBOX = (12.4800, 41.8950, 12.4950, 41.9050)

WINDOW_TASK_COLLECTION = 10  # milliseconds

VEHICLE_BEACON_INTERVAL_MS = 100  # Vehicle beacons every 100 ms
CLOUD_BEACON_INTERVAL_MS = 900000  # Cloud beacons every 15 minutes (900,000 ms)

NETWORK_OPERATORS = 1
NO_ENERGY_PRICE = 0.15  # KW/h

ALGORITHM_TIME_OVERHEAD = 0

COVERAGE_RADIUS = 1000
START_TIME = 200
INET_DELAY = 0.035
SEED_RANDOM = 100


ENERGY_AVAILABLE = 10e+12

NO_ID= 19250596

VERBOSE = True

TASK_INPUT_SIZE= 80000#bit
TASK_OUTPUT_SIZE = 80000 #bit
TASK_WORKLOAD=500000000

total_bandwidth_dl = 20e6  # Hz
total_bandwidth_ul = 10e6  # Hz



