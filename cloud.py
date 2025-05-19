import numpy as np

class Cloud:
    def __init__(self, cloud_id=None, cpu_capacity=None, queue_capacity=None, cpu_power=None,
                 tx_power=None, energy_available=None, dollars_per_kwh=None, ul_datarate=None, dl_datarate=None, position_x = None, position_y = None, speed = None ):
        self.cloud_id = cloud_id
        self.cpu_capacity = cpu_capacity
        self.cpu_power = cpu_power
        self.tx_power = tx_power
        self.energy_available = energy_available
        self.dollars_per_kwh = dollars_per_kwh
        self.queue_capacity = queue_capacity
        self.ul_datarate = ul_datarate
        self.dl_datarate = dl_datarate
        self.position_x = position_x
        self.position_y = position_y
        self.speed = speed

    def create_beacon(self, instant_sec: float, randomize: bool = False, seed_random: int = None):
        """
        Returns a beacon tuple with optional random variation.
        """
        np.random.seed(seed_random)

        # Validate required attributes
        for attr in ['cloud_id', 'cpu_capacity', 'queue_capacity', 'cpu_power', 'tx_power', 'energy_available', 'dollars_per_kwh', 'ul_datarate', 'dl_datarate', 'position_x', 'position_y', 'speed']:
            if getattr(self, attr) is None:
                raise ValueError(f"Cloud {attr} is not defined")

        # Base values
        beacon_id = self.cloud_id
        cpu_capacity = self.cpu_capacity
        cpu_power = self.cpu_power
        tx_power = self.tx_power
        energy_available = self.energy_available
        dollars_per_kwh = self.dollars_per_kwh
        queue_capacity = self.queue_capacity
        ul_datarate = self.ul_datarate
        dl_datarate = self.dl_datarate

        if randomize:
            cpu_capacity = np.random.normal(cpu_capacity, cpu_capacity * 0.1)
            cpu_power = np.random.normal(cpu_power, cpu_power * 0.1)
            tx_power = np.random.normal(tx_power, tx_power * 0.1)
            energy_available = np.random.normal(energy_available, energy_available * 0.1)
            dollars_per_kwh = np.random.normal(dollars_per_kwh, dollars_per_kwh * 0.05)
            ul_datarate = np.random.normal(ul_datarate, ul_datarate * 0.05)
            dl_datarate = np.random.normal(dl_datarate, dl_datarate * 0.05)


        return instant_sec, beacon_id, cpu_capacity, queue_capacity, cpu_power, tx_power, energy_available, dollars_per_kwh, ul_datarate, dl_datarate, self.position_x, self.position_y, self.speed