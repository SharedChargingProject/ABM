import numpy as np
import datetime

def gen_EP(seed, ts):
    """
    Generate a smooth Austrian-style energy price (in cents/kWh)
    based on UNIX timestamp using a double-peak daily model.
    """
    np.random.seed(seed + int(ts // 3600))
    
    # Convert timestamp to hour of day (0–23)
    hour = datetime.datetime.fromtimestamp(ts).hour + \
           datetime.datetime.fromtimestamp(ts).minute / 60.0

    # Base double-peak pattern (scaled to realistic cents range)
    morning_peak = np.exp(-0.8 * ((hour - 8) / 2)**2) * 10   # up to +10 c
    evening_peak = np.exp(-0.8 * ((hour - 18) / 2)**2) * 15  # up to +15 c
    base_price = 15 + morning_peak + evening_peak            # baseline 20 c

    # Add small noise
    noise = np.random.normal(0, 1.25)
    
    return base_price + noise

def gen_PEP(seed, ts, cp, duration_min):
    """
    Predict future energy price (in cents/kWh)
    based on current price, timestamp, and forecast duration in minutes.
    """
    np.random.seed(seed+int(ts // 3600))

    # Convert minutes to seconds for timestamp shift
    future_ts = ts + duration_min * 60.0

    # Model-based expected price at that future time
    future_price = gen_EP(seed, future_ts)

    # Add prediction error
    prediction_error = np.random.normal(-0.05*future_price, 0.05*future_price)  # 10% error

    predicted_price = future_price + prediction_error

    return predicted_price

def gen_PVShare(seed, ts):
    """
    Generate realistic PV share (0–1) for a given timestamp.
    """
    np.random.seed(seed + int(ts // 3600))  # stable hourly variability
    
    # Convert timestamp to hour of day (0–23)
    hour = datetime.datetime.fromtimestamp(ts).hour + \
           datetime.datetime.fromtimestamp(ts).minute / 60.0

    # Gaussian-shaped daylight curve (peak around noon)
    base_pv = np.exp(-0.5 * ((hour - 12) / 3)**2)
    base_pv = np.clip(base_pv, 0, 1)

    # Apply day-level cloudiness factor and small local noise
    cloud_factor = np.random.uniform(0.7, 1.0)      # cloudy to sunny
    noise = np.random.normal(0, 0.05)               # small local noise
    
    pv_share = np.clip(base_pv * cloud_factor + noise, 0, 1)
    
    return pv_share

def gen_PVShareP(seed, ts, cPVShare, duration_min):
    """
    Predict future PV share (0–1)
    based on current PV share, timestamp, and forecast duration in minutes.
    """
    np.random.seed(seed+int(ts // 3600))

    # Convert minutes to seconds for timestamp shift
    future_ts = ts + duration_min * 60.0

    # Model-based expected PV share at that future time
    future_PVShare = gen_PVShare(seed, future_ts)

    # Add prediction error
    prediction_error = np.random.normal(-0.05*future_PVShare, 0.05*future_PVShare)  # 10% error

    predicted_PVShare = future_PVShare + prediction_error

    return predicted_PVShare

