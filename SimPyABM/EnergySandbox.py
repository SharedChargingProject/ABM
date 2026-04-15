import simpy

class EnergySandbox():
    def __init__(self, env, Grid_max_power, PV_max_power, data_provider):
        self.env = env
        self.Grid_max_power = Grid_max_power # in kW
        self.PV_max_power = PV_max_power # in kW
        self.power_PV = simpy.Container(self.env, capacity=self.PV_max_power, init=self.PV_max_power) # represents the available power from the PV at any time
        self.power_grid = simpy.Container(self.env, capacity=self.Grid_max_power, init=self.Grid_max_power) # represents the available power from the grid at any time
        self.data_provider = data_provider
        self.current_pv_power = self.PV_max_power

    def pv_power_adjustment_process(self, env):
        while True:
            # Adjust PV power based on the current time and PV ratio
            current_time = env.now()
            pv_ratio = self.data_provider.getPVRatio_unix(current_time)
            new_pv_power = self.PV_max_power * pv_ratio
            self.current_pv_power = new_pv_power

            # log the current power output
            self.log_power_output(env)
            yield self.env.timeout(60*15) # adjust every 15 minutes
        
    def getEnergyPrice(self, timestamp):
        return self.data_provider.getEnergyPrice_unix(timestamp) * 0.001 # MWh to kWh
        
    def log_available_power(self,env):
        env.logger.insert(env.now(), agent="energy_sandbox", field="available_power", value=self.power_grid.level, )

    def log_power_output(self,env):
        amount_kW = self.Grid_max_power - self.power_grid.level
        env.logger.insert(env.now(), agent="energy_sandbox", field="power_output_grid_kW", value=amount_kW)
        # total power output is just from grid
        env.logger.insert(env.now(), agent="energy_sandbox", field="power_output_kW", value=amount_kW)
        # currently available PV
        env.logger.insert(env.now(), agent="energy_sandbox", field="current_pv_power_kW", value=self.current_pv_power)
    
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