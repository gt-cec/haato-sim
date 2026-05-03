import math
import os
import threading
import traceback
import warnings
from datetime import datetime
from queue import Queue
import time
from typing import Tuple
import numpy as np

from utility.base_classes import Wingman, GeoUtils
from utility.message_queue import Message
from utility.config_loader import get_config

from missions.fire.constants import NO_PLAN, PLAN_ACCEPT_PRIMARY, PLAN_ACCEPT_SECONDARY, TASK_DONE_CODES
from missions.fire.observation import parse_wingman_observation


class FireWatchWingman(Wingman):
    def __init__(self, xpc, start_lla, start_hdg, start_spd, mm, fire_layout, initiative_level=1.0):
        super().__init__(xpc, start_lla, start_hdg, start_spd, mm)
        self.xpc = xpc
        self.mm = mm
        self.initiative_level = initiative_level  # 0.0=Low, 1.0=Medium, 2.0=High
        self.type = 'heuristic'
        self.fire_layout = fire_layout
        self.initiative_level = initiative_level

        self.verbose = False


        #################### CONFIGS ###################################################################################
        _m = get_config()["missions"][fire_layout]
        self.required_cruise_altitude_ft = float(_m["required_altitude_ft_msl"])
        self.required_alt_fire_agl_ft = float(_m["required_altitude_fire_agl_ft"])
        self.wind_direction = float(_m["wind_direction"])
        self.required_drop_route_length = float(_m["required_drop_route_length"])
        self.mag_declination = float(_m["magnetic_declination"])

        _w = get_config()["wingman"]
        self.utility_weight = _w["utility_weight"]
        self.distance_weight = _w["distance_weight"]
        self.late_game_threshold_minutes = _w["late_game_threshold_minutes"]
        self.proximity_threshold_nm = _w["proximity_threshold_nm"]
        self.proximity_bonus = _w["proximity_bonus"]
        self.lookahead_depth = _w["lookahead_depth"]
        self.lookahead_discount = _w["lookahead_discount"]
        self.max_planning_time_s = _w["max_planning_time_s"]
        self.avg_cruise_speed_kts = _w["avg_cruise_speed_kts"]
        self.target_lock_distance = _w["target_lock_distance_nm"]
        self.overfly_tolerance = _w["overfly_tolerance_nm"]
        self.route_waypoint_tolerance = _w["route_waypoint_tolerance_nm"]

        self.max_speed = start_spd * 1.3  # The max speed the agent can command
        self.default_spd = start_spd


        #################### Initialize values #########################################################################

        self.lat = start_lla[0]
        self.long = start_lla[1]
        self.alt = start_lla[2]
        self.hdg = start_hdg
        self.spd = start_spd


        #################### Tracking variables ########################################################################

        self.status = 99.0
        self.last_status = 'none'
        self.action = None
        self.last_action = {'type':'none', 'goal': (0.0,0.0,0.0), 'request': 'none'}
        self.current_target = None  # Store the currently locked target
        self.request_response = 0.0
        self.requesting_help = False # Whether agent is requesting help with its current target.
        self.latest_human_command = None
        self.latest_human_message = None

        self.auto_spot = False # 1.0 true, 0.0 false

        # Route marking state
        self.current_route_target = None
        self.route_marking_stage = None  # 'flying_to_start', 'at_start', 'flying_route', 'at_end', 'complete'
        self.route_type = None  # 'initial' or 'refined'
        self.route_start_time = None

        # Position marking state
        self.marking_position_target = None
        self.position_marking_stage = None  # 'flying_to_overfly', 'complete'

        # Lookahead optimization: Cache for memoization (Phase 2)
        self.sent_first_plan = False
        self.current_plan_for_self = NO_PLAN
        self.latest_human_plan_sent = None
        self.latest_plan = None
        self.lookahead_count = 0

        self.started_planning_step = None
        self.ended_planning_step = None
        self.planning_thread = None
        self.planning_queue = Queue(maxsize=1)  # Holds latest plan result
        self.planning_lock = threading.Lock()
        self.is_planning = False
        self.cached_plans = {'human_plan': None, 'wingman_plan': None}  # Default/last result
        self._lookahead_cache = {}  # Cache lookahead values for identical fire states
        self._cache_stats = {'hits': 0, 'misses': 0}  # Track cache performance


    def reset(self):

        self.status = 99.0
        self.last_status = 'none'
        self.action = None
        self.last_action = {'type': 'none', 'goal': (0.0, 0.0, 0.0), 'request': 'none'}
        self.current_target = None  # Store the currently locked target
        self.request_response = 0.0
        self.requesting_help = False  # Whether agent is requesting help with its current target.
        self.latest_human_command = None
        self.latest_human_message = None

        self.auto_spot = False  # 1.0 true, 0.0 false

        # Route marking state
        self.current_route_target = None
        self.route_marking_stage = None  # 'flying_to_start', 'at_start', 'flying_route', 'at_end', 'complete'
        self.route_type = None  # 'initial' or 'refined'
        self.route_start_time = None

        # Position marking state
        self.marking_position_target = None
        self.position_marking_stage = None  # 'flying_to_overfly', 'complete'

        # Lookahead optimization: Cache for memoization (Phase 2)
        self.sent_first_plan = False
        self.current_plan_for_self = NO_PLAN
        self.latest_human_plan_sent = None
        self.latest_plan = None
        self.lookahead_count = 0

        self.started_planning_step = None
        self.ended_planning_step = None
        self.planning_thread = None
        self.planning_queue = Queue(maxsize=1)  # Holds latest plan result
        self.planning_lock = threading.Lock()
        self.is_planning = False
        self.cached_plans = {'human_plan': None, 'wingman_plan': None}  # Default/last result
        self._lookahead_cache = {}  # Cache lookahead values for identical fire states
        self._cache_stats = {'hits': 0, 'misses': 0}  # Track cache performance

    def receive_human_message(self, message: Message) -> None:
        self.latest_human_message = message
        self.log(f"[receive_human_message] {message.payload.get('normalized_text', '')}")

    def act(self, obs, messages):
        """Generate wingman action based on observation and incoming messages.

        Args:
            observation: numpy array containing:
                Indices 0-5: mission_timer, human_lat, human_long, human_alt, human_hdg, human_spd
                Indices 6-13: command_from_human, agent_task_accepted, human_recently_finished_task,
                             wingman_recently_finished_task, human_requests_plan_suggestion,
                             human_indicated_plan, wingman_status, plan_for_wingman
                Index 14: num_targets
                Index 15: Reserved
                Indices 16+: Target data blocks (10 values each)

            messages: List of Message objects for this wingman

        Returns:
            dict containing:
                'type' (str): Type of action (HSA or LLA)
                'goal' (tuple): e.g. (desired_hdg, desired_spd, desired_alt)
                'outgoing_messages' (list): List of Message objects to send
        """
        outgoing_messages = []
        action = {}

        parsed_obs = parse_wingman_observation(obs)
        mission_timer = parsed_obs.mission_timer

        for message in messages:
            if message.type == "freeform_text":
                self.receive_human_message(message)

        try:
            human_finished = parsed_obs.human_recently_finished_task in TASK_DONE_CODES
            wingman_finished = parsed_obs.wingman_recently_finished_task in TASK_DONE_CODES
            human_requests_plan = parsed_obs.human_requests_plan == 1.0

        except Exception as e:
            self.log(f'Error checking planning triggers: {e}')
            human_finished = False
            wingman_finished = False
            human_requests_plan = False

        already_planning_this_step = False
        if human_requests_plan or (self.initiative_level == 1.0 and self.current_plan_for_self == NO_PLAN and not self.is_planning):
            self.handle_planning(obs)
            already_planning_this_step = True
            self.xpc.sendDREF("custom/haato/human_requests_plan_suggestion", 0.0)
            #print(f'[act] Wingman got plan request, setting dref to zero.')
            self.is_planning = True


        ####### Handle human response to plan suggestion ###############################################################
        plan_accepted_this_step = False
        try:
            agent_task_accepted = parsed_obs.agent_task_accepted
            if self.latest_plan is not None:
                if agent_task_accepted == PLAN_ACCEPT_PRIMARY:
                    self.current_plan_for_self = self.latest_plan['wingman_plan']
                    self.log(f'[act] Using {self.current_plan_for_self} plan for self')
                    plan_accepted_this_step = True

                elif agent_task_accepted == PLAN_ACCEPT_SECONDARY:
                    self.current_plan_for_self = self.latest_plan['second_best_wingman_plan']
                    self.log(f'Human accepted alt plan, using {self.current_plan_for_self} plan')
                    plan_accepted_this_step = True

                elif agent_task_accepted not in (-1.0, 0.0):
                    warnings.warn(f'Got invalid task accepted value {agent_task_accepted}')

        except Exception as e:
            self.log(f'Error handling task accepted: {e}')
            traceback.print_exc()


        ###### Decide action based on initiative level and commands received ###########################################

        action = self.policy(obs)

        # Don't trigger re-planning if human just accepted a plan suggestion this step
        if (self.initiative_level == 2.0) or (self.initiative_level == 1.0 and self.current_plan_for_self == NO_PLAN):
            if (not self.sent_first_plan) or human_finished or wingman_finished:
                if not already_planning_this_step and not plan_accepted_this_step:
                    self.handle_planning(obs)


        if self.is_planning: # Check if new results are available
            # print(f'\n[act] Checking plan results')
            if not self.planning_queue.empty():
                try:
                    self.cached_plans = self.planning_queue.get_nowait()
                except Exception as e:
                    self.log(f'Error getting planning results: {e}')
                    traceback.print_exc()

                # Add cached plan to action
                action = action | self.cached_plans
                # print(f'Action: {action}')

                self.latest_human_plan_sent = action['human_plan']

                # Reset datarefs and tracking vars
                self.mm.ended_planning_step = self.mm.step_count
                # print(f'    Planning results gotten! (Took {self.mm.ended_planning_step-self.mm.started_planning_step} steps ({self.mm.started_planning_step} to {self.mm.ended_planning_step})')
                self.started_planning_step = None
                self.ended_planning_step = None
                self.is_planning = False
                try:
                    self.safe_send_dref("custom/haato/human_requests_plan_suggestion", 0.0, "human_requests_plan_suggestion")
                    self.mm.udp_bridge.current_state["human"]["recently_finished_task"] = -1.0
                    self.mm.udp_bridge.current_state["wingman"]["recently_finished_task"] = -1.0
                except Exception as e:
                    self.log(f'Error resetting plan datarefs: {e}')
                    traceback.print_exc()


        # Create status message
        outgoing_messages.append(Message(msg_type='status', sender='wingman_0', recipient='human', payload={'status_value': self.status}, timestamp=mission_timer))

        # Update last state
        self.last_status = self.status
        self.last_action = action

        # Add outgoing messages to action dict
        action['outgoing_messages'] = outgoing_messages
        action['status'] = self.status

        # Populate subtask info
        if self.route_marking_stage == 'flying_to_start' or self.position_marking_stage == 'flying_to_overfly':
            action['subtask'] = 1.0

        elif self.route_marking_stage == 'flying_route':
            action['subtask'] = 2.0

        else:
            action['subtask'] = 0.0

        return action


    def handle_planning(self, obs):
        self.log(f'[handle_planning] SEND PLAN TRIGGERED')
        human_finished = obs[8] in [3.0, 4.0]  # Human recently finished task
        wingman_finished = obs[9] in [3.0, 4.0]  # Wingman recently finished
        human_requests_plan = obs[10] == 1.0  # Human requesting plan

        self.log(f'    Human finished / wingman finished / human requests = {human_finished}/{wingman_finished}/{human_requests_plan}')

        # Generate team strategy
        self.sent_first_plan = True

        try:
            with self.planning_lock:
                if not self.is_planning:
                    self.is_planning = True
                    self.log(f'    Started plan thread on step {self.mm.step_count}')
                    self.mm.started_planning_step = self.mm.step_count
                    self.planning_thread = threading.Thread(
                        target=self._threaded_plan,
                        args=(obs.copy(),),  # Pass a copy to avoid race conditions
                        daemon=True
                    )
                    self.planning_thread.start()

        except Exception as e:
            self.log(f'    ERROR in multithread planning call: {e}. Calling regular planning fn.')
            self.cached_plans = self.plan(obs)

    def policy_combined(self, obs) -> dict:
        """Compatibility wrapper for the historical policy entrypoint."""
        return self.policy(obs)

    def plan_team_strategy(self, obs) -> dict:
        """Compatibility wrapper for the historical planning entrypoint."""
        return self.plan(obs)


    def _threaded_plan(self, obs):
        """Run plan in background and put result in queue"""
        try:
            team_plan = self.plan_team_strategy(obs)
            team_plan['show_plan'] = 1.0

            if self.verbose:
                print(f'[_threaded_plan] COMPLETE')
                for key, value in team_plan.items():
                    if key not in ['show_plan', 'mode', 'rationale']:
                        print(f"    {key}: {value}")

            # Clear old result and add new one
            if not self.planning_queue.empty():
                try:
                    self.planning_queue.get_nowait()
                except Exception as e:
                    self.log(f'Error clearing old planning results: {e}')
            self.planning_queue.put(team_plan)
        finally:
            with self.planning_lock:
                pass

    def _select_optimal_task(self, task_categories, human_indicated_fire_id):
        """
        Intelligent heuristic to select the optimal task for the wingman.

        Considers:
        - Distance from wingman to each fire
        - Sequential task priorities (earlier steps slightly preferred)
        - Human's indicated plan (avoids that fire completely)
        - Efficiency based on proximity

        Args:
            task_categories: Dict mapping task types to lists of target_info dicts
            human_lat, human_long: Human's current position
            human_indicated_fire_id: Fire ID human is working on (-1 if none)

        Returns:
            tuple: (chosen_target_info, chosen_task_type) or (None, None) if no tasks available
        """
        # Step priorities (lower = higher priority, but not as strong as in old system)
        # These are used as tiebreakers or slight weights
        step_weights = {
            'classify_fire': 1.0,      # Step 1
            'mark_position': 1.1,      # Step 2
            'mark_initial_route': 1.2,  # Step 3
            'mark_refined_route': 1.8   # Step 4
        }

        # Collect all candidate tasks with scores
        candidates = []
        backup_candidates = []
        for task_type, target_list in task_categories.items():
            if not target_list:
                continue

            step_weight = step_weights.get(task_type, 1.0)

            for target_info in target_list:
                target = target_info['target']

                # Skip fires the human is working on
                if 0.0 <= human_indicated_fire_id < 99.0 and target.id == human_indicated_fire_id:
                    continue

                # Calculate score based on distance and step priority
                distance = target_info['distance']
                score = distance * step_weight

                if target.id == self.latest_human_plan_sent: # Only consider the fire that we last suggested to the human if there are no other options
                    backup_candidates.append({
                        'target_info': target_info,
                        'task_type': task_type,
                        'score': score,
                        'distance': distance,
                    })

                else:
                    candidates.append({
                        'target_info': target_info,
                        'task_type': task_type,
                        'score': score,
                        'distance': distance,
                    })

        # Select the candidate with the lowest score
        if candidates:
            best_candidate = min(candidates, key=lambda c: c['score'])
            self.log(f'        Optimal task: {best_candidate["target_info"]["target"].id}, {best_candidate["task_type"]}')
            return best_candidate['target_info'], best_candidate['task_type']

        elif backup_candidates:
            best_candidate = min(backup_candidates, key=lambda c: c['score'])
            self.log(f'        Optimal task (backup): {best_candidate["target_info"]["target"].id}, {best_candidate["task_type"]}')
            return best_candidate['target_info'], best_candidate['task_type']

        else:
            self.log(f'    [select_optimal_task] No tasks available')
            return None, None


    def _search_task_categories(self, desired_target, task_categories, human_indicated_fire_id):
        # Search for the commanded target in task_categories

        chosen_target_info, chosen_task_type = None, None
        for task_type, target_list in task_categories.items():
            for target_info in target_list:
                if target_info['target'].id == desired_target:
                    chosen_target_info = target_info
                    chosen_task_type = task_type
                    self.log(f'    found chosen_target_info: {chosen_task_type} {target_info["target"].id}')
                    break
            if chosen_target_info is not None:
                break

        # if chosen_target_info is None:
        #     print(f"    ERROR: Could not find target {desired_target} in task_categories.")
        #     print(f'    Task categories\n {task_categories}')
        #     print(f'    Calling select optimal task:')
        #     chosen_target_info, chosen_task_type = self._select_optimal_task(task_categories, human_indicated_fire_id)
        #     print(f'    Chose task: {chosen_task_type} {chosen_target_info['target'].id}')

        return chosen_target_info, chosen_task_type


    def reset_modes(self):
        self.log(f'Reset route and position stages to None')
        # Reset route vars
        self.route_marking_stage = None
        self.current_route_target = None

        # Reset pos vars
        self.position_marking_stage = None
        self.marking_position_target = None


    def _parse_mission_state(self, observation):

        """
        Parses observation ONCE per frame.
        Returns a dictionary of numpy arrays for fast vectorized operations.
        """
        num_targets = int(observation[14])

        # Pre-allocate arrays
        statuses = np.zeros(num_targets)
        lats = np.zeros(num_targets)
        longs = np.zeros(num_targets)
        who_flew = np.zeros(num_targets)

        # Extract data in one pass. Keep this aligned with
        # missions.fire.observation.TARGET_BLOCK_SIZE.
        for i in range(num_targets):
            base_idx = 16 + (i * 14)
            lats[i] = observation[base_idx]
            longs[i] = observation[base_idx + 1]
            statuses[i] = observation[base_idx + 12]
            who_flew[i] = observation[base_idx + 13]

        # Vectorized distance calculation
        # TODO haversine needs to accept vectorized calls
        human_dists = GeoUtils.haversine_distance(observation[1], observation[2], lats, longs)
        wingman_dists = GeoUtils.haversine_distance(self.lat, self.long, lats, longs)

        return {
            'statuses': statuses,
            'lats': lats,
            'longs': longs,
            'who_flew': who_flew,
            'human_dists': human_dists,
            'wingman_dists': wingman_dists,
            'num_targets': num_targets
        }


    def is_valid_target(self, obs, target_id, mission_state=None):
        try:
            if target_id == -1.0:
                return False

            elif target_id < 0 or target_id >= self.mm.num_targets:
                self.log(f'    Target ID {target_id} outside bounds -> target is invalid')
                return False

            target_id = int(target_id)

            # Use cached mission_state if provided, otherwise fetch from observation
            if mission_state is not None:
                if target_id >= mission_state['num_targets']:
                    self.log(f'    Target data is none -> target is invalid')
                    return False
                status = mission_state['statuses'][target_id]
                whoflew = mission_state['who_flew'][target_id]
            else:
                target_data = self._get_target_data_from_observation(obs, target_id)
                if target_data is None:
                    self.log(f'    Target data is none -> target is invalid')
                    return False
                status = target_data['target_status']
                whoflew = target_data['target_whoflew_initial']

            if status == 4.0 or (status == 3.0 and whoflew == 2.0):
                self.log(f'    Target is 4.0 or whoflew = 2.0 -> target is invalid')
                return False
            else:
                return True
        except Exception as e:
            self.log(f'    Error in is_valid_target: {e}')
            return False


    def policy(self, obs) -> dict:
        """
        args:
        observation
        commanded_target

        Policy based on 4-step sequential workflow for each fire:
        1. Classify fire (fly within visual range)
        2. Mark GPS position (fly directly over fire)
        3. Mark initial drop route (2 NM upwind to 1 NM downwind)
        4. Mark refined drop route (can't refine own route)

        Uses intelligent heuristic to select tasks based on distance and human coordination.
        """

        # Initialize action dict
        action = {'type': 'hsa', 'goal': None, 'message': ''}

        # Parse observation data
        mission_timer = obs[0]
        commanded_target = obs[6]
        human_indicated_plan = obs[11]  # custom/haato/human_indicated_plan
        human_indicated_fire_id = int(human_indicated_plan) if 0.0 <= human_indicated_plan < 99.0 else -1

        # Parse mission state once for vectorized operations
        mission_state = self._parse_mission_state(obs)

        if commanded_target == 8.0:  # Follow human
            self.log(f'    Command is {commanded_target} - Following human')
            action['goal'] = self._calc_hsa_to_human_intercept(obs)
            action['message'] = 'Following human'
            self.status = 8.0
            return action

        if self.initiative_level == 0.0 and (commanded_target in [-1.0, 12.0] or not self.is_valid_target(obs, commanded_target, mission_state)):  # Low autonomy: holding pattern only
            self.log(f'    Init level 0 and no command given (val={commanded_target}) - HOLDING')
            action['goal'] = self._calc_hsa_holding_pattern(self.lat, self.long, self.alt, mission_timer)
            action['message'] = 'Holding (no command given)'
            self.reset_modes()
            self.status = 9.0
            return action



        #### Step 1: Clear stale states ########################################################################################
        if self.verbose:
            print(f'\n[Policy]')
            print(f'1. Clear stale states')

        # Check validity of current_plan_for_self
        if 0 <= self.current_plan_for_self < self.mm.num_targets:
            if not self.is_valid_target(obs, self.current_plan_for_self, mission_state):
                self.current_plan_for_self = 99.0
                self.reset_modes()
                self.log(f'    self.current_plan_for_self is invalid -> resetting')

        # Prevent wingman from using policy during initiative level 1.0 (must use plan from plan() to match init level 2
        if self.initiative_level == 1.0 and self.current_plan_for_self == 99.0:
            action['goal'] = self._calc_hsa_holding_pattern(self.lat, self.long, self.alt, mission_timer)
            action['message'] = 'Holding (no command given)'
            self.status = 9.0
            return action


        # Check validity of command from human
        if commanded_target not in [12.0, 99.0] and 0 <= commanded_target < self.mm.num_targets:
            if not self.is_valid_target(obs, commanded_target, mission_state):
                self.log(f'    Human command {commanded_target} is no longer a valid target. Reset.')
                commanded_target = 12.0
                self.xpc.sendDREF("custom/haato/command_from_human", 12.0)



        ###### Step 2: Add target tasks ########################################################################################
        # Categorize fires by what step they need next

        classify_fires = []  # Step 1: Not yet spotted
        mark_position_fires = []  # Step 2: Spotted but position not marked
        mark_initial_route_fires = []  # Step 3: Position marked but no initial route
        mark_refined_route_fires = []  # Step 4: Initial route done but no refined route
        excluded_targets = []

        for target in self.mm.targets:
            if target.status == 4.0: # Skip handled targets
                continue

            if human_indicated_fire_id != -1 and target.id == human_indicated_fire_id: # Exclude fires that the human is working on (TODO Might need to relax this)
                excluded_targets.append((target.id, 'Conflict with human plan'))
                continue

            # Check bounds before accessing arrays
            if target.id >= mission_state['num_targets']:
                self.log(f'    WARNING [Policy combined] Target {target.id} out of bounds')
                excluded_targets.append((target.id, 'Target data none'))
                continue

            target_info = {
                'target': target,
                'lat': target.lat,
                'long': target.long,
                'distance': mission_state['wingman_dists'][target.id]
            }

            # Determine next step based on current status - read from cached mission_state
            status = mission_state['statuses'][target.id]
            whoflew = mission_state['who_flew'][target.id]

            if status == 0.0: # Step 1: Need to classify
                classify_fires.append(target_info)

            elif status == 1.0: # Step 2: Need to mark position
                mark_position_fires.append(target_info)

            elif status == 2.0: # Step 3: Need initial route
                mark_initial_route_fires.append(target_info)

            elif status == 3.0 and whoflew != 2.0: # Step 4: Need refined route (but can't refine own route)
                mark_refined_route_fires.append(target_info)

            else:
                excluded_targets.append((target.id, f'Met no criteria (status = {status}, whoflew = {whoflew})'))

        # Collect all task categories
        task_categories = {
            'classify_fire': classify_fires,
            'mark_position': mark_position_fires,
            'mark_initial_route': mark_initial_route_fires,
            'mark_refined_route': mark_refined_route_fires,
        }

        # Collect all task categories (Mapping IDs for the dictionary view)
        #task_categories_ids = {k: [item['target'].id for item in v] for k, v in task_categories.items()}

        #self.log(f'    Task categories: {task_categories_ids}')
        self.log(f'    Classify: {[item["target"].id for item in classify_fires]}')
        self.log(f'    Mark Position: {[item["target"].id for item in mark_position_fires]}')
        self.log(f'    Mark Initial Route: {[item["target"].id for item in mark_initial_route_fires]}')
        self.log(f'    Mark refined route: {[item["target"].id for item in mark_refined_route_fires]}')
        self.log(f'    Excluded targets: {excluded_targets}')


        ################################################################################################################
        ### Step 3: Check if we have a priority target to follow (either commanded from human, or from last plan suggestion) ###

        # Priority 1: If wingman receives a task and it's valid, break everything else
        target_override = None
        if commanded_target not in [12.0, 99.0] and 0 <= commanded_target < self.mm.num_targets: # Fly to the commanded target
            if self.current_route_target != commanded_target and self.marking_position_target != commanded_target:
                target_override = int(commanded_target)
                self.reset_modes()
                self.current_plan_for_self = target_override # TODO make sure this doesn't break anything
                self.log(f'    New command from human: Wingman was flying a route/position but was re-commanded to target {commanded_target} - Setting target override and breaking route/pos status.')
            else:
                self.log(f'    Still commanded to {commanded_target} which is my current route/pos target.')


        # Priority 2, execute current plan for self
        elif self.current_plan_for_self not in [99.0, 99]:
            self.log(f'    Current plan for self is {self.current_plan_for_self}. Setting target override.')
            try:
                target_override = int(self.current_plan_for_self)
                if target_override < 0 or target_override >= self.mm.num_targets:
                    self.log(f'    ERROR: Invalid plan_for_self target: {target_override}')
                    target_override = None
            except Exception as e:
                self.log(f'    ERROR converting plan_for_self to int: {e}')
                traceback.print_exc()
                target_override = None


        ######## Step 4: Decide what to do #####################################################################################

        self.log(f'4. Decide what to do')

        should_recalculate = False
        chosen_target_info, chosen_task_type = None, None

        # 1. Obey target override
        if target_override is not None:
            chosen_target_info, chosen_task_type = self._search_task_categories(target_override, task_categories, human_indicated_fire_id)
            if chosen_target_info is None:
                self.log(f'    Override target {target_override} invalid or conflict. Recalculating.')
                should_recalculate = True
            else:
                self.log(f'    Using target override {target_override}')


        # 2. Continue flying route or position if that's in progress
        # 2.1. Route marking continuation
        elif self.route_marking_stage is not None and self.route_marking_stage != 'complete':
            try:
                target_index = self.mm.target_id_to_index.get(self.current_route_target, None)

                # Check validity of target_index and bounds
                if target_index is None:
                    self.reset_modes()
                    self.log(f'    Current route marking target index is None, BREAK')
                    should_recalculate = True

                elif target_index >= mission_state['num_targets']:
                    self.log(f'    Target index {target_index} out of bounds - should recalculate')
                    should_recalculate = True
                    self.reset_modes()

                else:
                    # Use cached mission_state for status and whoflew
                    status = mission_state['statuses'][target_index]
                    whoflew = mission_state['who_flew'][target_index]

                    # Break mode if human sets their plan to this target
                    if human_indicated_fire_id == target_index:
                        self.log(f'    Human indicated plan equals our route marking target - BREAK')
                        self.reset_modes()
                        should_recalculate = True

                    elif status == 3.0 and self.route_type == 'initial':
                        self.log(f'    Route marking target became 3.0 while marking initial route - BREAK')
                        self.reset_modes()
                        should_recalculate = True

                    elif status == 4.0 or (whoflew == 2.0 and self.route_type == 'refined'):
                        self.log(f'    Route marking target became 4.0 OR refining route and whoflew became 2.0 - BREAK')
                        self.reset_modes()
                        should_recalculate = True

                    else:
                        target = self.mm.targets[target_index]
                        self.log(f'    RETURN: Execute route marking (target {target.id}')
                        action['goal'], action['message'] = self._execute_route_marking(obs, target, self.route_type)
                        self.status = float(target.id)
                        return action


            except (KeyError, IndexError) as e:
                self.log(f'    Error accessing target for route marking: {e}')
                traceback.print_exc()

                self.reset_modes()
                self.log(f'    Error, break')

                action['goal'] = self._calc_hsa_holding_pattern(self.lat, self.long, self.alt, mission_timer)
                self.status = 9.0
                action['message'] = "Holding - no fires to work on"
                warnings.warn(f"{"\033[91m"}WINGMAN HAS NO PLAN - This should go away in a few seconds. If not, call REQUEST TEAM PLAN if initiative_level = 2 or send a manual agent command.{"\033[0m"}", UserWarning)
                self.log(f'    RETURN ACTION: {action['message']} (position 2)')
                return action


        # 2.2. Position marking continuation
        elif self.position_marking_stage is not None and self.position_marking_stage != 'complete':
            try:
                target_index = self.mm.target_id_to_index.get(self.marking_position_target, None)

                # Check validity of target_index and bounds
                if target_index is None:
                    self.reset_modes()
                    self.log(f'    Current pos marking target index is None, BREAK')
                    should_recalculate = True

                elif target_index >= mission_state['num_targets']:
                    self.log(f'    Target index {target_index} out of bounds - should recalculate')
                    should_recalculate = True
                    self.reset_modes()

                else:
                    # Use cached mission_state for status
                    status = mission_state['statuses'][target_index]

                    if human_indicated_fire_id == target_index:
                        self.log(f'    Humans indicated plan equals our position marking target - BREAK')
                        self.reset_modes()
                        should_recalculate = True

                    elif status >= 2.0: # Human beat us to it
                        self.reset_modes()
                        self.log(f'    Human beat us to the position mark, BREAK')
                        should_recalculate = True

                    else:
                        target = self.mm.targets[target_index]
                        self.log(f'    RETURN Execute position marking (target {target.id}) - position marking stage is {self.position_marking_stage}')
                        action['goal'], action['message'] = self._execute_position_marking(obs, target)
                        self.status = float(target.id)
                        return action


            except (KeyError, IndexError) as e:
                self.log(f'    ERROR accessing target for position marking: {e}')
                traceback.print_exc()

                self.position_marking_stage = 'complete'
                action['goal'] = self._calc_hsa_holding_pattern(self.lat, self.long, self.alt, mission_timer)
                action['message'] = "Holding - no fires to work on"
                self.status = 9.0

                warnings.warn(f"{"\033[91m"}WINGMAN HAS NO PLAN - This should go away in a few seconds. If not, call REQUEST TEAM PLAN if initiative_level = 2 or send a manual agent command.{"\033[0m"}", UserWarning)
                self.log(f'    RETURN ACTION: {action['message']} (position 5)')
                return action

        else:
            should_recalculate = True

        # 3. Use heuristic to select optimal task
        if should_recalculate:
            if self.initiative_level == 0.0:
                self.log(f'    [REACHED SHOULD_CALCULATE IN INIT 0] Init level 0 and no command given (val={commanded_target}) - HOLDING')
                action['goal'] = self._calc_hsa_holding_pattern(self.lat, self.long, self.alt, mission_timer)
                action['message'] = 'Holding (no command given)'
                self.status = 9.0
                return action

            chosen_target_info, chosen_task_type = self._select_optimal_task(task_categories, human_indicated_fire_id)
            if chosen_target_info is not None:
                self.log(f'    Using heuristic to select optimal task - {chosen_task_type} {chosen_target_info['target'].id}')
            else:
                self.log(f'    Using heuristic to select optimal task - CHOSEN TARGET INFO IS NONE')


        ################# Execute chosen task ##########################################################################

        self.log(f'5. Execute chosen task')

        # 4. Make sure the policy found a target for the selected action
        if chosen_target_info is None: # No valid targets - hold position
            warnings.warn(f"{"\033[91m"}WINGMAN HAS NO PLAN. If persists, click REQUEST TEAM PLAN if initiative_level = 2 or send a manual command.{"\033[0m"}", UserWarning)
            self.log(f'    ===== NO TARGET FOUND - DIAGNOSTICS =====')
            self.log(f'    human_indicated_fire_id: {human_indicated_fire_id}')
            self.log(f'    self.latest_human_plan_sent: {self.latest_human_plan_sent}')
            self.log(f'    self.current_route_target: {self.current_route_target}')
            self.log(f'    self.marking_position_target: {self.marking_position_target}')
            self.log(f'    ==========================================')

            self.status = 9.0
            action['goal'] = self._calc_hsa_holding_pattern(self.lat, self.long, self.alt, mission_timer)
            action['message'] = "Holding - no fires to work on"

            self.log(f'    RETURN ACTION: {action['message']}')


            return action

        target_obj = chosen_target_info['target']
        target_id = target_obj.id


        # Execute based on task type
        if chosen_task_type == 'mark_position': # Start position marking
            action['goal'], action['message'] = self._execute_position_marking(obs, target_obj)
            self.status = float(target_id)
          #  self.log(f'    FINAL ACTION: {action['message']}')
           # return action

        elif chosen_task_type == 'mark_initial_route': # Start initial route marking
            action['goal'], action['message'] = self._execute_route_marking(obs, target_obj, 'initial')
            self.status = float(target_id)
           # self.log(f'    FINAL ACTION: {action['message']}')
           # return action

        elif chosen_task_type == 'mark_refined_route': # Start refined route marking
            action['goal'], action['message'] = self._execute_route_marking(obs, target_obj, 'refined')
            self.status = float(target_id)
            #self.log(f'    FINAL ACTION: {action['message']}')
            #return action

        elif chosen_task_type == 'classify_fire': # Fly to fire to classify it
            action['goal'] = self._calc_hsa_to_target(obs, target_id)
            action['message'] = f"Classify {target_id}"
            self.status = float(target_id)

        else: # Fallback - shouldn't reach here
            action['goal'] = (self.hdg, self.default_spd, self.alt)
            action['message'] = "Unknown task"
            self.status = 9.0
            self.log(f'    ERROR: Reached fallback logic with chosen_task_type {chosen_task_type}')

        self.log(f'    RETURN ACTION: {action['message']}')
        return action


    def log(self, message, log_file="./logs/debug_log.txt", debug_prefix = None):
        """
        Log a message to the debug log file with a timestamp.
        Handles log file initialization automatically.

        Args:
            debug_prefix: Prefix to prepend to each log message
            message (str): The message to log
            log_file (str): Path to the log file. Defaults to "debug_log.txt"
        """
        # Initialize log file path as class attribute if not already set
        if debug_prefix:
            log_message = f'[{debug_prefix if debug_prefix else ""}] {message}'
        else:
            log_message = message

        if self.verbose:
            print(log_message)

            if not hasattr(self, '_log_file'):
                self._log_file = log_file

            # Create log directory if it doesn't exist
            log_dir = os.path.dirname(self._log_file)
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir)

            # Create log entry with timestamp
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_entry = f"[{timestamp}]" + log_message + "\n"

            # Append to the log file
            with open(self._log_file, 'a') as f:
                f.write(log_entry)


    def _get_target_data_from_observation(self, obs, target_id):
        """
        Extract target metadata from observation vector.

        Args:
            observation: Full observation numpy array
            target_id: ID of target to extract (0-indexed)

        Returns:
            dict with keys: 'target_status', 'target_whoflew_initial'
            Returns None if target_id is invalid
        """
        try:
            if target_id is None:
                self.log(f'Returning none, target_id is {target_id}')
                return None

            num_targets = int(obs[14])
            if target_id < 0 or target_id >= num_targets:
                self.log(f'Returning none, target_id is {target_id}, num targets is {num_targets}')
                return None

            base_size = 16
            target_data_size = 14
            start_idx = base_size + (target_id * target_data_size)

            return {
                'lat': obs[start_idx],
                'long': obs[start_idx + 1],
                'alt': obs[start_idx + 2],
                'reported_lat': obs[start_idx + 3],
                'reported_long': obs[start_idx + 4],
                'reported_alt': obs[start_idx + 5],
                'is_known_to_cockpit': obs[start_idx + 6],
                'spotted': obs[start_idx + 7],
                'handled': obs[start_idx + 8],
                'being_handled': obs[start_idx + 9],
                'human_in_range_time': obs[start_idx + 10],
                'wingman_in_range_time': obs[start_idx + 11],
                'target_status': obs[start_idx + 12],
                'target_whoflew_initial': obs[start_idx + 13]
            }
        except Exception as e:
            self.log(f'Error extracting target {target_id} from observation: {e}')
            traceback.print_exc()
            return None


    def _get_task_type_for_status(self, status):
        """Return task type needed for given fire status."""
        if status == 0.0:
            return 'classify'
        elif status == 1.0:
            return 'mark_position'
        elif status == 2.0:
            return 'initial_route'
        elif status == 3.0:
            return 'refine_route'
        return None

    def _get_task_eligibility(self, fire_id, task_type, obs):
        """Determine if human and wingman are eligible for this task.

        Args:
            fire_id: Target fire ID
            task_type: Type of task
            observation: Observation vector (optional, required for refine_route tasks)
        """
        if task_type in ['classify', 'mark_position', 'initial_route']:
            return True, True
        elif task_type == 'refine_route':
            # Read who flew initial route from observation
            if obs is not None:
                target_data = self._get_target_data_from_observation(obs, fire_id)
                if target_data is None:
                    return False, False
                who_flew_initial = target_data['target_whoflew_initial']
            else:
                # Fallback to getDREF if observation not provided (shouldn't happen)
                who_flew_initial = self.xpc.getDREF(f"custom/haato/target_whoflew_initial[{fire_id}]")
                warnings.warn(f'WARNING: _get_task_eligibility reached fallback to use datarefs. {fire_id} {task_type}')
            eligible_human = (who_flew_initial != 1.0)
            eligible_wingman = (who_flew_initial != 2.0)
            return eligible_human, eligible_wingman
        return False, False

    def _create_task(self, obs, fire, task_type, mission_timer=None, member_position=None):
        """Create task dictionary for given fire and task type."""
        # Get eligibility based on task type and who flew initial
        eligible_human, eligible_wingman = self._get_task_eligibility(fire.id, task_type, obs)

        # Calculate utility - use late-game mode if timer and position provided
        utility = 1.0
        if mission_timer is not None and member_position is not None:
            utility = self._calculate_late_game_utility(
                fire, task_type, member_position, mission_timer
            )

        return {
            'fire_id': fire.id,
            'task_type': task_type,
            'utility': utility,
            'target': fire,
            'eligible_human': eligible_human,
            'eligible_wingman': eligible_wingman
        }

    def _generate_tasks_from_fires(self, obs, fires, simulated_status=None, mission_timer=None, member_position=None):
        """
        Generate task list from fire states (same logic as Step 2).

        Args:
            obs: Observation vector
            fires: List of Target objects
            simulated_status: Optional numpy array of simulated fire statuses.
                            If provided, uses these instead of fire.status (for lookahead optimization)
            mission_timer: Optional mission timer for late-game mode
            member_position: Optional position for distance calculations

        Returns:
            List of task dictionaries
        """
        tasks = []

        for i, fire in enumerate(fires):
            # Use simulated status if provided, otherwise use fire.status
            status = simulated_status[i] if simulated_status is not None else fire.status

            if status == 0.0:
                tasks.append(self._create_task(obs, fire, 'classify', mission_timer, member_position))
            elif status == 1.0:
                tasks.append(self._create_task(obs, fire, 'mark_position', mission_timer, member_position))
            elif status == 2.0:
                tasks.append(self._create_task(obs, fire, 'initial_route', mission_timer, member_position))
            elif status == 3.0:
                # Refinement task with eligibility rules
                eligible_human, eligible_wingman = self._get_task_eligibility(fire.id, 'refine_route', obs)
                if eligible_human or eligible_wingman:
                    tasks.append(self._create_task(obs, fire, 'refine_route', mission_timer, member_position))

        return tasks

    def _get_fire_state_key(self, status_array, human_fire_id, wingman_fire_id, depth, effective_max_depth=None):
        """
        Create hashable cache key from current fire state and task assignment.

        Args:
            status_array: Numpy array of current fire statuses
            human_fire_id: Fire ID for human task (-1 if None)
            wingman_fire_id: Fire ID for wingman task (-1 if None)
            depth: Current recursion depth
            effective_max_depth: Effective max depth (for adaptive depth caching)

        Returns:
            Tuple: Hashable key for cache lookup
        """
        # Convert status array to tuple (hashable)
        status_tuple = tuple(status_array)
        # Include effective_max_depth to prevent stale cache hits when depth changes
        if effective_max_depth is not None:
            return (status_tuple, human_fire_id, wingman_fire_id, depth, effective_max_depth)
        else:
            return (status_tuple, human_fire_id, wingman_fire_id, depth)

    def _simulate_task_completion(self, current_status, human_task, wingman_task):
        """
        Create simulated fire states using status array (optimized, no deep copy).
        Returns numpy array of fire statuses instead of copying Target objects.

        This is ~30x faster than deep copying 8 Target objects.

        Args:
            current_status: Numpy array of current fire statuses
            human_task: Task dict for human (or None)
            wingman_task: Task dict for wingman (or None)

        Returns:
            Numpy array of simulated fire statuses
        """
        # Copy status array (8 floats = 64 bytes, very cheap)
        simulated_status = current_status.copy()

        # Update status for human's task (direct indexing, fire_id == index)
        if human_task:
            fire_id = human_task['fire_id']
            simulated_status[fire_id] = min(simulated_status[fire_id] + 1.0, 4.0)

        # Update status for wingman's task
        if wingman_task:
            fire_id = wingman_task['fire_id']
            simulated_status[fire_id] = min(simulated_status[fire_id] + 1.0, 4.0)

        return simulated_status

    def _calculate_late_game_utility(self, fire, task_type, member_position, mission_timer):
        """
        Calculate task utility in late-game mode.
        Prioritizes completable fires, but allows partial progress.
        """
        # Constants for time estimation (from config)
        AVG_CRUISE_SPEED_KNOTS = self.avg_cruise_speed_kts
        TASK_EXECUTION_TIMES = {
            'classify': 1.0,        # Minutes to complete task
            'mark_position': 1.5,
            'initial_route': 3.0,
            'refine_route': 3.0
        }

        fire_status = fire.status

        # Calculate time to reach fire
        distance_nm = GeoUtils.haversine_distance(
            member_position[0], member_position[1],
            fire.lat, fire.long
        )
        travel_time = (distance_nm / AVG_CRUISE_SPEED_KNOTS) * 60  # Convert to minutes

        # Estimate time to complete all remaining tasks on this fire
        # (Simplified: assumes this member does all remaining work)
        total_task_time = 0
        temp_status = fire_status
        while temp_status < 4.0:
            task_type_for_status = self._get_task_type_for_status(temp_status)
            total_task_time += TASK_EXECUTION_TIMES.get(task_type_for_status, 2.0)
            temp_status += 1.0

        estimated_completion_time = travel_time + total_task_time
        time_remaining = mission_timer

        # Calculate utility based on completion likelihood
        if estimated_completion_time <= time_remaining:
            # Fire is completable - prioritize based on how close to done
            completion_progress = fire_status / 4.0  # 0.0 to 0.75 (status 3)
            utility = 5.0 + (completion_progress * 10.0)  # 5.0 to 12.5
        else:
            # Fire probably won't complete
            # Still give partial credit for progress, but much lower
            completion_progress = fire_status / 4.0
            utility = 1.0 + (completion_progress * 2.0)  # 1.0 to 2.5

        return utility

    def _calculate_team_lookahead_value(
            self,
            obs,
            human_task,
            wingman_task,
            human_pos,
            wingman_pos,
            all_fires,
            depth,
            max_depth=2,
            discount=0.7,
            distance_weight=0.3,
            mission_timer=None,
            current_status=None,
            planning_start_time=None,
            max_planning_time=6.5
    ):
        """
        Calculate lookahead value for a team assignment considering future coordination.

        Args:
            human_task: Current task for human (or None)
            wingman_task: Current task for wingman (or None)
            human_pos: (lat, long) of human
            wingman_pos: (lat, long) of wingman
            all_fires: List of all fire Target objects (never modified, used for reference)
            depth: Current recursion depth
            max_depth: Maximum depth to search (2-3)
            discount: Future reward discount factor
            distance_weight: Weight for distance penalty
            mission_timer: Current mission timer for late-game mode
            current_status: Optional numpy array of current fire statuses (for optimization).
                          If None, will be extracted from all_fires.
            planning_start_time: Time when planning started (for adaptive depth)
            max_planning_time: Maximum planning time in seconds

        Returns:
            Total value including discounted future rewards
        """
        self.lookahead_count += 1

        # OPTIMIZATION: Adaptive lookahead depth based on time remaining
        effective_max_depth = max_depth
        if planning_start_time is not None:
            time_elapsed = time.time() - planning_start_time
            time_remaining_pct = 1.0 - (time_elapsed / max_planning_time)

            # Reduce depth when time budget is running low
            if time_remaining_pct < 0.5:  # Less than 50% time remaining
                effective_max_depth = 1  # Reduce to depth 1

        # Base case: reached effective max depth
        if depth >= effective_max_depth:
            return (0.0, {'best_followon_human': 99.0, 'best_followon_wingman': 99.0})

        # Extract current status if not provided (first call from plan)
        if current_status is None:
            current_status = np.array([fire.status for fire in all_fires], dtype=np.float32)

        # OPTIMIZATION PHASE 2: Check cache for this state
        # CRITICAL: Include effective_max_depth in cache key to avoid stale values
        cache_key = self._get_fire_state_key(
            current_status,
            human_task['fire_id'] if human_task else -1,
            wingman_task['fire_id'] if wingman_task else -1,
            depth,
            effective_max_depth
        )

        if cache_key in self._lookahead_cache:
            self._cache_stats['hits'] += 1
            # Cache stores float only; return with default metadata
            return (self._lookahead_cache[cache_key], {'best_followon_human': 99.0, 'best_followon_wingman': 99.0})

        self._cache_stats['misses'] += 1

        # Calculate immediate rewards for current tasks
        immediate_value = 0.0
        if human_task:
            immediate_value += human_task['utility']
        if wingman_task:
            immediate_value += wingman_task['utility']

        # Simulate completing these tasks - update fire states and positions
        # OPTIMIZATION: Returns status array instead of deep copying all fires (~30x faster)
        simulated_status = self._simulate_task_completion(current_status, human_task, wingman_task)
        new_human_pos = (human_task['target'].lat, human_task['target'].long) if human_task else human_pos
        new_wingman_pos = (wingman_task['target'].lat, wingman_task['target'].long) if wingman_task else wingman_pos

        # Generate future available tasks based on simulated state
        # OPTIMIZATION: Pass simulated_status array to avoid using deep-copied fires
        future_tasks = self._generate_tasks_from_fires(obs, all_fires, simulated_status, mission_timer, new_human_pos)

        # If no future tasks, return immediate value
        if not future_tasks:
            return (immediate_value, {'best_followon_human': 99.0, 'best_followon_wingman': 99.0})

        # OPTIMIZATION: Vectorize haversine distance calculations (16x reduction in function calls)
        # Extract all target coordinates as numpy arrays
        target_lats = np.array([t['target'].lat for t in future_tasks])
        target_lons = np.array([t['target'].long for t in future_tasks])

        # Single vectorized call for all human distances
        human_distances = GeoUtils.haversine_distance(
            new_human_pos[0], new_human_pos[1],
            target_lats, target_lons
        )

        # Single vectorized call for all wingman distances
        wingman_distances = GeoUtils.haversine_distance(
            new_wingman_pos[0], new_wingman_pos[1],
            target_lats, target_lons
        )

        # Assign distances and scores back to task dictionaries
        for i, task in enumerate(future_tasks):
            task['human_distance'] = human_distances[i]
            task['wingman_distance'] = wingman_distances[i]
            task['human_score'] = task['utility'] - (human_distances[i] * distance_weight)
            task['wingman_score'] = task['utility'] - (wingman_distances[i] * distance_weight)

        # Filter by eligibility
        human_eligible = [t for t in future_tasks if t['eligible_human']]
        wingman_eligible = [t for t in future_tasks if t['eligible_wingman']]

        # If no eligible tasks for either member, return immediate value
        if not human_eligible or not wingman_eligible:
            return (immediate_value, {'best_followon_human': 99.0, 'best_followon_wingman': 99.0})

        # Find best future assignment via recursive search
        best_future_value = 0.0
        best_followon_human_task = None
        best_followon_wingman_task = None

        for future_human_task in human_eligible:
            for future_wingman_task in wingman_eligible:
                # Avoid same-fire conflicts
                if future_human_task['fire_id'] == future_wingman_task['fire_id']:
                    continue

                # Recursively evaluate this future assignment
                # OPTIMIZATION: Pass simulated_status to avoid deep copying in recursive calls
                future_value, _ = self._calculate_team_lookahead_value(
                    obs,
                    future_human_task,
                    future_wingman_task,
                    new_human_pos,
                    new_wingman_pos,
                    all_fires,  # Always pass original fires (never modified)
                    depth + 1,
                    max_depth,
                    discount,
                    distance_weight,
                    mission_timer,
                    current_status=simulated_status,  # Pass simulated status to next level
                    planning_start_time=planning_start_time,
                    max_planning_time=max_planning_time
                )

                if future_value > best_future_value:
                    best_future_value = future_value
                    # Capture follow-on tasks ONLY at depth 0 (for immediate next move)
                    if depth == 0:
                        best_followon_human_task = future_human_task
                        best_followon_wingman_task = future_wingman_task

        # Calculate total value
        total_value = immediate_value + (discount * best_future_value)

        # OPTIMIZATION PHASE 2: Store result in cache before returning
        self._lookahead_cache[cache_key] = total_value

        # Build metadata dictionary with follow-on tasks (only meaningful at depth 0)
        metadata = {}
        if depth == 0 and best_followon_human_task and best_followon_wingman_task:
            metadata['best_followon_human'] = float(best_followon_human_task['fire_id'])
            metadata['best_followon_wingman'] = float(best_followon_wingman_task['fire_id'])
        else:
            metadata['best_followon_human'] = 99.0
            metadata['best_followon_wingman'] = 99.0

        return (total_value, metadata)

    def plan(self, obs) -> dict:
        """
        Generate a heuristic-based team plan for human and wingman.

        Uses a greedy heuristic to maximize total team utility by assigning tasks
        based on fire status, member positions, and distance. Only suggests plan
        changes if the new plan provides 30%+ improvement over current plans.

        Returns:
            dict with keys:
                'human_plan': float (0-7: Fire ID, 99.0: No change)
                'wingman_plan': float (0-7: Fire ID, 99.0: No change)
                'second_best_human_plan': float (second-best assignment)
                'second_best_wingman_plan': float (second-best assignment)
                'best_followon_human': float (next task after best plan)
                'best_followon_wingman': float (next task after best plan)
                'second_best_followon_human': float (next task after second-best)
                'second_best_followon_wingman': float (next task after second-best)
                'rationale': str ('prioritizing feasible fires for endgame' | 'normal searching')
                'mode': str ('endgame' | 'normal')
        """
        self.log(f'[plan] Starting')
        self.lookahead_count = 0

        # OPTIMIZATION PHASE 2: Clear lookahead cache for new planning cycle
        self._lookahead_cache.clear()
        self._cache_stats = {'hits': 0, 'misses': 0}

        # Tunable weights for balancing utility vs distance (from config)
        UTILITY_WEIGHT = self.utility_weight
        DISTANCE_WEIGHT = self.distance_weight

        # Enhancement parameters (from config)
        LATE_GAME_THRESHOLD_MINUTES = self.late_game_threshold_minutes
        PROXIMITY_THRESHOLD_NM = self.proximity_threshold_nm
        PROXIMITY_BONUS = self.proximity_bonus
        LOOKAHEAD_DEPTH = self.lookahead_depth
        LOOKAHEAD_DISCOUNT = self.lookahead_discount

        # OPTIMIZATION: Planning timeout (from config)
        MAX_PLANNING_TIME = self.max_planning_time_s


        # ============================== STEP 1: Parse Current State ===================================================
        try:
            mission_timer = obs[0]
            human_lat = obs[1]
            human_long = obs[2]
            # Read from observation vector instead of getDREF
            human_indicated_plan = obs[11]  # custom/haato/human_indicated_plan

            # Get wingman position
            wingman_lat = self.lat
            wingman_long = self.long

            # Wingman's current goal (fire ID or -1 if none) - read from observation
            wingman_current_goal = obs[12]  # custom/haato/wingman_status
            plan_for_wingman = obs[13]  # custom/haato/plan_for_wingman
        except Exception as e:
            self.log(f'    Error parsing current state: {e}')
            traceback.print_exc()
            return {'human_plan': 99.0, 'wingman_plan': 99.0, 'show_plan': 0.0}


        # ============================== STEP 2: Build Available Task Lists ============================================
        # Read all fire status and classification datarefs

        fire_tasks = []  # List of (fire_id, task_type, utility)

        # Check if in late-game mode
        in_late_game_mode = mission_timer < LATE_GAME_THRESHOLD_MINUTES
        human_pos = (human_lat, human_long)
        wingman_pos = (wingman_lat, wingman_long)

        for fire_id in range(self.mm.num_targets):
            try:
                # Get fire status from observation vector
                target_data = self._get_target_data_from_observation(obs, fire_id)
                if target_data is None:
                    self.log(f'    Fire ID {fire_id} out of range')
                    warnings.warn(f'WARNING')
                    continue

                status = target_data['target_status']

                if fire_id >= len(self.mm.targets):
                    warnings.warn(f'    Fire ID {fire_id} out of range', UserWarning)
                    continue

                target = self.mm.targets[fire_id]

                # Determine required task based on status
                if status == 0.0:  # Unclassified - needs classification
                    # Calculate utility (late-game mode if applicable)
                    utility = 1.0
                    if in_late_game_mode:
                        utility = self._calculate_late_game_utility(target, 'classify', human_pos, mission_timer)

                    fire_tasks.append({
                        'fire_id': fire_id,
                        'task_type': 'classify',
                        'utility': utility,
                        'target': target,
                        'eligible_human': True,
                        'eligible_wingman': not fire_id == int(human_indicated_plan)
                    })
                elif status == 1.0:  # Spotted - needs position marking
                    utility = 1.5
                    if in_late_game_mode:
                        utility = self._calculate_late_game_utility(target, 'mark_position', human_pos, mission_timer)

                    #if self.current_route_target != fire_id and self.marking_position_target != fire_id:
                    fire_tasks.append({
                        'fire_id': fire_id,
                        'task_type': 'mark_position',
                        'utility': utility,
                        'target': target,
                        'eligible_human': self.current_route_target != fire_id and self.marking_position_target != fire_id, # Don't tell human to do something wingman is already doing
                        'eligible_wingman': not fire_id == int(human_indicated_plan)
                    })
                elif status == 2.0:  # Position marked - needs initial drop route
                    utility = 1.5
                    if in_late_game_mode:
                        utility = self._calculate_late_game_utility(target, 'initial_route', human_pos, mission_timer)

                    #if self.current_route_target != fire_id and self.marking_position_target != fire_id:
                    fire_tasks.append({
                        'fire_id': fire_id,
                        'task_type': 'initial_route',
                        'utility': utility,
                        'target': target,
                        'eligible_human': self.current_route_target != fire_id and self.marking_position_target != fire_id, # Don't tell human to do something wingman is already doing
                        'eligible_wingman': not fire_id == int(human_indicated_plan)
                    })
                elif status == 3.0:  # Initial route complete - refinement
                    # Filter: can't refine own route - read from observation
                    who_flew = target_data['target_whoflew_initial']
                    eligible_human = who_flew != 1.0  # Human can refine if didn't fly initial
                    eligible_wingman = who_flew != 2.0 and not fire_id == int(human_indicated_plan) # Wingman can refine if didn't fly initial

                    if eligible_human or eligible_wingman:
                        utility = 2
                        if in_late_game_mode:
                            utility = self._calculate_late_game_utility(target, 'refine_route', human_pos, mission_timer)

                        fire_tasks.append({
                            'fire_id': fire_id,
                            'task_type': 'refine_route',
                            'utility': utility,
                            'target': target,
                            'eligible_human': eligible_human,
                            'eligible_wingman': eligible_wingman
                        })

            except Exception as e:
                self.log(f'    Error processing fire {fire_id}: {e}')
                traceback.print_exc()
                continue

        # If no tasks available, return no plans
        if len(fire_tasks) == 0:
            team_plan = {
                'human_plan': 99.0,
                'wingman_plan': 99.0,
                'second_best_human_plan': 99.0,
                'second_best_wingman_plan': 99.0,
                'best_followon_human': None,
                'best_followon_wingman': None,
                'second_best_followon_human': None,
                'second_best_followon_wingman': None,
                'rationale': 'default',
                'planning_mode': 'default',
                'show_plan': 1.0
            }
            return team_plan

        # ===== STEP 3: Calculate Distances and Adjusted Scores (VECTORIZED) =====
        target_lats = np.array([task['target'].lat for task in fire_tasks])
        target_lons = np.array([task['target'].long for task in fire_tasks])

        # Single vectorized call for all distances
        human_distances = GeoUtils.haversine_distance(human_lat, human_long, target_lats, target_lons)
        wingman_distances = GeoUtils.haversine_distance(wingman_lat, wingman_long, target_lats, target_lons)

        # Assign distances and scores back to task dictionaries
        for i, task in enumerate(fire_tasks):
            task['human_distance'] = human_distances[i]
            task['wingman_distance'] = wingman_distances[i]

            # Calculate distance-adjusted scores (higher = better)
            # Score = utility * weight - distance_penalty
            task['human_score'] = (task['utility'] * UTILITY_WEIGHT - task['human_distance'] * DISTANCE_WEIGHT)
            task['wingman_score'] = (task['utility'] * UTILITY_WEIGHT - task['wingman_distance'] * DISTANCE_WEIGHT)


        # ===== STEP 4: Find Optimal Task Assignments with Lookahead and Proximity =====
        # Try all valid (human_task, wingman_task) combinations
        best_score = float('-inf')
        best_human_task = None
        best_wingman_task = None
        best_followon_metadata = {'best_followon_human': 99.0, 'best_followon_wingman': 99.0}

        second_best_score = float('-inf')
        second_best_human_task = None
        second_best_wingman_task = None
        second_best_followon_metadata = {'best_followon_human': 99.0, 'best_followon_wingman': 99.0}

        # Create list of tasks eligible for each member
        human_eligible_tasks = [t for t in fire_tasks if t['eligible_human']]
        wingman_eligible_tasks = [t for t in fire_tasks if t['eligible_wingman']]
        human_candidates = human_eligible_tasks if human_eligible_tasks else [None]
        wingman_candidates = wingman_eligible_tasks if wingman_eligible_tasks else [None]

        # Count unrefined fires for proximity bonus logic - read from observation
        unrefined_count = 0
        for target in self.mm.targets:
            target_data = self._get_target_data_from_observation(obs, target.id)
            if target_data is not None and target_data['target_status'] < 4.0:
                unrefined_count += 1

        # OPTIMIZATION: Anytime algorithm - initialize with greedy solution (no lookahead)
        # This ensures we always have a valid plan even if timeout occurs
        greedy_best_score = float('-inf')
        for human_task in human_candidates:
            for wingman_task in wingman_candidates:
                # Safe ID and Score extraction handling None
                h_id = human_task['fire_id'] if human_task else -1
                w_id = wingman_task['fire_id'] if wingman_task else -2  # -2 ensures no accidental match with -1

                h_score = human_task['human_score'] if human_task else 0.0
                w_score = wingman_task['wingman_score'] if wingman_task else 0.0

                if h_id == w_id:
                    # Conflict: Same fire. Pick the agent with higher score, idle the other.
                    if h_score > w_score:
                        greedy_score = h_score
                        human_task_for_storage = human_task
                        wingman_task_for_storage = None
                    else:
                        greedy_score = w_score
                        human_task_for_storage = None
                        wingman_task_for_storage = wingman_task

                    if greedy_score > greedy_best_score:
                        greedy_best_score = greedy_score
                        best_human_task = human_task_for_storage
                        best_wingman_task = wingman_task_for_storage
                        best_followon_metadata = {'best_followon_human': 99.0, 'best_followon_wingman': 99.0}

                else: # No conflict
                    greedy_score = h_score + w_score

                    if greedy_score > greedy_best_score:
                        greedy_best_score = greedy_score
                        best_human_task = human_task
                        best_wingman_task = wingman_task
                        best_followon_metadata = {'best_followon_human': 99.0, 'best_followon_wingman': 99.0}

        # build and sort candidate pairs by heuristic score
        candidate_pairs = []
        for human_task in human_candidates:
            for wingman_task in wingman_candidates:
                h_id = human_task['fire_id'] if human_task else -1
                w_id = wingman_task['fire_id'] if wingman_task else -2

                if h_id == w_id:
                    continue  # Skip same-fire conflicts in detailed search

                # Heuristic score (safe access)
                h_score = human_task['human_score'] if human_task else 0.0
                w_score = wingman_task['wingman_score'] if wingman_task else 0.0

                heuristic_score = h_score + w_score
                candidate_pairs.append((heuristic_score, human_task, wingman_task))

        # Sort by heuristic score (descending - best candidates first)
        candidate_pairs.sort(key=lambda x: x[0], reverse=True)

        # Time-based early exit to guarantee planning completes within timeout
        planning_start_time = time.time()
        timeout_flag = False

        # Track consecutive non-improvements to detect when we've found the optimum
        no_improvement_count = 0
        NO_IMPROVEMENT_THRESHOLD = 10

        # Evaluate candidates in sorted order (best first)
        for heuristic_score, human_task, wingman_task in candidate_pairs:
            # Check timeout before expensive lookahead calculation
            if time.time() - planning_start_time > MAX_PLANNING_TIME:
                timeout_flag = True
                self.log(f"    [TIMEOUT] Planning exceeded {MAX_PLANNING_TIME}s, returning best plan found")
                break  # Exit loop with best plan found so far

            h_score = human_task['human_score'] if human_task else 0.0
            w_score = wingman_task['wingman_score'] if wingman_task else 0.0
            immediate_score = h_score + w_score

            # Calculate lookahead value and follow-on metadata
            lookahead_value, followon_metadata = self._calculate_team_lookahead_value(
                obs,
                human_task,
                wingman_task,
                human_pos,
                wingman_pos,
                self.mm.targets,
                depth=0,
                max_depth=LOOKAHEAD_DEPTH,
                discount=LOOKAHEAD_DISCOUNT,
                distance_weight=DISTANCE_WEIGHT,
                mission_timer=mission_timer if in_late_game_mode else None,
                planning_start_time=planning_start_time,
                max_planning_time=MAX_PLANNING_TIME
            )

            # Combined score = immediate + lookahead
            combined_score = immediate_score + lookahead_value

            if combined_score > best_score:
                # Old best becomes second-best
                second_best_score = best_score
                second_best_human_task = best_human_task
                second_best_wingman_task = best_wingman_task
                second_best_followon_metadata = best_followon_metadata

                # Update best
                best_score = combined_score
                best_human_task = human_task
                best_wingman_task = wingman_task
                best_followon_metadata = followon_metadata
                no_improvement_count = 0  # Reset counter on improvement
            elif combined_score > second_best_score:
                # Update second-best without affecting best
                second_best_score = combined_score
                second_best_human_task = human_task
                second_best_wingman_task = wingman_task
                second_best_followon_metadata = followon_metadata
                no_improvement_count += 1
            else:
                no_improvement_count += 1

            # Early exit if confident we found the optimum
            if no_improvement_count >= NO_IMPROVEMENT_THRESHOLD and best_human_task is not None:
                break

        # ===== STEP 5: Evaluate Against Current Plans =====
        # Calculate current plan scores (distance-adjusted)
        current_human_score = float('-inf')
        current_wingman_score = float('-inf')

        if self.verbose:
            try:
                print(f'    best_human_task: {best_human_task["task_type"]} {best_human_task["fire_id"]}')
            except (TypeError, KeyError):
                pass
            try:
                print(f'    best wingman task: {best_wingman_task["task_type"]} {best_wingman_task["fire_id"]}')
            except (TypeError, KeyError):
                pass

        # Human's current plan score
        current_human_task = None
        if human_indicated_plan >= 0.0 and human_indicated_plan <= 7.0:
            human_current_fire_id = int(human_indicated_plan)
            # Find the task for this fire
            for task in fire_tasks:
                if task['fire_id'] == human_current_fire_id and task['eligible_human']:
                    current_human_score = task['human_score']
                    current_human_task = task
                    break

        # Wingman's current plan score
        if wingman_current_goal >= 0 and wingman_current_goal <= 7:
            # Find the task for this fire
            for task in fire_tasks:
                if task['fire_id'] == wingman_current_goal and task['eligible_wingman']:
                    current_wingman_score = task['wingman_score']
                    break

        # Determine if we should change plans (30% threshold)
        human_plan = 99.0  # Default: no change
        #wingman_plan = wingman_current_goal  # Default: no change

        # Evaluate human plan change
        if best_human_task is not None:
            new_human_score = best_human_task['human_score']

            # If human has no current plan, always suggest new plan
            if human_indicated_plan < 0.0 or human_indicated_plan == 99.0:
                human_plan = float(best_human_task['fire_id'])
                self.log(f'    Human indicated plan is none. Sending new plan suggestion')

            # If current plan score is very low, suggest new plan
            elif current_human_score <= 0.0:
                human_plan = float(best_human_task['fire_id'])
                self.log(f'    Human indicated plan is not optimal. Sending new plan suggestion')

            else: # Calculate improvement based on distance-adjusted scores
                try:
                    if abs(current_human_score) < 0.001:  # Effectively zero
                        if new_human_score > 1.0:  # Significant positive improvement
                            improvement = 1.0  # Treat as 100% improvement
                        else:
                            improvement = 0.0
                    else:
                        improvement = (new_human_score - current_human_score) / abs(current_human_score)
                except (ZeroDivisionError, TypeError):
                    improvement = 0.0

                if improvement >= 0.3:  # 30% threshold
                    human_plan = float(best_human_task['fire_id'])
                    self.log(f'    SENDING HUMAN PLAN (New plan is >30% better than human current plan)')
                else:
                    human_plan = float(current_human_task['fire_id']) # Repeat human's current plan
                    self.log(f'    NOT SENDING HUMAN PLAN: New plan is {improvement:.1%} better than human current plan')

        # Evaluate wingman plan change
        if best_wingman_task is not None:
            # If wingman has no current goal, always suggest new plan
            if wingman_current_goal < 0 or plan_for_wingman in [99.0]:
                wingman_plan = float(best_wingman_task['fire_id'])
                self.log(f'wingman_plan = {wingman_plan}')

            # If current plan score is very low, suggest new plan
            elif current_wingman_score <= 0.0:
                wingman_plan = float(best_wingman_task['fire_id'])
            else:
                wingman_plan = float(best_wingman_task['fire_id'])

        else:
            wingman_plan = wingman_current_goal
            self.log(f'No wingman task found, keeping current goal: {wingman_current_goal}')

        # ===== Build second-best plan values =====
        if second_best_human_task is None:
            second_best_human_plan = 99.0
            second_best_wingman_plan = 99.0
            second_best_followon_human = 99.0
            second_best_followon_wingman = 99.0
        else:
            try:
                second_best_human_plan = float(second_best_human_task['fire_id'])
            except (TypeError, KeyError):
                second_best_human_plan = 99.0

            try:
                second_best_wingman_plan = float(second_best_wingman_task['fire_id'])
            except (TypeError, KeyError):
                second_best_wingman_plan = 99.0

            try:
                second_best_followon_human = second_best_followon_metadata['best_followon_human']
            except (TypeError, KeyError):
                second_best_followon_human = 99.0

            try:
                second_best_followon_wingman = second_best_followon_metadata['best_followon_wingman']
            except (TypeError, KeyError):
                second_best_followon_wingman = 99.0


        # ===== STEP 6: Return Plan Dictionary =====
        wingman_plan = float(wingman_plan) # Convert from numpy float to python float
        rationale = 'default'
        mode = 'default'
        team_plan = {
            'human_plan': human_plan,
            'wingman_plan': wingman_plan,
            'second_best_human_plan': second_best_human_plan,
            'second_best_wingman_plan': second_best_wingman_plan,
            'best_followon_human': best_followon_metadata['best_followon_human'],
            'best_followon_wingman': best_followon_metadata['best_followon_wingman'],
            'second_best_followon_human': second_best_followon_human,
            'second_best_followon_wingman': second_best_followon_wingman,
            'rationale': rationale,
            'planning_mode': mode,
            #'type': 'task_notification' if self.initiative_level == 1.0 else 'plan_suggestion'
        }
        self.current_plan_for_self = wingman_plan
        self.latest_plan = team_plan

        if self.verbose:
            planning_elapsed = time.time() - planning_start_time
            print(f'    TEAM PLAN: Wingman = {wingman_plan} | human = {human_plan}')
            print(f'    Total lookahead calls: {self.lookahead_count}')
            print(f"    Planning time: {planning_elapsed:.3f}s")
            total_cache_checks = self._cache_stats['hits'] + self._cache_stats['misses']
            if total_cache_checks > 0:
                hit_rate = self._cache_stats['hits'] / total_cache_checks
                print(f"    Lookahead cache: {hit_rate:.1%} hit rate ({self._cache_stats['hits']}/{total_cache_checks})")

        return team_plan


    def _calc_route_waypoint(self, target, waypoint_type):
        """
        Calculate route waypoint position based on wind direction.

        Args:
            target: Target object
            waypoint_type: 'route_start' or 'route_end'

        Returns:
            (lat, lon, alt) tuple for the waypoint
        """

        if waypoint_type == 'route_start':
            # 2 NM upwind from target (towards the wind source)
            distance_nm = self.required_drop_route_length
            bearing = (self.wind_direction + self.mag_declination + 180) % 360  # Opposite of wind direction
        else:  # route_end
            # 1 NM downwind from target (with the wind)
            distance_nm = self.required_drop_route_length / 2
            bearing = self.wind_direction + self.mag_declination

        # Calculate waypoint using great circle navigation
        lat_rad = math.radians(target.lat)
        lon_rad = math.radians(target.long)
        bearing_rad = math.radians(bearing)

        # Angular distance in radians
        angular_distance = distance_nm / 3440.065

        # Calculate new position
        waypoint_lat_rad = math.asin(
            math.sin(lat_rad) * math.cos(angular_distance) +
            math.cos(lat_rad) * math.sin(angular_distance) * math.cos(bearing_rad)
        )

        waypoint_lon_rad = lon_rad + math.atan2(
            math.sin(bearing_rad) * math.sin(angular_distance) * math.cos(lat_rad),
            math.cos(angular_distance) - math.sin(lat_rad) * math.sin(waypoint_lat_rad)
        )

        waypoint_lat = math.degrees(waypoint_lat_rad)
        waypoint_lon = math.degrees(waypoint_lon_rad)
        waypoint_alt = target.alt + self.mm.required_alt_fire_agl/3 # Target altitude + 500ft

        return (waypoint_lat, waypoint_lon, waypoint_alt)

    def _calc_hsa_to_route_waypoint(self, waypoint_lat, waypoint_lon, waypoint_alt):
        """
        Calculate HSA to fly to a route waypoint.

        Args:
            waypoint_lat, waypoint_lon, waypoint_alt: Waypoint position

        Returns:
            (heading, speed, altitude) tuple
        """
        # Calculate bearing to waypoint
        bearing = self._calculate_bearing(self.lat, self.long, waypoint_lat, waypoint_lon)

        # Calculate distance
        distance = self._calculate_distance(self.lat, self.long, waypoint_lat, waypoint_lon)

        # Speed management
        desired_spd = self.max_speed if distance > 5 else self.default_spd

        # Altitude management
        desired_alt = waypoint_alt

        return (bearing, desired_spd, desired_alt)

    def _at_route_waypoint(self, waypoint_lat, waypoint_lon):
        """
        Check if wingman is at a route waypoint.

        Args:
            waypoint_lat, waypoint_lon: Waypoint position

        Returns:
            bool: True if within tolerance
        """
        distance = self._calculate_distance(self.lat, self.long, waypoint_lat, waypoint_lon)
        return distance <= self.route_waypoint_tolerance

    def _execute_position_marking(self, obs, target):
        """
        Execute position marking behavior - fly directly over fire and mark its GPS position.

        State machine:
        1. Fly to overfly position (directly over fire)
        2. Mark position when within tolerance
        3. Update target status to 2.0

        Args:
            observation: Current observation array
            target: Target object to mark position for

        Returns:
            dict: Action dict with type='hsa', goal=(h,s,a), message=str
        """
        distance_to_target = self._calculate_distance(self.lat, self.long, target.lat, target.long)

        # Initialize state if starting new position marking
        if self.marking_position_target != target.id or self.position_marking_stage is None:
            self.current_route_target = None # TODO added. Clears state machine for other mode
            self.route_marking_stage = None

            self.marking_position_target = target.id
            self.position_marking_stage = 'flying_to_overfly'
            self.status = float(target.id)

        self.log(f'        [_execute_position_marking] - Target {target.id} - Stage = {self.position_marking_stage} - distance {distance_to_target:.2f}nm')

        # Execute based on current stage
        if self.position_marking_stage == 'flying_to_overfly': # Calculate HSA to fly directly over the fire
            try:
                target_index = self.mm.target_id_to_index.get(target.id, None)
                if target_index is not None and target_index >= len(self.mm.targets):
                    self.log(f'Target index {target_index} out of range')
                    target_index = None
            except Exception as e:
                self.log(f'Error getting target index: {e}')
                traceback.print_exc()
                target_index = None


            if target_index is not None:
                goal_hsa = self._calc_hsa_to_target(obs, target_index)

            else: # Fallback if target index not found
                goal_hsa = self._calc_hsa_holding_pattern(self.lat, self.long, self.alt,obs[0])
                message = 'Holding'


            # Check if within overfly range

            if distance_to_target <= self.overfly_tolerance:
                self.log(f'        Within overfly tolerance {self.overfly_tolerance}nm, marking position')
                # Mark the position
                target.marked_position = (self.lat, self.long)
                target.position_recorder = 'wingman_0'  # Track who marked the position

                # Update status dataref to 2.0
                self.xpc.sendDREF(f"custom/haato/target_status[{target.id}]", 2.0)
                target.position_recorded_by_wingman = True

                self.status = float(target.id)
                self.position_marking_stage = 'complete'

                # Reset state for next task
                self.marking_position_target = None
                self.position_marking_stage = None

            message = f'Overfly {target.id}'

            return goal_hsa, message

        # Default fallback
        goal_hsa = self._calc_hsa_holding_pattern(self.lat, self.long, self.alt,obs[0])  # (self.hdg, self.default_spd, self.alt)
        message = 'Holding'

        self.log(f'        [_execute_route_marking] Reached fallback, holding')
        return goal_hsa, message


    def _execute_route_marking(self, obs, target, route_type):
        """
        Execute the route marking behavior for a target.

        State machine:
        1. Fly to route start waypoint
        2. Mark start position
        3. Fly to route end waypoint
        4. Mark end position
        5. Update target status

        Args:
            obs: Current observation array
            target: Target object to mark route for
            route_type: 'initial' or 'refined'

        Returns:
            dict: Action dict with type='hsa', goal=(h,s,a), message=str
        """

        # Initialize state if starting new route
        if self.current_route_target != target.id or self.route_marking_stage is None:
            self.marking_position_target = None
            self.position_marking_stage = None # TODO added, test

            self.current_route_target = target.id
            self.route_marking_stage = 'flying_to_start'
            self.route_type = route_type
            self.status = float(target.id)

        # Create message for action
        route_label = 'initial' if route_type == 'initial' else 'refined'
        message = f'Mark {route_label} route {target.id}'

        self.log(f'        [_execute_route_marking] - Target {target.id} - Stage = {self.route_marking_stage}')

        # Calculate waypoints
        start_waypoint = self._calc_route_waypoint(target, 'route_start')
        end_waypoint = self._calc_route_waypoint(target, 'route_end')

        # Execute based on current stage
        if self.route_marking_stage == 'flying_to_start':
            #goal_hsa = self._calc_hsa_to_route_waypoint(start_waypoint[0], start_waypoint[1], start_waypoint[2])
            goal_hsa = self._calc_hsa_to_route_waypoint(start_waypoint[0], start_waypoint[1], self.mm.required_cruise_altitude_ft/3)

            # Check if reached start waypoint
            if self._at_route_waypoint(start_waypoint[0], start_waypoint[1]):
                self.route_marking_stage = 'flying_route'
                self.route_start_time = self.mm.mission_timer

                # Mark start position
                if route_type == 'initial':
                    target.route1_start = (self.lat, self.long)
                    target.route1_recorder = 'wingman_0'
                    self.log(f'        AT ROUTE WAYPOINT {start_waypoint} (wingman is at {self.lat, self.long}), set route1 start')
                elif route_type == 'refined':
                    self.log(f'        AT ROUTE WAYPOINT {start_waypoint} (wingman is at {self.lat, self.long}), set route2 start')
                    target.route2_start = (self.lat, self.long)
                    target.route2_recorder = 'wingman_0'

                self.status = float(target.id)

            return goal_hsa, message

        elif self.route_marking_stage == 'flying_route':
            goal_hsa = self._calc_hsa_to_route_waypoint(end_waypoint[0], end_waypoint[1], end_waypoint[2])

            # Check if reached end waypoint
            if self._at_route_waypoint(end_waypoint[0], end_waypoint[1]):
                self.route_marking_stage = 'complete'

                # Mark end position
                if route_type == 'initial':
                    self.log(f'        At route end waypoint {end_waypoint} (wingman is at {self.lat, self.long}), recording fire {target.id} initial drop route')
                    target.route1_end = (self.lat, self.long)
                    target.initial_drop_route_complete = True

                    target_data = self._get_target_data_from_observation(obs, target.id)

                    if target_data is not None:
                        if target_data['target_status'] == 3.0: # Human beat us to it
                            self.xpc.sendDREF(f"custom/haato/target_status[{target.id}]", 4.0)
                        else:
                            self.xpc.sendDREF(f"custom/haato/target_status[{target.id}]", 3.0)
                            self.xpc.sendDREF(f"custom/haato/target_whoflew_initial[{target.id}]", 2.0)
                    else:
                        self.xpc.sendDREF(f"custom/haato/target_status[{target.id}]", 3.0)
                        self.xpc.sendDREF(f"custom/haato/target_whoflew_initial[{target.id}]", 2.0)

                    self.status = float(target.id)

                elif route_type == 'refined':
                    self.log(f'        At route end waypoint {end_waypoint} (wingman is at {self.lat, self.long}), recording fire {target.id} initial drop route')
                    target.route2_end = (self.lat, self.long)
                    target.refined_drop_route_complete = True
                    self.xpc.sendDREF(f"custom/haato/target_status[{target.id}]", 4.0)
                    self.status = float(target.id)

                # Reset state for next task
                self.current_route_target = None
                self.route_marking_stage = None
                self.route_type = None

            return goal_hsa, message

        # Default fallback
        goal_hsa = self._calc_hsa_holding_pattern(self.lat, self.long, self.alt, obs[0]) #(self.hdg, self.default_spd, self.alt)
        self.log(f'        [_execute_route_marking] Reached fallback, holding')
        return goal_hsa, message
