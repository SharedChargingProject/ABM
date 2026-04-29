import yaml
from pathlib import Path

class Config:
    def __init__(self, cfg: dict):
        self.expriment_name = cfg['simulation']['name']
        self.random_seed = cfg['simulation']['random_seed']
        self.verbose = cfg['simulation']['verbose']
        self.start_date_time = cfg["simulation"]["start_date_time"]
        self.duration = cfg["simulation"]["duration_days"] * 24 * 3600  # days to seconds
        self.duration_days = cfg["simulation"]["duration_days"]
        self.time_resolution = cfg["simulation"]["time_resolution"]
        self.num_vehicles_per_day_min = cfg["simulation"]["num_vehicles_per_day_min"]
        self.num_vehicles_per_day_max = cfg["simulation"]["num_vehicles_per_day_max"]
        self.TTR_min = cfg["simulation"]["TTR_min"]

        self.energy_grid_max_power = cfg["energy_grid"]["max_power_kW"]
        self.energy_grid_max_power_PV = cfg["energy_grid"]["max_power_PV_kW"]

        self.charging_strategy = cfg["charging_column"]["strategy"]
        self.num_fast_chg_cols = cfg["charging_column"]["fast_charging_column"]["quantity"]
        self.num_slow_chg_cols = cfg["charging_column"]["slow_charging_column"]["quantity"]
        self.fast_chg_cols_power = cfg["charging_column"]["fast_charging_column"]["power"]
        self.slow_chg_cols_power = cfg["charging_column"]["slow_charging_column"]["power"]
        self.fast_chg_cols_ports = cfg["charging_column"]["fast_charging_column"]["ports"]
        self.slow_chg_cols_ports = cfg["charging_column"]["slow_charging_column"]["ports"]
        self.handshake_duration_min = cfg["charging_column"]["handshake_duration_sec_min"]
        self.handshake_duration_max = cfg["charging_column"]["handshake_duration_sec_max"]

        self.SoC_init_min = cfg["vehicles"]["soc_init"]["min"]
        self.SoC_init_max = cfg["vehicles"]["soc_init"]["max"]
        self.car_bat_cap_min = cfg["vehicles"]["battery_capacity_kwh"]["min"]
        self.car_bat_cap_max = cfg["vehicles"]["battery_capacity_kwh"]["max"]
        self.ev_enter_max_delay = cfg["vehicles"]["entry_delay_max_min"] * 60  # minutes to seconds
        self.ev_wait_time_min = cfg["vehicles"]["wait_time_min_min"] * 60  # minutes to seconds
        self.ev_wait_time_max = cfg["vehicles"]["wait_time_max_min"] * 60  # minutes to seconds
        self.park_time_min = cfg["vehicles"]["park_time_min_min"] * 60  # minutes to seconds
        self.park_time_max = cfg["vehicles"]["park_time_max_min"] * 60  # minutes to seconds
        self.bat_max_voltages = cfg["vehicles"]["bat_max_voltages"]
        self.bat_min_voltages = cfg["vehicles"]["bat_min_voltages"]
        self.bat_voltage_mix = cfg["vehicles"]["bat_voltage_mix"]

        self.SWRM_look_ahead_time_h = cfg["SWRM"]["look_ahead_time_h"]
        self.SWRM_look_ahead_time = self.SWRM_look_ahead_time_h * 3600  # hours to seconds
        self.SWRM_replan_interval_slots = cfg["SWRM"]["replan_interval_slots"]
        self.SWRM_a_pv = cfg["SWRM"]["a_pv"]
        self.SWRM_a_price = cfg["SWRM"]["a_price"]
        self.SWRM_a_grid = cfg["SWRM"]["a_grid"]
        self.SWRM_a_ramp = cfg["SWRM"]["a_ramp"]
        self.SWRM_a_scatter = cfg["SWRM"]["a_scatter"]
        self.SWRM_a_Q = cfg["SWRM"]["a_Q"]
        self.SWRM_a_patience = cfg["SWRM"]["a_patience"]

def load_config(path: str | Path) -> Config:
    path = Path(path)
    with path.open("r", encoding="utf-8") as f:
        cfg_dict = yaml.safe_load(f)
    return Config(cfg_dict)
