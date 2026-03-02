from concurrent.futures import ProcessPoolExecutor
import os
import pandas as pd

# --- Worker globals (each process gets its own copy) ---
_SANDBOX = None

def _worker_init():
    """Runs once when each worker process starts."""
    global _SANDBOX
    from SimPyABM.EnergySandbox import EnergySandbox
    _SANDBOX = EnergySandbox()


def run_one_sim(job):
    """
    Run one simulation job and return a pandas DataFrame.
    job: dict with keys {ev_count, seed, duration_days, config_path}
    """
    global _SANDBOX

    # Import inside worker to avoid pickling issues and to keep parent lean
    import numpy as np
    import pandas as pd
    from SimPyABM.Config import load_config
    from SimPyABM.Environment import Environment
    from SimPyABM.ChargingColumn import Charger
    from SimPyABM.Vehicle import Vehicle

    config = load_config(job["config_path"])
    config.duration_days = job["duration_days"]
    config.verbose = False

    ev_count = job["ev_count"]
    config.num_vehicles_per_day_min = ev_count
    config.num_vehicles_per_day_max = int(ev_count * 1.5)
    config.random_seed = job["seed"]

    env = Environment(config.random_seed, _SANDBOX, config.verbose)

    num_vehicles = env.rng.integers(
        config.num_vehicles_per_day_min,
        config.num_vehicles_per_day_max + 1,
        size=(config.duration_days,)
    )

    _CHG_Powers = config.chg_power_min + env.rng.random(config.num_chargers) * (config.chg_power_max - config.chg_power_min)
    chargers = [
        Charger(ch_i, config.chargers_cap, config.chargers_res, _CHG_Powers[ch_i], env)
        for ch_i in range(config.num_chargers)
    ]

    v_id = 0
    vehicles = []
    for day in range(config.duration_days):
        for _ in range(int(num_vehicles[day])):
            BAT_CAP = config.car_bat_cap_min + env.rng.random() * (config.car_bat_cap_max - config.car_bat_cap_min)
            SoC = 0.05 + (0.6 - 0.05) * env.rng.random()

            bat_max_voltage = config.bat_max_voltages[0] if env.rng.random() > config.bat_voltage_mix else config.bat_max_voltages[1]
            bat_min_voltage = config.bat_min_voltages[0] if env.rng.random() > config.bat_voltage_mix else config.bat_min_voltages[1]

            enter_delay = env.rng.random() * config.ev_enter_max_delay + day * 24 * 60
            park_duration = env.rng.random() * config.ev_park_time_max

            vehicle = Vehicle(v_id, SoC, BAT_CAP, bat_max_voltage, bat_min_voltage, env, enter_delay, park_duration)
            vehicles.append(vehicle)
            v_id += 1
            env.simpy_env.process(vehicle.plug_in(chargers, classic_charge=True))

    env.simpy_env.run(until=config.duration_days * 24 * 60)

    results_df = pd.DataFrame({
        "EV_id": [veh.id for veh in vehicles],
        "Cost_EUR": [veh.cost for veh in vehicles],
        "Energy_kWh": [veh.SoC - veh.init_SoC for veh in vehicles],
        "Waiting_time": [veh.charger_assigned_time - veh.enter_time for veh in vehicles],
        "Charge_duration": [veh.charge_duration for veh in vehicles],
        "Num_vehicles": ev_count,
        "Random_seed": config.random_seed,
    })

    return results_df


def main():
    config_path = "SimPyABM/config.yaml"
    duration_days = 60
    repeat_simulations = 30
    env_counts = [4, 5, 6, 7, 8, 10, 14, 16]

    # Build job list first (your idea)
    jobs = []
    for ev_count in env_counts:
        for i in range(repeat_simulations):
            jobs.append({
                "ev_count": ev_count,
                "seed": 42 + i * 10,
                "duration_days": duration_days,
                "config_path": config_path,
            })

    # Choose workers; memory-heavy sandbox => avoid too many
    max_workers = min(os.cpu_count() or 1, 4)

    dfs = []
    with ProcessPoolExecutor(max_workers=max_workers, initializer=_worker_init) as ex:
        # chunksize reduces overhead when jobs are small
        for df_part in ex.map(run_one_sim, jobs, chunksize=2):
            dfs.append(df_part)

    df_all = pd.concat(dfs, ignore_index=True)
    df_all.to_csv("results/simulation_results_parallel.csv", index=False)


if __name__ == "__main__":
    main()