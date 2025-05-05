import random
import seeds
random.seed(seeds.seed_random)



class Cloud:
    def __init__(self, id=None, cpu_capacity=None, cloud_queue_capacity=None, cpu_power=None,
                 tx_power=None, energy_available=None, dollars_per_kwh=None):

        self.id = id
        self.cpu_capacity = cpu_capacity
        self.cpu_power = cpu_power
        self.tx_power = tx_power
        self.energy_available = energy_available
        self.dollars_per_kwh = dollars_per_kwh
        self.cloud_queue_capacity = cloud_queue_capacity

    def create_communication_beacon(self):
        """
        Returns the cloud's variables directly

        Returns:
        - A tuple containing the cloud's values

        Raises:
        - ValueError: If required attributes are None
        """
        # Check for required attributes
        if self.id is None:
            raise ValueError("Cloud ID is not defined")
        if self.cpu_capacity is None:
            raise ValueError("CPU capacity is not defined")
        if self.cpu_power is None:
            raise ValueError("CPU power is not defined")
        if self.tx_power is None:
            raise ValueError("Transmission power is not defined")
        if self.energy_available is None:
            raise ValueError("Energy available is not defined")
        if self.dollars_per_kwh is None:
            raise ValueError("Dollars per kWh is not defined")

        # Return the cloud's variables directly
        return self.id, self.cpu_capacity, self.cpu_power, self.tx_power, self.energy_available, self.dollars_per_kwh, self.cloud_queue_capacity

    def create_real_beacon(self):
        """
        Returns randomized variations of the cloud's variables

        Returns:
        - A tuple containing randomized values

        Raises:
        - ValueError: If required attributes are None
        """

        # Check for required attributes
        if self.id is None:
            raise ValueError("Cloud ID is not defined")
        if self.cpu_capacity is None:
            raise ValueError("CPU capacity is not defined")
        if self.cpu_power is None:
            raise ValueError("CPU power is not defined")
        if self.tx_power is None:
            raise ValueError("Transmission power is not defined")
        if self.energy_available is None:
            raise ValueError("Energy available is not defined")
        if self.dollars_per_kwh is None:
            raise ValueError("Dollars per kWh is not defined")

        # Generate randomized values based on cloud attributes
        random_id = self.id
        random_cpu = random.normalvariate(self.cpu_capacity, self.cpu_capacity * 0.1)
        random_power = random.normalvariate(self.cpu_power, self.cpu_power * 0.1)
        random_tx = random.normalvariate(self.tx_power, self.tx_power * 0.1)
        random_energy = random.normalvariate(self.energy_available, self.energy_available * 0.1)
        random_dollars = random.normalvariate(self.dollars_per_kwh, self.dollars_per_kwh * 0.05)

        # Return the randomized values directly
        return (random_id, random_cpu, random_power, random_tx, random_energy, random_dollars, self.cloud_queue_capacity)
