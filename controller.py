import heapq

class Controller:
    def __init__(self, gnb_position_x=900, gnb_position_y=900):

        self.gnb_position_x = gnb_position_x
        self.gnb_position_y = gnb_position_y

        self.beacons = []
        self.beacon_timestamps = {}
        self.last_beacon_times = {}

        self.real_beacons = []
        self.real_beacon_timestamps = {}
        self.last_real_beacon_times = {}

    def receive_vehicle_beacon(self, beacon, current_time_ms, dwell_time):
        beacon_id = beacon[1]
        self.beacon_timestamps[beacon_id] = current_time_ms
        self.last_beacon_times[beacon_id] = current_time_ms

        self._add_vehicle_beacon_to_list(current_time_ms, beacon, dwell_time)

    def receive_vehicle_real_beacon(self, beacon, current_time_ms, dwell_time):

        beacon_id = beacon[1]

        self.real_beacon_timestamps[beacon_id] = current_time_ms
        self.last_real_beacon_times[beacon_id] = current_time_ms

        self._add_vehicle_real_beacon_to_list(current_time_ms, beacon, dwell_time)


    def _add_vehicle_beacon_to_list(self, current_time_ms, beacon, dwell_time):
        beacon_id = beacon[1]
        self.beacons = [b for b in self.beacons if b[1] != beacon_id]

        queue_capacity_vehicle = beacon[3]
        beacon_energy = beacon[6]
        new_beacon = (
            (-dwell_time, -beacon_energy, -queue_capacity_vehicle),
            beacon_id,
            {
                "type": "vehicle",
                "instant_sec": beacon[0],
                "beacon_id": beacon[1],
                "cpu_capacity": beacon[2],
                "queue_capacity": beacon[3],
                "cpu_power": beacon[4],
                "tx_power": beacon[5],
                "energy_available": beacon[6],
                "dollars_per_kwh": beacon[7],
                "ul_datarate": beacon[8],
                "dl_datarate": beacon[9],
                "position_x": beacon[10],
                "position_y": beacon[11],
                "speed": beacon[12]
            },
            current_time_ms

        )

        heapq.heappush(self.beacons, new_beacon)

    def _add_vehicle_real_beacon_to_list(self, current_time_ms, beacon, dwell_time):

        beacon_id = beacon[1]
        self.real_beacons = [b for b in self.real_beacons if b[1] != beacon_id]
        queue_capacity_vehicle = beacon[3]
        beacon_energy = beacon[6]

        new_real_beacon = (
            (-dwell_time, -beacon_energy, -queue_capacity_vehicle),
            beacon_id,
            {
                "type": "vehicle",
                "instant_sec": beacon[0],
                "beacon_id": beacon[1],
                "cpu_capacity": beacon[2],
                "queue_capacity": beacon[3],
                "cpu_power": beacon[4],
                "tx_power": beacon[5],
                "energy_available": beacon[6],
                "dollars_per_kwh": beacon[7],
                "ul_datarate": beacon[8],
                "dl_datarate": beacon[9],
                "position_x": beacon[10],
                "position_y": beacon[11],
                "speed": beacon[12]
            },
            current_time_ms

        )

        heapq.heappush(self.real_beacons, new_real_beacon)

    def receive_cloud_beacon(self, beacon, current_time_ms):

        beacon_id = beacon[1]

        self.beacon_timestamps[beacon_id] = current_time_ms
        self.last_beacon_times[beacon_id] = current_time_ms

        self._add_cloud_beacon_to_list(current_time_ms, beacon)

    def receive_cloud_real_beacon(self, beacon, current_time_ms):
        beacon_id = beacon[1]
        self.real_beacon_timestamps[beacon_id] = current_time_ms
        self.last_real_beacon_times[beacon_id] = current_time_ms

        self._add_cloud_real_beacon_to_list(current_time_ms, beacon)

    def _add_cloud_beacon_to_list(self, current_time_ms, beacon):
        dwell_time = 1e6
        beacon_id = beacon[1]
        self.beacons = [b for b in self.beacons if b[1] != beacon_id]

        queue_capacity_cloud = beacon[3]
        beacon_energy = beacon[6]
        new_beacon = (
            (-dwell_time, -beacon_energy, -queue_capacity_cloud),
            beacon_id,
            {
            "type": "cloud",
            "instant_sec": beacon[0],
            "beacon_id": beacon[1],
            "cpu_capacity": beacon[2],
            "queue_capacity": beacon[3],
            "cpu_power": beacon[4],
            "tx_power": beacon[5],
            "energy_available": beacon[6],
            "dollars_per_kwh": beacon[7],
            "ul_datarate": beacon[8],
            "dl_datarate": beacon[9],
            "position_x": beacon[10],
            "position_y": beacon[11],
            "speed": beacon[12]
            },
            current_time_ms

        )

        heapq.heappush(self.beacons, new_beacon)


    def _add_cloud_real_beacon_to_list(self, current_time_ms, beacon):
        dwell_time = 1e6
        beacon_id = beacon[1]
        self.real_beacons = [b for b in self.real_beacons if b[1] != beacon_id]
        queue_capacity_cloud = beacon[3]
        beacon_energy = beacon[6]

        new_real_beacon = (
            (-dwell_time, -beacon_energy, -queue_capacity_cloud),
            beacon_id,
            {
                "type": "cloud",
                "instant_sec": beacon[0],
                "beacon_id": beacon[1],
                "cpu_capacity": beacon[2],
                "queue_capacity": beacon[3],
                "cpu_power": beacon[4],
                "tx_power": beacon[5],
                "energy_available": beacon[6],
                "dollars_per_kwh": beacon[7],
                "ul_datarate": beacon[8],
                "dl_datarate": beacon[9],
                "position_x": beacon[10],
                "position_y": beacon[11],
                "speed": beacon[12]
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
