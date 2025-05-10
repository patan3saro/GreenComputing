import random

class Vehicle:
    def __init__(self, vehicle_id=None, cpu_capacity=None, queue_capacity=None, cpu_power=None,
                 ue_power=None, energy_available=None, dollars_per_kwh=None, ul_datarate=None, dl_datarate=None, position_x=None, position_y=None, speed=None):
        self.vehicle_id = vehicle_id
        self.cpu_capacity = cpu_capacity
        self.cpu_power = cpu_power
        self.ue_power = ue_power
        self.energy_available = energy_available
        self.dollars_per_kwh = dollars_per_kwh
        self.queue_capacity = queue_capacity
        self.ul_datarate = ul_datarate
        self.dl_datarate = dl_datarate
        self.position_x = position_x
        self.position_y = position_y
        self.speed = speed

    def create_beacon(self, instant_sec: float, randomize: bool = False,):
        """
        Returns a beacon tuple with mobility info and optional random variation.
        """
        # Validate
        for attr in ['vehicle_id', 'cpu_capacity', 'queue_capacity', 'cpu_power', 'ue_power', 'energy_available', 'dollars_per_kwh',
                     'ul_datarate', 'dl_datarate', 'position_x', 'position_y', 'speed']:
            if getattr(self, attr) is None:
                raise ValueError(f"Vehicle {attr} is not defined")

        # Base values
        beacon_id = self.vehicle_id
        cpu_capacity = self.cpu_capacity
        cpu_power = self.cpu_power
        ue_power = self.ue_power
        energy_available = self.energy_available
        dollars_per_kwh = self.dollars_per_kwh
        queue_capacity = self.queue_capacity

        if randomize:
            cpu_capacity = random.normalvariate(cpu_capacity, cpu_capacity * 0.1)
            cpu_power = random.normalvariate(cpu_power, cpu_power * 0.1)
            ue_power = random.normalvariate(ue_power, ue_power * 0.1)
            energy_available = random.normalvariate(energy_available, energy_available * 0.1)
            dollars_per_kwh = random.normalvariate(dollars_per_kwh, dollars_per_kwh * 0.05)
            queue_capacity = random.randint(queue_capacity, queue_capacity + 10)

        return instant_sec, beacon_id, cpu_capacity,  queue_capacity, cpu_power, ue_power, energy_available, dollars_per_kwh, self.ul_datarate, self.dl_datarate, self.position_x, self.position_y, self.speed

    def set_istantaneous_mobility_pattern(self, instant_sec, mobility_df):
        # Trova l'indice con timestamp più vicino a `instant`
        idx = (mobility_df['time'] - instant_sec).abs().idxmin()
        row = mobility_df.loc[idx]
        self.position_x = row['position_x']
        self.position_y = row['position_y']
        self.speed = row['speed']

    def set_istantaneous_datarate_pattern(self,ul_datarate, dl_datarate):
        self.ul_datarate = ul_datarate
        self.dl_datarate = dl_datarate


