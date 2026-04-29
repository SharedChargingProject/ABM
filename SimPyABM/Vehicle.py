import numpy as np
from datetime import datetime
from zoneinfo import ZoneInfo

class Vehicle():
    def __init__(self, id, SoC, TTR_min, Capacity_kWh, bat_max_voltage, bat_min_voltage, env, enter_delay, park_time, wait_time):
        self.id = id
        SoC = SoC * Capacity_kWh  # convert to kWh
        self.TTR_min = TTR_min # minimum energy to be delivered to the vehicle (kWh)
        self.init_SoC = SoC
        self.SoC = SoC
        self.Capacity_kWh = Capacity_kWh
        self.bat_max_voltage = bat_max_voltage
        self.bat_min_voltage = bat_min_voltage
        self.env = env
        self.charging_column = None
        self.charging_column_req = None
        self.cost = 0
        self.rec_energy = 0
        self.enter_delay = enter_delay
        self.enter_time = env.now() + self.enter_delay
        self.park_end = self.enter_time + park_time
        self.wait_time = wait_time
        self.wait_end = self.enter_time + wait_time
        self.charging_column_assigned_time = -1
        self.request_disconnect = self.env.simpy_env.event() # signal for charging column to disconnect
        self.request_disconnect_approved = self.env.simpy_env.event() # signal from charging column that disconnection is approved
        self.actual_wait_time = 0
        self.actual_charge_time = 0 # time spent actually charging (receiving energy)
        self.total_charge_time = 0 # time spent connected to charger (including waiting for energy)
        self.env.logger.insert(self.enter_time, agent=f"ev_{self.id}", field="initial_SoC", value=self.SoC, field2="charger_id", value2=-1)
        self.env.logger.insert(self.enter_time, agent=f"ev_{self.id}", field="initial_SoCp", value=self.get_SoC_percentage(), field2="charger_id", value2=-1)
        self.env.logger.insert(self.enter_time, agent=f"ev_{self.id}", field="SoC", value=self.SoC, field2="charger_id", value2=-1)
        self.env.logger.insert(self.enter_time, agent=f"ev_{self.id}", field="SoCp", value=self.get_SoC_percentage(), field2="charger_id", value2=-1)
        self.env.logger.insert(self.enter_time, agent=f"ev_{self.id}", field="SoC", value=self.SoC, field2="capacity", value2=self.Capacity_kWh)

    def plug_in(self, charging_columns):
        if self.enter_delay>0:
            self.env.log(f'EV {self.id} arrival is scheduled in {self.enter_delay/60:.1f} minute(s)...')
            yield self.env.simpy_env.timeout(self.enter_delay)

        self.env.log(f'EV {self.id} is looking for a charging_column ...')
        # Wait until at least one charging_column has free capacity, then pick the best one.
        while True:
            # compute free capacity for each charging_column
            free_ports = [c.capacity - c.count for c in charging_columns]
            max_free = max(free_ports)
            if max_free > 0:
                # pick among the best
                candidates = [c for c in charging_columns if (c.capacity - c.count) == max_free]
                self.charging_column = self.env.rng.choice(candidates)
                self.charging_column_assigned_time = self.env.now()
                self.actual_wait_time = self.env.now() - self.enter_time
                break
            # else:
            # no charging_column available: wait maximum of 1 second and try again
            yield self.env.simpy_env.timeout(min((self.wait_end - self.env.now()), 1))
            if self.wait_end <= self.env.now():
                self.env.log(f'EV {self.id} faild to get a charging_column and left. [waited for {self.wait_time/60} minutes]')
                self.actual_wait_time = self.env.now() - self.enter_time
                self.log_final_status()
                return
        
        self.charging_column_req = self.charging_column.request()
        self.charging_column_req.ev = self
        self.charging_column_req.assign_time = self.charging_column_assigned_time
        self.charging_column_req.handshake = False
        self.charging_column_req.last_charge_time = self.env.now()
        result = yield self.charging_column_req | self.env.simpy_env.timeout((self.wait_end - self.env.now()))

        # check if the charging_column was acquired
        if self.charging_column_req not in result:
            # cancel pending request so it does not stay in the charger queue
            self.charging_column.release(self.charging_column_req)
            # timeout occurred before acquiring the charging_column
            self.env.log(f'EV {self.id} could not acquire charging_column {self.charging_column.id} in time and left. [waited for {self.wait_time/60} minutes]')
            self.log_final_status()
            return
        
        self.charging_column.arrival_event.succeed()  # notify the charging_column that a new EV has arrived
        self.charging_column.arrival_event = self.env.simpy_env.event()  # reset for next arrival

        # self.env.logger.insert(self.env.now(), agent=f"ev_{self.id}", field="CC_connected", value=self.env.now(), field2="charger_id", value2=self.charging_column.id)
        self.env.log(f'EV {self.id} is connected to charging_column {self.charging_column.id}.')

        # Vehicle does not start charging, just waits until park time is over or charge is complete (signal from charging column)

        self.charge_cmpt_event = self.env.simpy_env.event()
        
        yield self.charge_cmpt_event | self.env.simpy_env.timeout(self.park_end - self.env.now())

        self.total_charge_time = self.env.now() - self.charging_column_assigned_time       
        self.env.log(f'EV {self.id}: charging duration {self.total_charge_time/60:.2f} minutes. Enter time: {self.env.unix_to_dt(self.enter_time)}, park end: {self.env.unix_to_dt(self.park_end)}, charging_column assigned time: {self.env.unix_to_dt(self.charging_column_assigned_time)}.')
        
        if self.charge_cmpt_event.triggered == False:
            self.env.log(f'EV {self.id}: charging ended before completion (SoC: {self.get_SoC_percentage()}%)')
        else:
            self.env.log(f'EV {self.id}: charging completed.')
        self.log_final_status()
        # stay to end
        if self.park_end >= self.env.now():
            yield self.env.simpy_env.timeout(self.park_end - self.env.now())

        yield self.env.simpy_env.process(self.unplug())

    def is_connected(self):
        return self.charging_column is not None
    
    def unplug(self):
        if self.charging_column is None:
            self.env.log("Warning: EV is not connected to any charging_column!")
            yield self.env.simpy_env.timeout(0)
            return
        else:
            self.request_disconnect.succeed() # signal to charging column that EV wants to disconnect
            yield self.request_disconnect_approved # wait for charging column to approve disconnection
            self.charging_column.release(self.charging_column_req)
            self.env.log(f'EV {self.id} just released charging_column {self.charging_column.id} and left.')
            # self.env.logger.insert(self.env.now(), agent=f"ev_{self.id}", field="leaving", value=self.env.now())
            self.charging_column_req = None
            self.charging_column = None

    def _rec_energy(self,amount_KWh):
        # self.env.logger.insert(self.env.now(), agent=f"ev_{self.id}", field="SoC", value=self.SoC, field2="charger_id", value2=self.charging_column.id)
        # self.env.logger.insert(self.env.now(), agent=f"ev_{self.id}", field="SoCp", value=self.get_SoC_percentage(), field2="charger_id", value2=self.charging_column.id)
        # self.env.logger.insert(self.env.now(), agent=f"ev_{self.id}", field="SoC", value=self.SoC, field2="capacity", value2=self.Capacity_kWh)
        self.SoC += amount_KWh
        self.env.logger.insert(self.env.now(), agent=f"ev_{self.id}", field="SoC", value=self.SoC, field2="charger_id", value2=self.charging_column.id)
        self.env.logger.insert(self.env.now(), agent=f"ev_{self.id}", field="SoCp", value=self.get_SoC_percentage(), field2="charger_id", value2=self.charging_column.id)
        self.env.logger.insert(self.env.now(), agent=f"ev_{self.id}", field="SoC", value=self.SoC, field2="capacity", value2=self.Capacity_kWh)
        # self.env.logger.insert(self.env.now(), agent=f"ev_{self.id}", field="rec_energy", value=self.rec_energy, field2="capacity", value2=self.Capacity_kWh)
        self.rec_energy += amount_KWh
        self.env.logger.insert(self.env.now(), agent=f"ev_{self.id}", field="rec_energy", value=self.rec_energy, field2="capacity", value2=self.Capacity_kWh)

    def _add_cost(self, amount_EUR):
        self.cost += amount_EUR

    def get_SoC_percentage(self):
        return round((self.SoC / self.Capacity_kWh) * 100,2)
    
    def get_max_energy_required(self):
        return self.Capacity_kWh - self.SoC
    
    def max_accepting_power(self, available_power):
        return available_power # TODO: adjust based on vehicle characteristics
    
    # CC/CV (Constant Current/Constant Voltage) charging
    def cPower(self, soc, available_power, ev):
        v_min = ev.bat_min_voltage
        v_max = ev.bat_max_voltage
        i_cc = available_power * 1000 / v_max
        i_cutoff = 3 # TODO: adjust if needed (SAL)
        soc_trans = 0.95
        B = 15 # TODO: adjust if needed (SAL)
        """CC-CV charging power function"""
        soc = np.atleast_1d(soc)
        cc = soc < soc_trans
        v = v_min + (v_max - v_min) * (soc / soc_trans)
        i = i_cutoff + (i_cc - i_cutoff) * np.exp(-B * (soc - soc_trans))
        return np.where(cc, i_cc * v, v_max * i)[0]/1000 # /1000 Wh -> kWh
    
    def log_final_status(self):
        # final SoC and charging status
        if self.SoC >= self.Capacity_kWh:
            status = "complete"
        elif self.env.now() >= self.park_end:
            status = "partial"
        else:
            status = "unserved"
        self.env.logger.insert(self.env.now(), agent=f"ev_{self.id}", field="final_status", value=status)
        self.env.logger.insert(self.env.now(), agent=f"ev_{self.id}", field="final_SoC", value=self.SoC, field2="final_status", value2=status)
        self.env.logger.insert(self.env.now(), agent=f"ev_{self.id}", field="final_SoCp", value=self.get_SoC_percentage())
        # final wait time
        self.env.logger.insert(self.env.now(), agent=f"ev_{self.id}", field="wait_time", value=self.actual_wait_time, field2="max_wait_time", value2=self.wait_time)
        # final charge time
        self.env.logger.insert(self.env.now(), agent=f"ev_{self.id}", field="charge_time", value=self.total_charge_time, field2="actual_charge_time", value2=self.actual_charge_time)
        # cost and received energy
        self.env.logger.insert(self.env.now(), agent=f"ev_{self.id}", field="total_cost", value=self.cost)
        self.env.logger.insert(self.env.now(), agent=f"ev_{self.id}", field="total_energy_received", value=self.rec_energy if self.rec_energy > 0 else 0)

