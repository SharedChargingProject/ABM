import numpy as np
import simpy
class ChargingColumn(simpy.Resource):
    def __init__(self, id, n_ports, resolution, handshake_duration_sec_min, handshake_duration_sec_max, power, env):
        super().__init__(env.simpy_env, n_ports)
        self.id = id
        self.resolution = resolution # charge time resolution in minutes (adjusts price at the beginning of each window)
        self.handshake_duration_sec_min = handshake_duration_sec_min
        self.handshake_duration_sec_max = handshake_duration_sec_max
        self.power = power
        self.current_consumption = 0
        self.env = env
        self.total_energy_delivered = 0
        self.total_cost = 0 # electricity sold out
        self.active_ev = None
        self.active_req = None
        self.arrival_event = self.env.simpy_env.event()

        # logging
        self.log_handshake_duration = 0
        self.log_charge_duration = 0
        self.longest_charge_duration = 0


    def connected_evs(self):
        return [req.ev for req in self.users]
    
    def handle_handshake(self,req):
        tic = self.env.now()
        if req.handshake is False:
            self.break_handshakes() # break handshakes with other EVs to ensure only one handshake at a time
            self.handshake_duration_sec = self.env.rng.uniform(self.handshake_duration_sec_min, self.handshake_duration_sec_max)
            yield self.env.simpy_env.timeout(self.handshake_duration_sec) | req.ev.request_disconnect # simulate handshake duration, but if EV requests disconnect during handshake, break immediately
            if req.ev.request_disconnect.triggered:
                req.ev.request_disconnect_approved.succeed() # approve disconnect request from EV
                self.env.log(f'EV {req.ev.id} requested disconnect during handshake at ChargingColumn {self.id}, waiting for next EV...')
                toc = self.env.now()
                self.log_handshake_duration += toc - tic
                return
            req.handshake = True
            self.env.log(f'Handshake completed between EV {req.ev.id} and ChargingColumn {self.id}.')
        yield self.env.simpy_env.timeout(0) # no delay
        toc = self.env.now()
        self.log_handshake_duration += toc - tic

    def break_handshakes(self):
        if self.current_consumption > 0:
            # release power back to energy sandbox if there is an ongoing charge
            self.env.simpy_env.process(self.env.energy_sandbox.release_power(self.env, self.current_consumption)) # release power back to energy sandbox after charge window
            self.current_consumption = 0
        for req in self.users:
            if req.handshake is True:
                req.handshake = False

    def FCFS_charging_loop(self):
        while True:
            if self.active_ev is None:
                if len(self.users) == 0:
                    # self.env.log(f'ChargingColumn {self.id} has no connected EVs, waiting for arrivals...')
                    yield self.arrival_event # reset by the EV
                    continue
                # FCFS
                req = None
                earliest_time = float('inf')
                for req_ in self.users:
                    if req_.assign_time < earliest_time and req_.ev.request_disconnect_approved.triggered is False:
                        req = req_
                        earliest_time = req_.assign_time
                
                if req is None:
                    # self.env.log(f'ChargingColumn {self.id} has no active EVs to charge, waiting...')
                    yield self.env.simpy_env.timeout(60) # wait 60 seconds TODO: can be more efficient by waiting for an event instead of timeout?
                    continue

                self.active_ev = req.ev
                self.active_req = req
                yield self.env.simpy_env.process(self.handle_handshake(req))
                # check if handshake was completed and EV is still connected
                if req.handshake is False:
                    # handshake was not completed, likely due to disconnect request during handshake
                    yield self.env.simpy_env.timeout(60) # wait 60 seconds
                    continue # skip to next EV

                # log start of charging
                self.env.logger.insert(self.env.now(), agent=f"ev_{self.active_ev.id}", field="SoC", value=self.active_ev.SoC, field2="charger_id", value2=self.id)
                self.env.logger.insert(self.env.now(), agent=f"ev_{self.active_ev.id}", field="SoCp", value=self.active_ev.get_SoC_percentage(), field2="charger_id", value2=self.id)
                self.env.logger.insert(self.env.now(), agent=f"ev_{self.active_ev.id}", field="SoC", value=self.active_ev.SoC, field2="capacity", value2=self.active_ev.Capacity_kWh)

            while self.active_ev.request_disconnect_approved.triggered is False:
                power = self.active_ev.max_accepting_power(self.power)
                if power <= 0:
                    self.active_ev.charge_cmpt_event.succeed()
                    self.active_ev.request_disconnect_approved.succeed() # approve disconnect request from EV
                    break # break charging loop

                max_energy = power * self.resolution / 3600 # limited to one charge window [kWh]
                max_energy = min(self.active_ev.get_max_energy_required(),max_energy) # maximum energy delivery should not exceed the required energy by EV
                if max_energy <= 0:
                    self.active_ev.charge_cmpt_event.succeed()
                    self.active_ev.request_disconnect_approved.succeed() # approve disconnect request from EV
                    break # break charging loop
                
                # request the missing power
                required_power = power - self.current_consumption
                if required_power > 0:
                    power_proc = self.env.simpy_env.process(
                        self.env.energy_sandbox.request_power(self.env, required_power)
                    )

                    res = yield power_proc | self.active_ev.request_disconnect

                    if self.active_ev.request_disconnect in res:
                        if not self.active_ev.request_disconnect_approved.triggered:
                            self.active_ev.request_disconnect_approved.succeed()

                        # If power request is still pending, CANCEL it so it can't allocate later
                        if not power_proc.triggered:
                            power_proc.interrupt("ev_disconnected")

                        # If it *already* granted at the same sim time, release it
                        if power_proc in res:
                            self.env.simpy_env.process(
                                self.env.energy_sandbox.release_power(self.env, required_power)
                            )
                        break  # (or continue in SHRD)

                    # else: power granted
                    self.current_consumption += required_power

                duration = (max_energy / power) * 3600  # duration in seconds

                start_time = self.env.now()
                yield self.env.simpy_env.timeout(duration) | self.active_ev.request_disconnect # wait until charge window is over or EV requests disconnect
                end_time = self.env.now()
                actual_duration = end_time - start_time
                self.log_charge_duration += actual_duration
                if actual_duration > self.longest_charge_duration:
                    self.longest_charge_duration = actual_duration
                delivered_energy = (actual_duration / 3600) * power # actual delivered energy based on time and power
                self.total_energy_delivered += delivered_energy # kWh used in this charge window
                cost_w = delivered_energy * self.env.energy_sandbox.getEnergyPrice(self.env.now()) # cost in EUR for this charge window
                self.total_cost += cost_w
                self.active_ev._rec_energy(delivered_energy)
                self.active_ev._add_cost(cost_w)
                self.active_ev.actual_charge_time += actual_duration # for logging: time spent receiving energy (excluding waiting time)
                if self.active_ev.request_disconnect.triggered:
                    self.env.log(f'EV {self.active_ev.id} requested disconnect during charging at ChargingColumn {self.id}, waiting for approval...')
                    self.active_ev.request_disconnect_approved.succeed() # approve disconnect request from EV
                    break # break the charging loop
            self.break_handshakes()
            self.active_ev = None
            self.active_req = None

    def shared_charging_loop(self):
        # EVs get charged in turns
        while True:
            if len(self.users) == 0:
                yield self.arrival_event # reset by the EV
                continue
            reqs = [req for req in self.users if req.ev.request_disconnect_approved.triggered is False]
            if len(reqs) == 0:
                # self.env.log(f'ChargingColumn {self.id} has no active EVs to charge, waiting...')
                yield self.env.simpy_env.timeout(60) # wait 60 seconds TODO: wait for arrival event instead of timeout?
                continue
            else:    
                self.active_req = reqs[0]
                for req in reqs:
                    if req.last_charge_time < self.active_req.last_charge_time:
                        self.active_req = req
                self.active_req.last_charge_time = self.env.now()
                self.active_ev = self.active_req.ev
                yield self.env.simpy_env.process(self.handle_handshake(self.active_req))
                # check if EV is still connected after handshake
                if self.active_req.handshake is False:
                    # request is already approved for disconnect
                    yield self.env.simpy_env.timeout(60) # wait 60 seconds
                    continue # skip to next EV

                power = self.active_ev.max_accepting_power(self.power)
                if power <= 0:
                    self.active_ev.charge_cmpt_event.succeed()
                    self.active_ev.request_disconnect_approved.succeed() # approve disconnect request from EV
                    continue # skip if no power can be delivered

                max_energy = power * self.resolution / 3600 # limited to one charge window [kWh]
                max_energy = min(self.active_ev.get_max_energy_required(),max_energy) # maximum energy delivery should not exceed the required energy by EV
                
                if max_energy <= 0:
                    self.active_ev.charge_cmpt_event.succeed()
                    self.active_ev.request_disconnect_approved.succeed() # approve disconnect request from EV
                    continue # skip if no energy is required

                # request the missing power
                required_power = power - self.current_consumption
                if required_power > 0:
                    power_proc = self.env.simpy_env.process(
                        self.env.energy_sandbox.request_power(self.env, required_power)
                    )
                    res = yield power_proc | self.active_ev.request_disconnect

                    if self.active_ev.request_disconnect in res:
                        if not self.active_ev.request_disconnect_approved.triggered:
                            self.active_ev.request_disconnect_approved.succeed()

                        # cancel pending grid get so it can't allocate later
                        if not power_proc.triggered:
                            power_proc.interrupt("disconnect")

                        # if it granted at same sim time, put it back
                        if power_proc in res:
                            self.env.simpy_env.process(
                                self.env.energy_sandbox.release_power(self.env, required_power)
                            )

                        yield self.env.simpy_env.timeout(60)
                        continue  # skip to next EV

                    # else, power is granted
                    self.current_consumption += required_power
                
                duration = (max_energy / power) * 3600  # duration in seconds
                
                start_time = self.env.now()
                yield self.env.simpy_env.timeout(duration) | self.active_ev.request_disconnect # wait until charge window is over or EV requests disconnect
                end_time = self.env.now()
                actual_duration = end_time - start_time
                self.log_charge_duration += actual_duration
                if actual_duration > self.longest_charge_duration:
                    self.longest_charge_duration = actual_duration
                delivered_energy = (actual_duration / 3600) * power # actual delivered energy based on time and power
                self.total_energy_delivered += delivered_energy # kWh used in this charge window
                cost_w = delivered_energy * self.env.energy_sandbox.getEnergyPrice(self.env.now()) # cost in EUR for this charge window
                self.total_cost += cost_w
                self.active_ev._rec_energy(delivered_energy)
                self.active_ev._add_cost(cost_w)
                self.active_ev.actual_charge_time += actual_duration # for logging: time spent receiving energy (excluding waiting time)
                if self.active_ev.get_max_energy_required() <= 0.1: # TODO: 0.1 is a small threshold to account for floating point precision issues, can be adjusted
                    # if EV needs no more energy, then break the handshake
                    self.active_ev.charge_cmpt_event.succeed()
                    self.break_handshakes()
                    self.active_ev.request_disconnect_approved.succeed() # approve disconnect request from EV
                elif self.active_ev.request_disconnect.triggered:
                    self.env.log(f'EV {self.active_ev.id} requested disconnect during charging at ChargingColumn {self.id}, waiting for approval...')
                    self.break_handshakes()
                    self.active_ev.request_disconnect_approved.succeed() # approve disconnect request from EV
    def final_logging(self):
        # log total energy delivered and total cost for this charging column
        self.env.logger.insert(self.env.now(), agent=f"charging_column_{self.id}", field="total_energy_delivered_kWh", value=self.total_energy_delivered)
        self.env.logger.insert(self.env.now(), agent=f"charging_column_{self.id}", field="total_cost_EUR", value=self.total_cost)
        self.env.logger.insert(self.env.now(), agent=f"charging_column_{self.id}", field="log_handshake_duration_sec", value=self.log_handshake_duration)
        self.env.logger.insert(self.env.now(), agent=f"charging_column_{self.id}", field="log_charge_duration_sec", value=self.log_charge_duration)
        self.env.logger.insert(self.env.now(), agent=f"charging_column_{self.id}", field="longest_charge_duration_sec", value=self.longest_charge_duration)
    def main_loop(self, strategy="FCFS"):
        if strategy == "FCFS":
            return self.FCFS_charging_loop()
        elif strategy == "SHRD":
            return self.shared_charging_loop()
        else:
            raise ValueError(f"Unknown charging strategy: {strategy}")