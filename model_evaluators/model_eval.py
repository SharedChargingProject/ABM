#!/usr/bin/env python3
# meta_run.py  (sweep ANY list leaf anywhere, except runner keys)

import os, sys, argparse, itertools
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

import yaml
import pandas as pd
import simpy

_DP = None
_CFG_PARAMS = None


# ---------- worker init (1 DataProvider per process) ----------
def _init_worker(project_root: str, cfg_params: list[dict]):
    global _DP, _CFG_PARAMS
    sys.path.append(project_root)
    from SimPyABM.DataProvider import DataProvider
    _DP = DataProvider()
    _CFG_PARAMS = cfg_params


# ---------- config utils ----------
RUNNER_KEYS = {"base_config", "outdir", "experiment", "repetitions", "base_seed", "workers"}

def _deepcopy(obj):
    return yaml.safe_load(yaml.safe_dump(obj))

def _get_path(d, path):
    cur = d
    for k in path:
        cur = cur[k]
    return cur

def _set_path(d, path, value):
    cur = d
    for k in path[:-1]:
        if k not in cur or not isinstance(cur[k], dict):
            cur[k] = {}
        cur = cur[k]
    cur[path[-1]] = value

def _collect_list_leaves(d, prefix=()):
    out = []
    if isinstance(d, dict):
        for k, v in d.items():
            out.extend(_collect_list_leaves(v, prefix + (k,)))
    elif isinstance(d, list):
        out.append((prefix, d))
    return out

def _flatten_cfg(d, prefix=()):
    out = {}
    if isinstance(d, dict):
        for k, v in d.items():
            out.update(_flatten_cfg(v, prefix + (k,)))
    elif isinstance(d, list):
        out["__".join(prefix)] = yaml.safe_dump(d, default_flow_style=True).strip()
    else:
        out["__".join(prefix)] = d
    return out


# ---------- one simulation ----------
def _run_one(args):
    config_path, seed, outdir, run_id, cfg_i = args

    from SimPyABM.ChargingColumn import ChargingColumn
    from SimPyABM.Vehicle import Vehicle
    from SimPyABM.Environment import Environment
    from SimPyABM.EnergySandbox import EnergySandbox
    from SimPyABM.Config import load_config

    config = load_config(config_path)
    config.random_seed = int(seed)

    simpy_env = simpy.Environment()
    energy_sandbox = EnergySandbox(simpy_env, config.energy_grid_max_power, _DP)
    env = Environment(simpy_env, energy_sandbox, config.random_seed, config.start_date_time, config.verbose)

    ch_i, charging_columns = 0, []
    for _ in range(config.num_fast_chg_cols):
        charging_columns.append(
            ChargingColumn(
                ch_i, config.fast_chg_cols_ports, config.chg_cols_resolution,
                config.handshake_duration_min, config.handshake_duration_max,
                config.fast_chg_cols_power, env
            )
        ); ch_i += 1
    for _ in range(config.num_slow_chg_cols):
        charging_columns.append(
            ChargingColumn(
                ch_i, config.slow_chg_cols_ports, config.chg_cols_resolution,
                config.handshake_duration_min, config.handshake_duration_max,
                config.slow_chg_cols_power, env
            )
        ); ch_i += 1
    for cc in charging_columns:
        env.simpy_env.process(cc.main_loop(strategy=config.charging_strategy))

    num_vehicles = env.rng.integers(
        config.num_vehicles_per_day_min, config.num_vehicles_per_day_max + 1,
        size=(config.duration_days,)
    )

    v_id = 0
    for day in range(config.duration_days):
        for _ in range(int(num_vehicles[day])):
            BAT_CAP = config.car_bat_cap_min + env.rng.random() * (config.car_bat_cap_max - config.car_bat_cap_min)
            SoC = config.SoC_init_min + (config.SoC_init_max - config.SoC_init_min) * env.rng.random()
            bat_max_voltage = config.bat_max_voltages[0] if env.rng.random() > config.bat_voltage_mix else config.bat_max_voltages[1]
            bat_min_voltage = config.bat_min_voltages[0] if env.rng.random() > config.bat_voltage_mix else config.bat_min_voltages[1]
            enter_delay = env.rng.random() * config.ev_enter_max_delay + day * 24 * 3600
            park_duration = config.park_time_min + env.rng.random() * (config.park_time_max - config.park_time_min)
            wait_duration = config.ev_wait_time_min + env.rng.random() * (config.ev_wait_time_max - config.ev_wait_time_min)
            env.simpy_env.process(
                Vehicle(v_id, SoC, BAT_CAP, bat_max_voltage, bat_min_voltage, env,
                        enter_delay, park_duration, wait_duration).plug_in(charging_columns)
            )
            v_id += 1

    env.simpy_env.run(config.duration)

    
    for charging_column in charging_columns:
        charging_column.final_logging()

    df = env.logger.to_df()
    df["seed"] = int(seed)
    df["run_id"] = int(run_id)
    df["cfg_i"] = int(cfg_i)

    params = _CFG_PARAMS[cfg_i]  # FULL flattened params
    for k, v in params.items():
        df[k] = v

    p = Path(outdir) / f"run_{run_id:06d}.csv"
    df.to_csv(p, index=False)
    return str(p)


# ---------- main ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--meta", required=True)
    ap.add_argument("--keep-configs", action="store_true")   # <-- debug
    a = ap.parse_args()

    meta_path = Path(a.meta).resolve()
    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))

    base_config_path = Path(meta["base_config"]).resolve()
    outdir = Path(meta["outdir"]).resolve()
    experiment = meta["experiment"]
    reps = int(meta.get("repetitions", 1))
    base_seed = int(meta.get("base_seed", 0))
    workers = int(meta.get("workers", os.cpu_count() or 1))

    outdir.mkdir(parents=True, exist_ok=True)

    base_cfg = yaml.safe_load(base_config_path.read_text(encoding="utf-8"))

    # everything in meta except runner keys is treated as "sweep spec"
    sweep_spec = {k: v for k, v in meta.items() if k not in RUNNER_KEYS}

    # collect list leaves anywhere in sweep_spec
    list_leaves = _collect_list_leaves(sweep_spec)
    paths = [p for p, _ in list_leaves]
    value_lists = [vals for _, vals in list_leaves]

    combos = list(itertools.product(*value_lists)) if value_lists else [()]
    num_cfgs = len(combos)
    total_runs = num_cfgs * reps
    print(f"configs={num_cfgs}  repetitions={reps}  total_runs={total_runs}")

    # generate concrete configs (base + one combo applied)
    cfg_dir = outdir / f"_{experiment}_configs"
    cfg_dir.mkdir(parents=True, exist_ok=True)

    cfg_paths, cfg_params = [], []
    for i, vals in enumerate(combos):
        cfg = _deepcopy(base_cfg)
        for p, v in zip(paths, vals):
            _set_path(cfg, p, v)
        cfg_path = cfg_dir / f"cfg_{i:05d}.yaml"
        cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
        cfg_paths.append(str(cfg_path))
        cfg_params.append(_flatten_cfg(cfg))

    # expanded meta (full params per concrete config)
    expanded_meta = {
        "base_config": str(base_config_path),
        "meta_config": str(meta_path),
        "experiment": experiment,
        "repetitions": reps,
        "base_seed": base_seed,
        "workers": workers,
        "num_configs": num_cfgs,
        "total_runs": total_runs,
        "swept_paths": ["__".join(p) for p in paths],
        "configs": [{"cfg_i": i, "config_file": cfg_paths[i], "params": cfg_params[i]} for i in range(num_cfgs)],
    }
    (outdir / f"{experiment}__expanded_meta.yaml").write_text(
        yaml.safe_dump(expanded_meta, sort_keys=False),
        encoding="utf-8",
    )

    # tasks: every (config, repetition)
    tasks, run_id = [], 0
    for cfg_i, cfg_path in enumerate(cfg_paths):
        for r in range(reps):
            tasks.append((cfg_path, base_seed + r, str(outdir), run_id, cfg_i))
            run_id += 1

    project_root = str(Path(__file__).resolve().parent.parent)

    done, csvs = 0, []
    with ProcessPoolExecutor(
        max_workers=workers,
        initializer=_init_worker,
        initargs=(project_root, cfg_params),
    ) as ex:
        futs = [ex.submit(_run_one, t) for t in tasks]
        for f in as_completed(futs):
            csvs.append(f.result())
            done += 1
            print(f"{done}/{total_runs} ({100*done/total_runs:.1f}%)")

    merged = pd.concat(
        (pd.read_csv(p, dtype={"value2": "string"}, low_memory=False) for p in csvs),
        ignore_index=True
        )
    final_path = outdir / f"{experiment}.csv"
    merged.to_csv(final_path, index=False)

    for p in csvs:
        Path(p).unlink()
    if not a.keep_configs:
        for p in cfg_paths:
            Path(p).unlink()
        cfg_dir.rmdir()
    else:
        print(f"[debug] kept generated configs in: {cfg_dir}")


if __name__ == "__main__":
    main()