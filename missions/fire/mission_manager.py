"""Defines the mission manager and wingman agent for the Firewatch mission."""

import logging
import math
import os
import traceback
from datetime import datetime
from typing import Tuple
import numpy as np

from missions.fire.types import MissionRuntimeState
from utility.base_classes import MissionManager, GeoUtils, Target
from utility.haato_udp import HaatoUDPBridge
from utility.message_queue import Message, MessageQueue, MessageLogger
from utility.agent_voice import PiperTTSVoice

from missions.fire.config import load_fire_mission_config
from missions.fire.constants import DREF_PAUSED, DREF_RESET_WINGMAN, NO_COMMAND
from utility.config_loader import get_config
from missions.fire.dref_io import FireMissionDrefIO
from missions.fire.message_bridge import FireMessageBridge
from missions.fire.observation import build_wingman_observation
from missions.fire.wingman.agent import FireWatchWingman

def build_runtime_state() -> MissionRuntimeState:
    return MissionRuntimeState()

logger = logging.getLogger(__name__)


class FireWatchMM(MissionManager):
    @staticmethod
    def _team_plan_signature(plan: dict | None):
        if not plan:
            return None
        return (
            float(plan.get("human_plan", 99.0)),
            float(plan.get("wingman_plan", 99.0)),
            float(plan.get("second_best_human_plan", 99.0)),
            float(plan.get("second_best_wingman_plan", 99.0)),
            float(plan.get("best_followon_human", 99.0)),
            float(plan.get("best_followon_wingman", 99.0)),
            float(plan.get("second_best_followon_human", 99.0)),
            float(plan.get("second_best_followon_wingman", 99.0)),
            float(plan.get("rationale_code", 99.0)),
            float(plan.get("planning_mode_code", 99.0)),
            1.0 if plan.get("show_plan") else 0.0,
        )

    def __init__(self, user_id, xpc, fire_layout, initiative_level, log_file_identifier, control_prefix = 'thrustmaster', verbose=False, dev_mode=False, num_wingmen = 1, sim_human=None, noreset=False, resume=False, testing_wingman = False):
        super().__init__(user_id, xpc, dev_mode, num_wingmen)

        self.user_id = user_id  # Participant ID for studies. Default 99 for testing
        self.log_file_identifier = log_file_identifier
        self.xpc = xpc
        self.verbose = verbose
        self.dev_mode = dev_mode
        self.fire_layout = fire_layout # Layout number (1-3) determines which target file to use
        self.initiative_level = initiative_level  # 0=Low, 1=Medium, 2=High
        self.control_prefix = control_prefix
        self.sim_human = sim_human
        self.noreset = noreset
        self.resume = resume

        self.testing_wingman = testing_wingman
        self.runtime = build_runtime_state()
        self.start_time_offset = 0

        # Load targets based on layout number
        self.load_mission_config(None)
        self.num_targets = len(self.targets)

        ################################# CONFIGURATION ################################################################

        _cfg = get_config()
        _mp = _cfg["mission_parameters"]
        _fm = _cfg["flight_model"]

        self.visual_detection_range = _mp["visual_detection_range_nm"]
        self.max_mission_time = _mp["max_mission_time_s"]
        self.wingman_action_frequency = _mp["wingman_action_frequency"]

        # Human and wingman start conditions
        self.human_lla = self.human_spawn_lla  # For tracking
        self.human_hdg, self.human_spd = None, None

        self.ai_default_spd = _fm["ai_default_spd_kts"]
        self.ai_start_hdg = _fm["ai_start_hdg_deg"]

        self.hdg_tolerance = _fm["hdg_tolerance_deg"]
        self.spd_tolerance = _fm["spd_tolerance_kts"]
        self.alt_tolerance = _fm["alt_tolerance_m"]
        self.hdg_rate = _fm["hdg_rate_deg_per_s"]
        self.spd_rate = _fm["spd_rate_kts_per_s"]
        self.alt_rate = _fm["alt_rate_m_per_s"]

        self.debug_print_freq = 120  # How often to print debug logs
        if self.testing_wingman:
            self.ai_default_spd *= 2

        self.debug_modes = {
            'move_ai_hsa': False
        }

        ################################# INIT ENTITIES ################################################################

        # Initialize messaging system
        self.message_queue = MessageQueue(max_size=50)
        self.message_logger = MessageLogger(log_file_identifier=log_file_identifier, user_id=user_id, fire_layout=fire_layout, initiative_level=initiative_level)

        # Pre-build message codes dictionary and target position arrays
        self._build_message_codes()
        self._init_vectorized_arrays()

        # Set dref names here (they are all defined in custom_datarefs.lua)
        self.help_request_dref = "custom/haato/help_request"
        self.help_request_response_dref = "custom/haato/help_request_response"
        self.udp_bridge = HaatoUDPBridge(logger=self.log)
        self.udp_bridge.start()
        self.dref_io = FireMissionDrefIO(self)
        self.message_bridge = FireMessageBridge(self)

        #################################### GEOMETRY SETUP ############################################################

        self.aor_center = tuple(_mp["aor_center"])
        self.aor_size = _mp["aor_size_nm"]
        self.airfield_lla = tuple(_mp["airfield_lla"])
        self.airport_elevation = _mp["airport_elevation_m"]

        aor_size_lat, aor_size_lon = self.aor_size / 60, self.aor_size / 60 * math.cos(math.radians(self.aor_center[0]))
        self.aor_bounds = [  # Lat, long bounds for the mission. Format: [latmin, latmax, longmin, longmax]
            self.aor_center[0] - aor_size_lat / 2,  # Latmin
            self.aor_center[0] + aor_size_lat / 2,  # Latmax
            self.aor_center[1] - aor_size_lon / 2,  # Longmin
            self.aor_center[1] + aor_size_lon / 2  # Longmax
        ]

        self.inv_earth_radius_nm = 1.0 / 3440.065  # Inverse earth radius for faster calculation

        ################################# TRACKING ATTRIBUTES ##########################################################

        # Track last dataref values to detect changes
        self._last_human_command = NO_COMMAND
        self._last_request_response = 0.0  # Neutral value for request_response
        self._last_id_response = 0.0  # Track ID request responses
        self.latest_observation = None

        self.mission_timer = 0
        self.human_yaw_ang = None
        self.human_roll_ang = None
        self.human_pitch_ang = None
        self.human_roll_rate = None
        self.human_pitch_rate = None
        self.human_has_taken_off = False

        # Task completion tracking for autonomy level 2
        self.previous_handled_states = {target.id: False for target in self.targets}
        self.previous_target_status = {target.id: 0.0 for target in self.targets}  # Track status changes
        self.last_plan_send_time = -999.0  # Time when last plan was sent
        self.cached_wingman_action = None
        self.timesteps_since_action_calc = 0
        self.last_wingman_message_count = 0  # Track message count for change detection
        self.current_team_plan = None
        self.latest_human_message_text = ""

        self.tts_voice = PiperTTSVoice()       # Piper TTS for wingman speech
        self._last_spoken_status = None        # Track last spoken status to avoid repetition


    def log(self, message, log_file="./logs/debug_log.txt", debug_prefix=None):
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
            log_message = f'[{debug_prefix if debug_prefix else ''}] {message}'
        else:
            log_message = message
        logger.info(log_message)

        if self.verbose:
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


    def reset(self):
        """Reset mission state and all datarefs to initial values"""

        self.xpc.subscribeDREFs([('sim/flightmodel/position/true_psi',1)])

        # Load human's first LLA position
        self.human_lla = self.human_spawn_lla

        self._mission_status = "not complete"
        self._wingman_goal_hdg = 0.0
        self._wingman_goal_spd = 0.0
        self._wingman_goal_alt = 0.0

        # Spawn AI wingman
        self.wingman = FireWatchWingman(self.xpc, self.ai_spawn_lla, self.ai_start_hdg, self.ai_default_spd, self, fire_layout=self.fire_layout, initiative_level=self.initiative_level)

        ################################# SET CONDITIONS ################################################################

        # Set initial positions in sim mode
        if self.xpc.sim_mode is not None:
            self.setup_sim_mode()

        # Core reset commands
        try:
            if not self.noreset:
                self.xpc.sendCMND("sim/operation/reset_to_runway")

            self.dref_io.reset_plugin_managed_datarefs()

            # Pause
            if self.safe_get_dref(DREF_PAUSED, 0, "paused") != 1:
                self.xpc.sendCMND("sim/operation/pause_toggle")
        except Exception as e:
            self.log(f'Error sending reset commands: {e}')

        # Mission configuration datarefs
        try:
            self.dref_io.set_mission_config()
        except Exception as e:
            self.log(f'Error setting mission config datarefs: {e}')

        # Weather configuration
        self.dref_io.set_weather_conditions(speed=10.0, direction=self.wind_direction, visibility=12.0)

        # Set human position and velocity
        self.dref_io.set_human_lla(self.human_spawn_lla)
        self.dref_io.set_human_airspeed(self.human_spawn_spd)

        # Communication & Commands datarefs
        try:
            self.dref_io.reset_human_command()
        except Exception as e:
            self.log(f'Error setting communication datarefs: {e}')

        # Reset message tracking
        self._last_human_command = NO_COMMAND
        self._last_request_response = 0.0
        self._last_id_response = 0.0
        self.runtime.last_human_command = NO_COMMAND
        self.runtime.last_request_response = 0.0
        self.runtime.last_id_response = 0.0
        self.runtime.active_team_plan_signature = None
        self.runtime.last_answered_plan_signature = None
        self.runtime.last_answered_plan_time = -999.0
        self.latest_observation = None

        # Reset parameters
        self.mission_timer = 0
        self.previous_handled_states = {target.id: False for target in self.targets}
        self.previous_target_status = {target.id: 0.0 for target in self.targets}  # Track status changes
        self.last_plan_send_time = -999.0
        self.current_team_plan = None
        self.latest_human_message_text = ""
        self.message_bridge.reset_shared_state()

        self.step_count = 0
        self.started_planning_step = None
        self.ended_planning_step = None

        # Reset dynamic fire state so events fire again on re-run
        self.targets = [t for t in self.targets if not t.is_dynamic]
        self.pending_dynamic_events = list(self._all_dynamic_event_configs)
        self._spawned_dynamic_ids = set()
        self.num_targets = len(self.targets)

        # Spawn targets
        try:
            for target in self.targets:
                target.human_in_range_time = 0.0 # Deprecated
                target.wingman_in_range_time = 0.0 # Deprecated
                target.wingman_observation_time = 0.0 # Deprecated
                target.handling_start_time = None # Deprecated
                target.is_being_handled = False # Deprecated
                target.is_known_to_cockpit = target._initially_known
            self.dref_io.initialize_target_datarefs()
        except Exception as e:
            self.log(f'Error initializing target datarefs: {e}')

        self._init_vectorized_arrays()

        # Tell cockpit plugin which fires are known at mission start
        try:
            self.message_bridge.send_mission_init()
        except Exception as e:
            self.log(f'Error sending mission_init: {e}')

    def receive_human_message(self, text: str, source: str = "voice_input") -> None:
        normalized_text = (text or "").strip()
        if not normalized_text:
            return

        mission_time = float(getattr(self, "mission_timer", 0.0) or 0.0)
        message = Message(
            msg_type="freeform_text",
            sender="human",
            recipient="wingman_0",
            payload={
                "text": normalized_text,
                "raw_text": text,
                "normalized_text": normalized_text,
                "source": source,
                "input_mode": "ptt",
                "mission_time": mission_time,
            },
            timestamp=mission_time,
        )
        self.latest_human_message_text = normalized_text
        self.message_queue.send(message)
        self.message_logger.log(message)
        self.log(f"[human voice] source={source} text={normalized_text}")


    def resume_start_conditions(self, start_conditions):
        if not start_conditions:
            return

        self.log("Applying start conditions...")
        self.ai_spawn_lla = (start_conditions['wingman_lat'], start_conditions['wingman_long'], start_conditions['wingman_alt'])
        self.wingman.lat, self.wingman.long, self.wingman.alt = self.ai_spawn_lla
        self.log(f'    AI spawn = {self.ai_spawn_lla}')
        self.human_spawn_lla = (start_conditions['human_lat'], start_conditions['human_long'], start_conditions['human_alt'])
        self.log(f'    Human spawn = {self.human_spawn_lla}')
        self.xpc.sendPOSI(self.human_spawn_lla[0], self.human_spawn_lla[1], self.human_spawn_lla[2], -0.25221577, 4.2194324, 78.849)

        for target in self.targets:
            target_status = start_conditions['target_status'][target.id]
            target_classification = start_conditions['target_classification'][target.id]
            target_whoflew = start_conditions['target_whoflew'][target.id]
            self.log(f'    Target {target.id}: status {target_status} class {target_classification} whoflew {target_whoflew}')

        self.dref_io.apply_start_conditions(start_conditions)

        self.start_time_offset = self.max_mission_time - start_conditions['mission_time_remaining']
        self.runtime.start_time_offset = self.start_time_offset
        self.log(f"    Mission time: {start_conditions['mission_time_remaining']:.0f}s")
        self.log("    Start conditions applied successfully")


    def step(self, dt, met):
        """Execute one simulation step"""

        self.start_time_offset = self.runtime.start_time_offset or self.start_time_offset
        self.mission_timer = met + self.start_time_offset
        self.step_count += 1
        self.runtime.step_count = self.step_count

        # Spawn any dynamic fires whose trigger time has elapsed
        self._check_dynamic_fire_triggers()

        if self.safe_get_dref(DREF_RESET_WINGMAN, fallback=0.0) == 1.0:
            self.wingman.reset()
            self.xpc.sendDREF(DREF_RESET_WINGMAN, 0.0)
            self.log('RESET WINGMAN')

        # Get human position
        self._get_human_lla()
        if self.human_lla[2] >= self.airport_elevation + 200:
            self.human_has_taken_off = True


        ########## MESSAGING SYSTEM ##########
        self._poll_human_messages()

        ########## Handle wingman ##########
        try:
            self.human_status, self.human_target = self.get_human_status()
        except Exception as e:
            self.log(f'[mm.step] Error getting human status: {e}')
            traceback.print_exc()
            self.human_status, self.human_target = None, None

        try:
            wingman_observation = self.get_observation(obs_type='wingman')
        except Exception as e:
            self.log(f'[mm.step] Error getting wingman observation: {e}')
            traceback.print_exc()
            wingman_observation = np.zeros(50)  # Create minimal observation

        # Get wingman's messages from queue
        wingman_messages = self.message_queue.get_messages('wingman_0', mark_processed=True)
        for i, msg in enumerate(wingman_messages):
            msg.mark_processed(self.mission_timer)

        # Wingman action calculation
        if self.wingman_active:
            new_messages_arrived = len(wingman_messages) > 0
            should_recalculate = (self.cached_wingman_action is None or self.timesteps_since_action_calc >= self.wingman_action_frequency or new_messages_arrived)
            if should_recalculate:
                try:
                    agent_action = self.wingman.act(wingman_observation, wingman_messages)
                    self.cached_wingman_action = agent_action
                    self.timesteps_since_action_calc = 0
                except Exception as e:
                    self.log(f'[mm.step] Error in wingman.act(): {e}')
                    traceback.print_exc()
                    # Use previous action or create safe default
                    if self.cached_wingman_action is not None:
                        agent_action = self.cached_wingman_action
                    else:
                        agent_action = {'type': 'hsa', 'goal': (0, 100, 7000), 'status': 9.0}
            else:
                agent_action = self.cached_wingman_action
                self.timesteps_since_action_calc += 1

            agent_goal = agent_action['goal']

            # Update wingman status
            try:
                current_status = self.udp_bridge.current_state["wingman"]["status"]
                if agent_action['status'] != current_status:
                    self.udp_bridge.current_state["wingman"]["status"] = agent_action['status']
                    self.udp_bridge.current_state["wingman"]["subtask"] = agent_action['subtask']
                    self._send_shared_state("status_change")
            except Exception as e:
                self.log(f'[mm.step] Error updating wingman status: {e}')

            # Handle outgoing messages from wingman (only send when action was recalculated)
            if should_recalculate and 'outgoing_messages' in agent_action:
                for msg in agent_action['outgoing_messages']:
                    self.message_queue.send(msg)
                    #self.message_logger.log(msg) # TODO temporarily disabled to check for stuttering

            # Team plan generation (High autonomy mode)
            if self.initiative_level in [1.0, 2.0]:
                try:
                    human_plan = agent_action.get('human_plan', None)
                    wingman_plan = agent_action.get('wingman_plan', None)

                    if human_plan is not None or wingman_plan is not None:
                        time_since_last_plan = self.mission_timer - self.last_plan_send_time
                        if time_since_last_plan >= 10.0:
                            self.rationale_key = {'prioritizing feasible fires for endgame': 1.0, 'normal searching': 2.0, 'Prepare for route handoff': 3.0}
                            self.mode_key = {'normal': 1.0, 'endgame': 2.0}
                            rationale_val = self.rationale_key.get(agent_action.get('rationale', 'normal searching'), 2.0)
                            mode_val = self.mode_key.get(agent_action.get('planning_mode', 'normal'), 1.0)
                            proposed_plan = {
                                "show_plan": bool(agent_action.get('show_plan', 0.0)),
                                "human_plan": agent_action.get('human_plan', 99.0),
                                "wingman_plan": agent_action.get('wingman_plan', 99.0),
                                "second_best_human_plan": agent_action.get('second_best_human_plan', 99.0),
                                "second_best_wingman_plan": agent_action.get('second_best_wingman_plan', 99.0),
                                "best_followon_human": agent_action.get('best_followon_human', 99.0),
                                "best_followon_wingman": agent_action.get('best_followon_wingman', 99.0),
                                "second_best_followon_human": agent_action.get('second_best_followon_human', 99.0),
                                "second_best_followon_wingman": agent_action.get('second_best_followon_wingman', 99.0),
                                "rationale_code": rationale_val,
                                "planning_mode_code": mode_val,
                                "mission_time": self.mission_timer,
                            }
                            proposed_signature = self._team_plan_signature(proposed_plan)
                            active_signature = self.runtime.active_team_plan_signature
                            answered_signature = self.runtime.last_answered_plan_signature

                            if proposed_signature != active_signature and proposed_signature != answered_signature:
                                self.udp_bridge.current_state["human"]["recently_finished_task"] = -1.0
                                self.udp_bridge.current_state["wingman"]["recently_finished_task"] = -1.0
                                self.current_team_plan = proposed_plan
                                self.runtime.active_team_plan_signature = proposed_signature
                                self.udp_bridge.send_team_plan_suggestion(self.current_team_plan)
                                self._send_shared_state("plan_change")

                                self.last_plan_send_time = self.mission_timer
                except Exception as e:
                    self.log(f'[mm.step] Error in team plan generation: {e}')
        try:
            self.message_queue.cleanup_old_processed_messages(self.mission_timer, age_threshold=30.0)
        except Exception as e:
            self.log(f'[mm.step] Error publishing messages: {e}')

        # Execute movement
        if self.wingman_active:
            if agent_action['type'] == 'hsa':
                self._move_ai_hsa(agent_goal, dt)
                #self.safe_send_dref("custom/haato/wingman_hdg", float(self.wingman.hdg), "wingman_hdg")
            else:
                raise ValueError(f'Non-HSA action type "{agent_action["type"]}" not supported yet')

        # Update targets
        self._update_target_classes()

        if self.wingman_active:
            self._wingman_classify_targets(dt)

        # Check mission completion
        done, completion_reason = self._check_mission_progress()
        self._send_shared_state("periodic")

        return done

    def get_human_status(self) -> tuple[str | None, Target | None]:
        try:
            human_plan_raw = self.udp_bridge.current_state["human"]["indicated_plan"]
            human_plan = int(human_plan_raw)
            # Validate range
            if human_plan < -1 or human_plan >= len(self.targets):
                self.log(f'[mm.step] Invalid human plan index: {human_plan}')
                return None, None
        except (ValueError, TypeError) as e:
            self.log(f'[mm.step] Error converting human_plan to int: {e}')
            return None, None

        if human_plan == -1:
            return None, None

        try:
            human_target = self.targets[human_plan]
        except Exception as e:
            self.log(f'[mm.step] Error accessing target: {e}')
            return None, None

        human_lat, human_long, human_alt = self.human_lla
        human_distance_to_target_nm = GeoUtils.haversine_distance(human_lat, human_long, human_target.lat, human_target.long)

        task_dict = {0.0:'classify', 1.0: 'mark position', 2.0: f'ly route', 3.0: 'refine route', 4.0: f'ire complete'}
        task = task_dict[human_target.status]

        if task in [f'ly route', 'refine route']: # Recording a route
            if self.udp_bridge.current_state["human"]["recording_route"]:
                human_status_prefix = 'currently '
            else:
                human_status_prefix = 'approaching to '

        else: # Classifying and marking position
            if human_distance_to_target_nm > 2.0:
                human_status_prefix = 'approaching to '
            else:
                human_status_prefix = 'currently '

        human_status = human_status_prefix + task

        return human_status, human_target

    def _check_mission_progress(self) -> Tuple[bool, str]:
        """ Check mission progress and whether the mission is complete. Send mission status to the mission status DREF.
            returns:
                done (Bool)
                completion_reason (str)
        """
        try:
            complete_targets, targets_spotted = 0,0
            for target in self.targets:
                if target.status == 4.0:
                    complete_targets += 1

            if complete_targets == len(self.targets):
                done = True
                completion_reason = 'all fires extinguished'

            elif self.max_mission_time - self.mission_timer <= 0:
                done = True
                completion_reason = 'out of time'

            else:
                done = False
                completion_reason = 'not complete'

            self._mission_status = completion_reason

        except Exception as e:
            self.log(f'[mm.step] Error checking mission progress: {e}')
            done = False
            completion_reason = 'error'

        return done, completion_reason


    def _update_target_classes(self):
        """Update target states from datarefs"""

        try:

            for i, target in enumerate(self.targets):
                try:

                    # Get target status and classification with fallbacks
                    target_status_dref = self.safe_get_dref(
                        f"custom/haato/target_status[{target.id}]",
                        target.status,  # Fallback to current value
                        f"target_status[{target.id}]"
                    )
                    target_classification_dref = self.safe_get_dref(
                        f"custom/haato/target_classification[{target.id}]",
                        target.classification,  # Fallback to current value
                        f"target_classification[{target.id}]"
                    )

                    target.status = target_status_dref
                    target.classification = target_classification_dref

                    # If human has classified via GUI
                    if target_classification_dref > 0.0 and target.status == 0.0:
                        target.status = 1.0
                        target_status_dref = 1.0
                        self.safe_send_dref(f"custom/haato/target_status[{target.id}]", 1.0, f"target_status[{target.id}]")

                        agent_request = self.udp_bridge.current_agent_id_request
                        if agent_request["active"] and agent_request["target_id"] == int(target.id):
                            self.udp_bridge.send_agent_requests_id({
                                "active": False,
                                "target_id": None,
                                "mission_time": self.mission_timer,
                            })
                            self.log(f'Detected that requested target {target.id} was classified. Resetting request dref')

                    # Update spotted status
                    if 0.0 < target_status_dref <= 1.0 and not target.spotted:
                        target.spotted = True
                        target.status = 1.0

                    # Update position marked
                    if target_status_dref >= 2.0 and target.marked_position is None:
                        target.marked_position = (target.lat, target.long)
                        target.status = 2.0

                    # Update initial drop route complete
                    if target_status_dref >= 3.0 and not target.initial_drop_route_complete:
                        target.initial_drop_route_complete = True
                        target.status = 3.0

                    # Update refined drop route complete
                    if target_status_dref >= 4.0 and not target.refined_drop_route_complete:
                        target.refined_drop_route_complete = True
                        target.status = 4.0
                        target.handled = True

                    # Update progress
                    if 1.0 < target_status_dref < 2.0:
                        target.progress = target_status_dref - 1.0
                    elif target_status_dref >= 2.0:
                        target.progress = 1.0

                    # Detect wingman task completion
                    previous_status = self.previous_target_status.get(target.id, 0.0)
                    current_status = target.status

                    if current_status > previous_status:
                        wingman_completed_task = -1.0
                        speak_status = False

                        # Classification complete (0 -> 1)
                        if previous_status == 0.0 and current_status >= 1.0:
                            speak_status = True
                            wingman_completed_task = 1.0

                        # Position marking complete (1 -> 2)
                        elif previous_status == 1.0 and current_status >= 2.0:
                            if target.position_recorded_by_wingman:
                                wingman_completed_task = 2.0
                                speak_status = True

                        # Initial route complete (2 -> 3)
                        elif previous_status == 2.0 and current_status >= 3.0:
                            who_flew_initial = self.safe_get_dref(
                                f"custom/haato/target_whoflew_initial[{target.id}]",
                                0.0,
                                f"target_whoflew_initial[{target.id}]"
                            )
                            if who_flew_initial == 2.0:
                                wingman_completed_task = 3.0
                                speak_status = True

                        # Refined route complete (3 -> 4)
                        elif previous_status == 3.0 and current_status >= 4.0:
                            who_flew_initial = self.safe_get_dref(
                                f"custom/haato/target_whoflew_initial[{target.id}]",
                                0.0,
                                f"target_whoflew_initial[{target.id}]"
                            )
                            if who_flew_initial != 2.0:
                                wingman_completed_task = 4.0
                                speak_status = True

                        if wingman_completed_task != -1.0:
                            self.udp_bridge.current_state["wingman"]["recently_finished_task"] = wingman_completed_task
                            self._send_shared_state("task_change")
                            self.log(f"Wingman completed task at target {target.id}: status {previous_status} -> {current_status}")

                    # Update previous status for next iteration
                    self.previous_target_status[target.id] = current_status

                except Exception as e:
                    self.log('TARGET_UPDATE_ERROR', f'Error updating target {target.id}: {e}')
                    continue # Continue with next target

        except Exception as e:
            self.log(f'[mm.step] Error updating target classes: {e}')

    def _speak(self, text: str) -> None:
        """Speak text via Piper TTS in a background thread (non-blocking)."""
        if not text:
            return
        t = threading.Thread(target=self.tts_voice.speak, args=(text,), daemon=True)
        t.start()

    def _wingman_status_to_voice(self, status_value: float) -> str:
        """Convert wingman status float to a spoken aviation phrase."""
        if status_value == 99.0:
            return ""                            # Idle / uninitialized — don't speak
        if status_value == 9.0:
            return "Lead 2, holding."
        if status_value == 8.0:
            return "Lead 2, following your lead."
        fire_id = int(status_value)
        if 0 <= fire_id < len(self.targets):
            target = self.targets[fire_id]
            fire_label = f"fire {fire_id + 1}"   # 1-indexed for human readability
            task_map = {
                0.0: f"Lead 2, classifying {fire_label}.",
                1.0: f"Lead 2, marking position at {fire_label}.",
                2.0: f"Lead 2, marking initial route at {fire_label}.",
                3.0: f"Lead 2, marking refined route at {fire_label}.",
            }
            return task_map.get(target.status, f"Lead 2, working on {fire_label}.")
        return f"Lead 2, status {int(status_value)}."

    def cleanup(self) -> None:
        """Clean up resources on mission end."""
        if hasattr(self, 'tts_voice') and self.tts_voice:
            self.tts_voice.close()

    def _wingman_classify_targets(self, dt):
        """
        Handle the wingman classifying a target
        """
        try:
            # Calculate ranges to all targets at once
            wingman_ranges, wingman_bearings, wingman_alt_diffs = self._calculate_ranges_vectorized((self.wingman.lat, self.wingman.long, self.wingman.alt), update_cache=False)

            for i in range(self.num_targets):
                target = self.targets[i]

                if wingman_ranges[i] <= self.visual_detection_range and target.status == 0.0:

                    # Notify cockpit if this fire was previously unknown
                    if not target.is_known_to_cockpit:
                        target.is_known_to_cockpit = True
                        try:
                            self.message_bridge.send_fire_discovered(target)
                        except Exception as e:
                            self.log(f'[mm] Error sending fire_discovered for target {target.id}: {e}')

                    # If wingman is already set to auto spot or the human tells it to auto spot:
                    if self.udp_bridge.current_id_response["response"] == 1.0 or self.udp_bridge.current_state["settings"]["auto_spot"]:
                        target.status = 1.0
                        if random.random() < 0.7:  # Classify correctly
                            classification_value = 2.0 if target.type == "severe" else 1.0
                        else:  # Misclassification (swap moderate/severe)
                            classification_value = 1.0 if target.type == "severe" else 2.0

                        self.xpc.sendDREF(f"custom/haato/target_classification[{target.id}]", classification_value)
                        self.xpc.sendDREF(f"custom/haato/target_status[{target.id}]", 1.0)
                        self.udp_bridge.send_agent_requests_id({
                            "active": False,
                            "target_id": None,
                            "mission_time": self.mission_timer,
                        })
                        self.udp_bridge.current_id_response["response"] = 0.0

                        # Wingman completed classification task
                        self.udp_bridge.current_state["wingman"]["recently_finished_task"] = 1.0
                        self._send_shared_state("task_change")
                        self.log(f"Wingman completed classification task at target {target.id}")

                    else: # Not set to auto spot. Ask human
                        self.udp_bridge.send_agent_requests_id({
                            "active": True,
                            "target_id": int(target.id),
                            "mission_time": self.mission_timer,
                        })
                        self._speak("Lead 2, requesting fire ID, check your display.")
                        self.log(f'agent requesting ID of target {target.id}')

        except Exception as e:
            self.log(f'[mm.step] Error in wingman target classification: {e}')


    def _get_human_lla(self):
        """Get current human position and orientation from X-Plane"""
        # Get orientation data
        self.human_yaw_ang = self.safe_get_dref('sim/flightmodel/position/true_psi')
        self.human_roll_ang = self.safe_get_dref('sim/flightmodel/position/true_phi')
        self.human_pitch_ang = self.safe_get_dref('sim/flightmodel/position/true_theta')
        self.human_roll_rate = self.safe_get_dref('sim/flightmodel/position/Prad')
        self.human_pitch_rate = self.safe_get_dref('sim/flightmodel/position/Qrad')

        # Get position data with fallbacks
        human_lat = self.safe_get_dref('sim/flightmodel/position/latitude', self.human_lla[0], 'lat')
        human_lon = self.safe_get_dref('sim/flightmodel/position/longitude', self.human_lla[1], 'lon')
        human_alt = self.safe_get_dref('sim/flightmodel/position/elevation', self.human_lla[2], 'alt')

        self.human_lla = (human_lat, human_lon, human_alt)

        # Get heading and speed
        self.human_hdg = self.xpc.current_dref_values['sim/flightmodel/position/true_psi']['value'] # self.safe_get_dref('sim/flightmodel/position/true_psi')

        # Calculate ground speed
        vx = self.safe_get_dref('sim/flightmodel/position/local_vx', 0, 'vx')
        vy = self.safe_get_dref('sim/flightmodel/position/local_vy', 0, 'vy')
        vz = self.safe_get_dref('sim/flightmodel/position/local_vz', 0, 'vz')
        self.human_spd = np.sqrt(vx ** 2 + vy ** 2 + vz ** 2)


    def _move_ai_hsa(self, action: Tuple[float, float, float], dt):
        """Take agent's action, process it as needed, calculate new position, and push it to DREFs to be rendered
        args:
            action: (goal_heading, goal_speed, goal_altitude) from agent
        returns:
            Nothing, but updates wingman's lat, long and HSA and sends to Xplane
        """
        try:

            old_state = (self.wingman.lat, self.wingman.long, self.wingman.alt, self.wingman.hdg, self.wingman.spd)

            # Configuration parameters (read from instance attrs set in __init__)
            hdg_tolerance = self.hdg_tolerance
            spd_tolerance = self.spd_tolerance
            alt_tolerance = self.alt_tolerance
            hdg_rate = self.hdg_rate
            spd_rate = self.spd_rate
            alt_rate = self.alt_rate

            # Extract action and current state
            goal_hdg, goal_spd, goal_alt = action
            self._wingman_goal_hdg = goal_hdg
            self._wingman_goal_spd = goal_spd
            self._wingman_goal_alt = goal_alt
            current_hdg = self.wingman.hdg  # deg
            current_spd = self.wingman.spd  # knots
            current_alt = self.wingman.alt  # m
            current_lat = self.wingman.lat  # deg
            current_long = self.wingman.long  # deg

            # Calculate deltas
            d_hdg = goal_hdg - current_hdg
            d_spd = goal_spd - current_spd
            d_alt = goal_alt - current_alt

            # Handle heading wrap-around for delta calculation
            if d_hdg > 180: d_hdg -= 360
            elif d_hdg < -180: d_hdg += 360

            def calc_goal_component(current_comp, delta, rate, dt, tolerance, goal, name):
                if abs(delta) > tolerance:
                    if delta > 0:
                        new_comp = current_comp + min(rate * dt, delta)
                    else:
                        new_comp = current_comp + max(-rate * dt, delta)
                else:
                    new_comp = goal  # Close enough, snap to target
                return new_comp

            new_hdg = calc_goal_component(current_hdg, d_hdg, hdg_rate, dt, hdg_tolerance, goal_hdg, "HEADING")
            new_hdg = new_hdg % 360  # Handle heading wrap-around (0-360 degrees)
            new_spd = calc_goal_component(current_spd, d_spd, spd_rate, dt, spd_tolerance, goal_spd, "SPEED")
            new_spd = max(0, new_spd)  # Ensure speed doesn't go negative
            new_alt = calc_goal_component(current_alt, d_alt, alt_rate, dt, alt_tolerance, goal_alt, "ALT")

            # Calculate distance traveled in this time step
            distance_nm = new_spd * (dt / 3600.0)  # Convert knots to nautical miles per second

            # Navigation calculation
            math_bearing = new_hdg % 360
            bearing_rad = math.radians(math_bearing)

            # Calculate new position using great circle navigation
            lat_rad = math.radians(current_lat)
            lon_rad = math.radians(current_long)
            angular_distance = distance_nm * self.inv_earth_radius_nm  # Angular distance

            # Calculate new latitude and longitude using spherical trigonometry
            try:
                new_lat_rad = math.asin(math.sin(lat_rad) * math.cos(angular_distance) +math.cos(lat_rad) * math.sin(angular_distance) * math.cos(bearing_rad))
                new_lon_rad = lon_rad + math.atan2(math.sin(bearing_rad) * math.sin(angular_distance) * math.cos(lat_rad),math.cos(angular_distance) - math.sin(lat_rad) * math.sin(new_lat_rad))
                new_lat = math.degrees(new_lat_rad)
                new_lon = math.degrees(new_lon_rad)
                calculation_success = True

            except Exception as e:
                new_lat = current_lat
                new_lon = current_long
                calculation_success = False

            # Update wingman state
            self.wingman.hdg = new_hdg
            self.wingman.spd = new_spd
            self.wingman.alt = new_alt
            self.wingman.lat = new_lat
            self.wingman.long = new_lon

        except Exception as e:
            self.log(f'Error in move_ai_hsa: {e}')
            traceback.print_exc()
            return old_state[0], old_state[1], old_state[2]

        return new_lat, new_lon, new_alt


    def get_state(self):
        """Formats state into a dictionary for use in debugging, logging etc"""

        # Calculate mission progress metrics
        targets_handled = sum(1 for target in self.targets if target.handled)
        targets_spotted = sum(1 for target in self.targets if target.spotted)
        targets_being_handled = sum(1 for target in self.targets if target.is_being_handled)
        unknown_targets = len(self.targets) - targets_spotted

        # Calculate range between human and wingman
        human_wingman_range, human_wingman_bearing, human_wingman_alt_diff = self._calculate_range(
            self.human_lla, (self.wingman.lat, self.wingman.long, self.wingman.alt)
        )

        # Build target details list
        target_details = []
        # Use vectorized calculations for all ranges at once
        human_ranges, human_bearings, human_alt_diffs = self._calculate_ranges_vectorized(self.human_lla, update_cache=False)
        wingman_ranges, wingman_bearings, wingman_alt_diffs = self._calculate_ranges_vectorized(
            (self.wingman.lat, self.wingman.long, self.wingman.alt), update_cache=False
        )

        for i, target in enumerate(self.targets):
            target_info = {
                'id': target.id,
                'type': target.type,
                'position': {
                    'lat': target.lat,
                    'lon': target.long,
                    'alt': target.alt
                },
                'status': {
                    'spotted': target.spotted,
                    'handled': target.handled,
                    'being_handled': target.is_being_handled,
                    'handling_start_time': target.handling_start_time
                },
                'handling_times': {
                    'human_in_range_time': target.human_in_range_time,
                    'wingman_in_range_time': target.wingman_in_range_time
                },
                'ranges': {
                    'human_range_nm': human_ranges[i],
                    'human_bearing_deg': math.degrees(human_bearings[i]),
                    'human_alt_diff_m': human_alt_diffs[i],
                    'wingman_range_nm': wingman_ranges[i],
                    'wingman_bearing_deg': math.degrees(wingman_bearings[i]),
                    'wingman_alt_diff_m': wingman_alt_diffs[i]
                },
                'in_range_status': {
                    'human_in_visual_range': human_ranges[i] <= self.visual_detection_range
                }
            }
            target_details.append(target_info)

        # Check mission completion status
        mission_complete, completion_reason = self._check_mission_progress()

        state = {
            'mission_info': {
                'timer': self.mission_timer,
                'time_remaining': self.max_mission_time - self.mission_timer,
                'user_id': self.user_id,
                'complete': mission_complete,
                'completion_reason': completion_reason
            },

            'human_state': {
                'position': {
                    'lat': self.human_lla[0],
                    'lon': self.human_lla[1],
                    'alt': self.human_lla[2]
                },
                'orientation': {
                    'heading': self.human_hdg,
                    'yaw': getattr(self, 'human_yaw_ang', None),
                    'pitch': getattr(self, 'human_pitch_ang', None),
                    'roll': getattr(self, 'human_roll_ang', None)
                },
                'motion': {
                    'speed': self.human_spd,
                    'pitch_rate': getattr(self, 'human_pitch_rate', None),
                    'roll_rate': getattr(self, 'human_roll_rate', None)
                }
            },

            'wingman_state': {
                'position': {
                    'lat': self.wingman.lat,
                    'lon': self.wingman.long,
                    'alt': self.wingman.alt
                },
                'motion': {
                    'heading': self.wingman.hdg,
                    'speed': self.wingman.spd
                },
                'spawn_info': {
                    'spawn_lat': self.ai_spawn_lla[0],
                    'spawn_lon': self.ai_spawn_lla[1],
                    'spawn_alt': self.ai_spawn_lla[2],
                    'default_speed': self.ai_default_spd,
                    'start_heading': self.ai_start_hdg
                }
            },

            'human_wingman_relationship': {
                'range_nm': human_wingman_range,
                'bearing_deg': math.degrees(human_wingman_bearing),
                'altitude_diff_m': human_wingman_alt_diff
            },

            'target_summary': {
                'total': len(self.targets),
                'handled': targets_handled,
                'spotted': targets_spotted,
                'being_handled': targets_being_handled,
                'unknown': unknown_targets,
                'completion_percentage': (targets_handled / len(self.targets)) * 100 if self.targets else 0
            },

            'targets': target_details,

            'mission_parameters': {
                'visual_detection_range_nm': self.visual_detection_range,
                'aor_center': self.aor_center,
                'aor_size_nm': self.aor_size,
                'aor_bounds': self.aor_bounds,
                'airfield_lla': self.airfield_lla
            }
        }

        return state


    def is_valid_for_human(self, target_id):
        """Check if a target is valid for the human"""
        try:
            if target_id == -1.0:
                return False
            if target_id < 0 or target_id > self.num_targets:
                self.log(f'    Target ID {target_id} outside bounds -> target is invalid')
                return False
            target_id = int(target_id)
            status = self.targets[target_id].status
            whoflew = self.targets[target_id].route1_recorder

            if status == 4.0 or (status == 3.0 and whoflew == 'human'):
                return False
            else:
                return True
        except Exception as e:
            self.log(f'    Error in is_valid_for_human: {e}')
            return False


    def get_observation(self, obs_type='wingman'):
        if obs_type != 'wingman':
            raise ValueError(f'Observation type {obs_type} not supported')

        obs = build_wingman_observation(self)
        self.latest_observation = obs
        return obs


    def load_mission_config(self, json_file_path):
        mission_config = load_fire_mission_config(self.fire_layout, testing_wingman=self.testing_wingman)
        self.mission_config_path = mission_config.path
        self.targets = mission_config.targets
        self.human_spawn_lla = mission_config.human_spawn_lla
        self.human_spawn_spd = mission_config.human_spawn_spd
        self.human_spawn_hdg = mission_config.human_spawn_hdg
        self.required_cruise_altitude_ft = mission_config.required_cruise_altitude_ft
        self.required_alt_fire_agl = mission_config.required_alt_fire_agl
        self.wind_direction = mission_config.wind_direction
        self.mag_declination = mission_config.mag_declination
        self.required_drop_route_length = mission_config.required_drop_route_length
        self.ai_spawn_lla = mission_config.ai_spawn_lla
        self.wingman_active = mission_config.wingman_active

        # Dynamic fire event support
        self._all_dynamic_event_configs: list[dict] = list(mission_config.dynamic_event_configs)
        self.pending_dynamic_events: list[dict] = list(self._all_dynamic_event_configs)
        self._spawned_dynamic_ids: set[int] = set()

    def _build_message_codes(self):

        self.message_codes = {}
        num_targets = self.num_targets

        for target_idx in range(num_targets):
            self.message_codes[f'flying to fire {target_idx} to classify'] = float(target_idx)  # 0.0-7.0
            self.message_codes[f'currently classifying fire {target_idx}'] = num_targets + float(target_idx)  # 8.0-15.0
            self.message_codes[f'flying to fire {target_idx} to extinguish'] = 2 * num_targets + float(target_idx)  # 16.0-23.0
            self.message_codes[f'currently extinguishing {self.targets[target_idx].type} fire {target_idx}'] = 3 * num_targets + float(target_idx)  # 24.0-31.0
            self.message_codes[f'requesting help at {self.targets[target_idx].type} fire {target_idx}'] = 4 * num_targets + float(target_idx)  # 32.0-39.0
            self.message_codes[f'meeting human at fire {target_idx}'] = 5 * num_targets + float(target_idx)  # 40.0-47.0
            self.message_codes[f'flying to fire {target_idx}'] = 6 * num_targets + float(target_idx)  # 48.0-55.0

        self.message_codes[f'ollowing human'] = float(num_targets * 7)  # 56.0
        self.message_codes['no valid fires, holding'] = float(num_targets * 7 + 1)  # 57.0
        self.message_codes[f'lying to custom waypoint'] = float(num_targets * 7 + 2)  # 58.0
        self.message_codes['placeholder'] = float(num_targets * 7 + 3)

        self.message_codes['correction_messages'] = {
            'none': 0.0,
            'altitude low - cruise':1.0,
            'altitude high - cruise':2.0,
            'altitude low = target':3.0,
            'altitude high - target':40,
            'check heading east':5.0,
            'check heading west':6.0
        }


    def _init_vectorized_arrays(self):
        # Pre-allocate arrays for target positions (lat, lon, alt)
        self.target_positions = np.zeros((self.num_targets, 3), dtype=np.float64)

        # Update target positions array
        for i, target in enumerate(self.targets):
            self.target_positions[i] = [target.lat, target.long, target.alt]

        # Create O(1) lookup dictionary for target ID to index mapping
        self.target_id_to_index = {target.id: i for i, target in enumerate(self.targets)}

        # Pre-allocate result arrays for range calculations
        self.ranges_to_targets = np.zeros(self.num_targets, dtype=np.float64)
        self.bearings_to_targets = np.zeros(self.num_targets, dtype=np.float64)
        self.alt_diffs_to_targets = np.zeros(self.num_targets, dtype=np.float64)


    def _check_dynamic_fire_triggers(self) -> None:
        """Spawn any dynamic fires whose trigger time has passed."""
        for ec in list(self.pending_dynamic_events):
            if self.mission_timer >= ec["trigger_time_s"]:
                self._spawn_dynamic_fire(ec)
                self.pending_dynamic_events.remove(ec)

    def _spawn_dynamic_fire(self, ec: dict) -> None:
        """Create a new Target at runtime and notify the cockpit plugin."""
        fid = ec["id"]
        if fid in self._spawned_dynamic_ids:
            return
        self._spawned_dynamic_ids.add(fid)

        new_target = Target(
            lat=ec["true_lat"],
            long=ec["true_long"],
            alt=ec["true_alt"],
            type=ec["type"],
            id=fid,
            reported_lat=ec.get("reported_lat"),
            reported_long=ec.get("reported_long"),
            reported_alt=ec.get("reported_alt"),
            image_path=ec.get("image_path", ""),
            image_res=ec.get("image_res"),
            is_dynamic=True,
            trigger_time_s=ec["trigger_time_s"],
        )
        self.targets.append(new_target)
        self.num_targets = len(self.targets)

        # Extend vectorized arrays in-place (avoids full rebuild)
        new_row = np.array([[new_target.lat, new_target.long, new_target.alt]])
        self.target_positions = np.vstack([self.target_positions, new_row])
        self.ranges_to_targets = np.append(self.ranges_to_targets, 0.0)
        self.bearings_to_targets = np.append(self.bearings_to_targets, 0.0)
        self.alt_diffs_to_targets = np.append(self.alt_diffs_to_targets, 0.0)
        self.target_id_to_index[fid] = self.num_targets - 1

        # Initialise tracking dicts (added during reset())
        self.previous_handled_states[fid] = False
        self.previous_target_status[fid] = 0.0

        # Initialise datarefs for this target
        self.dref_io.initialize_single_target_dataref(new_target)

        # Rebuild message codes now that num_targets changed
        self._build_message_codes()

        # Notify cockpit plugin
        self.message_bridge.send_fire_spawn_event(new_target)
        self.log(f"[dynamic fire] spawned id={fid} type={new_target.type} at met={self.mission_timer:.1f}s")

    def _calculate_ranges_vectorized(self, observer_lla: Tuple[float, float, float], update_cache=True):
        """
        Args:
            observer_lla: (lat, lon, alt) of the observer
            update_cache: If True, updates self.ranges_to_targets cache

        Returns:
            ranges (nm), bearings (rad), alt_diffs (m) as numpy arrays
        """
        obs_lat, obs_lon, obs_alt = observer_lla

        # Convert to radians for vectorized calculation
        obs_lat_rad = np.radians(obs_lat)
        obs_lon_rad = np.radians(obs_lon)

        target_lats_rad = np.radians(self.target_positions[:, 0])
        target_lons_rad = np.radians(self.target_positions[:, 1])

        # Haversine formula - vectorized
        dlat = target_lats_rad - obs_lat_rad
        dlon = target_lons_rad - obs_lon_rad

        a = np.sin(dlat / 2) ** 2 + np.cos(obs_lat_rad) * np.cos(target_lats_rad) * np.sin(dlon / 2) ** 2
        c = 2 * np.arcsin(np.sqrt(a))

        ranges = c / self.inv_earth_radius_nm

        # Bearing calculation
        y = np.sin(dlon) * np.cos(target_lats_rad)
        x = np.cos(obs_lat_rad) * np.sin(target_lats_rad) - np.sin(obs_lat_rad) * np.cos(target_lats_rad) * np.cos(dlon)
        bearings = np.arctan2(y, x)

        # Altitude difference
        alt_diffs = self.target_positions[:, 2] - obs_alt

        if update_cache:
            self.ranges_to_targets[:] = ranges
            self.bearings_to_targets[:] = bearings
            self.alt_diffs_to_targets[:] = alt_diffs

        return ranges, bearings, alt_diffs


    def _poll_human_messages(self):
        self.message_bridge.poll_human_messages()
        self._last_human_command = self.runtime.last_human_command
        self._last_request_response = self.runtime.last_request_response
        self._last_id_response = self.runtime.last_id_response

    def _send_shared_state(self, reason="periodic"):
        self.message_bridge.send_shared_state(reason)

    def _publish_messages_to_datarefs(self):
        self.message_bridge.publish_messages_to_datarefs()


    def set_weather_conditions(self, speed, direction, visibility):
        self.dref_io.set_weather_conditions(speed, direction, visibility)

    def set_human_airspeed(self, speed):
        self.dref_io.set_human_airspeed(speed)

    def set_human_lla(self, lla: Tuple):
        self.dref_io.set_human_lla(lla)

    def setup_sim_mode(self):
        """Initialize datarefs for sim mode"""
        try:
            self.xpc.sim_mode.dref_dict['sim/flightmodel/position/latitude'] = self.human_lla[0]
            self.xpc.sim_mode.dref_dict['sim/flightmodel/position/longitude'] = self.human_lla[1]
            self.xpc.sim_mode.dref_dict['sim/flightmodel/position/elevation'] = self.human_lla[2]
            self.log('Sim mode positions set')
        except Exception as e:
            self.log(f'Error setting sim mode positions: {e}')
