import simpy

class EnergySandbox():
    def __init__(self, env, max_power, data_provider):
        self.env = env
        self.max_power = max_power # in kW
        self.power_grid = simpy.Container(self.env, capacity=self.max_power, init=self.max_power) # represents the available power from the grid at any time
        self.data_provider = data_provider
        
    def getEnergyPrice(self, timestamp):
        return self.data_provider.getEnergyPrice_unix(timestamp) * 0.001 # MWh to kWh
        
    def log_available_power(self,env):
        env.logger.insert(env.now(), agent="energy_sandbox", field="available_power", value=self.power_grid.level, )

    def log_power_output(self,env):
        amount_kW = self.max_power - self.power_grid.level
        env.logger.insert(env.now(), agent="energy_sandbox", field="power_output_kW", value=amount_kW)
    
    def request_power(self, env, p_kw: float):
        """Block until p_kw is available, then reserve it."""
        self.log_available_power(env)
        self.log_power_output(env)

        get_evt = self.power_grid.get(p_kw)
        try:
            yield get_evt
        except simpy.Interrupt:
            # If still pending, remove it from the container's queue.
            if not get_evt.triggered:
                try:
                    self.power_grid.get_queue.remove(get_evt)
                except ValueError:
                    pass  # already removed by SimPy
            else:
                # It already succeeded (same sim time race) -> rollback
                self.power_grid.put(p_kw)

            self.log_available_power(env)
            self.log_power_output(env)
            return

        self.log_available_power(env)
        self.log_power_output(env)

    def release_power(self, env, p_kw: float):
        """Return reserved power."""
        self.log_available_power(env)
        self.log_power_output(env)
        yield self.power_grid.put(p_kw)
        self.log_available_power(env)
        self.log_power_output(env)