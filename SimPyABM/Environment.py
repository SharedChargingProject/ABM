import sys
sys.path.append('..')
import simpy
import numpy as np
from datetime import datetime
from zoneinfo import ZoneInfo
from SimPyABM.logger import Logger

class Environment:
    def __init__(self, simpy_env,energy_sandbox, config):
        self.simpy_env = simpy_env
        self.config = config
        self.rng = np.random.default_rng(config.random_seed)
        self.energy_sandbox = energy_sandbox
        self.verbose = config.verbose
        
        # example: '2023-06-05 06:00:00#Europe/Vienna' (includes timezone)
        self.start_datetime = datetime.strptime(config.start_date_time.split('#')[0], '%Y-%m-%d %H:%M:%S').replace(tzinfo=ZoneInfo(config.start_date_time.split('#')[1]))
        self.start_unix = int(self.start_datetime.timestamp())
        self.end_unix = self.start_unix + config.duration

        self.logger = Logger()

        self.slot_sec = config.time_resolution
        self.n_slots = int(np.ceil(config.duration / self.slot_sec))

        # G: planned / reserved global power usage per slot [kW]
        self.G = np.zeros(self.n_slots, dtype=float)

        # P: PV ratio per slot [0..1]
        self.P = np.array([
            self.energy_sandbox.data_provider.getPVRatio_unix(self.start_unix + k * self.slot_sec)
            for k in range(self.n_slots)
        ], dtype=float)

        # C: energy price per slot [EUR/kWh]
        self.C = np.array([
            self.energy_sandbox.getEnergyPrice(self.start_unix + k * self.slot_sec)
            for k in range(self.n_slots)
        ], dtype=float)

        # log energy price (PV is being logged in the energy sandbox)
        for k in range(self.n_slots):
            self.logger.insert(
                time=self.start_unix + k * self.slot_sec,
                field="energy_price",
                value=self.C[k],
                agent='env')
    
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

    def get_slot_idx(self, unix_time=None):
        if unix_time is None:
            unix_time = self.now()
        idx = int((unix_time - self.start_unix) // self.slot_sec)
        return max(0, min(idx, self.n_slots - 1))

    def log(self, *args, **kwargs):
        if self.verbose:
            print(self.unix_to_dt(self.now()), end=' - ')
            print(*args, **kwargs)
