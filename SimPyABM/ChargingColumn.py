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

        # L: local CC load timeline = number of EVs selecting each slot
        self.L = np.zeros(self.env.n_slots, dtype=int)

    def add_ev_slots_to_L(self, slots):
        for k in slots:
            if 0 <= k < self.env.n_slots:
                self.L[k] += 1

    def remove_ev_slots_from_L(self, slots):
        for k in slots:
            if 0 <= k < self.env.n_slots:
                self.L[k] = max(0, self.L[k] - 1)
    
    def S(self, selected_slots, k):
        """
        Scatter penalty for choosing slot k.
        Lower is better.
        - isolated slot -> 1.0
        - one adjacent selected slot -> 0.5
        - two adjacent selected slots -> 0.25
        """
        left = 1 if (k - 1) in selected_slots else 0
        right = 1 if (k + 1) in selected_slots else 0
        adjacency = left + right
        return 1.0 / (1 + adjacency)

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
                # self.env.logger.insert(self.env.now(), agent=f"ev_{self.active_ev.id}", field="SoC", value=self.active_ev.SoC, field2="charger_id", value2=self.id)
                # self.env.logger.insert(self.env.now(), agent=f"ev_{self.active_ev.id}", field="SoCp", value=self.active_ev.get_SoC_percentage(), field2="charger_id", value2=self.id)
                # self.env.logger.insert(self.env.now(), agent=f"ev_{self.active_ev.id}", field="SoC", value=self.active_ev.SoC, field2="capacity", value2=self.active_ev.Capacity_kWh)

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

                    # else, power is granted?
                    granted = (power_proc in res) and bool(power_proc.value)
                    if not granted:
                        self._go_idle(break_handshakes=True)
                        continue
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
    
    def select_required_slots(self, ev):
        eps = 1e-9

        max_lookahead_slots = int(np.ceil(
            self.env.config.SWRM_look_ahead_time / self.env.slot_sec
        ))

        a_pv = self.env.config.SWRM_a_pv
        a_price = self.env.config.SWRM_a_price
        a_grid = self.env.config.SWRM_a_grid
        a_ramp = self.env.config.SWRM_a_ramp
        a_scatter = self.env.config.SWRM_a_scatter
        a_Q = self.env.config.SWRM_a_Q
        a_patience = self.env.config.SWRM_a_patience

        k_now = self.env.get_slot_idx(self.env.now())
        k_end = self.env.get_slot_idx(ev.park_end)
        k_end = int(min(k_end, k_now + max_lookahead_slots - 1))

        if max_lookahead_slots is not None:
            k_end = min(k_end, k_now + max_lookahead_slots - 1)

        if k_end < k_now:
            return []

        slots = np.arange(k_now, k_end + 1, dtype=int)
        n_avail = len(slots)

        remaining_need = max(ev.get_max_energy_required(), 0.0)
        power = max(ev.max_accepting_power(self.power), 0.0)
        max_energy_per_slot = max(power * self.resolution / 3600.0, eps)

        n_req = int(np.ceil(remaining_need / max_energy_per_slot)) * 2
        n_pick = min(n_req, n_avail)

        if n_pick <= 0:
            return []

        # If the remaining parking window is tight, ignore SWRM scoring.
        # Select the earliest slots that have not been locally selected.
        if n_avail < a_Q * n_req:
            locally_empty_slots = slots[self.L[slots] == 0]
            return locally_empty_slots[:n_pick].tolist()

        p_slice = np.asarray(self.env.P[k_now:k_end + 1], dtype=float)
        c_slice = np.asarray(self.env.C[k_now:k_end + 1], dtype=float)
        g_slice = np.asarray(self.env.G[k_now:k_end + 1], dtype=float)
        l_slice = np.asarray(self.L[slots], dtype=float)

        c_max = max(np.max(c_slice), eps)
        g_max = max(np.max(g_slice), eps)

        pv_term = np.maximum(p_slice, eps) ** a_pv
        price_term = np.maximum(c_slice / c_max, eps) ** a_price
        grid_term = np.maximum(g_slice / g_max, eps) ** a_grid

        # Patience term.
        a_patience = self.env.config.SWRM_a_patience

        slot_rank = np.arange(n_avail, dtype=float)

        # Scale by the number of slots the EV actually needs,
        # not by the full lookahead window.
        need_scale = max(float(n_req), 1.0)

        patience_term = np.exp(-a_patience * slot_rank / need_scale)

        if k_now == 0:
            prev_g = np.empty_like(g_slice)
            prev_g[0] = g_slice[0]
            if n_avail > 1:
                prev_g[1:] = g_slice[:-1]
            ramp_raw = np.abs(g_slice - prev_g)
            ramp_raw[0] = 0.0
        else:
            prev_g = np.asarray(self.env.G[k_now - 1:k_end], dtype=float)
            ramp_raw = np.abs(g_slice - prev_g)

        r_max = max(np.max(ramp_raw), eps)
        ramp_term = np.maximum(ramp_raw / r_max, eps) ** a_ramp

        # Local anti-selection term.
        # A slot selected by more EVs on this charging column receives lower utility.
        local_term = np.where(l_slice > 0, 1e6, 1.0)

        base_utility = (pv_term * patience_term) / (
            price_term * grid_term * ramp_term * local_term
        )
        selected_mask = np.zeros(n_avail, dtype=bool)
        adjacency = np.zeros(n_avail, dtype=float)
        scores = base_utility.copy()

        for _ in range(n_pick):
            scores[selected_mask] = -np.inf

            best_idx = int(np.argmax(scores))
            if not np.isfinite(scores[best_idx]):
                break

            selected_mask[best_idx] = True
            scores[best_idx] = -np.inf

            for j in (best_idx - 1, best_idx + 1):
                if 0 <= j < n_avail and not selected_mask[j]:
                    adjacency[j] += 1.0
                    scores[j] = base_utility[j] * ((1.0 + adjacency[j]) ** a_scatter)

        return slots[selected_mask].tolist()


    def _release_reserved_power(self):
        if self.current_consumption > 0:
            p = self.current_consumption
            self.current_consumption = 0
            self.env.simpy_env.process(
                self.env.energy_sandbox.release_power(self.env, p)
            )

    def _go_idle(self, break_handshakes=False):
        self._release_reserved_power()
        if break_handshakes:
            for req in self.users:
                req.handshake = False
        self.active_ev = None
        self.active_req = None

    def swarm_charging_loop(self):
        max_lookahead_slots = int(np.ceil(self.env.config.SWRM_look_ahead_time / self.env.slot_sec))

        def _unreserve(req, num_slots=None):
            old_slots = list(getattr(req, "selected_slots", []))

            if not old_slots:
                req.selected_slots = []
                req.selected_slots_set = set()
                return

            if num_slots is None:
                slots_to_remove = old_slots
                remaining_slots = []
            else:
                slots_to_remove = old_slots[-num_slots:]
                remaining_slots = old_slots[:-num_slots]

            if slots_to_remove:
                self.remove_ev_slots_from_L(slots_to_remove)
                idx = np.asarray(slots_to_remove, dtype=int)
                self.env.G[idx] = np.maximum(0.0, self.env.G[idx] - self.power)

            req.selected_slots = remaining_slots
            req.selected_slots_set = set(remaining_slots)


        def _reserve(req, new_slots):
            if not new_slots:
                req.selected_slots = []
                req.selected_slots_set = set()
                return

            new_slots = sorted(set(int(k) for k in new_slots))

            req.selected_slots = new_slots
            req.selected_slots_set = set(new_slots)

            self.add_ev_slots_to_L(new_slots)

            idx = np.asarray(new_slots, dtype=int)
            self.env.G[idx] += self.power

        def _seconds_to_next_slot():
            k_now = self.env.get_slot_idx(self.env.now())
            k_next = k_now + 1
            next_slot_unix = self.env.start_unix + (k_next) * self.env.slot_sec
            return max(0, next_slot_unix - self.env.now())

        while True:
            if len(self.users) == 0:
                self._go_idle(break_handshakes=True)
                yield self.arrival_event
                continue

            # clear stale reservations from EVs that are already done/disconnected
            for req in list(self.users):
                if getattr(req, "selected_slots", None) and req.ev.request_disconnect_approved.triggered:
                    _unreserve(req)

            reqs = [req for req in self.users if req.ev.request_disconnect_approved.triggered is False]

            if len(reqs) == 0:
                self._go_idle(break_handshakes=True)
                yield self.env.simpy_env.timeout(60)
                continue

            # re-plan reservations for all active EVs
            k_now = self.env.get_slot_idx(self.env.now())
            if k_now % self.env.config.SWRM_replan_interval_slots == 0:
                for req in reqs:
                    _unreserve(req, max_lookahead_slots)
                    new_slots = self.select_required_slots(
                        req.ev
                    )
                    _reserve(req, new_slots)

            # EVs that want the current slot
            empty_set = set()
            claimants = [
                req for req in reqs
                if k_now in getattr(req, "selected_slots_set", empty_set)
                        ]

            if len(claimants) == 0:
                # nobody charges in this slot -> release held power and break handshake continuity
                self._go_idle(break_handshakes=True)
                wait_sec = _seconds_to_next_slot()
                if wait_sec > 0:
                    yield self.env.simpy_env.timeout(wait_sec)
                continue
            
            # among candidates, shortlist the ones who yet not received TTR_min energy
            # then pick the one with min amount of received energy so far
            # if all have received more than TTR_min, then prefer the one how already has a handshake
            # if none has handshake, then pick the one with min normalized SoC (most urgent)
            selected = None
            for candidate in claimants:
                if candidate.ev.rec_energy < self.env.config.TTR_min:
                    if selected is None or candidate.ev.rec_energy < selected.ev.rec_energy:
                        selected = candidate
            if selected is None:
                 for candidate in claimants:
                     if candidate.handshake:
                         selected = candidate
                         break
            if selected is None:
                selected = min(claimants, key=lambda r: r.ev.SoC / r.ev.Capacity_kWh)

            self.active_req = selected  
            self.active_req.last_charge_time = self.env.now()
            self.active_ev = self.active_req.ev

            yield self.env.simpy_env.process(self.handle_handshake(self.active_req))

            # EV may disconnect during handshake
            if self.active_req.handshake is False:
                self._go_idle(break_handshakes=True)
                wait_sec = _seconds_to_next_slot()
                if wait_sec > 0:
                    yield self.env.simpy_env.timeout(wait_sec)
                continue

            power = self.active_ev.max_accepting_power(self.power)

            if power <= 0:
                if not self.active_ev.charge_cmpt_event.triggered:
                    self.active_ev.charge_cmpt_event.succeed()
                if not self.active_ev.request_disconnect_approved.triggered:
                    self.active_ev.request_disconnect_approved.succeed()
                _unreserve(self.active_req)
                self._go_idle(break_handshakes=True)

                wait_sec = _seconds_to_next_slot()
                if wait_sec > 0:
                    yield self.env.simpy_env.timeout(wait_sec)
                continue

            max_energy = power * self.resolution / 3600.0
            max_energy = min(self.active_ev.get_max_energy_required(), max_energy)

            if max_energy <= 0:
                if not self.active_ev.charge_cmpt_event.triggered:
                    self.active_ev.charge_cmpt_event.succeed()
                if not self.active_ev.request_disconnect_approved.triggered:
                    self.active_ev.request_disconnect_approved.succeed()
                _unreserve(self.active_req)
                self._go_idle(break_handshakes=True)

                wait_sec = _seconds_to_next_slot()
                if wait_sec > 0:
                    yield self.env.simpy_env.timeout(wait_sec)
                continue

            required_power = power - self.current_consumption
            if required_power > 0:
                power_proc = self.env.simpy_env.process(
                    self.env.energy_sandbox.request_power(self.env, required_power)
                )
                res = yield power_proc | self.active_ev.request_disconnect

                if self.active_ev.request_disconnect in res:
                    if not self.active_ev.request_disconnect_approved.triggered:
                        self.active_ev.request_disconnect_approved.succeed()

                    if not power_proc.triggered:
                        power_proc.interrupt("disconnect")

                    if power_proc in res:
                        self.env.simpy_env.process(
                            self.env.energy_sandbox.release_power(self.env, required_power)
                        )

                    _unreserve(self.active_req)
                    self._go_idle(break_handshakes=True)

                    wait_sec = _seconds_to_next_slot()
                    if wait_sec > 0:
                        yield self.env.simpy_env.timeout(wait_sec)
                    continue

                self.current_consumption += required_power

            # charge only within the remaining part of the current slot
            charge_duration = min((max_energy / power) * 3600.0, _seconds_to_next_slot())

            if charge_duration > 0:
                start_time = self.env.now()
                yield self.env.simpy_env.timeout(charge_duration) | self.active_ev.request_disconnect
                end_time = self.env.now()

                actual_duration = end_time - start_time
                self.log_charge_duration += actual_duration
                if actual_duration > self.longest_charge_duration:
                    self.longest_charge_duration = actual_duration

                delivered_energy = (actual_duration / 3600.0) * power
                self.total_energy_delivered += delivered_energy
                cost_w = delivered_energy * self.env.energy_sandbox.getEnergyPrice(self.env.now())
                self.total_cost += cost_w
                self.active_ev._rec_energy(delivered_energy)
                self.active_ev._add_cost(cost_w)
                self.active_ev.actual_charge_time += actual_duration

            # always release reserved power at slot boundary
            self._release_reserved_power()

            if self.active_ev.get_max_energy_required() <= 0.1:
                if not self.active_ev.charge_cmpt_event.triggered:
                    self.active_ev.charge_cmpt_event.succeed()
                if not self.active_ev.request_disconnect_approved.triggered:
                    self.active_ev.request_disconnect_approved.succeed()
                _unreserve(self.active_req)
                self._go_idle(break_handshakes=True)

            elif self.active_ev.request_disconnect.triggered:
                self.env.log(
                    f'EV {self.active_ev.id} requested disconnect during charging at ChargingColumn {self.id}, waiting for approval...'
                )
                if not self.active_ev.request_disconnect_approved.triggered:
                    self.active_ev.request_disconnect_approved.succeed()
                _unreserve(self.active_req)
                self._go_idle(break_handshakes=True)

            else:
                # keep handshake if the same EV continues in adjacent slots
                self.active_ev = None
                self.active_req = None

            yield self.env.simpy_env.timeout(0)

    def final_logging(self):
        # log total energy delivered and total cost for this charging column
        # self.env.logger.insert(self.env.now(), agent=f"charging_column_{self.id}", field="total_energy_delivered_kWh", value=self.total_energy_delivered)
        # self.env.logger.insert(self.env.now(), agent=f"charging_column_{self.id}", field="total_cost_EUR", value=self.total_cost)
        # self.env.logger.insert(self.env.now(), agent=f"charging_column_{self.id}", field="log_handshake_duration_sec", value=self.log_handshake_duration)
        # self.env.logger.insert(self.env.now(), agent=f"charging_column_{self.id}", field="log_charge_duration_sec", value=self.log_charge_duration)
        # self.env.logger.insert(self.env.now(), agent=f"charging_column_{self.id}", field="longest_charge_duration_sec", value=self.longest_charge_duration)
        pass
    def main_loop(self, strategy="FCFS"):
        if strategy == "FCFS":
            return self.FCFS_charging_loop()
        elif strategy == "SHRD":
            return self.shared_charging_loop()
        elif strategy == "SWRM":
            return self.swarm_charging_loop()
        else:
            raise ValueError(f"Unknown charging strategy: {strategy}")