from concurrent.futures import ProcessPoolExecutor
import os
from typing import Dict, Iterable, List

import pandas as pd

# --- Worker globals (each process gets its own copy) ---
_DATA_PROVIDER = None


def _worker_init():
    """Runs once when each worker process starts."""
    global _DATA_PROVIDER
    from SimPyABM.DataProvider import DataProvider

    _DATA_PROVIDER = DataProvider()


def _set_duration(config, duration_days: int) -> None:
    """Keep notebook-style duration settings consistent."""
    config.duration_days = duration_days

    # The notebook now operates in seconds.
    if hasattr(config, "duration"):
        config.duration = duration_days * 24 * 3600


def _build_charging_columns(config, env):
    """Build charging columns using the current notebook API, with a fallback for older configs."""
    from SimPyABM.ChargingColumn import ChargingColumn

    charging_columns = []
    ch_i = 0

    # Current notebook/config layout: explicit fast/slow charging columns.
    if hasattr(config, "num_fast_chg_cols") and hasattr(config, "num_slow_chg_cols"):
        for _ in range(config.num_fast_chg_cols):
            charging_columns.append(
                ChargingColumn(
                    ch_i,
                    config.fast_chg_cols_ports,
                    config.time_resolution,
                    config.handshake_duration_min,
                    config.handshake_duration_max,
                    config.fast_chg_cols_power,
                    env,
                )
            )
            ch_i += 1

        for _ in range(config.num_slow_chg_cols):
            charging_columns.append(
                ChargingColumn(
                    ch_i,
                    config.slow_chg_cols_ports,
                    config.time_resolution,
                    config.handshake_duration_min,
                    config.handshake_duration_max,
                    config.slow_chg_cols_power,
                    env,
                )
            )
            ch_i += 1

        return charging_columns

    # Fallback for the older flat charger config used by the legacy script.
    chg_powers = config.chg_power_min + env.rng.random(config.num_chargers) * (
        config.chg_power_max - config.chg_power_min
    )
    for ch_i in range(config.num_chargers):
        charging_columns.append(
            ChargingColumn(
                ch_i,
                config.chargers_cap,
                config.chargers_res,
                0,
                0,
                chg_powers[ch_i],
                env,
            )
        )

    return charging_columns


def _start_background_processes(charging_columns, env, energy_sandbox, strategy):
    """Start notebook-style long-running processes if available."""
    for charging_column in charging_columns:
        if hasattr(charging_column, "main_loop"):
            env.simpy_env.process(charging_column.main_loop(strategy=strategy))

    if hasattr(energy_sandbox, "pv_power_adjustment_process"):
        env.simpy_env.process(energy_sandbox.pv_power_adjustment_process(env))


def _spawn_vehicles(config, env, charging_columns):
    """Create vehicles using the current notebook logic, with signature fallbacks."""
    from SimPyABM.Vehicle import Vehicle

    num_vehicles = env.rng.integers(
        config.num_vehicles_per_day_min,
        config.num_vehicles_per_day_max + 1,
        size=(config.duration_days,),
    )

    v_id = 0
    vehicles = []

    soc_min = getattr(config, "SoC_init_min", 0.05)
    soc_max = getattr(config, "SoC_init_max", 0.60)
    ttr_min = getattr(config, "TTR_min", 0)
    park_time_min = getattr(config, "park_time_min", 0)
    park_time_max = getattr(config, "park_time_max", getattr(config, "ev_park_time_max", 0))
    wait_time_min = getattr(config, "ev_wait_time_min", 0)
    wait_time_max = getattr(config, "ev_wait_time_max", 0)

    for day in range(config.duration_days):
        for _ in range(int(num_vehicles[day])):
            bat_cap = config.car_bat_cap_min + env.rng.random() * (
                config.car_bat_cap_max - config.car_bat_cap_min
            )
            soc = soc_min + (soc_max - soc_min) * env.rng.random()

            bat_max_voltage = (
                config.bat_max_voltages[0]
                if env.rng.random() > config.bat_voltage_mix
                else config.bat_max_voltages[1]
            )
            bat_min_voltage = (
                config.bat_min_voltages[0]
                if env.rng.random() > config.bat_voltage_mix
                else config.bat_min_voltages[1]
            )

            # Notebook timing is in seconds.
            enter_delay = env.rng.random() * config.ev_enter_max_delay + day * 24 * 3600
            park_duration = park_time_min + env.rng.random() * (park_time_max - park_time_min)
            wait_duration = wait_time_min + env.rng.random() * (wait_time_max - wait_time_min)

            # Current notebook signature.
            try:
                vehicle = Vehicle(
                    v_id,
                    soc,
                    ttr_min,
                    bat_cap,
                    bat_max_voltage,
                    bat_min_voltage,
                    env,
                    enter_delay,
                    park_duration,
                    wait_duration,
                )
                env.simpy_env.process(vehicle.plug_in(charging_columns))
            except TypeError:
                # Legacy fallback.
                vehicle = Vehicle(
                    v_id,
                    soc,
                    bat_cap,
                    bat_max_voltage,
                    bat_min_voltage,
                    env,
                    enter_delay,
                    park_duration,
                )
                env.simpy_env.process(vehicle.plug_in(charging_columns, classic_charge=True))

            vehicles.append(vehicle)
            v_id += 1

    return vehicles


def _pick_first_available(df: pd.DataFrame, candidates: Iterable[str]) -> pd.Series:
    out = pd.Series(float("nan"), index=df.index, dtype="float64")
    for col in candidates:
        if col in df.columns:
            out = out.fillna(df[col])
    return out


def _extract_vehicle_results_from_logger(log_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate one row per EV from env.logger.to_df()."""
    if log_df is None or log_df.empty:
        return pd.DataFrame(columns=["EV_id", "Cost_EUR", "Energy_kWh", "Waiting_time", "Charge_duration"])

    required_cols = {"agent", "field", "value"}
    if not required_cols.issubset(log_df.columns):
        return pd.DataFrame(columns=["EV_id", "Cost_EUR", "Energy_kWh", "Waiting_time", "Charge_duration"])

    ev_log = log_df[log_df["agent"].astype(str).str.match(r"^ev_\d+$")].copy()
    if ev_log.empty:
        return pd.DataFrame(columns=["EV_id", "Cost_EUR", "Energy_kWh", "Waiting_time", "Charge_duration"])

    if "time" in ev_log.columns:
        ev_log["time"] = pd.to_numeric(ev_log["time"], errors="coerce")
    else:
        ev_log["time"] = range(len(ev_log))

    ev_log["value"] = pd.to_numeric(ev_log["value"], errors="coerce")
    ev_log = ev_log.sort_values(["agent", "field", "time"])

    last_vals = ev_log.groupby(["agent", "field"], as_index=False).last()
    wide = last_vals.pivot(index="agent", columns="field", values="value").reset_index()
    wide["EV_id"] = wide["agent"].str.extract(r"(\d+)").astype(int)

    result = pd.DataFrame({"EV_id": wide["EV_id"]})
    result["Cost_EUR"] = _pick_first_available(wide, ["total_cost", "cost", "Cost_EUR"])
    result["Energy_kWh"] = _pick_first_available(
        wide,
        ["rec_energy", "total_energy_received", "energy_received", "Energy_kWh"],
    )
    result["Waiting_time"] = _pick_first_available(
        wide,
        ["wait_time", "waiting_time", "Waiting_time"],
    )
    result["Charge_duration"] = _pick_first_available(
        wide,
        ["charge_time", "charge_duration", "Charge_duration"],
    )

    initial_soc = _pick_first_available(wide, ["initial_SoC", "initial_SoCp"])
    final_soc = _pick_first_available(wide, ["final_SoC", "final_SoCp", "SoC"])
    if result["Energy_kWh"].isna().all() and not initial_soc.isna().all() and not final_soc.isna().all():
        result["Energy_kWh"] = final_soc - initial_soc

    return result.sort_values("EV_id").reset_index(drop=True)


def _extract_vehicle_results_from_objects(vehicles) -> pd.DataFrame:
    """Fallback aggregation if logger output is unavailable."""
    records = []
    for vehicle in vehicles:
        waiting_time = pd.NA
        if hasattr(vehicle, "charger_assigned_time") and hasattr(vehicle, "enter_time"):
            if vehicle.charger_assigned_time is not None and vehicle.enter_time is not None:
                waiting_time = vehicle.charger_assigned_time - vehicle.enter_time

        energy_kwh = pd.NA
        if hasattr(vehicle, "SoC") and hasattr(vehicle, "init_SoC"):
            try:
                energy_kwh = vehicle.SoC - vehicle.init_SoC
            except Exception:
                pass

        records.append(
            {
                "EV_id": getattr(vehicle, "id", pd.NA),
                "Cost_EUR": getattr(vehicle, "cost", pd.NA),
                "Energy_kWh": energy_kwh,
                "Waiting_time": waiting_time,
                "Charge_duration": getattr(vehicle, "charge_duration", pd.NA),
            }
        )

    return pd.DataFrame.from_records(records)


def run_one_sim(job: Dict) -> pd.DataFrame:
    """
    Run one simulation job and return a pandas DataFrame.
    job: dict with keys {ev_count, seed, duration_days, config_path}
    """
    global _DATA_PROVIDER

    import simpy
    from SimPyABM.Config import load_config
    from SimPyABM.Environment import Environment
    from SimPyABM.EnergySandbox import EnergySandbox

    config = load_config(job["config_path"])
    _set_duration(config, job["duration_days"])
    if hasattr(config, "verbose"):
        config.verbose = False

    ev_count = job["ev_count"]
    config.num_vehicles_per_day_min = ev_count
    config.num_vehicles_per_day_max = int(ev_count * 1.5)
    config.random_seed = job["seed"]

    simpy_env = simpy.Environment()
    energy_sandbox = EnergySandbox(
        simpy_env,
        config.energy_grid_max_power,
        config.energy_grid_max_power_PV,
        _DATA_PROVIDER,
    )
    env = Environment(simpy_env, energy_sandbox, config)

    charging_columns = _build_charging_columns(config, env)
    strategy = getattr(config, "charging_strategy", None)
    _start_background_processes(charging_columns, env, energy_sandbox, strategy)
    vehicles = _spawn_vehicles(config, env, charging_columns)

    run_until = getattr(config, "duration", config.duration_days * 24 * 3600)
    env.simpy_env.run(until=run_until)

    for charging_column in charging_columns:
        if hasattr(charging_column, "final_logging"):
            charging_column.final_logging()

    log_df = env.logger.to_df() if hasattr(env, "logger") else pd.DataFrame()
    results_df = _extract_vehicle_results_from_logger(log_df)
    if results_df.empty:
        results_df = _extract_vehicle_results_from_objects(vehicles)

    results_df["Num_vehicles"] = ev_count
    results_df["Random_seed"] = config.random_seed
    results_df["Strategy"] = strategy

    return results_df


def main():
    config_path = "SimPyABM/config.yaml"
    duration_days = 60
    repeat_simulations = 30
    env_counts = [4, 5, 6, 7, 8, 10, 14, 16]

    jobs: List[Dict] = []
    for ev_count in env_counts:
        for i in range(repeat_simulations):
            jobs.append(
                {
                    "ev_count": ev_count,
                    "seed": 42 + i * 10,
                    "duration_days": duration_days,
                    "config_path": config_path,
                }
            )

    max_workers = min(os.cpu_count() or 1, 4)
    os.makedirs("results", exist_ok=True)

    dfs = []
    with ProcessPoolExecutor(max_workers=max_workers, initializer=_worker_init) as ex:
        for df_part in ex.map(run_one_sim, jobs, chunksize=2):
            dfs.append(df_part)

    df_all = pd.concat(dfs, ignore_index=True)
    df_all.to_csv("results/simulation_results_parallel.csv", index=False)


if __name__ == "__main__":
    main()
