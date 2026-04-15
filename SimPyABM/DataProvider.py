import pandas as pd
from pathlib import Path
class DataProvider:
    def __init__(self):
        BASE_DIR = Path(__file__).resolve().parent
        GRIDDATA_DIR = BASE_DIR.parent / "GridData"

        self.energy_price_data = pd.read_csv(
            GRIDDATA_DIR / "GridData.csv",
            parse_dates=["Time"]
        ).set_index("Time").sort_index()

        self.PVRatio_data = pd.read_csv(
            GRIDDATA_DIR / "PVRatioData.csv",
            parse_dates=["Time"]
        ).set_index("Time").sort_index()
        
    def getEnergyPrice(self,timestamp):
        df = self.energy_price_data

        # Ensure timestamp is a pandas Timestamp (and same tz handling if applicable)
        timestamp = pd.Timestamp(timestamp)

        # 1) Exact match
        if timestamp in df.index:
            return df.loc[timestamp, "Price"] if pd.api.types.is_scalar(df.loc[timestamp, "Price"]) \
                else df.loc[timestamp, "Price"].iloc[0]

        # 2) Neighbors for interpolation
        before = df.loc[:timestamp].tail(1)
        after  = df.loc[timestamp:].head(1)

        if before.empty or after.empty:
            return None

        before_time = before.index[0]
        after_time  = after.index[0]
        before_price = float(before["Price"].iloc[0])
        after_price  = float(after["Price"].iloc[0])

        total_diff = (after_time - before_time).total_seconds()
        if total_diff == 0:
            return before_price  # same timestamp duplicated / zero interval

        timestamp_diff = (timestamp - before_time).total_seconds()

        return before_price + (after_price - before_price) * (timestamp_diff / total_diff)

    def getEnergyPrice_unix(self, unix_timestamp: int):
        # convert unix timestamp to pd.Timestamp with timezone awareness
        timestamp = pd.to_datetime(unix_timestamp, unit="s", utc=True)
        timestamp = timestamp.tz_convert("Europe/Vienna")
        return self.getEnergyPrice(timestamp)
    
    def getPVRatio(self, timestamp):
        df = self.PVRatio_data

        # Ensure timestamp is a pandas Timestamp (and same tz handling if applicable)
        timestamp = pd.Timestamp(timestamp)

        # 1) Exact match
        if timestamp in df.index:
            return df.loc[timestamp, "Solar_Ratio"] if pd.api.types.is_scalar(df.loc[timestamp, "Solar_Ratio"]) \
                else df.loc[timestamp, "Solar_Ratio"].iloc[0]
        # 2) Neighbors for interpolation
        before = df.loc[:timestamp].tail(1)
        after  = df.loc[timestamp:].head(1)
        if before.empty or after.empty:
            return None
        before_time = before.index[0]
        after_time  = after.index[0]
        before_ratio = float(before["Solar_Ratio"].iloc[0])
        after_ratio  = float(after["Solar_Ratio"].iloc[0])
        total_diff = (after_time - before_time).total_seconds()
        if total_diff == 0:
            return before_ratio  # same timestamp duplicated / zero interval
        timestamp_diff = (timestamp - before_time).total_seconds()
        return before_ratio + (after_ratio - before_ratio) * (timestamp_diff / total_diff)
    
    def getPVRatio_unix(self, unix_timestamp: int):
        # convert unix timestamp to pd.Timestamp with timezone awareness
        timestamp = pd.to_datetime(unix_timestamp, unit="s", utc=True)
        timestamp = timestamp.tz_convert("Europe/Vienna")
        return self.getPVRatio(timestamp)