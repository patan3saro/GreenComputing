from config import *
import random

random.seed(SEED_RANDOM)


class Vehicle:
    def __init__(self, id=None, cpu_capacity=None, queue_capacity=None,  cpu_power=None, ue_power=None, energy_available=None,
                 dollars_per_kwh=None, mobility_df=None):

        # One instance values
        self.id = id  # constant for all the simulation
        self.cpu_capacity = cpu_capacity  # constant
        self.queue_capacity = int(queue_capacity)
        self.cpu_power = cpu_power  # constant
        self.energy_available = energy_available  # changes and diminishes over time
        self.ue_power = ue_power
        self.dollars_per_kwh = dollars_per_kwh


        # DataFrame containing mobility data (position_x, position_y, speed, etc.)
        self.mobility_df = mobility_df

    def get_position_and_speed(self, instant):
        """
        Get vehicle position and speed at the time instant closest to the provided value.

        Parameters:
        - instant: The time value to find position and speed for

        Returns:
        - Tuple of (position_x, position_y, speed) for the time closest to the given instant
        - None if mobility data is not available
        """
        if self.mobility_df is None:
            raise ValueError("Mobility data is not defined")

        # If 'time' is an index
        if self.mobility_df.index.name == 'time':
            # Find closest index value
            closest_idx = (self.mobility_df.index - instant).abs().argmin()
            row = self.mobility_df.iloc[closest_idx]
            return row['position_x'], row['position_y'], row['speed']

        # If 'time' is a column
        elif 'time' in self.mobility_df.columns:
            # Find closest time value
            closest_idx = (self.mobility_df['time'] - instant).abs().argmin()
            row = self.mobility_df.iloc[closest_idx]
            return row['position_x'], row['position_y'], row['speed']

        # If no time column or index is found
        return None

    def create_communication_beacon(self, instant):

        # Check for required attributes
        if self.id is None:
            raise ValueError("Vehicle ID is not defined")
        if self.cpu_power is None:
            raise ValueError("CPU power is not defined")
        if self.energy_available is None:
            raise ValueError("Energy available is not defined")
        if self.cpu_capacity is None:
            raise ValueError("CPU capacity is not defined")
        if self.ue_power is None:
            raise ValueError("UE power is not defined")
        if self.dollars_per_kwh is None:
            raise ValueError("Dollars per kWh is not defined")

        mobility_info = self.get_position_and_speed(instant)


        if mobility_info is None:
            return None

        pos_x, pos_y, speed = mobility_info

        # Create mobility dictionary instead of tuple
        mobility_dict = {
            'position_x': pos_x,
            'position_y': pos_y,
            'speed': speed
        }

        # Return a tuple with beacon information
        return (self.id, self.cpu_capacity, self.cpu_power, self.ue_power,
                self.energy_available, self.dollars_per_kwh, mobility_dict, self.queue_capacity)

    def create_real_beacon(self, beacon_original):

        # Get position and speed at this instant
        mobility_info = beacon_original[6]

        # Generate beacon ID based on vehicle ID
        beacon_id = self.id

        # Generate randomized values based on vehicle attributes with normal distribution
        # For each value, use the vehicle's attribute as mean and add random variation

        # CPU capacity with random variation
        beacon_cpu_capacity = random.normalvariate(self.cpu_capacity, self.cpu_capacity * 0.1)

        # CPU power with random variation
        beacon_cpu_power = random.normalvariate(self.cpu_power, self.cpu_power * 0.1)

        # UE power with random variation
        beacon_ue_power = random.normalvariate(self.ue_power, self.ue_power * 0.1)

        # Energy available with random variation
        beacon_energy = random.normalvariate(self.energy_available, self.energy_available * 0.1)

        beacon_dollars_per_kwh = random.normalvariate(self.dollars_per_kwh, self.dollars_per_kwh * 0.05)
        beacon_queue_capacity = random.randint(self.queue_capacity, 10 + self.queue_capacity)

        """
        print(f"Real beacon created by vehicle {self.id}")
        print(f"CPU capacity: {beacon_cpu_capacity:.2f}, CPU power: {beacon_cpu_power:.2f}")
        print(f"UE power: {beacon_ue_power:.2f}, Energy: {beacon_energy:.2f}")
        print(f"Energy cost: ${beacon_dollars_per_kwh:.4f} per kWh")
        """
        # Return a tuple with all beacon information
        return (beacon_id, beacon_cpu_capacity, beacon_cpu_power, beacon_ue_power,
                beacon_energy, beacon_dollars_per_kwh, mobility_info, beacon_queue_capacity)
