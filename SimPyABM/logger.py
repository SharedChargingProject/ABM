import pandas as pd

class Logger:
    def __init__(self):
        self.rows = []

    def insert(self, time, field, value, field2=None, value2=None, agent=None):
        self.rows.append({
            "time": time,
            "field": field,
            "value": value,
            "field2": field2,
            "value2": value2,
            "agent": agent,
        })

    def to_df(self):
        return pd.DataFrame(
            self.rows,
            columns=["time", "agent", "field", "value", "field2", "value2"],
        )

    def get_field1_data(self, field, agent=None, time_col=False):
        df = self.to_df()
        df = df[df["field"] == field]

        if agent is not None:
            df = df[df["agent"] == agent]

        if time_col:
            return df[["time", "value"]].values.tolist()
        else:
            return df["value"].tolist()
        
    def get_field12_data(self, agent=None, field1 = None, field2 = None, time_col=False):
        df = pd.DataFrame(self.rows)

        if agent is not None:
            df = df[df["agent"] == agent]
        if field1 is not None:
            df = df[df["field"] == field1]
        if field2 is not None:
            df = df[df["field2"] == field2]

        if time_col:
            return df[["time", "value", "value2"]].values.tolist()
        else:
            return df[["value", "value2"]].values.tolist()

