import simpy

class EnergySandbox:
    def __init__(self, env, Grid_max_power, PV_max_power, data_provider):
        self.env = env
        self.Grid_max_power = Grid_max_power
        self.PV_max_power = PV_max_power
        self.data_provider = data_provider

        self.current_pv_power = self.PV_max_power

        # Container level = currently free total power
        # Capacity = maximum possible total power
        self.power = simpy.Container(
            self.env,
            capacity=self.Grid_max_power + self.PV_max_power,
            init=self.Grid_max_power + self.current_pv_power
        )

    def current_total_capacity(self):
        return self.Grid_max_power + self.current_pv_power

    def current_total_used(self):
        return self.current_total_capacity() - self.power.level

    def current_pv_used(self):
        return min(self.current_total_used(), self.current_pv_power)

    def current_grid_used(self):
        return max(0.0, self.current_total_used() - self.current_pv_power)

    def pv_power_adjustment_process(self, env):
        while True:
            current_time = env.now()
            pv_ratio = self.data_provider.getPVRatio_unix(current_time)
            new_pv_power = self.PV_max_power * pv_ratio

            delta = new_pv_power - self.current_pv_power

            if delta > 0:
                # PV availability increases, so free total capacity increases
                yield self.power.put(delta)

            elif delta < 0:
                # PV availability decreases, so free total capacity decreases
                reduction = -delta

                if reduction > self.power.level + 1e-6:
                    raise RuntimeError(
                        "PV reduction cannot be covered by free power. "
                        "Reserved power exceeds Grid + current PV capacity."
                    )

                yield self.power.get(reduction)

            self.current_pv_power = new_pv_power

            self.log_power_output(env)
            yield self.env.timeout(60 * 15)

    def request_power(self, env, p_kw: float):
        """
        Block until p_kw is available, then reserve it.

        Interrupt-safe:
        if EV leaves while waiting, pending get is removed.
        if power was already granted before interrupt, it is returned.
        """
        self.log_power_output(env)

        get_evt = self.power.get(p_kw)
        granted = False

        try:
            yield get_evt
            granted = True

        except simpy.Interrupt:
            if not get_evt.triggered:
                try:
                    self.power.get_queue.remove(get_evt)
                except ValueError:
                    pass
            else:
                granted = True

            if granted:
                yield self.power.put(p_kw)

            self.log_power_output(env)
            return False

        self.log_power_output(env)
        return True

    def release_power(self, env, p_kw: float):
        """Return reserved power."""
        self.log_power_output(env)

        free_room = self.current_total_capacity() - self.power.level
        releaseable = min(p_kw, free_room)

        if releaseable > 1e-6:
            yield self.power.put(releaseable)

        remaining = p_kw - releaseable
        if remaining > 1e-6:
            env.log(f"WARNING: release_power could not return {remaining:.3f} kW")

        self.log_power_output(env)

    def log_power_output(self, env):
        grid_used = self.current_grid_used()
        pv_used = self.current_pv_used()
        total_used = grid_used + pv_used

        env.logger.insert(env.now(), agent="energy_sandbox", field="power_output_grid_kW", value=grid_used)
        env.logger.insert(env.now(), agent="energy_sandbox", field="power_output_PV_kW", value=pv_used)
        env.logger.insert(env.now(), agent="energy_sandbox", field="power_output_kW", value=total_used)
        env.logger.insert(env.now(), agent="energy_sandbox", field="current_pv_power_kW", value=self.current_pv_power)

    def getEnergyPrice(self, timestamp):
        return self.data_provider.getEnergyPrice_unix(timestamp) * 0.001