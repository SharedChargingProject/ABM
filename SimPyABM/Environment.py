import sys
sys.path.append('..')
import simpy
import numpy as np
from datetime import datetime
from zoneinfo import ZoneInfo
from SimPyABM.logger import Logger

class Environment:
    def __init__(self, simpy_env,energy_sandbox, seed, sim_start_datetime, verbose):
        self.simpy_env = simpy_env
        self.rng = np.random.default_rng(seed)
        self.energy_sandbox = energy_sandbox
        self.verbose = verbose
        
        # example: '2023-06-05 06:00:00#Europe/Vienna' (includes timezone)
        self.start_datetime = datetime.strptime(sim_start_datetime.split('#')[0], '%Y-%m-%d %H:%M:%S').replace(tzinfo=ZoneInfo(sim_start_datetime.split('#')[1]))
        self.start_unix = int(self.start_datetime.timestamp())

        self.logger = Logger()

    def now(self):
        """
        Returns current simulation time as UNIX timestamp (int seconds).
        Assumption: simpy time unit = sec.
        """
        return self.start_unix + int(self.simpy_env.now)
    
    def unix_to_dt(self, unix_timestamp):
        """
        Converts a UNIX timestamp (int seconds) to a datetime object with timezone.
        """
        return datetime.fromtimestamp(unix_timestamp, tz=self.start_datetime.tzinfo)

    def energy_price_adjustment_process(self):
        while True:
            # Adjust energy price based on the current time
            current_time = self.now()
            new_energy_price = self.energy_sandbox.data_provider.getEnergyPrice_unix(current_time)
            self.current_energy_price = new_energy_price

            # log the current energy price
            self.logger.insert(
                time=current_time,
                field="energy_price",
                value=self.current_energy_price,
                agent='env')
            yield self.simpy_env.timeout(60*15) # adjust every 15 minutes

    def log(self, *args, **kwargs):
        if self.verbose:
            print(self.unix_to_dt(self.now()), end=' - ')
            print(*args, **kwargs)
