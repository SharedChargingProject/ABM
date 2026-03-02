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

    def log(self, *args, **kwargs):
        if self.verbose:
            print(self.unix_to_dt(self.now()), end=' - ')
            print(*args, **kwargs)
