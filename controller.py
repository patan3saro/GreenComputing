from config import *
import heapq

class Controller:
    def __init__(self, gnb_position_x=0, gnb_position_y=0):
        self.gnb_position_x = gnb_position_x
        self.gnb_position_y = gnb_position_y
        self.beacons = []
        self.beacon_timestamps = {}
        self.last_beacon_times = {}
        self.real_beacons = []
        self.real_beacon_timestamps = {}
        self.last_real_beacon_times = {}

    def receive_vehicle_beacon(self, beacon, current_time_ms, dwell_time):
        (beacon_id, beacon_cpu_capacity, beacon_cpu_power, beacon_ue_power,
         beacon_energy, beacon_dollars_per_kwh, mobility_info, queue_capacity_vehicle,
         ul_datarate, dl_datarate) = beacon

        self.beacon_timestamps[beacon_id] = current_time_ms
        self.last_beacon_times[beacon_id] = current_time_ms

        self._add_vehicle_beacon_to_list(
            beacon_id, beacon_cpu_capacity, beacon_cpu_power, beacon_ue_power,
            beacon_energy, beacon_dollars_per_kwh, mobility_info,
            current_time_ms, dwell_time, queue_capacity_vehicle,
            ul_datarate, dl_datarate
        )

        return True

    def receive_vehicle_real_beacon(self, beacon, current_time_ms, dwell_time):
        (beacon_id, beacon_cpu_capacity, beacon_cpu_power, beacon_ue_power,
         beacon_energy, beacon_dollars_per_kwh, mobility_info, queue_capacity_vehicle,
         ul_datarate, dl_datarate) = beacon

        self.real_beacon_timestamps[beacon_id] = current_time_ms
        self.last_real_beacon_times[beacon_id] = current_time_ms

        self._add_vehicle_real_beacon_to_list(
            beacon_id, beacon_cpu_capacity, beacon_cpu_power, beacon_ue_power,
            beacon_energy, beacon_dollars_per_kwh, mobility_info,
            current_time_ms, dwell_time, queue_capacity_vehicle,
            ul_datarate, dl_datarate
        )

        return True

    def _add_vehicle_beacon_to_list(self, beacon_id, beacon_cpu_capacity, beacon_cpu_power, beacon_ue_power,
                                    beacon_energy, beacon_dollars_per_kwh, mobility_info,
                                    current_time_ms, dwell_time, queue_capacity_vehicle,
                                    ul_datarate, dl_datarate):
        self.beacons = [b for b in self.beacons if b[1] != beacon_id]

        new_beacon = (
            (-dwell_time, -beacon_energy, -queue_capacity_vehicle),
            beacon_id,
            {
                'type': 'vehicle',
                'power': beacon_cpu_power,
                'tx_power': beacon_ue_power,
                'energy': beacon_energy,
                'position_x': mobility_info['position_x'],
                'position_y': mobility_info['position_y'],
                'dollars_per_kwh': beacon_dollars_per_kwh,
                'speed': mobility_info['speed'],
                'cpu_capacity': beacon_cpu_capacity,
                'queue_capacity': queue_capacity_vehicle,
                'useful_throughput_dl': dl_datarate,
                'useful_throughput_ul': ul_datarate
            },
            current_time_ms
        )

        heapq.heappush(self.beacons, new_beacon)

    def _add_vehicle_real_beacon_to_list(self, beacon_id, beacon_cpu_capacity, beacon_cpu_power, beacon_ue_power,
                                         beacon_energy, beacon_dollars_per_kwh, mobility_info,
                                         current_time_ms, dwell_time, queue_capacity_vehicle,
                                         ul_datarate, dl_datarate):
        self.real_beacons = [b for b in self.real_beacons if b[1] != beacon_id]

        new_real_beacon = (
            (-dwell_time, -beacon_energy, -queue_capacity_vehicle),
            beacon_id,
            {
                'type': 'vehicle',
                'power': beacon_cpu_power,
                'tx_power': beacon_ue_power,
                'energy': beacon_energy,
                'position_x': mobility_info['position_x'],
                'position_y': mobility_info['position_y'],
                'dollars_per_kwh': beacon_dollars_per_kwh,
                'speed': mobility_info['speed'],
                'cpu_capacity': beacon_cpu_capacity,
                'queue_capacity': queue_capacity_vehicle,
                'useful_throughput_dl': dl_datarate,
                'useful_throughput_ul': ul_datarate
            },
            current_time_ms
        )

        heapq.heappush(self.real_beacons, new_real_beacon)

    def receive_cloud_beacon(self, beacon, current_time_ms):
        beacon_id, beacon_cpu_capacity, beacon_cpu_power, beacon_ue_power, beacon_energy, beacon_dollars_per_kwh, queue_capacity, ul_datarate, dl_datarate = beacon
        self.beacon_timestamps[beacon_id] = current_time_ms
        self.last_beacon_times[beacon_id] = current_time_ms
        self._add_cloud_beacon_to_list(beacon_id, beacon_cpu_capacity, beacon_cpu_power, beacon_ue_power,
                                       beacon_energy, beacon_dollars_per_kwh, current_time_ms)
        return True

    def receive_cloud_real_beacon(self, beacon, current_time_ms):
        beacon_id, beacon_cpu_capacity, beacon_cpu_power, beacon_ue_power, beacon_energy, beacon_dollars_per_kwh, queue_capacity, ul_datarate, dl_datarate = beacon
        self.real_beacon_timestamps[beacon_id] = current_time_ms
        self.last_real_beacon_times[beacon_id] = current_time_ms
        self._add_cloud_real_beacon_to_list(beacon_id, beacon_cpu_capacity, beacon_cpu_power, beacon_ue_power,
                                            beacon_energy, beacon_dollars_per_kwh, current_time_ms)
        return True

    def _add_cloud_beacon_to_list(self, beacon_id, beacon_cpu_capacity, beacon_cpu_power, beacon_ue_power,
                                  beacon_energy, beacon_dollars_per_kwh, current_time_ms):
        dwell_time = 1e6
        queue_capacity = CLOUD_QUEUE_CAPACITY
        self.beacons = [b for b in self.beacons if b[1] != beacon_id]

        new_beacon = (
            (-dwell_time, -beacon_energy, -queue_capacity),
            beacon_id,
            {
                'type': 'cloud',
                'cpu_capacity': beacon_cpu_capacity,
                'power': beacon_cpu_power,
                'tx_power': beacon_ue_power,
                'energy': beacon_energy,
                'position_x': 0,
                'position_y': 0,
                'dollars_per_kwh': beacon_dollars_per_kwh,
                'queue_capacity': queue_capacity
            },
            current_time_ms
        )

        heapq.heappush(self.beacons, new_beacon)

    def _add_cloud_real_beacon_to_list(self, beacon_id, beacon_cpu_capacity, beacon_cpu_power, beacon_ue_power,
                                       beacon_energy, beacon_dollars_per_kwh, current_time_ms):
        dwell_time = 1e6
        queue_capacity = CLOUD_QUEUE_CAPACITY
        self.real_beacons = [b for b in self.real_beacons if b[1] != beacon_id]

        new_real_beacon = (
            (-dwell_time, -beacon_energy, -queue_capacity),
            beacon_id,
            {
                'type': 'cloud',
                'cpu_capacity': beacon_cpu_capacity,
                'power': beacon_cpu_power,
                'tx_power': beacon_ue_power,
                'energy': beacon_energy,
                'position_x': 0,
                'position_y': 0,
                'dollars_per_kwh': beacon_dollars_per_kwh,
                'queue_capacity': queue_capacity
            },
            current_time_ms
        )

        heapq.heappush(self.real_beacons, new_real_beacon)

    def clean_expired_beacons(self, current_time_ms, vehicle_expiry_ms=500, cloud_expiry_ms=900000):
        valid_beacons = []
        while self.beacons:
            beacon = heapq.heappop(self.beacons)
            _, beacon_id, details, timestamp = beacon
            expiry = vehicle_expiry_ms if details['type'] == 'vehicle' else cloud_expiry_ms
            self.beacon_timestamps.pop(beacon_id, None)
            self.last_beacon_times.pop(beacon_id, None)

            if current_time_ms - timestamp <= expiry:
                valid_beacons.append(beacon)
        self.beacons = valid_beacons

    def clean_expired_real_beacons(self, current_time_ms, vehicle_expiry_ms=500, cloud_expiry_ms=900000):
        valid_beacons = []
        while self.real_beacons:
            beacon = heapq.heappop(self.real_beacons)
            _, beacon_id, details, timestamp = beacon
            expiry = vehicle_expiry_ms if details['type'] == 'vehicle' else cloud_expiry_ms
            self.beacon_timestamps.pop(beacon_id, None)
            self.last_beacon_times.pop(beacon_id, None)

            if current_time_ms - timestamp <= expiry:
                valid_beacons.append(beacon)
        self.real_beacons = valid_beacons

    def get_top_nodes(self, count):
        return [b[1] for b in heapq.nsmallest(count, self.beacons)]

    def get_top_real_nodes(self, count):
        return [b[1] for b in heapq.nsmallest(count, self.real_beacons)]
