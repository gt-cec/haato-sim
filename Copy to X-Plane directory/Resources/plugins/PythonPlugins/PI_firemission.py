import xp
from XPPython3 import xpgl
from XPPython3.xpgl import Colors
from XPPython3.utils.datarefs import find_dataref
from XPPython3.utils import commands

from fire_classes import RadioHandler, Target, PositionRecording, RouteRecording, SoundManager
from py_utilities.grid_system import GridSystem
from py_utilities.revamped_input_handling import InputManager, InputAction
import py_utilities.rendering as rendering
from py_utilities.gui_components import Button, ButtonGrid, Screen

import math
import time
import traceback
import datetime
import json
import os
import sys
import random
import wave
import sys
import glob
import numpy as np
from haato_udp import CockpitHaatoUDPBridge
from fire_mission import fire_gui, fire_recordings


plugin_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
py_utilities_path = os.path.join(plugin_path, 'HAATO_assets', 'py_utilities')
if py_utilities_path not in sys.path:
  sys.path.insert(0, py_utilities_path)

_HAATO_ASSETS_DIR = os.path.join(plugin_path, 'HAATO_assets')


def _load_haato_config(assets_dir):
    """Load HAATO config.yaml from HAATO_assets/. Tries PyYAML; falls back to
    a minimal inline parser that handles the bounded YAML subset used here."""
    config_path = os.path.join(assets_dir, 'config.yaml')
    try:
        import yaml
        with open(config_path, 'r', encoding='utf-8') as fh:
            return yaml.safe_load(fh)
    except ImportError:
        return _parse_haato_config_fallback(config_path)


def _parse_haato_config_fallback(config_path):
    """Parse the bounded YAML subset used by HAATO's config.yaml."""

    def _strip_inline_comment(text):
        in_quote = None
        bracket_depth = 0
        brace_depth = 0
        for idx, char in enumerate(text):
            if in_quote:
                if char == in_quote:
                    in_quote = None
                continue
            if char in ("'", '"'):
                in_quote = char
            elif char == '[':
                bracket_depth += 1
            elif char == ']':
                bracket_depth = max(0, bracket_depth - 1)
            elif char == '{':
                brace_depth += 1
            elif char == '}':
                brace_depth = max(0, brace_depth - 1)
            elif char == '#' and bracket_depth == 0 and brace_depth == 0:
                return text[:idx].rstrip()
        return text.rstrip()

    def _split_top_level(text, delimiter=','):
        parts = []
        current = []
        in_quote = None
        bracket_depth = 0
        brace_depth = 0
        for char in text:
            if in_quote:
                current.append(char)
                if char == in_quote:
                    in_quote = None
                continue
            if char in ("'", '"'):
                in_quote = char
                current.append(char)
                continue
            if char == '[':
                bracket_depth += 1
            elif char == ']':
                bracket_depth -= 1
            elif char == '{':
                brace_depth += 1
            elif char == '}':
                brace_depth -= 1
            if char == delimiter and bracket_depth == 0 and brace_depth == 0:
                part = ''.join(current).strip()
                if part:
                    parts.append(part)
                current = []
                continue
            current.append(char)
        tail = ''.join(current).strip()
        if tail:
            parts.append(tail)
        return parts

    def _split_key_value(text):
        in_quote = None
        bracket_depth = 0
        brace_depth = 0
        for idx, char in enumerate(text):
            if in_quote:
                if char == in_quote:
                    in_quote = None
                continue
            if char in ("'", '"'):
                in_quote = char
            elif char == '[':
                bracket_depth += 1
            elif char == ']':
                bracket_depth -= 1
            elif char == '{':
                brace_depth += 1
            elif char == '}':
                brace_depth -= 1
            elif char == ':' and bracket_depth == 0 and brace_depth == 0:
                return text[:idx].strip(), text[idx + 1:].strip()
        raise ValueError(f"Invalid mapping entry: {text}")

    def _cast_scalar(value):
        value = _strip_inline_comment(value).strip()
        if value == '':
            return ''
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            return value[1:-1]
        lower = value.lower()
        if lower == 'true':
            return True
        if lower == 'false':
            return False
        if lower in ('null', 'none'):
            return None
        try:
            return int(value)
        except ValueError:
            pass
        try:
            return float(value)
        except ValueError:
            pass
        return value

    def _parse_flow_value(value):
        value = _strip_inline_comment(value).strip()
        if value.startswith('[') and value.endswith(']'):
            inner = value[1:-1].strip()
            if inner == '':
                return []
            return [_parse_flow_value(part) for part in _split_top_level(inner)]
        if value.startswith('{') and value.endswith('}'):
            inner = value[1:-1].strip()
            if inner == '':
                return {}
            parsed = {}
            for part in _split_top_level(inner):
                key, nested_value = _split_key_value(part)
                parsed[key] = _parse_flow_value(nested_value)
            return parsed
        return _cast_scalar(value)

    def _parse_block(entries, index, indent):
        if index >= len(entries):
            return {}, index
        if entries[index][1].startswith('- '):
            return _parse_list(entries, index, indent)
        return _parse_mapping(entries, index, indent)

    def _parse_list(entries, index, indent):
        result = []
        while index < len(entries):
            entry_indent, content = entries[index]
            if entry_indent < indent or entry_indent != indent or not content.startswith('- '):
                break
            item_content = content[2:].strip()
            index += 1
            if item_content == '':
                if index < len(entries) and entries[index][0] > indent:
                    child, index = _parse_block(entries, index, entries[index][0])
                    result.append(child)
                else:
                    result.append(None)
            else:
                result.append(_parse_flow_value(item_content))
        return result, index

    def _parse_mapping(entries, index, indent):
        result = {}
        while index < len(entries):
            entry_indent, content = entries[index]
            if entry_indent < indent or entry_indent != indent or content.startswith('- '):
                break
            key, value = _split_key_value(content)
            index += 1
            if value == '':
                if index < len(entries) and entries[index][0] > indent:
                    child, index = _parse_block(entries, index, entries[index][0])
                    result[key] = child
                else:
                    result[key] = {}
            else:
                result[key] = _parse_flow_value(value)
        return result, index

    with open(config_path, 'r', encoding='utf-8') as fh:
        entries = []
        for raw_line in fh:
            stripped = raw_line.rstrip('\n')
            if not stripped.strip() or stripped.lstrip().startswith('#'):
                continue
            indent = len(raw_line) - len(raw_line.lstrip(' '))
            entries.append((indent, stripped.strip()))

    root, _ = _parse_block(entries, 0, entries[0][0] if entries else 0)

    for section in ('missions', 'configs'):
        if section in root:
            root[section] = {
                int(k) if str(k).lstrip('-').isdigit() else k: v
                for k, v in root[section].items()
            }
        if 'experiment' in root and section in root['experiment']:
            root['experiment'][section] = {
                int(k) if str(k).lstrip('-').isdigit() else k: v
                for k, v in root['experiment'][section].items()
            }
    return root


class ScalarProxy:
    def __init__(self, getter=None, setter=None):
        self._getter = getter or (lambda: 0.0)
        self._setter = setter

    @property
    def value(self):
        return self._getter()

    @value.setter
    def value(self, new_value):
        if self._setter:
            self._setter(new_value)


class ArrayProxy:
    def __init__(self, length, getter=None, setter=None):
        self._length = length
        self._getter = getter or (lambda idx: 0.0)
        self._setter = setter

    def __getitem__(self, index):
        return self._getter(index)

    def __setitem__(self, index, value):
        if self._setter:
            self._setter(index, value)


class PythonInterface:
    def __init__(self):
        self.avionics_callbacks = []

        self.flight_loop_id = None

        self.last_update_time = 0
        self.update_interval = 1.0  # Update every N seconds
        self.steps_since_last_status_update = 99
        self.gui_out_of_date = False
        self.first_step_done = False

        ######################################## CONFIGS ########################################

        self.control_prefix =  None #'thrustmaster' or 'logitech'. Set by dataref when mission starts
        self.num_joystick_values_to_get = 2000

        self.saved_recordings_file_path = None # 'C:\X-Plane 12\Resources\plugins\PythonPlugins\saved_recordings_backup.json'

        self.initiative_level = None
        self.participant_id = None
        self.fire_layout = None

        ####################################### RENDERING CONSTANTS ##################################################

        self.aor_center_lat = 47.836467
        self.aor_center_long = -121.108091
        self.GRID_SW_LAT = 47.694800
        self.GRID_SW_LON = -121.318566
        self.GRID_NE_LAT = 47.978133
        self.GRID_NE_LON = -120.897615
        self.GRID_CENTER_LAT = 47.836467
        self.GRID_CENTER_LON = -121.108091

        self.mag_declination = 15

        self.m_to_ft = 3.28084
        self.ft_to_m = 1 / self.m_to_ft

        self.screen_width = 1024
        self.screen_height = 768

        self.lat_scale_nm = 60 # Nautical miles per degree
        self.lon_scale_nm = 60 * math.cos(math.radians(self.aor_center_lat))

        self.mfd_center_x, self.mfd_center_y = 552 + 38, 340 + 26  # Confirmed MFD center accounting for left pane

        # MFD map display: square display area, half-height from center to top/bottom edge
        # Note: The G1000 range setting represents the TOTAL vertical distance (full height)
        self.map_radius_pixels = 340  # Half-height of the square map display area in pixels

        self.mission_start_time = time.time()
        self.dev_mode = False
        self.step = 0
        self.show_wingman_status = False
        self.first_speakstatus_called = False  # Use this to suppress first speakstatus call when plugins reset
        self.spoken_yet = False
        self.human_in_classify_range = None
        self.already_started_logging = False
        self.show_best_plan = True # For plan suggestion

        self.human_has_taken_off = False
        self.has_played_classify_hint = False
        self.has_played_position_hint = False
        self.has_played_route_hint = False
        self.has_played_route_hint_2 = False
        self.last_wingman_plan = None

        self.current_screen = 'splashscreen'  # splashscreen, primary, classify, classify-agent, commands
        find_dataref("custom/haato/current_screen").value = 7.0

        self.font_grid = xpgl.loadFont("Resources/fonts/Roboto-Bold.ttf", 35)
        self.font = xpgl.loadFont("Resources/fonts/Roboto-Bold.ttf", 28)
        self.font_firestatuses = xpgl.loadFont("Resources/fonts/Roboto-Bold.ttf", 37)
        self.font_medium = xpgl.loadFont("Resources/fonts/Roboto-Bold.ttf", 20)
        self.font_mediumlarge = xpgl.loadFont("Resources/fonts/Roboto-Bold.ttf", 33)
        self.font_big = xpgl.loadFont("Resources/fonts/Roboto-Bold.ttf", 40)
        self.font_morebig = xpgl.loadFont("Resources/fonts/Roboto-Bold.ttf", 45)
        self.font25 = xpgl.loadFont("Resources/fonts/Roboto-Bold.ttf", 25)
        self.font30 = xpgl.loadFont("Resources/fonts/Roboto-Bold.ttf", 30)
        self.font35 = xpgl.loadFont("Resources/fonts/Roboto-Bold.ttf", 35)
        self.font32 = xpgl.loadFont("Resources/fonts/Roboto-Bold.ttf", 32)
        self.font50 = xpgl.loadFont("Resources/fonts/Roboto-Bold.ttf", 50)
        self.font60 = xpgl.loadFont("Resources/fonts/Roboto-Bold.ttf", 60)
        self.font_reallybig = xpgl.loadFont("Resources/fonts/Roboto-Bold.ttf", 80)
        self.font_small = xpgl.loadFont("Resources/fonts/Roboto-Bold.ttf", 14)

        self.grid_fonts = [self.font60, self.font60, self.font60, self.font60, self.font60, self.font50, self.font50,
                           self.font35, self.font35, self.font30, self.font25, self.font25, self.font25, self.font25,
                           self.font25]

        self.message_codes = {
            'correction_messages': {
                0.0: 'none',
                1.0: 'Lead 1, check altitude low',
                2.0: 'Lead 1, check altitude high',
                3.0: 'Lead 1, check altitude low',
                4.0: 'Lead 1, check altitude high',
                5.0: 'Lead 1, check heading east',
                6.0: 'Lead 1, check heading west',
                7.0: f'Lead 2 copies, lead 1 has target'
                },
            'voice_messages': {
                0.0: 'none',
                1.0: '1 standby for suggested plan'
            }
        }

        self.task_dict = {
            0.0: 'CLASSIFYING FIRE',
            1.0: 'MARKING POSITION',
            2.0: 'FLYING ROUTE',
            3.0: 'REFINING ROUTE',
            4.0: 'RE PLANNING'
        }

        self.screen_val_dict = {
            1.0: 'primary',
            7.0: 'splashscreen',
            2.0: 'plan_suggestion',
            3.0: 'commands',
            4.0: 'human_plan',
            5.0: 'classify',
            6.0: 'classify_agent',
            8.0: 'review_recording',
            9.0: 'control_reference',
            10.0: 'task_notification'
        }

        # Initialize SoundManager before RadioHandler
        self.sound_manager = SoundManager()
        self.radio_handler = RadioHandler(self, self.sound_manager)

        self.wingman_response_scheduled_time = None
        self.wingman_last_radio_call_time = None
        self.wingman_handle_response_scheduled_time = None

        self.target_types = [0.0] * 8  # Initialize target types for fire classification

        # Cache dataref handles for better performance - will be initialized in XPluginEnable
        self.reset_mission_dataref = None
        self.dataref_mission_time_left = None
        self.dataref_wingman_status = None
        self.dataref_help_request = None
        self.dataref_auto_spot = None
        self.dataref_water_remaining = None
        self.dataref_target_statuses = None
        self.dataref_taskpriority_spotunknown = None
        self.dataref_taskpriority_handlemoderate = None
        self.dataref_taskpriority_handlesevere = None
        self.dataref_wingman_messages = None
        self.dataref_human_messages = None
        self.dataref_set_wingman_greedy = None
        self.command_from_human_dataref = None
        self.agent_id_request_dataref = None
        self.id_request_response_dataref = None
        self.human_in_classify_range_dataref = None
        self.lat_dataref = None
        self.lon_dataref = None
        self.dataref_target_classifications = None
        self.dataref_mission_time_left = None
        self.human_plan_response_dataref = None
        self.wingman_subtask_proxy = None

        # Experiment log file
        self.experiment_log_file = None
        self.experiment_log_path = None
        self.last_show_plan_value = 0.0  # Track for plan detection

        # Define sound file paths (will be loaded when play_sound() is called
        self.error_sound = 'Resources/plugins/HAATO_assets/error_sound.wav'
        self.recording_beep_sound = 'Resources/plugins/HAATO_assets/recording_beep.wav'
        self.notification_sound = 'Resources/plugins/HAATO_assets/notification_sound.wav'

        # Attributes used to track if the human is within range of a fire for certain tasks
        self.target_in_classify_range, self.target_in_overfly_range, self.at_drop_route1_start, self.at_drop_route1_end, self.at_drop_route2_start, self.at_drop_route2_end = None, None, None, None, None, None

        # G1000 range command references
        self.range_up_cmd = None
        self.range_down_cmd = None
        self.current_range_level = 6  # Default to level 6 (8 NM range)
        self.g1000_range_steps = [0.5, 1, 1.5, 2, 3, 5, 8, 10, 15, 20, 30, 50, 80, 100, 150] # G1000 range steps (nautical miles) - typical G1000 zoom levels

        self.fire_images = {}

        self.left_key = None#xp.VK_LEFT
        self.right_key = None#xp.VK_RIGHT
        self.down_key = xp.VK_DOWN
        self.up_key = xp.VK_UP
        self.select_keys = [xp.VK_RETURN, xp.VK_SPACE]
        self.primary_screen_key = xp.VK_Z
        self.command_screen_key = xp.VK_LEFT
        self.show_human_plan_key = xp.VK_RIGHT
        #self.developer_screen_key = xp.VK_L
        self.delete_key = xp.VK_DELETE
        self.auto_spot_switch_key = xp.VK_V
        self.reject_key = xp.VK_R
        self.map_zoom_in_key = xp.VK_ADD
        self.map_zoom_out_key = xp.VK_SUBTRACT
        self.record_key = xp.VK_H
        self.relay_recording_key = xp.VK_T

        self.time_since_last_human_correction = 99
        self.last_wingman_status_update_time = 0

        self.mic_release_time = None
        self.mic_press_time = None
        self.recording_mode = 'position'  # 'position' or 'route' — toggled by user in future
        self.active_route_recording = None  # Set to a RouteRecording while a route is in progress

        # Range thresholds for various operations (in nautical miles)
        self.range_to_classify = 1.0  # Range for fire classification
        self.range_to_overfly = 0.7  # Range for marking fire position during overfly
        self.range_to_start_route = 1.0  # Range for marking drop route start
        self.range_to_end_route = 1.0  # Range for marking drop route end

        self.classified_targets = []

        # Recordings list navigation state
        self.selected_recording_index = 0  # Currently selected recording in the list
        self.control_reference_page = 0
        self.highlighted_recording = None  # Index of recording marked for relay (yellow highlight)

        # Grid-based selection state (managed by ButtonGrid objects; initialized in setup_screens())
        self.commands_grid = None
        self.human_plan_grid = None
        self.classify_grid = None
        self.classify_agent_grid = None
        self.review_grid = None
        self.plan_grid = None

        # Commands screen toggle button states
        self.spt_exting_state = True  # True = "SPT > EXTING", False = "EXTING > SPT"
        self.severe_moderate_state = True  # True = "SEVERE > MODERATE", False = "MODERATE > SEVERE"
        self.greedy_state = False  # True = active (green), False = inactive (gray)

        # Key debounce tracking to prevent auto-repeat
        self.last_key_press_time = {}  # Tracks last press time for each key
        self.key_debounce_delay = 0.25  # Seconds to wait before accepting next key press

        self.classify_agent_request_time = None
        self.classify_agent_time_limit = 15 # How long agent requests a classification before auto-classifying

        # Joystick button debounce tracking
        self.last_joystick_button_press_time = {}  # Tracks last press time for each joystick button

        # Classify-agent screen cooldown to allow id_request dataref to reset
        self.classify_agent_cooldown_start = None  # Timestamp when classify-agent button was pressed
        self.classify_agent_cooldown_duration = 5.0  # Cooldown duration in seconds

        # ID request response dataref auto-reset timer
        self.id_request_response_set_time = None  # Timestamp when response was set
        self.id_request_response_reset_delay = 1.0  # Delay before resetting to 0.0 (seconds)

        # Human plan screen state
        self.human_plan_selected_button = 0  # 0-7 for fires, 8 for clear
        self.human_plan_last_selected = None  # Tracks last selected fire for green highlight

        # Input management (initialized in XPluginEnable → setup_controls())
        self.input_manager = None
        self.joystick_input_enabled = False
        self.joystick_config_path = None
        self.mic_button_name = None
        self.dpad_name = 'D-PAD'
        self.select_button_name = 'TRIGGER'
        self.udp_bridge = None
        self.team_plan_cache = [0.0] + [99.0] * 10
        self.human_plan_response_cache = [-1.0, -1.0, -1.0]
        self.last_answered_plan_signature = None
        self._udp_debug_render_count = 0


    def log(self, message):
        """Wrapper around xp.log"""

        xp.log(message)

    def _mission_time_elapsed(self):
        try:
            return max(0.0, 1800.0 - float(self.dataref_mission_time_left.value))
        except Exception:
            return 0.0

    def _sync_team_plan_cache_from_udp(self):
        udp_bridge = getattr(self, "udp_bridge", None)
        if udp_bridge is None:
            return
        plan = udp_bridge.current_team_plan
        if not plan:
            return
        if self._get_team_plan_signature(plan) == self.last_answered_plan_signature:
            self._reset_team_plan_cache()
            return
        self.team_plan_cache[0] = 1.0 if plan.get('show_plan') else 0.0
        self.team_plan_cache[1] = float(plan.get('human_plan', 99.0))
        self.team_plan_cache[2] = float(plan.get('wingman_plan', 99.0))
        self.team_plan_cache[3] = float(plan.get('second_best_human_plan', 99.0))
        self.team_plan_cache[4] = float(plan.get('second_best_wingman_plan', 99.0))
        self.team_plan_cache[5] = float(plan.get('best_followon_human', 99.0))
        self.team_plan_cache[6] = float(plan.get('best_followon_wingman', 99.0))
        self.team_plan_cache[7] = float(plan.get('second_best_followon_human', 99.0))
        self.team_plan_cache[8] = float(plan.get('second_best_followon_wingman', 99.0))
        self.team_plan_cache[9] = float(plan.get('rationale_code', 99.0))
        self.team_plan_cache[10] = float(plan.get('planning_mode_code', 99.0))

    def _get_team_plan_signature(self, plan):
        if not plan:
            return None
        return (
            float(plan.get('human_plan', 99.0)),
            float(plan.get('wingman_plan', 99.0)),
            float(plan.get('second_best_human_plan', 99.0)),
            float(plan.get('second_best_wingman_plan', 99.0)),
            float(plan.get('best_followon_human', 99.0)),
            float(plan.get('best_followon_wingman', 99.0)),
            float(plan.get('second_best_followon_human', 99.0)),
            float(plan.get('second_best_followon_wingman', 99.0)),
            float(plan.get('rationale_code', 99.0)),
            float(plan.get('planning_mode_code', 99.0)),
            1.0 if plan.get('show_plan') else 0.0,
        )

    def _reset_team_plan_cache(self):
        self.team_plan_cache = [0.0] + [99.0] * 10

    def _dismiss_active_team_plan(self):
        udp_bridge = getattr(self, "udp_bridge", None)
        if udp_bridge is not None:
            self.last_answered_plan_signature = self._get_team_plan_signature(udp_bridge.current_team_plan)
            udp_bridge.current_team_plan = None
        self._reset_team_plan_cache()
        self.last_show_plan_value = 0.0

    def _send_human_state_update(self, reason="ui_update"):
        if self.udp_bridge is None:
            return
        self.udp_bridge.send_human_state_update(
            human={
                "recently_finished_task": self.udp_bridge.current_state["human"]["recently_finished_task"],
                "indicated_plan": self.udp_bridge.current_state["human"]["indicated_plan"],
                "recording_route": self.udp_bridge.current_state["human"]["recording_route"],
            },
            settings={
                "auto_spot": self.udp_bridge.current_state["settings"]["auto_spot"],
            },
            mission_time=self._mission_time_elapsed(),
            sequence_reason=reason,
        )

    def _log_udp_bridge_state(self, context, force=False):
        if self.udp_bridge is None:
            self.log(f"[PI_firemission] {context}: udp_bridge=None")
            return

        self._udp_debug_render_count += 1
        if not force and self._udp_debug_render_count % 120 != 0:
            return

        protocol = getattr(self.udp_bridge, "protocol", None)
        current_state = getattr(self.udp_bridge, "current_state", {})
        wingman = current_state.get("wingman", {})
        self.log(
            f"[PI_firemission] {context}: bridge_id={id(self.udp_bridge)} "
            f"protocol_id={getattr(protocol, 'instance_id', 'n/a')} "
            f"recv_count={getattr(protocol, 'recv_count', 'n/a')} "
            f"shared_state_count={getattr(self.udp_bridge, 'shared_state_count', 'n/a')} "
            f"left={float(current_state.get('mission_time_left', 0.0)):.1f} "
            f"mission_status={current_state.get('mission_status', 'n/a')} "
            f"reason={current_state.get('sequence_reason', 'n/a')} "
            f"wingman=({float(wingman.get('lat', 0.0)):.5f},{float(wingman.get('lon', 0.0)):.5f}) "
            f"wingman_status={float(wingman.get('status', 0.0)):.1f}"
        )

    def _set_auto_spot_state(self, new_value):
        self.udp_bridge.current_state["settings"]["auto_spot"] = bool(new_value == 1.0)
        self._send_human_state_update("auto_spot")

    def _set_human_indicated_plan_state(self, plan_val):
        self.udp_bridge.current_state["human"]["indicated_plan"] = float(plan_val)
        self._send_human_state_update("human_plan")

    def _set_human_recently_finished_task(self, task_value):
        self.udp_bridge.current_state["human"]["recently_finished_task"] = float(task_value)
        self._send_human_state_update("task_change")

    def _set_human_recording_route_state(self, is_recording):
        self.udp_bridge.current_state["human"]["recording_route"] = bool(is_recording)
        self._send_human_state_update("recording_route")

    def _set_human_plan_response_value(self, index, value):
        self.human_plan_response_cache[index] = float(value)

    def _set_team_plan_value(self, index, value):
        self.team_plan_cache[index] = float(value)

    def _send_plan_response(self, human_response, agent_response, selected_variant):
        if self.udp_bridge is None:
            return
        self.human_plan_response_cache[0] = 1.0
        self.human_plan_response_cache[1] = float(human_response)
        self.human_plan_response_cache[2] = float(agent_response)
        self.udp_bridge.send_human_plan_response({
            "human_response": float(human_response),
            "agent_response": float(agent_response),
            "selected_variant": selected_variant,
            "source_screen": "plan_suggestion",
            "mission_time": self._mission_time_elapsed(),
        })

    def _send_human_id_response_value(self, response_value):
        if self.udp_bridge is None:
            return
        response_value = float(response_value)
        if response_value == 0.0:
            return
        target_id = self.udp_bridge.current_agent_id_request.get("target_id")
        self.udp_bridge.send_human_id_response({
            "response": response_value,
            "target_id": target_id,
            "mission_time": self._mission_time_elapsed(),
        })

    def XPluginStart(self):
        """Plugin startup - called when plugin is loaded"""
        return "Custom G1000 Overlay", "com.example.g1000overlay", "Custom G1000 screen modification"


    def XPluginEnable(self):
        try:
            if self.udp_bridge is None:
                self.log("[PI_firemission] Creating UDP bridge in XPluginEnable")
                self.udp_bridge = CockpitHaatoUDPBridge()
                self.log(
                    f"[PI_firemission] Created UDP bridge id={id(self.udp_bridge)} "
                    f"protocol_id={getattr(self.udp_bridge.protocol, 'instance_id', 'n/a')}"
                )
            else:
                self.log(
                    f"[PI_firemission] Reusing UDP bridge id={id(self.udp_bridge)} "
                    f"protocol_id={getattr(self.udp_bridge.protocol, 'instance_id', 'n/a')}"
                )


            ############ Load joystick config from JSON file ############
            control_val = find_dataref("custom/haato/control_prefix").value
            if control_val == 0:
                self.control_prefix = 'logitech'
            elif control_val == 1:
                self.control_prefix = 'thrustmaster'
            elif control_val == 4:
                self.control_prefix = 'microsoft'
            else:
                self.control_prefix = 'unknown_prefix'
                self.log(f"Unknown control prefix value: {control_val}")

            ############ Initialize ############
            self.saved_recordings_file_path = r'C:\Simulation\X-Plane 12\Resources\plugins\PythonPlugins\saved_recordings_backup.json'
            xp.log(f'Using {self.saved_recordings_file_path} for recordings backup')

            # Resolve YAML config path
            candidate_path = os.path.join(os.path.dirname(__file__), f'joystick_{self.control_prefix}.yaml')
            if os.path.exists(candidate_path):
                self.joystick_config_path = candidate_path
                self.joystick_input_enabled = True
            else:
                self.log(f'[PI_gui] Joystick YAML not found at {candidate_path}. Joystick input disabled.')

            self.input_manager = InputManager(
                parent_plugin=self,
                config_path=self.joystick_config_path,
                debounce_delay=0.25
            )

            self.participant_id = self.safe_int_conversion(find_dataref("custom/haato/participant_id").value, 0)
            self.fire_layout = self.safe_int_conversion(find_dataref("custom/haato/fire_layout").value, 0)
            self.initiative_level = self.safe_int_conversion(find_dataref("custom/haato/initiative_level").value, 0)
            self.wingman_active = not self.fire_layout == 4 # Wingman is disabled for practice flight 1 (fire layout 4) but enabled for all other flights

            _haato_cfg = _load_haato_config(_HAATO_ASSETS_DIR)
            self.load_targets_from_yaml(_haato_cfg['missions'][self.fire_layout])
            self.log('loaded targets from config.yaml')
            _plugin_cfg = _haato_cfg.get('plugin', {})
            self.range_to_classify = _plugin_cfg.get('range_to_classify_nm', self.range_to_classify)
            self.range_to_overfly = _plugin_cfg.get('range_to_overfly_nm', self.range_to_overfly)
            self.classify_agent_time_limit = _plugin_cfg.get('classify_agent_time_limit_s', self.classify_agent_time_limit)

            self.load_external_recordings_list()

            self._initialize_datarefs()

            self.input_manager.initialize_joystick()

            self.place_fires()

            self.setup_screens()

            self.setup_controls()

            self.mic_keyed_dref = find_dataref("custom/haato/mic_keyed")
            if self.mic_keyed_dref is None:
                xp.log("custom/haato/mic_keyed dataref not found during enable")

            self.wind_dir = self.wind_dataref.value + self.mag_declination

            # Register command handlers to intercept range knob turns
            xp.registerCommandHandler(self.range_up_cmd, self.range_command_handler, 1, 'up')
            xp.registerCommandHandler(self.range_down_cmd, self.range_command_handler, 1, 'down')
            self.log("Registered G1000 range command handlers")

            self.sim_paused_dataref = find_dataref("sim/time/paused")
            if self.sim_paused_dataref == 0:
                xp.commandOnce(xp.findCommand("sim/operation/pause_toggle"))

            if self.fire_layout == 4:
                xp.speakString(f'Welcome to the first practice flight. Please take off and head to the mission area.')

        except Exception as e:
            self.log(f"ERROR: Could not enable GUI plugin: {e}")
            self.log(traceback.format_exc())

        self.load_splashscreen_image()

        try:
            self.control_reference_image = xpgl.loadImage(f"Resources/plugins/HAATO_assets/control_reference_{self.control_prefix}.png", 0, 0, 1228, 684)
            self.fire_workflow_image = xpgl.loadImage(f"Resources/plugins/HAATO_assets/fire_workflow_reference.png", 0, 0, 1716, 962)
        except:
            self.control_reference_image = None
            self.fire_workflow_image = None


        # === FLIGHT LOOP CREATION ===
        try:
            self.log("=== ATTEMPTING FLIGHT LOOP CREATION ===")
            self.flight_loop_id = xp.createFlightLoop(self.flight_loop_callback)
            self.log(f"flight loop id = {self.flight_loop_id}")
            self.log(f"flight loop id type: {type(self.flight_loop_id)} | bool: {bool(self.flight_loop_id)}")

            if self.flight_loop_id:
                xp.scheduleFlightLoop(self.flight_loop_id, -1)  # -1 means every frame
                self.log('SUCCESS: Flight loop scheduled successfully')
            else:
                self.log("ERROR: createFlightLoop returned None/False/NULL!")
                self.log("ERROR: XPPython3 rejected the flight loop creation")
                self.log("ERROR: This indicates a system-specific issue with flight loop registration")

        except Exception as e:
            self.log("=" * 60)
            self.log(f"EXCEPTION during flight loop creation: {e}")
            self.log(f"Exception type: {type(e)}")
            self.log("Full traceback:")
            self.log(traceback.format_exc())
            self.log("=" * 60)

        # Register callbacks associated with the G1000 screens
        avionics_id_PFD = xp.registerAvionicsCallbacksEx(xp.Device_G1000_PFD_1, after=self.draw_custom_screen_PFD) # xp.Device_G1000_PFD_1 is for the pilot-side display
        avionics_id_MFD = xp.registerAvionicsCallbacksEx(xp.Device_G1000_MFD, after=self.draw_custom_screen_MFD) # xp.Device_G1000_MFD is for the copilot side
        self.log(f"======= Successfully registered callbacks for G1000 device")
        xp.registerKeySniffer(self.MySniffer)

        return 1


    def XPluginDisable(self):
        """Plugin disable - cleanup"""
        # Close experiment log file
        if self.experiment_log_file:
            try:
                # Write final metadata entry
                import datetime
                final_entry = {
                    "metadata": "end",
                    "timestamp": datetime.datetime.now().isoformat(),
                    "mission_time_remaining": self.dataref_mission_time_left.value if self.dataref_mission_time_left else "N/A"
                }
                self.experiment_log_file.write(json.dumps(final_entry) + '\n')
                self.experiment_log_file.close()
                self.log(f"Closed experiment log: {self.experiment_log_path}")
            except Exception as e:
                self.log(f"Error closing experiment log: {e}")

        # Destroy the flight loop
        if self.flight_loop_id:
            xp.destroyFlightLoop(self.flight_loop_id)
            self.flight_loop_id = None

        # Unregister G1000 range command handlers
        if self.range_up_cmd:
            xp.unregisterCommandHandler(self.range_up_cmd, self.range_command_handler, 1, 'up')
            self.log("Unregistered range_up command handler")
        if self.range_down_cmd:
            xp.unregisterCommandHandler(self.range_down_cmd, self.range_command_handler, 1, 'down')
            self.log("Unregistered range_down command handler")

        # Unregister avionics callbacks
        for avionics_id, device_name in self.avionics_callbacks:
            try:
                xp.unregisterAvionicsCallbacks(avionics_id)
                self.log(f"Unregistered callbacks for device: {device_name}")
            except Exception as e:
                self.log(f"Error unregistering device {device_name}: {e}")

        self.avionics_callbacks.clear()

        if getattr(self, 'udp_bridge', None):
            try:
                self.log(
                    f"[PI_firemission] Stopping UDP bridge id={id(self.udp_bridge)} "
                    f"protocol_id={getattr(self.udp_bridge.protocol, 'instance_id', 'n/a')}"
                )
                self.udp_bridge.stop()
                self.log("[PI_gui] Stopped UDP bridge")
            except Exception as e:
                self.log(f"[PI_gui] Error stopping UDP bridge: {e}")
            finally:
                self.udp_bridge = None

    def XPluginStop(self):
        """Plugin stop - final cleanup"""
        if getattr(self, 'udp_bridge', None):
            try:
                self.log(
                    f"[PI_firemission] Stopping UDP bridge in XPluginStop id={id(self.udp_bridge)} "
                    f"protocol_id={getattr(self.udp_bridge.protocol, 'instance_id', 'n/a')}"
                )
                self.udp_bridge.stop()
                self.log("[PI_gui] Stopped UDP bridge in XPluginStop")
            except Exception as e:
                self.log(f"[PI_gui] Error stopping UDP bridge in XPluginStop: {e}")
            finally:
                self.udp_bridge = None


    def load_splashscreen_image(self):
        if self.fire_layout in [4, 5]:
            splashscreen_path = f'splashscreen_practice{self.fire_layout - 3}.png' # practice1 for layout 4, practice2 for layout 5
        else:
            name_dict = {0: 'reactive', 1: 'selfmanaging', 2: 'collaborative'}
            splashscreen_path = f'splashscreen_{name_dict[self.initiative_level]}.png'

        splashscreen_dim_dict = {
            'splashscreen_practice1.png': [1266,888],
            'splashscreen_practice2.png': [1216,854],
            'splashscreen_collaborative.png': [1262,888],
            'splashscreen_reactive.png': [1265,892],
            'splashscreen_selfmanaging.png': [1267,893]
        }
        dims = splashscreen_dim_dict[splashscreen_path]
        self.splashscreen_image = xpgl.loadImage(f"Resources/plugins/HAATO_assets/{splashscreen_path}", 0, 0, dims[0], dims[1])

    def setup_screens(self):
        """Initialize ButtonGrid objects for interactive screens and set up Screen objects."""
        # Determine number of active targets
        active_targets = [t for t in self.targets if t.id != 99]
        n_targets = max(len(active_targets), 1)  # At least 1 to avoid empty grid

        # Commands screen grid
        self.commands_grid = ButtonGrid(rows=n_targets, cols=1)

        # Human plan screen grid
        self.human_plan_grid = ButtonGrid(rows=n_targets, cols=1)

        # Classify screen: 2 cols (MODERATE=0, SEVERE=1)
        self.classify_grid = ButtonGrid(rows=1, cols=2)

        # Classify-agent screen: 3 cols (MODRT=0, AUTO=1, SEVERE=2)
        self.classify_agent_grid = ButtonGrid(rows=1, cols=3)

        # Review recording screen: 2 cols (RELAY=0, ERASE=1)
        self.review_grid = ButtonGrid(rows=1, cols=2)

        # Plan suggestion screen: 2 rows (ACCEPT=0, REJECT=1)
        self.plan_grid = ButtonGrid(rows=2, cols=1)

    def setup_controls(self):
        """Configure all keyboard and joystick controls in one place."""
        # Reset (safe to re-run on re-enable)
        self.input_manager.action_callbacks = {}
        self.input_manager.named_button_callbacks = {}
        self.input_manager.previous_button_states = {}

        # Keyboard bindings (always enabled)
        self.input_manager.register_action_callback(InputAction.UP, self._on_navigate_up)
        self.input_manager.register_action_callback(InputAction.DOWN, self._on_navigate_down)
        self.input_manager.register_action_callback(InputAction.LEFT, self._on_navigate_left)
        self.input_manager.register_action_callback(InputAction.RIGHT, self._on_navigate_right)
        self.input_manager.register_action_callback(InputAction.SELECT, self._on_select)
        self.input_manager.register_action_callback(InputAction.BACK, self._on_goto_primary)

        if not self.joystick_input_enabled:
            self.mic_button_name = None
            return

        # Navigation (all joystick types)
        self.input_manager.register_button('DPAD_UP', fn=self._on_navigate_up)
        self.input_manager.register_button('DPAD_DOWN', fn=self._on_navigate_down)
        self.input_manager.register_button('DPAD_LEFT', fn=self._on_navigate_left)
        self.input_manager.register_button('DPAD_RIGHT', fn=self._on_navigate_right)
        self.input_manager.register_button('TRIGGER', fn=self._on_select)

        # Global actions
        self.input_manager.register_button('RECORD', fn=self.handle_recording)
        self.input_manager.register_button('MAP_ZOOM_IN', fn=self._on_map_zoom_in)
        self.input_manager.register_button('MAP_ZOOM_OUT', fn=self._on_map_zoom_out)
        self.input_manager.register_button('AUTO_SPOT', fn=self._on_auto_spot_toggle)
        self.input_manager.register_button('QUERY_STATUS', fn=self._on_query_status)

        # Map correction buttons (thrustmaster/microsoft only — skipped if not in YAML)
        self.input_manager.register_button('MAP_ZOOM_IN_CORRECTION', fn=self._on_map_zoom_in_correction)
        self.input_manager.register_button('MAP_ZOOM_OUT_CORRECTION', fn=self._on_map_zoom_out_correction)

        # Screen shortcuts
        self.input_manager.register_button('PRIMARY_ESC', fn=self._on_goto_primary)
        self.input_manager.register_button('COMMANDS_SCREEN', fn=lambda: self.set_screen('commands'))
        self.input_manager.register_button('HUMAN_PLAN', fn=lambda: self.set_screen('human_plan'))
        self.input_manager.register_button('CONTROL_REF', fn=lambda: self.set_screen('control_reference'))

        # Mic button by joystick type
        mic_names = {'logitech': 'THUMB', 'microsoft': 'THUMB', 'thrustmaster': 'THUMB'}
        self.mic_button_name = mic_names.get(self.control_prefix)

        self.log('[PI_gui] setup_controls complete')

    def _get_input_screen(self):
        """Return the effective screen for input, including modal overlays not yet rendered."""
        if self.team_plan_dataref and self.team_plan_dataref[0] == 1.0:
            if self.initiative_level == 2.0:
                return 'plan_suggestion'
            if self.initiative_level in [1.0, 1]:
                return 'wingman_task_notification'
        return self.current_screen

    def _plan_suggestion_is_modal(self):
        return self._get_input_screen() == 'plan_suggestion'

    def _on_navigate_up(self):
        screen = self._get_input_screen()
        if screen == 'commands':
            self.commands_grid.navigate('up')
        elif screen == 'human_plan':
            self.human_plan_grid.navigate('up')
        elif screen == 'plan_suggestion':
            self.plan_grid.navigate('up')
            self.human_plan_response_dataref[0] = 1.0
        elif screen == 'primary':
            self.selected_recording_index = max(0, self.selected_recording_index - 1)

    def _on_navigate_down(self):
        screen = self._get_input_screen()
        if screen == 'commands':
            self.commands_grid.navigate('down')
        elif screen == 'human_plan':
            self.human_plan_grid.navigate('down')
        elif screen == 'plan_suggestion':
            self.plan_grid.navigate('down')
            self.human_plan_response_dataref[0] = 1.0
        elif screen == 'primary':
            self.selected_recording_index = min(len(self.saved_recordings), self.selected_recording_index + 1)

    def _on_navigate_left(self):
        screen = self._get_input_screen()
        if screen == 'primary':
            self.set_screen('commands')
        elif screen == 'classify':
            self.classify_grid.navigate('left')
        elif screen == 'classify-agent':
            self.classify_agent_grid.navigate('left')
        elif screen == 'review_recording':
            self.review_grid.navigate('left')
        elif screen == 'plan_suggestion':
            self.show_best_plan = not self.show_best_plan
            self.human_plan_response_dataref[0] = 1.0
        elif screen == 'control_reference':
            self.control_reference_page = max(0, self.control_reference_page - 1)

    def _on_navigate_right(self):
        screen = self._get_input_screen()
        if screen == 'primary':
            self.set_screen('human_plan')
        elif screen == 'classify':
            self.classify_grid.navigate('right')
        elif screen == 'classify-agent':
            self.classify_agent_grid.navigate('right')
        elif screen == 'review_recording':
            self.review_grid.navigate('right')
        elif screen == 'plan_suggestion':
            self.show_best_plan = not self.show_best_plan
            self.human_plan_response_dataref[0] = 1.0
        elif screen == 'control_reference':
            self.control_reference_page = min(self.control_reference_page + 1, 1)

    def _on_select(self):
        screen = self._get_input_screen()

        if screen == 'primary':
            if len(self.saved_recordings) > 0:
                self.set_screen('review_recording')
                self.review_grid.selected_col = 0
                self.cleanup_recordings()

        elif screen == 'wingman_task_notification':
            self._send_plan_response(1.0, 1.0, "primary")
            self._dismiss_active_team_plan()
            self.human_request_plan_suggestion_dataref.value = 0.0
            self.set_screen('primary')
            self.log("Joystick: Task notification dismissed - returned to primary screen")

        elif screen == 'plan_suggestion':
            accept_row = 0
            reject_row = 1

            if self.plan_grid.selected_row == accept_row:
                if self.show_best_plan:
                    self._send_plan_response(1.0, 1.0, "primary")
                    human_task_accepted = 'best_plan'
                    agent_task_accepted = 'best_plan'
                else:
                    self._send_plan_response(2.0, 2.0, "secondary")
                    human_task_accepted = 'second_best_plan'
                    agent_task_accepted = 'second_best_plan'
                self.log("Joystick: PLAN ACCEPTED")
                xp.speakString('2 copies.')
            elif self.plan_grid.selected_row == reject_row:
                human_task_accepted = 'rejected'
                agent_task_accepted = 'rejected'
                self._send_plan_response(0.0, 0.0, "rejected")
                self.log("Joystick: PLAN REJECTED")
                xp.speakString('2 copies, set target when able.')
            else:
                human_task_accepted = 'na'
                agent_task_accepted = 'na'

            if human_task_accepted in ['best_plan', 'second_best_plan']:
                if self.team_plan_dataref[1] != 99.0:
                    if self.show_best_plan:
                        self.set_human_indicated_plan(self.team_plan_dataref[1])
                    else:
                        self.set_human_indicated_plan(self.team_plan_dataref[3])

            self.log_experiment_data({
                'event_type': 'human_plan_response',
                'accept_human': human_task_accepted,
                'accept_agent': agent_task_accepted,
                'plan_for_human': self.team_plan_dataref[1],
                'plan_for_agent': self.team_plan_dataref[2],
            })

            self._dismiss_active_team_plan()
            self.plan_grid.selected_row = 0
            self.plan_grid.selected_col = 0
            self.human_request_plan_suggestion_dataref.value = 0.0
            self.set_screen("primary")
            self.log("Joystick: Plan suggestion DONE - returned to primary screen")

        elif screen == 'classify':
            target_id = self.target_in_classify_range
            classification_value = 1.0 if self.classify_grid.selected_col == 0 else 2.0
            self.dataref_target_classifications[target_id] = classification_value
            xp.log(f'(handle joystick buttons) Classified target {target_id} (1)')

            if self.fire_layout == 4 and not self.has_played_position_hint:
                xp.speakString("Now fly directly over the fire and press the missile release button to record its position.")
                self.has_played_position_hint = True

            self.dataref_target_statuses[target_id] = 1.0
            xp.log(f'Set target {target_id} status to 1.0 (handle_joystick_buttons)')
            if target_id not in self.classified_targets:
                self.classified_targets.append(target_id)

            true_classification = "moderate" if self.targets[target_id].type == 1.0 else "severe"
            marked_classification = "moderate" if classification_value == 1.0 else "severe"
            correct = true_classification == marked_classification
            self.log_experiment_data({
                'event_type': 'human_classify_fire',
                'player': 'human',
                'fire_id': target_id,
                'classification_marked': marked_classification,
                'classification_true': true_classification,
                'correct': correct
            })

            self.set_screen("primary")
            self.log(f"Joystick: Human classified fire {target_id} as {'MODERATE' if self.classify_grid.selected_col == 0 else 'SEVERE'}")

        elif screen == 'classify-agent':
            target_id = self.safe_int_conversion(self.agent_id_request_dataref.value, default=99)
            if target_id < 0 or target_id >= len(self.targets):
                self.log(f"Invalid target_id {target_id} from agent_id_request_dataref")
                return

            if self.classify_agent_grid.selected_col == 1:  # AUTO selected
                self.id_request_response_dataref.value = 1.0
                xp.speakString(f'2 copies, auto-classifying')
                self.log_experiment_data({
                    'event_type': 'wingman_classification_request_response_set_to_auto',
                    'player': 'human',
                    'fire_id': target_id,
                    'classification': 'auto_(check_other_log)'
                })
            else:
                if self.classify_agent_grid.selected_col == 0:
                    classification_value = 1.0
                    response = 2.0
                elif self.classify_agent_grid.selected_col == 2:
                    classification_value = 2.0
                    response = 3.0
                else:
                    xp.log(f'ERROR: Invalid selected_col {self.classify_agent_grid.selected_col} in classify-agent screen')
                    response = -1.0
                    classification_value = None

                if classification_value:
                    if self.dataref_target_classifications and 0 <= target_id < len(self.dataref_target_classifications):
                        self.dataref_target_classifications[target_id] = classification_value
                    else:
                        self.log(f"Cannot set classification for target_id {target_id} - array bounds error")
                xp.log(f'(handle joystick buttons) Classified target {target_id} (2)')
                self.id_request_response_dataref.value = response
                xp.speakString(f'2 copies, classifying {"MODERATE" if classification_value == 1.0 else "SEVERE"}')

                if target_id not in self.classified_targets:
                    self.classified_targets.append(target_id)

                target = self.safe_target_access(target_id)
                if target:
                    true_classification = "moderate" if target.type == 1.0 else "severe"
                else:
                    true_classification = "unknown"
                    self.log(f"Cannot get true classification for invalid target_id {target_id}")
                marked_classification = 'moderate' if self.classify_agent_grid.selected_col == 0 else 'severe'
                correct = true_classification == marked_classification
                self.log_experiment_data({
                    'event_type': 'human_classify_wingman_requested_fire',
                    'fire_id': target_id,
                    'classification_marked': marked_classification,
                    'classification_true': true_classification,
                    'correct': correct
                })
                self.log(f"Joystick: Classified fire {target_id} as {'MODERATE' if self.classify_agent_grid.selected_col == 0 else 'SEVERE'} for agent")

            self.classify_agent_cooldown_start = time.time()
            self.set_screen("primary")

        elif screen == 'commands':
            active_targets = [t for t in self.targets if t.id != 99]
            if self.commands_grid.selected_row < len(active_targets):
                selected_target = active_targets[self.commands_grid.selected_row]
                self.send_command_from_human(selected_target.id)

                if self.target_is_valid_for_wingman(selected_target.id):
                    self.log(f"Joystick: Commanded wingman to target {selected_target.grid_position} (ID: {selected_target.id})")
                    xp.speakString(f'2 copies, going to {selected_target.grid_position}')
                else:
                    self.log(f"Joystick: INVALID Commanded wingman to target {selected_target.grid_position} (ID: {selected_target.id})")

                self.log_experiment_data({
                    'event_type': 'human_command',
                    'command_name': f'FIRE_{selected_target.id}',
                    'fire_id': selected_target.id
                })
            self.set_screen("primary")

        elif screen == 'review_recording':
            if self.selected_recording_index < len(self.saved_recordings):
                recording = self.saved_recordings[self.selected_recording_index]

                if self.review_grid.selected_col == 0:  # RELAY
                    if recording.type == 'position':
                        self.dataref_target_statuses[recording.fire_id] = 2.0
                        self.log(f"Joystick: Relayed position recording for fire {recording.fire_id}")
                        recording.sent_to_ground = True
                        self.saved_recordings = []
                        self.update_external_recordings_list()

                        if self.fire_layout == 4 and not self.has_played_route_hint:
                            xp.speakString("Now fly the drop route over the fire, starting 2 miles upwind and ending 1 mile downwind. The wind direction is shown on your MFD map. When you reach the start position, press the missile release button once to start recording.")
                            self.has_played_route_hint = True

                    elif recording.type == 'initial' and recording.end_pos is not None:
                        self.targets[recording.fire_id].route1_end = recording.end_pos
                        self.targets[recording.fire_id].route1_recorder = 'human'
                        self.targets[recording.fire_id].initial_drop_route_complete = True
                        self.dataref_target_statuses[recording.fire_id] = 3.0
                        xp.log(f'Set target {recording.fire_id} status to 3.0 (handle_joystick_buttons)')
                        self.dataref_target_whoflew_list[recording.fire_id] = 1.0

                        self._set_human_recently_finished_task(3.0)
                        self.human_indicated_plan_dataref.value = -1.0

                        if self.fire_layout == 4 and not self.has_played_route_hint:
                            xp.speakString("Nice job! This practice flight is complete.")
                            self.has_played_route_hint = True

                        recording.sent_to_ground = True
                        self.saved_recordings = []
                        self.update_external_recordings_list()

                    elif recording.type == 'refined' and recording.end_pos is not None:
                        self.targets[recording.fire_id].route2_end = recording.end_pos
                        self.targets[recording.fire_id].route2_recorder = 'human'
                        self.targets[recording.fire_id].refined_drop_route_complete = True
                        self.dataref_target_statuses[recording.fire_id] = 4.0
                        xp.log(f'Set target {recording.fire_id} status to 4.0 (handle_joystick_buttons)')

                        self._set_human_recently_finished_task(4.0)
                        self.human_indicated_plan_dataref.value = -1.0

                        recording.sent_to_ground = True
                        self.saved_recordings = []
                        self.update_external_recordings_list()

                elif self.review_grid.selected_col == 1:  # ERASE
                    self.saved_recordings = []
                    self.update_external_recordings_list()
                    self.log(f"Joystick: Erased recording {self.selected_recording_index}")

                # All options return to primary
                self.set_screen("primary")
                self.review_grid.selected_col = 0

        elif screen == 'human_plan':
            active_targets = [t for t in self.targets if t.id != 99]
            if self.human_plan_grid.selected_row < len(active_targets):
                selected_target = active_targets[self.human_plan_grid.selected_row]
                self.set_human_indicated_plan(float(selected_target.id))
                self.human_plan_last_selected = selected_target.id
                self.log(f"Joystick: Human indicated plan for target {selected_target.grid_position} (ID: {selected_target.id})")
                grid_pos = selected_target.grid_position
                if grid_pos and len(grid_pos) > 1:
                    if grid_pos[0] == 'E':
                        grid_pos = grid_pos[0] + 'e' + grid_pos[1:]
                        xp.log(f'Corrected grid pos to {grid_pos}')
                else:
                    self.log(f"WARNING: Invalid grid_position format: {grid_pos}")
                xp.speakString(f'2 copies, lead 1 {grid_pos}')

            self.set_screen("primary")

    def _on_goto_primary(self):
        """Return to primary screen (blocked from classify/classify-agent screens)."""
        if self.current_screen in ['classify', 'classify-agent'] or self._plan_suggestion_is_modal():
            return
        self.set_screen('primary')

    def _on_map_zoom_in(self):
        xp.commandOnce(self.range_up_cmd)

    def _on_map_zoom_out(self):
        xp.commandOnce(self.range_down_cmd)

    def _on_map_zoom_in_correction(self):
        self.current_range_level = max(0, self.current_range_level - 1)

    def _on_map_zoom_out_correction(self):
        self.current_range_level = min(len(self.g1000_range_steps) - 1, self.current_range_level + 1)

    def _on_auto_spot_toggle(self):
        if self.dataref_auto_spot:
            self.dataref_auto_spot.value = 0.0 if self.dataref_auto_spot.value == 1.0 else 1.0

    def _on_query_status(self):
        if self.wingman_active:
            self.speak_wingman_status()

    def _poll_mic_button(self):
        """Read mic button state from InputManager and handle press/release edge detection."""
        if not self.mic_button_name or not self.input_manager:
            return

        mic_idx = self.input_manager.named_button_map.get(self.mic_button_name.upper())
        if mic_idx is None:
            return

        #mic_state = self.input_manager.safe_joystick_button_state(mic_idx)

        # if mic_state == 1 and not self.mic_press_time:
        #     self.mic_press_time = time.time()
        #
        #
        # if mic_state == 0 and self.mic_press_time:
        #     self.mic_release_time = time.time()
        #     length_of_transmission = self.mic_release_time - self.mic_press_time
        #     radio_call_type, valid_response, response_delay = self.radio_handler.handle_response(length_of_transmission)
        #     self.log_experiment_data({
        #         'event_type': 'radio_call_response',
        #         'radio_call_type': radio_call_type,
        #         'length_of_response': length_of_transmission,
        #         'valid_response': valid_response,
        #         'response_delay': response_delay
        #     })
        #     self.mic_press_time, self.mic_release_time = 0, 0

        btn_idx = self.input_manager.named_button_map.get(self.mic_button_name.upper())
        if btn_idx is None:
            return
        new_val = 1.0 if self.input_manager.safe_joystick_button_state(btn_idx) == 1 else 0.0
        if self.mic_keyed_dref.value != new_val:
            self.mic_keyed_dref.value = new_val
            timestamp = time.time()
            xp.log(f"[CopilotGUI] {timestamp} mic_keyed -> {new_val}")

    def place_fires(self):
        """Place 3-D fire objects for all static (non-dynamic) fires at mission start."""
        xp.log('Placing fires')
        if not hasattr(self, '_fire_instances'):
            self._fire_instances = {}
        for fire in self.targets:
            if not getattr(fire, 'is_dynamic', False):
                self.place_single_fire(fire)
        self.log('Placed all fires')

    def place_single_fire(self, fire):
        """Place a single fire's 3-D instance at its true position."""
        pitch, heading, roll = (0, 0, 0)
        if fire.type == 'moderate':
            objRef = xp.loadObject(r'Custom Scenery\FireSmoke Resources\objects\smoke_fire_emitter_moderate.obj')
        else:
            objRef = xp.loadObject(r'Custom Scenery\FireSmoke Resources\objects\smoke_fire_emitter_severe.obj')
        xp.log(f'Object: {objRef}')
        instance = xp.createInstance(objRef)
        xp.log(f'Instance: {instance}')
        x, y, z = xp.worldToLocal(fire.lat, fire.long, fire.alt)
        position = x, y, z + 10, pitch, heading, roll
        xp.instanceSetPosition(instance, position)
        if not hasattr(self, '_fire_instances'):
            self._fire_instances = {}
        self._fire_instances[fire.id] = instance
        xp.log(f'Placed fire {fire.id}')

        # For debugging - Uncomment this to render a fire at the runway
        # lat = 47.71044513620272
        # long = -121.34487916904042
        # alt = 299.4
        # pitch, heading, roll = (0, 0, 0)
        # objRef = xp.loadObject('Custom Scenery\FireSmoke Resources\objects\smoke_fire_emitter_moderate.obj')
        # instance = xp.createInstance(objRef)
        # x, y, z = xp.worldToLocal(lat, long, alt)
        # position = x, y, z + 10, pitch, heading, roll
        # xp.instanceSetPosition(instance, position)

    def _get_target_by_id(self, target_id):
        for t in self.targets:
            if t.id == target_id:
                return t
        return None

    def _apply_mission_init(self, payload):
        """Apply mission_init: set reported positions and visibility for all known fires."""
        fires = payload.get('fires', [])
        for fd in fires:
            fid = int(fd['id'])
            target = self._get_target_by_id(fid)
            if target is None:
                xp.log(f"[PI_firemission] mission_init: unknown fire id={fid}, skipping")
                continue
            target.reported_lat = float(fd['reported_lat'])
            target.reported_long = float(fd['reported_lon'])
            target.reported_alt = float(fd.get('reported_alt', target.alt))
            target.is_known_to_cockpit = True
        xp.log(f"[PI_firemission] mission_init applied: {len(fires)} known fires")

    def _apply_fire_spawn_event(self, payload):
        """Handle a dynamic fire appearing mid-mission."""
        fid = int(payload['id'])
        is_known = bool(payload.get('is_known', False))
        target = self._get_target_by_id(fid)
        if target is None:
            xp.log(f"[PI_firemission] fire_spawn_event: fire id={fid} not in targets list (was it pre-loaded?)")
            return
        target.is_known_to_cockpit = is_known
        if is_known:
            target.reported_lat = float(payload.get('reported_lat', target.lat))
            target.reported_long = float(payload.get('reported_lon', target.long))
            target.reported_alt = float(payload.get('reported_alt', target.alt))
        # Place the 3-D fire object at its true position now that the event has fired
        try:
            self.place_single_fire(target)
        except Exception as e:
            xp.log(f"[PI_firemission] fire_spawn_event: error placing fire id={fid}: {e}")
        xp.log(f"[PI_firemission] fire_spawn_event applied: id={fid} known={is_known}")

    def _apply_fire_discovered(self, payload):
        """Handle a previously-unknown fire being discovered within visual range."""
        fid = int(payload['id'])
        target = self._get_target_by_id(fid)
        if target is None:
            xp.log(f"[PI_firemission] fire_discovered: unknown fire id={fid}, skipping")
            return
        target.reported_lat = float(payload['reported_lat'])
        target.reported_long = float(payload['reported_lon'])
        target.reported_alt = float(payload.get('reported_alt', target.alt))
        target.is_known_to_cockpit = True
        xp.log(f"[PI_firemission] fire_discovered: id={fid} now visible on MFD")

    def route_start_is_allowed(self, fire_id):
        return fire_recordings.route_start_is_allowed(self, fire_id)
    def handle_recording(self):
        if self._plan_suggestion_is_modal():
            self.log("Ignored recording input while plan suggestion screen is active")
            return
        return fire_recordings.handle_recording(self)
    def _placeholder_handle_joystick_start(self):
        pass

    def flight_loop_callback(self, sinceLast, elapsedTime, counter, refCon):
        self.step += 1
        if self.udp_bridge is not None:
            self.udp_bridge.flight_loop_callback()
            if self.step <= 5 or self.step % 300 == 0:
                self._log_udp_bridge_state(f"flight_loop step={self.step}", force=True)

            # Process pending fire state events from the server
            if self.udp_bridge.pending_mission_init is not None:
                self._apply_mission_init(self.udp_bridge.pending_mission_init)
                self.udp_bridge.pending_mission_init = None

            for evt in list(self.udp_bridge.pending_fire_spawn_events):
                self._apply_fire_spawn_event(evt)
            self.udp_bridge.pending_fire_spawn_events.clear()

            for evt in list(self.udp_bridge.pending_fire_discovered):
                self._apply_fire_discovered(evt)
            self.udp_bridge.pending_fire_discovered.clear()

        self._sync_team_plan_cache_from_udp()

        if self.change_screen_dataref.value != -1.0:
            self.current_screen = self.screen_val_dict[self.change_screen_dataref.value]
            self.change_screen_dataref.value = -1.0

        self.pixels_per_nm = (self.map_radius_pixels * 2) / self.g1000_range_steps[self.current_range_level]

        current_wingman_plan = self.dataref_wingman_status.value # TODO test



        if self.initiative_level == 1.0:
            if self.first_step_done:
                if current_wingman_plan not in [99.0, 9.0] and current_wingman_plan != self.last_wingman_plan and current_wingman_plan != self.command_from_human_dataref.value:
                    self.speak_wingman_status()
                    self.current_screen = 'wingman_task_notification'
        self.first_step_done = True
        self.last_wingman_plan = current_wingman_plan


        if self.fire_layout == 4 and self.human_alt_dref.value > 400 and not self.human_has_taken_off:
            self.human_has_taken_off = True
            xp.speakString("Check the map on your right MFD to see where the fire is. You can also see it from here. Fly to the fire and classify it.")

        # Decide whether wingman should send a status update
        if self.steps_since_last_status_update > 20 and self.wingman_active:
            #self.speak_wingman_status() # Was causing bug
            self.steps_since_last_status_update = 0
        self.steps_since_last_status_update += 1

        # Initialize experiment log file
        if self.start_logging_dataref.value == 1.0 and not self.already_started_logging and find_dataref("custom/haato/initiative_level").value != 99.0:
            self._initialize_experiment_log()
            self.already_started_logging = True
            self.log(f'Got start_logging dataref. Initializing experiment log')


        if self.map_zoom_range_dref.value != -1.0:
            try:
                self.current_range_level = self.g1000_range_steps.index(int(self.map_zoom_range_dref.value))
                self.map_zoom_range_dref.value = -1.0 # Reset back to inactive
            except:
                self.log(f'invalid map zoom range specified')

        # Handle radio calls
        #self.radio_handler.act()

        # Process sound queue for delayed sounds
        self.sound_manager._process_queue()

        # Handle joystick and keyboard input
        if self.input_manager:
            self.input_manager.process_joystick_buttons()
            self._poll_mic_button()

        # Periodically update classified_targets from datarefs
        if elapsedTime - self.last_update_time >= self.update_interval:
            for i in range(self.num_targets):
                class_dref = self.dataref_target_classifications[i]
                classification = class_dref#.value
                if classification in [1.0, 2.0] and i not in self.classified_targets:
                    self.classified_targets.append(i)
                if classification == 0.0 and i in self.classified_targets:
                    self.classified_targets.remove(i)
            self.last_update_time = elapsedTime

        # Check if we need to reset id_request_response dataref after delay
        if self.id_request_response_set_time is not None:
            elapsed = time.time() - self.id_request_response_set_time
            if elapsed >= self.id_request_response_reset_delay:
                self.id_request_response_set_time = None

        # Recording trajectory points
        human_recording_route = False
        if self.active_route_recording is not None:
            recording = self.active_route_recording
            current_pos = (self.human_lat_dref.value, self.human_long_dref.value, self.human_alt_dref.value)
            human_recording_route = True

            # Only add point if we've moved enough distance (0.05 NM)
            if recording.trajectory_points:
                last_point = recording.trajectory_points[-1]
                distance = GridSystem.calculate_distance(
                    last_point[0], last_point[1],
                    current_pos[0], current_pos[1]
                )
                if distance >= 0.05:
                    recording.trajectory_points.append(current_pos)
            else:
                recording.trajectory_points.append(current_pos)

        self._set_human_recording_route_state(human_recording_route)

        return -1


    def speak_wingman_status(self):
        wingman_status_val = self.dataref_wingman_status.value
        wingman_subtask = self.wingman_subtask_proxy.value
        wingman_position = GridSystem.latlon_to_grid_position(self.wingman_lat_dref.value, self.wingman_long_dref.value)

        fire_id = self.safe_int_conversion(wingman_status_val, 99)
        if fire_id <= self.num_targets:
            fire_lat, fire_long = self.targets[fire_id].lat, self.targets[fire_id].long
        else:
            fire_lat, fire_long = None, None

        if wingman_status_val <= len(self.targets):
            wingman_target = self.safe_target_access(fire_id)
            if wingman_target is None:
                self.log(f"Cannot access wingman target {fire_id}")
                return
            try:
                wingman_task = self.task_dict[wingman_target.status]
            except:
                wingman_task = 'UNKNOWN TASK'

            whoflew = self.safe_array_access(self.dataref_target_whoflew_list, fire_id, 0.0)
            status_is_valid = not (wingman_task == self.task_dict.get(3.0, 'UNKNOWN') and whoflew == 2.0) # Invalid if wingman flew initial and is about to say it will refine the same route

            if wingman_subtask == 1.0 or wingman_task in ['CLASSIFYING FIRE', 'MARKING POSITION']:
                if fire_lat is not None:
                    dist_to_target = GridSystem.calculate_distance(self.wingman_lat_dref.value, self.wingman_long_dref.value, fire_lat, fire_long)
                    additional_info = f', {round(dist_to_target)} miles out'
                else:
                    additional_info = ''

            elif wingman_subtask == 2.0:
                additional_info = ' midroute'
            else:
                additional_info = ''

            message = f'{wingman_task} at {wingman_target.grid_position} {additional_info} Lead 2.'

            if status_is_valid and self.first_speakstatus_called:
                pass  # xp.speakString(message)   # Disabled: Python-side Piper TTS handles wingman audio

        elif wingman_status_val == 9.0:
            message = f'Holding in {wingman_position} Lead 2.'
            # xp.speakString(message)   # Disabled: Python-side Piper TTS handles wingman audio
        else:
            message = 'status unknown Lead 2.'
            # xp.speakString(message)   # Disabled: Python-side Piper TTS handles wingman audio

        self.first_speakstatus_called = True


    def range_command_handler(self, commandRef, phase, refCon):
        # TODO move into haato utilities
        """
        Callback when G1000 Range Rotary knob is turned

        Args:
            commandRef: The command that was executed
            phase: 0=CommandBegin, 1=CommandContinue, 2=CommandEnd
            refCon: 'up' or 'down' (the string we passed during registration)

        Returns:
            1 to allow X-Plane to continue processing the command
        """
        #self.log(f'range_command_handler phase = {phase}, refCon = {refCon}')
        if phase == 0:  # Command begins (knob turned)
            if refCon == 'up':
                # Zoom OUT (increase range, decrease zoom level)
                self.current_range_level = min(len(self.g1000_range_steps) - 1, self.current_range_level + 1)
                self.log(f"Range knob turned UP, new level: {self.current_range_level}, range: {self.g1000_range_steps[self.current_range_level]} nm")
            elif refCon == 'down':
                # Zoom IN (decrease range, increase zoom level)
                self.current_range_level = max(0, self.current_range_level - 1)
                self.log(f"Range knob turned DOWN, new level: {self.current_range_level}, range: {self.g1000_range_steps[self.current_range_level]} nm")

        return 1  # Return 1 to allow X-Plane to continue processing

    def draw_custom_screen_PFD(self, deviceID, isBefore, refCon):
        # dimensions are 1024x768
        """Custom drawing callback for the G1000 screen"""
        try:
            xp.setGraphicsState(0, 1)

            if self.log_file_identifier != int(find_dataref("custom/haato/log_file_identifier").value):
                rendering.draw_refresh_reminder(self.font60)
                return 1

            self.update_target_classes()
            self.get_target_options()
            agent_request_id = self.agent_id_request_dataref.value

            # Check for plan suggestion screen (highest priority)
            if self.team_plan_dataref[0] == 1.0: # Detect when plan is first sent (transition from 0 to 1)

                if self.last_show_plan_value == 0.0:
                    self.log_experiment_data({
                        'event_type': 'agent_send_plan',
                        'plan_for_human': self.team_plan_dataref[1],
                        'plan_for_agent': self.team_plan_dataref[2]
                    })

                if self.initiative_level in [1.0, 1] and self.current_screen != 'wingman_task_notification':
                    xp.log(f'Init level 1 and plan received, setting to task notification screen')
                    self.current_screen = 'wingman_task_notification'
                    find_dataref("custom/haato/current_screen").value = 10.0
                    self.sound_manager.play_sound(self.notification_sound)
                    self.speak_wingman_status()

                elif self.initiative_level == 2.0 and self.current_screen != 'plan_suggestion':
                    xp.log(f'Init level 2 and plan received, setting to plan suggest screen')
                    self.current_screen = 'plan_suggestion'
                    find_dataref("custom/haato/current_screen").value = 2.0
                    self.show_best_plan = True
                    self.sound_manager.play_sound(self.notification_sound)

                    if self.team_plan_dataref[1] == 99.0 and self.team_plan_dataref[2] == 99.0: # No plan found for either member
                        xp.speakString('No plan calculated, proceed as needed')
                    else:
                        xp.speakString('Lead 2 Recommending task plan')
                    self.plan_grid.selected_row = 0
                    self.plan_grid.selected_col = 0


            # Check if agent is requesting ID help (takes priority over human proximity)
            elif agent_request_id != 99.0 and self.current_screen not in ['none', 'splashscreen'] and agent_request_id not in self.classified_targets:
                cooldown_active = False # Check if cooldown is active
                if self.classify_agent_cooldown_start is not None:
                    elapsed = time.time() - self.classify_agent_cooldown_start
                    if elapsed < self.classify_agent_cooldown_duration:
                        cooldown_active = True

                # Force the agent classify screen when agent requests help (unless cooldown is active)
                if not cooldown_active and self.current_screen != 'classify-agent':
                    self.log('current screen is not classify-agent')
                    # Only reset selection when first entering classify-agent screen
                    self.current_screen = 'classify-agent'
                    find_dataref("custom/haato/current_screen").value = 6.0
                    self.classify_agent_request_time = time.time()
                    self.sound_manager.play_sound(self.notification_sound)
                    # xp.speakString(f'1 request ID of fire on your display')  # Disabled: Python-side Piper TTS
                    self.classify_agent_grid.selected_col = 1  # Reset selection to AUTO (middle button) by default

            else:
                # Check if human is in range of a target and force classify screen
                if self.target_in_classify_range is not None and self.current_screen not in ['none', 'splashscreen'] and self.targets[int(self.target_in_classify_range)].classification is None: #self.human_in_classify_range not in self.classified_targets:
                    # Force the classify screen when in range of a target
                    if self.current_screen != 'classify': # Only reset selection when first entering classify screen
                        self.current_screen = 'classify'
                        find_dataref("custom/haato/current_screen").value = 5.0
                        self.sound_manager.play_sound(self.notification_sound)
                        self.classify_grid.selected_col = 0  # Reset selection to MODERATE by default

                        if self.fire_layout == 4 and not self.has_played_classify_hint:
                            xp.speakString("Press the thumbstick left or right to choose a classification, then pull the trigger to select.")
                            self.has_played_classify_hint = True


            # Track show_plan value for next iteration
            self.last_show_plan_value = self.team_plan_dataref[0]

            if self.current_screen == 'none':
                return 0

            elif self.current_screen == 'control_reference':
                self.render_control_reference_screen()

            elif self.current_screen == 'splashscreen':
                self.render_splashscreen()

            elif self.current_screen == 'primary':
                self.render_primary_screen()

            elif self.current_screen == 'review_recording':
                self.render_review_recording_screen()

            elif self.current_screen == 'classify':
                self.render_classify_screen()

            elif self.current_screen == 'classify-agent':
                self.render_classify_agent_screen()

            elif self.current_screen == 'commands':
                self.render_commands_screen()

            elif self.current_screen == 'plan_suggestion':
                self.render_plan_suggestion()

            elif self.current_screen == 'wingman_task_notification':
                self.render_task_notification()

            elif self.current_screen == 'human_plan':
                self.render_human_plan_screen()

            return 1  # Returning 1 means the function should continue to draw. Return 0 to skip rendering this frame

        except Exception as e:
            self.log(f"Error in draw_custom_screen_PFD: {e}")
            self.log(traceback.format_exc())
            return 0  # Stop rendering on error to prevent spam


    def draw_custom_screen_MFD(self, deviceID, isBefore, refCon):
        """Custom drawing callback for the G1000 MFD screen"""

        xp.setGraphicsState(0, 1)
        if self.log_file_identifier != int(find_dataref("custom/haato/log_file_identifier").value):
            rendering.draw_refresh_reminder(self.font60)
            return 1

        ############ Draw wind direction arrow in bottom right corner ############
        rendering.draw_wind_arrow(x=0, y=30, length=70, wind_direction=self.wind_dir, font=self.font_big)

        # Draw human position as a green triangle
        current_heading = int(find_dataref('sim/flightmodel/position/true_psi').value)
        rendering.draw_angled_triangle(self.screen_width / 2 + 65, self.screen_height / 2 - 20, 30, current_heading + self.mag_declination, color = Colors['green'])

        ############ Draw grid on MFD ############
        grid_offset_x = (self.aor_center_long - self.lon_dataref.value) * self.lon_scale_nm * self.pixels_per_nm
        grid_offset_y = (self.aor_center_lat - self.lat_dataref.value) * self.lat_scale_nm * self.pixels_per_nm

        if self.current_screen == 'plan_suggestion':
            grid_thickness = 2.5
            alpha = 0.3
            self.draw_border_around_screen(Colors['red'], thickness=20, flashing=True)
        else:
            grid_thickness = 4.0
            alpha = 0.6
        self.draw_grid_on_mfd(self.aor_center_lat, self.aor_center_long, self.mfd_center_x + grid_offset_x, self.mfd_center_y + grid_offset_y, self.pixels_per_nm, grid_thickness, alpha)

        xpgl.drawText(self.font, self.screen_width/4, 45, "ZOOM IN/OUT: TMS UP/DOWN")


        ############ Draw fires ############
        for i in range(len(self.targets)):
            target = self.targets[i]

            # Only render fires the cockpit knows about
            if not getattr(target, 'is_known_to_cockpit', True):
                continue

            # Use the reported (MFD) position for rendering, not the true physics position
            render_lat = getattr(target, 'reported_lat', target.lat)
            render_long = getattr(target, 'reported_long', target.long)
            offset_x, offset_y = GridSystem.latlon_to_map_pixel_offset(render_lat, render_long, self.aor_center_lat, self.aor_center_long, self.pixels_per_nm)

            # Index status by target.id (not list index) to support non-sequential fire IDs
            target_status = self.dataref_target_statuses[target.id]

            if target_status < 1.0: # Highlight grid cell red for unclassified fires
                grid_cell_center_x = round(offset_x / self.pixels_per_nm) * self.pixels_per_nm
                grid_cell_center_y = round(offset_y / self.pixels_per_nm) * self.pixels_per_nm

                # Calculate grid cell bounds (1 NM cells)
                cell_half_size = self.pixels_per_nm / 2
                cell_left = self.mfd_center_x + grid_offset_x + grid_cell_center_x - cell_half_size
                cell_bottom = self.mfd_center_y + grid_offset_y + grid_cell_center_y - cell_half_size
                cell_width = self.pixels_per_nm
                cell_height = self.pixels_per_nm
                xpgl.drawRectangle(cell_left, cell_bottom, cell_width, cell_height, color=Colors['red'])

            else:
                target_screen_x = self.mfd_center_x + grid_offset_x + offset_x
                target_screen_y = self.mfd_center_y + grid_offset_y + offset_y

                if target_status == 1.0: # Classified. Render as a small dot
                    xpgl.drawCircle(int(target_screen_x), int(target_screen_y), 10, isFilled=True, num_vertices=8,color=Colors['red'])
                    xpgl.drawCircle(int(target_screen_x), int(target_screen_y), 10, isFilled=False, num_vertices=8,color=Colors['black'])

                elif target_status == 2.0: # Position marked. Render as a red circle with dot inside
                    xpgl.drawCircle(int(target_screen_x), int(target_screen_y), 10, isFilled=True, num_vertices=8,color=Colors['red'])
                    xpgl.drawCircle(int(target_screen_x), int(target_screen_y), 10, isFilled=False, num_vertices=8,color=Colors['black'])
                    xpgl.drawCircle(int(target_screen_x), int(target_screen_y), 5, isFilled=False, num_vertices=8,color=Colors['black'])
                    self.draw_drop_route(target.lat, target.long, Colors['red'])

                elif target_status == 3.0: # Initial route marked
                    xpgl.drawCircle(int(target_screen_x), int(target_screen_y), 10, isFilled=True, num_vertices=8,color=Colors['red'])
                    xpgl.drawCircle(int(target_screen_x), int(target_screen_y), 10, isFilled=False, num_vertices=8,color=Colors['black'])
                    xpgl.drawCircle(int(target_screen_x), int(target_screen_y), 5, isFilled=False, num_vertices=8,color=Colors['black'])

                    whoflew = self.dataref_target_whoflew_list[target.id]
                    if whoflew == 1.0:  # Human flew
                        self.draw_drop_route(target.lat, target.long, (0, 1.0, 0)) # green
                    else:  # Wingman flew
                        self.draw_drop_route(target.lat, target.long, Colors['cyan'])

                elif target_status == 4.0: # second route marked. color gray
                    xpgl.drawCircle(int(target_screen_x), int(target_screen_y), 10, isFilled=True, num_vertices=8, color=Colors['blue'])
                    self.draw_drop_route(target.lat, target.long, (0.2, 0.2, 0.2))

                # Render target's altitude on MFD so the human can follow altitude constraints
                if target_status != 4.0:
                    xpgl.drawText(self.font50, int(target_screen_x + 20), int(target_screen_y - 15), f"{int(target.alt*self.m_to_ft)}'", alignment="L", color=Colors['red']) # TODO remove the altitude meter conversion when we convert everything to ft


        ############ Draw markers for human and wingman current targets ############
        marker_size = 0.35235 * self.pixels_per_nm
        if self.human_indicated_plan_dataref.value >= 0:
            pos = self.get_target_screen_position(self.human_indicated_plan_dataref.value, grid_offset_x, grid_offset_y)
            if pos:
                self.draw_target_marker(pos[0], pos[1], Colors['green'], 'H', marker_size = marker_size)

        if self.dataref_wingman_status.value >= 0:
            pos = self.get_target_screen_position(self.dataref_wingman_status.value, grid_offset_x, grid_offset_y)
            if pos:
                self.draw_target_marker(pos[0], pos[1], Colors['cyan'], 'W', marker_size = marker_size)


        ############ Draw wingman position ############
        wingman_lat = self.wingman_lat_dref.value
        wingman_lon = self.wingman_long_dref.value
        if wingman_lat != 0 or wingman_lon != 0:
            wingman_offset_x, wingman_offset_y = GridSystem.latlon_to_map_pixel_offset(wingman_lat, wingman_lon, self.aor_center_lat, self.aor_center_long, self.pixels_per_nm) # Calculate offset from fixed grid center
            wingman_screen_x = self.mfd_center_x + grid_offset_x + wingman_offset_x # Calculate final screen position with grid offset
            wingman_screen_y = self.mfd_center_y + grid_offset_y + wingman_offset_y

            rendering.draw_angled_triangle(wingman_screen_x, wingman_screen_y, 30, self.wingman_heading_dref.value)
            xpgl.drawText(self.font_small, int(wingman_screen_x + 20), int(wingman_screen_y + -8), "W", alignment="L", color=Colors['cyan'])

        # Display current map zoom level in top-right corner of MFD
        map_range_nm = self.g1000_range_steps[self.current_range_level]
        zoom_text = f"{map_range_nm:.0f} NM"
        xpgl.drawText(self.font, 1020, 85, zoom_text, alignment="R", color=Colors['white'])

        if self.current_screen == 'plan_suggestion':
            self.render_plan_suggestion_MFD(wingman_screen_x, wingman_screen_y, grid_offset_x, grid_offset_y)
        return 1


    def render_plan_suggestion_MFD(self, wingman_screen_x, wingman_screen_y, grid_offset_x, grid_offset_y):
        return fire_gui.render_plan_suggestion_MFD(
            self,
            {},
            wingman_screen_x,
            wingman_screen_y,
            grid_offset_x,
            grid_offset_y,
        )
    def draw_drop_route(self, lat, long, color):
        return fire_gui.draw_drop_route(self, lat, long, color)
    def draw_grid_on_mfd(self, lat, lon, center_x, center_y, pixels_per_nm, thickness=4.0, alpha=0.6):
        return fire_gui.draw_grid_on_mfd(self, lat, lon, center_x, center_y, pixels_per_nm, thickness, alpha)
    def _log_recording_success(self, message):
        """Play beep sound and log success message"""
        self.log(message)
        self.sound_manager.play_sound(self.recording_beep_sound)
        self.log('played beep')


    def _find_route_recording(self, fire_id, route_type):
        return fire_recordings._find_route_recording(self, fire_id, route_type)
    def _get_route_heading(self, fire_id, from_position):
        return fire_recordings._get_route_heading(self, fire_id, from_position)
    def _build_position_log_data(self, fire_id, recording, marked_position):
        return fire_recordings._build_position_log_data(self, fire_id, recording, marked_position)
    def _build_route_log_data(self, fire_id, recording, position, heading, event_type, route_type=None):
        return fire_recordings._build_route_log_data(self, fire_id, recording, position, heading, event_type, route_type)
    def _handle_position_recording(self, fire_id, marked_position):
        return fire_recordings._handle_position_recording(self, fire_id, marked_position)
    def _handle_route_start(self, marked_position):
        return fire_recordings._handle_route_start(self, marked_position)
    def _handle_route_end(self, marked_position):
        return fire_recordings._handle_route_end(self, marked_position)
    def cleanup_recordings(self):
        return fire_recordings.cleanup_recordings(self)
    def update_external_recordings_list(self):
        return fire_recordings.update_external_recordings_list(self)
    def load_external_recordings_list(self):
        return fire_recordings.load_external_recordings_list(self)
    def MySniffer(self, key, flags, vKey, refCon):
        if self.input_manager:
            self.input_manager.process_keyboard(vKey)
        return 1

    def send_command_from_human(self, cmd_val):
        cmd_val = float(cmd_val)
        self.command_from_human_dataref.value = cmd_val

        if not self.target_is_valid_for_wingman(cmd_val):
            xp.speakString(f'Negative lead 1, target invalid.')
            self.command_from_human_dataref.value = 12.0

        if cmd_val == self.human_indicated_plan_dataref.value:
            self.human_indicated_plan_dataref.value = -1.0

    def set_human_indicated_plan(self, plan_val):
        plan_val = float(plan_val)
        self.human_indicated_plan_dataref.value = plan_val

        if plan_val == self.command_from_human_dataref.value:
            self.command_from_human_dataref.value = 12.0

    def target_is_valid_for_wingman(self, target_id):
        try:
            target = self.targets[int(target_id)]
            self.log(f'Target is valid for wingman: {target_id} - status {target.status}, target.route1_recorder = {target.route1_recorder}')
            if target.status == 4.0 or (target.status == 3.0 and target.route1_recorder == 'wingman'):
                self.log(f'FALSE: target status {target.status}, target.route1_recorder = {target.route1_recorder}')
                return False
            else:
                return True
        except Exception as e:
            self.log(traceback.format_exc())
            self.log(e)
            return False

    def activate_selected_button(self):
        """Activate the currently selected button on the commands screen"""
        if self.commands_grid.selected_row == 0: # Top row: Fire 0-7 buttons
            # Set command_from_human to values 0-7 (fire commands) and latch the selection
            fire_id = self.commands_grid.selected_col
            self.send_command_from_human(fire_id)
            self.log(f"Activated Fire {fire_id} button (command value: {fire_id})")

            # Log human command
            self.log_experiment_data({
                'event_type': 'human_command',
                'command_name': f'FIRE_{fire_id}',
                'fire_id': fire_id
            })

        elif self.commands_grid.selected_row == 1: # Bottom row: Other command buttons
            if self.commands_grid.selected_col == 0: # FOLLOW ME button
                self.send_command_from_human(8.0)
                self.log("Activated FOLLOW ME button")

                # Log human command
                self.log_experiment_data({
                    'event_type': 'human_command',
                    'command_name': 'FOLLOW_ME'
                })

            elif self.commands_grid.selected_col == 1: # CLR COMMANDS button
                self.command_from_human_dataref.value = 12.0
                self.log("Activated CLR COMMANDS button")

                # Log human command
                self.log_experiment_data({
                    'event_type': 'human_command',
                    'command_name': 'CLR_COMMANDS'
                })

            elif self.commands_grid.selected_col == 2:
                self.human_request_plan_suggestion_dataref.value = 1.0
                self.sound_manager.play_sound(self.recording_beep_sound)

    def activate_human_plan_button(self):
        """Activate the currently selected button on the human plan screen"""
        if self.human_plan_selected_button < 8:
            # Fire buttons (0-7): Send fire ID to dataref
            fire_id = self.human_plan_selected_button

            self.set_human_indicated_plan(float(fire_id))
            self.human_plan_last_selected = fire_id
            self.log(f"Human indicated plan: Fire {fire_id + 1} (dataref value: {float(fire_id)})")
        else:
            # Clear button (8): Send -1.0 to clear selection
            self.human_indicated_plan_dataref.value = -1.0
            self.human_plan_last_selected = None
            self.log("Human indicated plan: Cleared (dataref value: -1.0)")

        # Auto-close screen after selection
        self.set_screen("primary")
        self.log("Closed human plan screen after selection")

    def _get_render_control_reference_screen_data(self):
        return {'page': self.control_reference_page}

    def _get_render_splashscreen_data(self):
        return {'image': self.splashscreen_image}

    def _get_render_primary_screen_data(self):
        self._log_udp_bridge_state("render_primary")
        return {
            'current_heading': (int(find_dataref('sim/flightmodel/position/true_psi').value) - self.mag_declination) % 360,
            'time_remaining': None if self.dataref_mission_time_left is None else self.dataref_mission_time_left.value,
            'current_alt': find_dataref('sim/cockpit/pressure/cabin_altitude_actual_ft').value,
        }

    def _get_render_commands_screen_data(self):
        return {'version': 'command_wingman', 'map_side': 'right'}

    def _get_render_human_plan_screen_data(self):
        return {'version': 'human_plan', 'map_side': 'left'}

    def _get_render_task_assignment_screen_data(self, version, map_side):
        return {'version': version, 'map_side': map_side}

    def _get_render_task_notification_data(self):
        return {}

    def _get_render_plan_suggestion_data(self):
        return {}

    def _get_render_classify_screen_data(self):
        target_id = self.target_in_classify_range
        return {
            'target_id': target_id,
            'fire_image': None if target_id is None else self.fire_images.get(target_id),
            'selected_col': 0 if self.classify_grid is None else self.classify_grid.selected_col,
        }

    def _get_render_review_recording_screen_data(self):
        if not self.saved_recordings or self.selected_recording_index >= len(self.saved_recordings):
            return {'recording': None}
        return {'recording': self.saved_recordings[self.selected_recording_index]}

    def _get_render_classify_agent_screen_data(self):
        target_id_raw = self.agent_id_request_dataref.value
        target_id = int(target_id_raw)
        return {
            'target_id_raw': target_id_raw,
            'target_id': target_id,
            'fire_image': self.fire_images.get(target_id),
            'selected_col': 0 if self.classify_agent_grid is None else self.classify_agent_grid.selected_col,
        }

    def render_control_reference_screen(self):
        return fire_gui.render_control_reference_screen(self, self._get_render_control_reference_screen_data())

    def render_splashscreen(self):
        return fire_gui.render_splashscreen(self, self._get_render_splashscreen_data())

    def render_primary_screen(self):
        return fire_gui.render_primary_screen(self, self._get_render_primary_screen_data())

    def render_commands_screen(self):
        data = self._get_render_commands_screen_data()
        return fire_gui.render_commands_screen(self, data)

    def render_human_plan_screen(self):
        data = self._get_render_human_plan_screen_data()
        return fire_gui.render_human_plan_screen(self, data)

    def render_task_assignment_screen(self, version:str, map_side:str):
        data = self._get_render_task_assignment_screen_data(version, map_side)
        return fire_gui.render_task_assignment_screen(self, data, version, map_side)
    def parse_task_float(self, dref_value):
        """
        Parse task float from dataref to extract task type and target ID.

        Args:
            dref_value: Float value from plan dataref (0.0-7.0 for fire IDs, 99.0 for no plan)

        Returns:
            Tuple of (task_type: str, target_id: int)
            - task_type: "classify", "mark_position", "initial_route", "refined_route", or None
            - target_id: Fire index (0-7) or None
        """
        # Check for "no plan" value
        if dref_value == 99.0:
            return (None, None)

        if dref_value == 9.0:
            return ('HOLDING', None)

        if dref_value >= len(self.targets):
            task_type = 'Wait to refine'
            target_id = self.safe_int_conversion(dref_value, -1) - len(self.targets)
            return (task_type, target_id)

        # Extract fire ID
        target_id = self.safe_int_conversion(dref_value, -1)

        # Validate fire ID is in valid range
        if target_id < 0 or target_id > 7:
            return (None, None)

        # Look up the fire's current status
        target = self.safe_target_access(target_id)
        if target is None:
            return (None, None)
        status = target.status

        # Map status to task type
        if status == 0.0:
            task_type = "classify"
        elif status == 1.0:
            task_type = "mark position"
        elif status == 2.0:
            task_type = "initial route"
        elif status == 3.0:
            task_type = "refined route"
        else:
            # Status 4.0 or invalid - task complete or unknown
            task_type = "unknown"
       # xp.log(f'[Parse task float]: {task_type}, {target_id}')
        return (task_type, target_id)


    def render_task_notification(self):
        return fire_gui.render_task_notification(self, self._get_render_task_notification_data())

    def render_plan_suggestion(self):
        return fire_gui.render_plan_suggestion(self, self._get_render_plan_suggestion_data())
    def set_screen(self, screen_name:str):
        prev_screen = self.current_screen
        self.current_screen = screen_name
        self.log(f"Switch screen: {prev_screen} -> {self.current_screen}")

        new_screen_id = 99.0
        for key in self.screen_val_dict:
            if self.screen_val_dict[key] == screen_name:
                new_screen_id = key
        find_dataref("custom/haato/current_screen").value = new_screen_id

        if self.current_screen == 'primary':
             if self.sim_paused_dataref.value == 1:
                xp.commandOnce(xp.findCommand("sim/operation/pause_toggle"))



    def render_classify_screen(self):
        return fire_gui.render_classify_screen(self, self._get_render_classify_screen_data())

    def render_review_recording_screen(self):
        return fire_gui.render_review_recording_screen(self, self._get_render_review_recording_screen_data())

    def render_classify_agent_screen(self):
        return fire_gui.render_classify_agent_screen(self, self._get_render_classify_agent_screen_data())

    def draw_target_for_task(self, task_type, target, grid_params, member, xy_override=None):
        return fire_gui.draw_target_for_task(self, task_type, target, grid_params, member, xy_override)

    def draw_target_marker(self, screen_x, screen_y, color, label, linewidth=6.0, marker_size=20, label_offset_y = 25):
        return fire_gui.draw_target_marker(self, screen_x, screen_y, color, label, linewidth, marker_size, label_offset_y)
    def load_targets_from_yaml(self, mission_data):
        """Load targets from a pre-parsed mission config dict into self.targets list.

        Supports both the new schema (fires / fires_reported / dynamic_events) and
        the legacy schema (data_points).  Reported positions are placeholders until
        the server sends a mission_init UDP message at the start of each run.
        """
        try:
            self.required_cruise_altitude_ft = mission_data['required_altitude_ft_msl']
            self.required_alt_fire_agl = mission_data['required_altitude_fire_agl_ft']
            self.wind_direction = mission_data['wind_direction']
            self.required_drop_route_length = mission_data['required_drop_route_length']

            self.targets = []
            self.fire_images = {}

            if 'fires' in mission_data:
                # New schema — seed startup MFD state from fires_reported, then allow UDP to refresh it.
                reported_fires = {
                    int(fd['id']): fd for fd in mission_data.get('fires_reported', [])
                }
                for fire_data in mission_data['fires']:
                    fid = int(fire_data['id'])
                    target = Target(
                        lat=fire_data['latitude'],
                        long=fire_data['longitude'],
                        alt=fire_data['altitude'],
                        type=fire_data['type'],
                        id=fid,
                    )
                    target.grid_position = GridSystem.latlon_to_grid_position(fire_data['latitude'], fire_data['longitude'])
                    reported_fire = reported_fires.get(fid)
                    if reported_fire is not None:
                        target.reported_lat = float(reported_fire['latitude'])
                        target.reported_long = float(reported_fire['longitude'])
                        target.reported_alt = float(reported_fire.get('altitude', fire_data['altitude']))
                        target.is_known_to_cockpit = True
                    else:
                        target.reported_lat = float(fire_data['latitude'])
                        target.reported_long = float(fire_data['longitude'])
                        target.reported_alt = float(fire_data['altitude'])
                        target.is_known_to_cockpit = False
                    self.targets.append(target)

                    filename = fire_data.get('image_path', '')
                    resolution = fire_data.get('image_res', [512, 512])
                    if filename:
                        fire_path = f"Resources/plugins/HAATO_assets/{filename}"
                        self.fire_images[fid] = xpgl.loadImage(fire_path, 0, 0, resolution[0], resolution[1])
                        self.log(f"Loaded fire image id={fid}: {filename}")

                # Pre-load dynamic fire images so they are ready when the spawn event arrives.
                # Their 3-D instances are NOT placed here — that happens on fire_spawn_event.
                for de in mission_data.get('dynamic_events', []):
                    fid = int(de['id'])
                    target = Target(
                        lat=de['true_latitude'],
                        long=de['true_longitude'],
                        alt=de['true_altitude'],
                        type=de.get('type', 'moderate'),
                        id=fid,
                        is_dynamic=True,
                        trigger_time_s=float(de['trigger_time_s']),
                    )
                    target.grid_position = GridSystem.latlon_to_grid_position(de['true_latitude'], de['true_longitude'])
                    target.reported_lat = float(de.get('reported_latitude', de['true_latitude']))
                    target.reported_long = float(de.get('reported_longitude', de['true_longitude']))
                    target.reported_alt = float(de.get('reported_altitude', de['true_altitude']))
                    target.is_known_to_cockpit = False
                    self.targets.append(target)

                    filename = de.get('image_path', '')
                    resolution = de.get('image_res', [512, 512])
                    if filename:
                        fire_path = f"Resources/plugins/HAATO_assets/{filename}"
                        self.fire_images[fid] = xpgl.loadImage(fire_path, 0, 0, resolution[0], resolution[1])
                        self.log(f"Loaded dynamic fire image id={fid}: {filename}")

            else:
                # Legacy schema — data_points, perfect information, is_known_to_cockpit=True
                for i, target_data in enumerate(mission_data.get('data_points', [])):
                    target = Target(
                        lat=target_data['latitude'],
                        long=target_data['longitude'],
                        alt=target_data['altitude'],
                        type=target_data['type'],
                        id=i,
                    )
                    target.grid_position = GridSystem.latlon_to_grid_position(target_data['latitude'], target_data['longitude'])
                    target.reported_lat = float(target_data['latitude'])
                    target.reported_long = float(target_data['longitude'])
                    target.reported_alt = float(target_data['altitude'])
                    target.is_known_to_cockpit = True  # legacy: all fires known at start
                    self.targets.append(target)

                    filename = target_data.get('image_path', '')
                    resolution = target_data.get('image_res', [512, 512])
                    if filename:
                        fire_path = f"Resources/plugins/HAATO_assets/{filename}"
                        self.fire_images[i] = xpgl.loadImage(fire_path, 0, 0, resolution[0], resolution[1])
                        self.log(f"Loaded fire image {i}: {filename}")

            self.num_targets = len(self.targets)
            self.log(f"Loaded {self.num_targets} targets from config.yaml (schema={'new' if 'fires' in mission_data else 'legacy'})")

        except KeyError as e:
            print(f"Error: Missing key {e} in mission config data")
        except Exception as e:
            print(f"Error loading targets: {e}")

    def get_target_options(self):
        human_lat = self.human_lat_dref.value
        human_long = self.human_long_dref.value

        self.target_in_classify_range, self.target_in_overfly_range, self.at_drop_route1_start, self.at_drop_route2_start, self.at_drop_route1_end, self.at_drop_route2_end = None, None, None, None, None, None
        for target in self.targets:
            # Calculate drop route start/end positions based on wind direction
            # Wind direction is "from" direction, so upwind is towards wind, downwind is away from wind

            downwind_bearing = (self.wind_dir + 180) % 360

            # Route start: 2 NM upwind (towards the wind direction)
            route_start_lat, route_start_long = GridSystem.destination_point(target.lat, target.long, downwind_bearing, self.required_drop_route_length)

            # Route end: 2 NM downwind (opposite of wind direction)
            route_end_lat, route_end_long = GridSystem.destination_point(target.lat, target.long, self.wind_dir, self.required_drop_route_length/2)

            if GridSystem.calculate_distance(human_lat, human_long, target.lat, target.long) <= self.range_to_classify and (target.status == 0.0):
                target.human_in_classify_range = True
                self.target_in_classify_range = target.id
            else:
                target.human_in_classify_range = False

            if GridSystem.calculate_distance(human_lat, human_long, target.lat, target.long) <= self.range_to_overfly and (target.status == 1.0):
                target.human_in_overfly_range = True
                self.target_in_overfly_range = target.id
            else:
                target.human_in_overfly_range = False

            if GridSystem.calculate_distance(human_lat, human_long, route_start_lat, route_start_long) <= self.range_to_start_route and target.status == 2.0 and not target.initial_drop_route_complete:
                target.human_at_drop_route1_start = True
                self.at_drop_route1_start = target.id
            else:
                target.human_at_drop_route1_start = False

            if GridSystem.calculate_distance(human_lat, human_long, route_end_lat, route_end_long) <= self.range_to_end_route and target.status == 2.0 and not target.initial_drop_route_complete and target.route1_start is not None:
                target.human_at_drop_route1_end = True
                self.at_drop_route1_end = target.id
            else:
                target.human_at_drop_route1_end = False

            if GridSystem.calculate_distance(human_lat, human_long, route_start_lat, route_start_long) <= self.range_to_start_route and target.status == 3.0 and not self.dataref_target_whoflew_list[target.id] == 1.0: # TODO TEST
                target.human_at_drop_route2_start = True
                self.at_drop_route2_start = target.id
            else:
                target.human_at_drop_route2_start = False

            if GridSystem.calculate_distance(human_lat, human_long, route_end_lat, route_end_long) <= self.range_to_end_route and target.status == 3.0 and target.route2_start is not None:
                target.human_at_drop_route2_end = True
                self.at_drop_route2_end = target.id
            else:
                target.human_at_drop_route2_end = False


    def update_target_classes(self):
        """Update target status and classification from datarefs"""

        for i in range(self.num_targets):
            status_value = self.safe_array_access(self.dataref_target_statuses, i, 0.0)
            classification = self.safe_array_access(self.dataref_target_classifications, i, 0.0)
            whoflew = self.safe_array_access(self.dataref_target_whoflew_list, i, 0.0)

            target = self.safe_target_access(i)
            if target is None:
                continue  # Skip if target doesn't exist

            if target.status != status_value:
                target.status = status_value

            if classification != 0.0: # Only update if non-zero (0.0 means unclassified)
                target.classification = classification
            elif classification == 0.0 and target.classification is not None: # Reset classification if dataref was cleared
                target.classification = None

            if whoflew == 2.0:# and target.route1_recorder == 'human': # Dataref says wingman flew first but GUI target class says human did
                target.route1_recorder = 'wingman' # Use dataref as the truth source


    def _initialize_experiment_log(self):
        """Initialize the experiment log file with metadata header."""
        try:
            self.log_file_identifier = int(find_dataref("custom/haato/log_file_identifier").value)
            self.participant_id = int(find_dataref("custom/haato/participant_id").value)
            self.fire_layout = int(find_dataref("custom/haato/fire_layout").value)
            self.initiative_level = int(find_dataref("custom/haato/initiative_level").value)

            # Create log directory if it doesn't exist
            log_dir = './Resources/plugins/HAATO_assets/haato_logs'
            os.makedirs(log_dir, exist_ok=True)

            pattern = f"events_p{self.participant_id}_initiative{self.initiative_level}_layout{self.fire_layout}_*_id{self.log_file_identifier}.jsonl"
            matching_files = glob.glob(os.path.join(log_dir, pattern))

            if matching_files:
                self.experiment_log_path = max(matching_files, key=os.path.getmtime)
                self.experiment_log_file = open(self.experiment_log_path, 'a')
                self.log(f'Found log file with identifier {self.log_file_identifier}. Opening')
            else:
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"events_p{self.participant_id}_initiative{self.initiative_level}_layout{self.fire_layout}_{timestamp}_id{self.log_file_identifier}.jsonl"
                self.experiment_log_path = os.path.join(log_dir, filename)
                self.experiment_log_file = open(self.experiment_log_path, 'w')

                # Write metadata header as first JSON object
                metadata = {
                    "metadata": "start",
                    "timestamp": datetime.datetime.now().isoformat(),
                    "participant_id": self.participant_id,
                    "initiative_level": self.initiative_level,
                    "fire_layout": self.fire_layout,
                    "wind_setting": self.wind_dataref.value,
                    "range_thresholds": {
                        "classify": self.range_to_classify,
                        "overfly": self.range_to_overfly,
                        "route_start": self.range_to_start_route,
                        "route_end": self.range_to_end_route
                    }
                }
                self.experiment_log_file.write(json.dumps(metadata) + '\n')
                self.experiment_log_file.flush()

                self.log(f"Initialized experiment log: {self.experiment_log_path}")

            # # Generate filename with timestamp
            # timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            # filename = f"events_p{self.participant_id}_initiative{self.initiative_level}_layout{self.fire_layout}_{timestamp}_id{log_file_identifier}.jsonl"
            # self.experiment_log_path = os.path.join(log_dir, filename)
            #
            # # Open file for writing
            # self.experiment_log_file = open(self.experiment_log_path, 'w')

        except Exception as e:
            self.log(f"ERROR: Could not initialize experiment log: {e}")
            self.log(traceback.format_exc())
            self.experiment_log_file = None

    def log_experiment_data(self, event_dict):
        """
        Log experiment event data to JSONL file.

        Args:
            event_dict: Dictionary containing event-specific data.
                       Must include 'event_type' key.
        """
        if (not self.experiment_log_file) or self.dataref_mission_time_left.value < 0:
            return  # Log file not initialized, skip logging

        try:
            # Add common fields
            event_dict['timestamp'] = datetime.datetime.now().isoformat()
            event_dict['met'] = self.dataref_mission_time_left.value

            # Write as single-line JSON
            self.experiment_log_file.write(json.dumps(event_dict) + '\n')
            self.experiment_log_file.flush()  # Ensure data is written immediately

        except Exception as e:
            self.log(f"ERROR: Could not write to experiment log: {e}")
            self.log(traceback.format_exc())

    def get_target_screen_position(self, target_idx, grid_offset_x, grid_offset_y):
        """Calculate screen position for a given target id using the MFD-reported position."""
        if target_idx < 0:
            return None

        target = self._get_target_by_id(int(target_idx))
        if target is None:
            return None

        target_lat = getattr(target, 'reported_lat', target.lat)
        target_lon = getattr(target, 'reported_long', target.long)

        target_lat_diff = target_lat - self.aor_center_lat
        target_lon_diff = target_lon - self.aor_center_long

        target_offset_x_nm = target_lon_diff * self.lon_scale_nm
        target_offset_y_nm = target_lat_diff * self.lat_scale_nm

        offset_x = target_offset_x_nm * self.pixels_per_nm
        offset_y = target_offset_y_nm * self.pixels_per_nm

        screen_x = self.mfd_center_x + grid_offset_x + offset_x
        screen_y = self.mfd_center_y + grid_offset_y + offset_y

        return (screen_x, screen_y)

    def draw_border_around_screen(self, color, thickness, flashing=False, flash_interval=100):
        return fire_gui.draw_border_around_screen(self, color, thickness, flashing, flash_interval)
    def _initialize_datarefs(self):
        self.log("=== Starting dataref initialization ===")
        self.udp_bridge.flight_loop_callback()
        self.log(
            f"[PI_firemission] _initialize_datarefs bridge_id={id(self.udp_bridge)} "
            f"protocol_id={getattr(self.udp_bridge.protocol, 'instance_id', 'n/a')} "
            f"recv_count={getattr(self.udp_bridge.protocol, 'recv_count', 'n/a')}"
        )

        self.reset_mission_dataref = find_dataref("custom/haato/reset_mission")
        self.start_logging_dataref = find_dataref("custom/haato/start_logging")

        self.change_screen_dataref = find_dataref("custom/haato/change_screen")

        self.speak_status_dataref = None
        self.map_zoom_range_dref = find_dataref("custom/haato/map_zoom_range")

        self.dataref_mission_time_left = ScalarProxy(lambda: self.udp_bridge.current_state["mission_time_left"])
        self.dataref_wingman_status = ScalarProxy(lambda: self.udp_bridge.current_state["wingman"]["status"])
        self.dataref_help_request = None

        self.dataref_auto_spot = ScalarProxy(
            getter=lambda: 1.0 if self.udp_bridge.current_state["settings"]["auto_spot"] else 0.0,
            setter=self._set_auto_spot_state,
        )
        self.command_from_human_dataref = find_dataref("custom/haato/command_from_human")
        self.agent_id_request_dataref = ScalarProxy(
            getter=lambda: float(self.udp_bridge.current_agent_id_request["target_id"])
            if self.udp_bridge.current_agent_id_request["active"] and self.udp_bridge.current_agent_id_request["target_id"] is not None
            else 99.0
        )
        self.lat_dataref = find_dataref("sim/flightmodel/position/latitude")
        self.lon_dataref = find_dataref('sim/flightmodel/position/longitude')
        self.id_request_response_dataref = ScalarProxy(
            getter=lambda: 0.0,
            setter=self._send_human_id_response_value,
        )

        self.dataref_target_statuses = find_dataref("custom/haato/target_status")  # [find_dataref(f"custom/haato/target_status[{i}]") for i in range(self.num_targets)]
        self.dataref_target_classifications = find_dataref("custom/haato/target_classification")  # [find_dataref(f"custom/haato/target_classification[{i}]") for i in range(self.num_targets)]
        self.dataref_target_whoflew_list = find_dataref("custom/haato/target_whoflew_initial")  # [find_dataref(f"custom/haato/target_whoflew_initial[{i}]") for i in range(self.num_targets)]

        self.dataref_wingman_messages = None
        self.dataref_human_messages = None

        self.team_plan_dataref = ArrayProxy(11, getter=lambda idx: self.team_plan_cache[idx], setter=self._set_team_plan_value)
        self.human_plan_response_dataref = ArrayProxy(3, getter=lambda idx: self.human_plan_response_cache[idx], setter=self._set_human_plan_response_value)
        self.human_indicated_plan_dataref = ScalarProxy(
            getter=lambda: self.udp_bridge.current_state["human"]["indicated_plan"],
            setter=self._set_human_indicated_plan_state,
        )
        self.human_request_plan_suggestion_dataref = find_dataref("custom/haato/human_requests_plan_suggestion")

        self.range_up_cmd = xp.findCommand('sim/GPS/g1000n3_range_up')  # G1000 range command handlers
        self.range_down_cmd = xp.findCommand('sim/GPS/g1000n3_range_down')

        self.wind_dataref = find_dataref("custom/haato/wind_direction")

        self.log("=== Successfully initialized ALL custom datarefs ===")

        self.human_lat_dref = find_dataref('sim/flightmodel/position/latitude')
        self.human_long_dref = find_dataref('sim/flightmodel/position/longitude')
        self.human_alt_dref = find_dataref('sim/flightmodel/position/elevation')

        self.wingman_lat_dref = ScalarProxy(lambda: self.udp_bridge.current_state["wingman"]["lat"])
        self.wingman_long_dref = ScalarProxy(lambda: self.udp_bridge.current_state["wingman"]["lon"])
        self.wingman_subtask_proxy = ScalarProxy(lambda: self.udp_bridge.current_state["wingman"]["subtask"])
        self.wingman_heading_dref = ScalarProxy(lambda: self.udp_bridge.current_state["wingman"]["hdg"])

        self._log_udp_bridge_state("_initialize_datarefs complete", force=True)

        self.joystick_dref = xp.findDataRef(
            "sim/joystick/joystick_button_values")  # NOTE: This dataref is accessed differently from the others intentionally

    def safe_array_access(self, array, index, default=None):
        """Safely access array element with bounds checking"""
        if array is None:
            return default
        try:
            index = int(index)
            if 0 <= index < len(array):
                return array[index]
            return default
        except (IndexError, TypeError, ValueError) as e:
            self.log(f"Array access error at index {index}: {e}")
            return default


    def safe_int_conversion(self, value, default=0):
        """Safely convert value to int"""
        try:
            return int(value)
        except (ValueError, TypeError) as e:
            self.log(f"Int conversion error for value '{value}': {e}")
            return default

    def safe_target_access(self, target_id):
        """Safely access target by ID with validation"""
        try:
            target_id = int(target_id)
            if hasattr(self, 'targets') and self.targets and 0 <= target_id < len(self.targets):
                return self.targets[target_id]
        except (ValueError, TypeError, IndexError) as e:
            self.log(f"Target access error for ID {target_id}: {e}")
        return None

    def safe_joystick_button_state(self, button_index):
        """Safely get joystick button state with bounds checking (delegates to InputManager)."""
        if self.input_manager:
            return self.input_manager.safe_joystick_button_state(button_index)
        return 0

    def get_target_by_id_safe(self, target_id, context=""):
        """
        Safely retrieve target with comprehensive logging

        Args:
            target_id: Target ID to retrieve
            context: Context string for logging (e.g., "wingman status")

        Returns:
            Target object or None
        """
        target = self.safe_target_access(target_id)
        if target is None and context:
            self.log(f"[{context}] Cannot access target {target_id}")
        return target


# Required for XPPython3
PI = PythonInterface()
