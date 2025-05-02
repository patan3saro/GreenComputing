from config import *
import heapq

class Controller:
    """
    Controller class that collects and manages communication beacons from vehicles and cloud nodes,
    maintains prioritized lists, and assigns tasks to available nodes.
    """

    def __init__(self, gnb_position_x=0, gnb_position_y=0):
        """
        Initialize the Controller

        Parameters:
        - gnb_position_x: X coordinate of the GNB position (default: 0)
        - gnb_position_y: Y coordinate of the GNB position (default: 0)
        """
        self.gnb_position_x = gnb_position_x
        self.gnb_position_y = gnb_position_y

        # Communication beacons
        self.beacons = []  # List of collected communication beacons
        self.beacon_timestamps = {}  # Dictionary to track when beacons were received
        self.last_beacon_times = {}  # Dictionary to track last beacon time per node

        # Real beacons
        self.real_beacons = []  # List of collected real beacons
        self.real_beacon_timestamps = {}  # Dictionary to track when real beacons were received
        self.last_real_beacon_times = {}  # Dictionary to track last real beacon time per node

    def receive_vehicle_beacon(self, beacon, current_time_ms, dwell_time):
        """
        Receive a communication beacon from a vehicle

        Parameters:
        - beacon: Tuple containing beacon information
        - current_time_ms: Current simulation time in milliseconds
        - dwell_time: Expected dwell time for this vehicle

        Returns:
        - True if beacon was accepted, False otherwise
        """
        # Parse beacon information
        (beacon_id, beacon_cpu_capacity, beacon_cpu_power, beacon_ue_power,
         beacon_energy, beacon_dollars_per_kwh, mobility_info, queue_capacity_vehicle) = beacon

        # Track when this beacon was received
        self.beacon_timestamps[beacon_id] = current_time_ms
        self.last_beacon_times[beacon_id] = current_time_ms

        # Process the beacon and add to the list
        self._add_vehicle_beacon_to_list(beacon_id, beacon_cpu_capacity, beacon_cpu_power, beacon_ue_power,
                beacon_energy, beacon_dollars_per_kwh, mobility_info, current_time_ms, dwell_time, queue_capacity_vehicle)

        return True

    def receive_vehicle_real_beacon(self, beacon, current_time_ms, dwell_time):
        """
        Receive a real beacon from a vehicle with additional information

        Parameters:
        - beacon: Tuple containing real beacon information
        - current_time_ms: Current simulation time in milliseconds

        Returns:
        - True if beacon was accepted, False otherwise
        """
        # Parse beacon information
        (beacon_id, beacon_cpu_capacity, beacon_cpu_power, beacon_ue_power,
                beacon_energy, beacon_dollars_per_kwh, mobility_info, queue_capacity_vehicle) = beacon

        # Track when this real beacon was received
        self.real_beacon_timestamps[beacon_id] = current_time_ms
        self.last_real_beacon_times[beacon_id] = current_time_ms

        # Process the beacon and add to the real beacons list
        self._add_vehicle_real_beacon_to_list(beacon_id, beacon_cpu_capacity, beacon_cpu_power, beacon_ue_power,
                beacon_energy, beacon_dollars_per_kwh, mobility_info, current_time_ms, dwell_time, queue_capacity_vehicle)

        return True

    def _calculate_dwell_time(self, mobility_info):
        """
        Calculate dwell time based on mobility information

        Parameters:
        - mobility_info: Dictionary containing vehicle mobility details

        Returns:
        - Calculated dwell time in milliseconds
        """
        # This is a placeholder implementation
        # Replace with actual calculation based on speed, position, etc.
        speed = mobility_info.get('speed', 0)
        if speed <= 0:
            return float('inf')  # Stationary vehicle
        else:
            # Simple calculation for demonstration
            return 10000 / speed  # Just an example formula

    def receive_cloud_beacon(self, beacon, current_time_ms):
        """
        Receive a communication beacon from a cloud node

        Parameters:
        - beacon: Tuple containing beacon information
        - current_time_ms: Current simulation time in milliseconds

        Returns:
        - True if beacon was accepted, False otherwise
        """
        # Parse beacon information
        beacon_id, beacon_cpu_capacity,  beacon_cpu_power, beacon_ue_power, beacon_energy, beacon_dollars_per_kwh, queue_capacity = beacon

        # Track when this beacon was received
        self.beacon_timestamps[beacon_id] = current_time_ms
        self.last_beacon_times[beacon_id] = current_time_ms

        # Cloud nodes are considered stationary with infinite dwell time
        self._add_cloud_beacon_to_list(beacon_id, beacon_cpu_capacity, beacon_cpu_power, beacon_ue_power, beacon_energy, beacon_dollars_per_kwh,
                                       current_time_ms)

        return True

    def receive_cloud_real_beacon(self, beacon, current_time_ms):
        """
        Receive a real beacon from a cloud node with additional information

        Parameters:
        - beacon: Tuple containing real beacon information
        - current_time_ms: Current simulation time in milliseconds

        Returns:
        - True if beacon was accepted, False otherwise
        """
        # Parse beacon information
        beacon_id, beacon_cpu_capacity, beacon_cpu_power, beacon_ue_power, beacon_energy, beacon_dollars_per_kwh, cloud_queue_capacity  = beacon

        # Track when this real beacon was received
        self.real_beacon_timestamps[beacon_id] = current_time_ms
        self.last_real_beacon_times[beacon_id] = current_time_ms

        # Process the beacon and add to the real beacons list
        self._add_cloud_real_beacon_to_list(beacon_id, beacon_cpu_capacity, beacon_cpu_power, beacon_ue_power,
                                           beacon_energy, beacon_dollars_per_kwh, current_time_ms)

        return True

    def _add_vehicle_beacon_to_list(self, beacon_id, beacon_cpu_capacity, beacon_cpu_power, beacon_ue_power,
                               beacon_energy, beacon_dollars_per_kwh, mobility_info, current_time_ms, dwell_time, queue_capacity_vehicle):
        """
        Add a vehicle communication beacon to the prioritized list

        Parameters:
        - beacon_id: Identifier for the vehicle
        - beacon_cpu_capacity: CPU capacity of the vehicle
        - beacon_cpu_power: CPU power consumption of the vehicle
        - beacon_ue_power: Transmission power of the vehicle
        - beacon_energy: Energy available in the vehicle
        - beacon_dollars_per_kwh: Price in dollars per kilowatt-hour
        - mobility_info: Dictionary containing vehicle mobility details
        - current_time_ms: Current simulation time in milliseconds
        - dwell_time: Expected dwell time for this vehicle
        """
        # Determine queue capacity (number of tasks the node can handle)
        queue_capacity = queue_capacity_vehicle

        # Remove existing beacon with the same ID if present
        self.beacons = [b for b in self.beacons if b[1] != beacon_id]

        # Create new beacon with priority information
        # Format: (priority_tuple, beacon_id, beacon_details, timestamp)
        # Priority tuple is: (-dwell_time, -energy, -queue_capacity)
        # Negative values make heapq behave like a max-heap
        new_beacon = (
            (-dwell_time, -beacon_energy, -queue_capacity),
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
                'queue_capacity': queue_capacity
            },
            current_time_ms
        )

        # Add to beacon list
        heapq.heappush(self.beacons, new_beacon)

    def _add_vehicle_real_beacon_to_list(self, beacon_id, beacon_cpu_capacity, beacon_cpu_power, beacon_ue_power,
                                       beacon_energy, beacon_dollars_per_kwh, mobility_info, current_time_ms, dwell_time, queue_capacity_vehicle):
        """
        Add a vehicle real beacon to the prioritized real beacons list

        Parameters:
        - beacon_id: Identifier for the vehicle
        - beacon_cpu_capacity: CPU capacity of the vehicle
        - beacon_cpu_power: CPU power consumption of the vehicle
        - beacon_ue_power: Transmission power of the vehicle
        - beacon_energy: Energy available in the vehicle
        - beacon_dollars_per_kwh: Price in dollars per kilowatt-hour
        - mobility_info: Dictionary containing vehicle mobility details
        - current_time_ms: Current simulation time in milliseconds
        - dwell_time: Expected dwell time for this vehicle
        """

        # Remove existing real beacon with the same ID if present
        self.real_beacons = [b for b in self.real_beacons if b[1] != beacon_id]

        # Create new real beacon with priority information
        # Format: (priority_tuple, beacon_id, beacon_details, timestamp)
        # Priority tuple is: (-dwell_time, -energy, -queue_capacity)
        # Negative values make heapq behave like a max-heap
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
                'queue_capacity': queue_capacity_vehicle
            },
            current_time_ms
        )

        # Add to real beacon list
        heapq.heappush(self.real_beacons, new_real_beacon)

    def _add_cloud_beacon_to_list(self, beacon_id, beacon_cpu_capacity, beacon_cpu_power, beacon_ue_power,
                                 beacon_energy, beacon_dollars_per_kwh, current_time_ms):
        """
        Add a cloud communication beacon to the prioritized list

        Parameters:
        - beacon_id: Identifier for the cloud service
        - beacon_cpu_capacity: CPU capacity of the cloud node
        - beacon_cpu_power: CPU power consumption of the cloud node
        - beacon_ue_power: Transmission power of the cloud node
        - beacon_energy: Energy available in the cloud node
        - beacon_dollars_per_kwh: Price in dollars per kilowatt-hour
        - current_time_ms: Current simulation time in milliseconds
        """
        # Cloud nodes are stationary, so dwell time is infinite
        dwell_time = float('inf')

        # Determine queue capacity (number of tasks the node can handle)
        queue_capacity = CLOUD_QUEUE_CAPACITY

        # Remove existing beacon with the same ID if present
        self.beacons = [b for b in self.beacons if b[1] != beacon_id]

        # Create new beacon with priority information
        new_beacon = (
            (-dwell_time, -beacon_energy, -queue_capacity),
            beacon_id,
            {
                'type': 'cloud',
                'cpu_capacity': beacon_cpu_capacity,
                'power': beacon_cpu_power,
                'tx_power': beacon_ue_power,
                'energy': beacon_energy,
                'position_x': 0,  # Default position for cloud nodes
                'position_y': 0,  # Default position for cloud nodes
                'dollars_per_kwh': beacon_dollars_per_kwh,
                'queue_capacity': queue_capacity
            },
            current_time_ms
        )

        # Add to beacon list
        heapq.heappush(self.beacons, new_beacon)

    def _add_cloud_real_beacon_to_list(self, beacon_id, beacon_cpu_capacity, beacon_cpu_power, beacon_ue_power,
                                     beacon_energy, beacon_dollars_per_kwh, current_time_ms):
        """
        Add a cloud real beacon to the prioritized real beacons list

        Parameters:
        - beacon_id: Identifier for the cloud service
        - beacon_cpu_capacity: CPU capacity of the cloud node
        - beacon_cpu_power: CPU power consumption of the cloud node
        - beacon_ue_power: Transmission power of the cloud node
        - beacon_energy: Energy available in the cloud node
        - beacon_dollars_per_kwh: Price in dollars per kilowatt-hour
        - current_time_ms: Current simulation time in milliseconds
        """
        # Cloud nodes are stationary, so dwell time is infinite
        dwell_time = float('inf')

        # Determine queue capacity (number of tasks the node can handle)
        queue_capacity = CLOUD_QUEUE_CAPACITY

        # Remove existing real beacon with the same ID if present
        self.real_beacons = [b for b in self.real_beacons if b[1] != beacon_id]

        # Create new real beacon with priority information
        new_real_beacon = (
            (-dwell_time, -beacon_energy, -queue_capacity),
            beacon_id,
            {
                'type': 'cloud',
                'cpu_capacity': beacon_cpu_capacity,
                'power': beacon_cpu_power,
                'tx_power': beacon_ue_power,
                'energy': beacon_energy,
                'position_x': 0,  # Default position for cloud nodes
                'position_y': 0,  # Default position for cloud nodes
                'dollars_per_kwh': beacon_dollars_per_kwh,
                'queue_capacity': queue_capacity
            },
            current_time_ms
        )

        # Add to real beacon list
        heapq.heappush(self.real_beacons, new_real_beacon)

    def clean_expired_beacons(self, current_time_ms, vehicle_expiry_ms=500, cloud_expiry_ms=900000):
        """
        Remove expired communication beacons from the list

        Parameters:
        - current_time_ms: Current simulation time in milliseconds
        - vehicle_expiry_ms: Time after which vehicle beacons expire (default: 500ms)
        - cloud_expiry_ms: Time after which cloud beacons expire (default: 900000ms = 15min)
        """
        valid_beacons = []

        while self.beacons:
            beacon = heapq.heappop(self.beacons)
            priority, beacon_id, details, timestamp = beacon

            # Check if beacon is from vehicle or cloud
            is_vehicle = details['type'] == 'vehicle'
            expiry_time = vehicle_expiry_ms if is_vehicle else cloud_expiry_ms

            # Check if beacon is still valid
            if current_time_ms - timestamp <= expiry_time:
                valid_beacons.append(beacon)

        # Rebuild the heap with valid beacons
        self.beacons = []
        for beacon in valid_beacons:
            heapq.heappush(self.beacons, beacon)

    def clean_expired_real_beacons(self, current_time_ms, vehicle_expiry_ms=500, cloud_expiry_ms=900000):
        """
        Remove expired real beacons from the real beacons list

        Parameters:
        - current_time_ms: Current simulation time in milliseconds
        - vehicle_expiry_ms: Time after which vehicle real beacons expire (default: 500ms)
        - cloud_expiry_ms: Time after which cloud real beacons expire (default: 900000ms = 15min)
        """
        valid_real_beacons = []

        while self.real_beacons:
            real_beacon = heapq.heappop(self.real_beacons)
            priority, beacon_id, details, timestamp = real_beacon

            # Check if real beacon is from vehicle or cloud
            is_vehicle = details['type'] == 'vehicle'
            expiry_time = vehicle_expiry_ms if is_vehicle else cloud_expiry_ms

            # Check if real beacon is still valid
            if current_time_ms - timestamp <= expiry_time:
                valid_real_beacons.append(real_beacon)

        # Rebuild the heap with valid real beacons
        self.real_beacons = []
        for real_beacon in valid_real_beacons:
            heapq.heappush(self.real_beacons, real_beacon)

    def get_top_nodes(self, count):
        """
        Get the top N nodes based on prioritization from communication beacons

        Parameters:
        - count: Number of top nodes to return

        Returns:
        - List of top N beacon IDs
        """
        # Create a copy of the beacons to avoid modifying the original heap
        beacon_copy = self.beacons.copy()
        top_nodes = []

        # Extract top N nodes
        for _ in range(min(count, len(beacon_copy))):
            if beacon_copy:
                _, beacon_id, _, _ = heapq.heappop(beacon_copy)
                top_nodes.append(beacon_id)

        return top_nodes

    def get_top_real_nodes(self, count):
        """
        Get the top N nodes based on prioritization from real beacons

        Parameters:
        - count: Number of top nodes to return

        Returns:
        - List of top N real beacon IDs
        """
        # Create a copy of the real beacons to avoid modifying the original heap
        real_beacon_copy = self.real_beacons.copy()
        top_real_nodes = []

        # Extract top N real nodes
        for _ in range(min(count, len(real_beacon_copy))):
            if real_beacon_copy:
                _, beacon_id, _, _ = heapq.heappop(real_beacon_copy)
                top_real_nodes.append(beacon_id)

        return top_real_nodes

    def print_beacon_status(self):
        """Print the current status of all communication beacons in the prioritized list"""
        print("\n=== Current Communication Beacon Status ===")
        print(f"Total communication beacons: {len(self.beacons)}")

        if not self.beacons:
            print("No communication beacons available")
            return

        # Create a copy to avoid modifying the original
        beacon_copy = self.beacons.copy()
        sorted_beacons = []

        while beacon_copy:
            sorted_beacons.append(heapq.heappop(beacon_copy))

        print("\nCommunication beacons sorted by priority:")
        for i, (priority, beacon_id, details, timestamp) in enumerate(sorted_beacons):
            dwell_time = -priority[0]  # Convert back to positive
            energy = -priority[1]  # Convert back to positive
            queue_capacity = -priority[2]  # Convert back to positive

            node_type = details['type']
            if node_type == 'vehicle':
                print(f"{i + 1}. Vehicle {beacon_id}: Dwell time={dwell_time:.2f}ms, Energy={energy:.2f}, "
                      f"Queue capacity={queue_capacity}, Last update={timestamp}ms")
            else:
                print(f"{i + 1}. Cloud {beacon_id}: Dwell time=∞, Energy={energy:.2f}, "
                      f"Queue capacity={queue_capacity}, Last update={timestamp}ms")

    def print_real_beacon_status(self):
        """Print the current status of all real beacons in the prioritized list"""
        print("\n=== Current Real Beacon Status ===")
        print(f"Total real beacons: {len(self.real_beacons)}")

        if not self.real_beacons:
            print("No real beacons available")
            return

        # Create a copy to avoid modifying the original
        real_beacon_copy = self.real_beacons.copy()
        sorted_real_beacons = []

        while real_beacon_copy:
            sorted_real_beacons.append(heapq.heappop(real_beacon_copy))

        print("\nReal beacons sorted by priority:")
        for i, (priority, beacon_id, details, timestamp) in enumerate(sorted_real_beacons):
            dwell_time = -priority[0]  # Convert back to positive
            energy = -priority[1]  # Convert back to positive
            queue_capacity = -priority[2]  # Convert back to positive

            node_type = details['type']
            if node_type == 'vehicle':
                print(f"{i + 1}. Vehicle {beacon_id}: Dwell time={dwell_time:.2f}ms, Energy={energy:.2f}, "
                      f"Queue capacity={queue_capacity}, Last update={timestamp}ms")
            else:
                print(f"{i + 1}. Cloud {beacon_id}: Dwell time=∞, Energy={energy:.2f}, "
                      f"Queue capacity={queue_capacity}, Last update={timestamp}ms")
