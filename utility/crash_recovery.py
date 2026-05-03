"""
Crash recovery module for mission runner.
Handles saving and restoring mission state for crash recovery.
"""
import os
import json
import glob
import threading
import traceback
from datetime import datetime
from typing import Optional, Dict, Any, List
import time
from queue import Queue, Empty


class CrashStateSaverThread(threading.Thread):
    """
    Background thread that handles periodic crash state saving.
    Uses a queue to receive save requests from the main thread.
    """

    def __init__(self, xpc, mm, crash_dir, save_interval_steps=10):
        """
        Args:
            xpc: X-Plane connection instance
            mm: Mission manager instance
            crash_dir: Directory to save crash state files
            save_interval_steps: Number of steps between saves
        """
        super().__init__(daemon=True)
        self.xpc = xpc
        self.mm = mm
        self.crash_dir = crash_dir
        self.save_interval_steps = save_interval_steps

        self.save_queue = Queue(maxsize=1)  # Only keep latest save request
        self.stop_flag = threading.Event()
        self.steps_since_save = 0
        self.last_save_time = 0

    def request_save(self, met, step_count, exception_info=None):
        """
        Request a save operation. Non-blocking - drops request if queue is full.

        Args:
            met: Mission elapsed time
            step_count: Current step count
            exception_info: Optional exception info dict for crash saves
        """
        self.steps_since_save += 1

        # Only save every N steps (unless there's an exception)
        if exception_info or self.steps_since_save >= self.save_interval_steps:
            try:
                # Use put_nowait to avoid blocking the main thread
                # If queue is full, old request is discarded (we only want latest state anyway)
                self.save_queue.put_nowait({
                    'met': met,
                    'step_count': step_count,
                    'exception_info': exception_info or {}
                })
                self.steps_since_save = 0
            except Exception:
                # Queue full, skip this save (main thread continues unblocked)
                pass

    def run(self):
        """Main thread loop - processes save requests from queue."""
        #print("[CrashStateSaver] Background thread started")

        while not self.stop_flag.is_set():
            try:
                # Wait for save request with timeout
                save_request = self.save_queue.get(timeout=1.0)

                # Perform the save operation
                try:
                    start_time = time.time()
                    crash_file = save_crash_state(
                        self.xpc,
                        self.mm,
                        self.crash_dir,
                        save_request['exception_info']
                    )
                    save_duration = time.time() - start_time

                    self.last_save_time = time.time()

                    if save_request['exception_info']:
                        print(
                            f'[CrashStateSaver] EXCEPTION CRASH STATE SAVED TO: {crash_file} (took {save_duration:.2f}s)')
                    #else:
                        #print(f'[CrashStateSaver] Periodic state saved to: {crash_file} (took {save_duration:.2f}s)')

                except Exception as save_error:
                    print(f'[CrashStateSaver] FAILED TO SAVE CRASH STATE: {save_error}')
                    traceback.print_exc()

            except Empty:
                # Timeout, no save request - continue waiting
                continue
            except Exception as e:
                print(f'[CrashStateSaver] Error in save thread: {e}')
                traceback.print_exc()

        print("[CrashStateSaver] Background thread stopped")

    def stop(self):
        """Signal the thread to stop and wait for it to finish."""
        self.stop_flag.set()
        self.join(timeout=5.0)  # Wait up to 5 seconds for thread to finish

# ===================================================================================================
# DATAREF CATEGORY DEFINITIONS
# ===================================================================================================

MISSION_CONFIG_DREFS = [
    'custom/haato/participant_id',
    'custom/haato/fire_layout',
    'custom/haato/initiative_level',
    'custom/haato/control_prefix',
    'custom/haato/log_file_identifier',
    'custom/haato/wind_direction',
    'custom/haato/required_altitude_msl_ft'
]

MISSION_STATE_DREFS = [
    'custom/haato/human_in_range_of_target'
]

WINGMAN_DREFS = []

COMMUNICATION_DREFS = [
    'custom/haato/command_from_human',
    'custom/haato/human_requests_plan_suggestion'
]

PLANNING_DREFS = [
]

TASK_PRIORITY_DREFS = [
    'custom/haato/taskpriority_spotunknown',
    'custom/haato/taskpriority_handlemoderate',
    'custom/haato/taskpriority_handlesevere',
    'custom/haato/set_wingman_greedy'
]

HUMAN_POSITION_DREFS = [
    'sim/flightmodel/position/latitude',
    'sim/flightmodel/position/longitude',
    'sim/flightmodel/position/elevation'
]

# Array datarefs (handled separately with indexing)
TARGET_ARRAY_DREFS = ['target_status', 'target_classification', 'target_whoflew_initial']
TEAM_PLAN_ARRAY_DREF = None


# ===================================================================================================
# HELPER FUNCTIONS
# ===================================================================================================

def find_latest_crash_file(crash_dir: str) -> Optional[str]:
    """
    Find the most recent crash file in the crash directory.

    Args:
        crash_dir: Path to the crashed mission files directory

    Returns:
        Path to the most recent crash file, or None if no files found
    """
    if not os.path.exists(crash_dir):
        return None

    crash_files = glob.glob(os.path.join(crash_dir, 'crashed_mission_state_*.json'))

    if not crash_files:
        return None

    # Sort by modification time (most recent first)
    crash_files.sort(key=os.path.getmtime, reverse=True)

    return crash_files[0]


def validate_crash_state(data: Dict[str, Any]) -> bool:
    """
    Validate that the loaded JSON has the required structure.

    Args:
        data: Loaded crash state dictionary

    Returns:
        True if valid, False otherwise
    """
    required_keys = ['metadata', 'mission_config', 'targets', 'wingman', 'human']

    for key in required_keys:
        if key not in data:
            print(f'[Crash Recovery] Validation failed: missing key "{key}"')
            return False

    # Validate metadata
    if 'mission_timer' not in data['metadata']:
        print(f'[Crash Recovery] Validation failed: missing metadata.mission_timer')
        return False

    # Validate targets is a list
    if not isinstance(data['targets'], list):
        print(f'[Crash Recovery] Validation failed: targets is not a list')
        return False

    return True


def serialize_target(target) -> Dict[str, Any]:
    """
    Convert a Target object to a dictionary.

    Args:
        target: Target object from utility.base_classes

    Returns:
        Dictionary representation of the target
    """
    return {
        'id': target.id,
        'lat': target.lat,
        'long': target.long,
        'alt': target.alt,
        'type': target.type,
        'spotted': target.spotted,
        'handled': target.handled,
        'status': target.status,
        'classification': target.classification,
        'human_in_range_time': target.human_in_range_time,
        'wingman_in_range_time': target.wingman_in_range_time,
        'wingman_observation_time': target.wingman_observation_time,
        'handling_start_time': target.handling_start_time,
        'is_being_handled': target.is_being_handled,
        'position_recorded_by_wingman': target.position_recorded_by_wingman,
        'route1_start': target.route1_start,
        'route1_end': target.route1_end,
        'route1_recorder': target.route1_recorder,
        'route2_start': target.route2_start,
        'route2_end': target.route2_end,
        'route2_recorder': target.route2_recorder,
        'marked_position': target.marked_position,
        'initial_drop_route_complete': target.initial_drop_route_complete,
        'refined_drop_route_complete': target.refined_drop_route_complete,
        'progress': getattr(target, 'progress', 0.0)
    }


def collect_datarefs(xpc, dref_list: List[str], category_name: str) -> Dict[str, Any]:
    """
    Collect values for a list of datarefs.

    Args:
        xpc: XPlaneConnectX instance
        dref_list: List of dataref names
        category_name: Name of category for logging

    Returns:
        Dictionary mapping dataref names to values
    """
    result = {}

    for dref in dref_list:
        try:
            value = xpc.getDREF(dref)
            result[dref] = value
        except Exception as e:
            print(f'[Crash Recovery] Failed to get {category_name} dref "{dref}": {e}')
            result[dref] = None

    return result


# ===================================================================================================
# MAIN FUNCTIONS
# ===================================================================================================

def save_crash_state(xpc, mm, crash_dir: str, exception_info: Optional[Dict[str, Any]] = None) -> str:
    """
    Save complete mission state to JSON file in crash directory.

    Args:
        xpc: XPlaneConnectX instance
        mm: FireWatchMM instance
        crash_dir: Directory path for crash files
        exception_info: Optional dictionary with exception details

    Returns:
        Path to the saved crash file
    """
    #print(f'\n[Crash Recovery] Saving crash state...')

    # Create crash directory if it doesn't exist
    os.makedirs(crash_dir, exist_ok=True)

    # Collect all datarefs by category
    mission_config = collect_datarefs(xpc, MISSION_CONFIG_DREFS, 'mission_config')
    mission_state = collect_datarefs(xpc, MISSION_STATE_DREFS, 'mission_state')
    wingman_drefs = collect_datarefs(xpc, WINGMAN_DREFS, 'wingman')
    communication = collect_datarefs(xpc, COMMUNICATION_DREFS, 'communication')
    planning = collect_datarefs(xpc, PLANNING_DREFS, 'planning')
    task_priorities = collect_datarefs(xpc, TASK_PRIORITY_DREFS, 'task_priorities')
    human_position = collect_datarefs(xpc, HUMAN_POSITION_DREFS, 'human_position')
    # So it looks like {

    # Collect target array datarefs
    target_arrays = {}
    for array_name in TARGET_ARRAY_DREFS:
        array_values = []
        for i in range(8):
            try:
                value = xpc.getDREF(f'custom/haato/{array_name}[{i}]')
                array_values.append(value)
            except Exception as e:
                print(f'[Crash Recovery] Failed to get {array_name}[{i}]: {e}')
                array_values.append(None)
        target_arrays[array_name] = array_values

    if hasattr(mm, 'udp_bridge'):
        planning['udp_state'] = getattr(mm.udp_bridge, 'current_state', {})
        planning['udp_team_plan'] = getattr(mm, 'current_team_plan', None)
        planning['udp_agent_id_request'] = getattr(mm.udp_bridge, 'current_agent_id_request', {})

    # Serialize Target objects
    targets = []
    if hasattr(mm, 'targets') and mm.targets:
        for target in mm.targets:
            try:
                targets.append(serialize_target(target))
            except Exception as e:
                print(f'[Crash Recovery] Failed to serialize target {target.id}: {e}')

    # Collect FireWatchMM state variables
    mm_state = {
        'last_human_command': getattr(mm, '_last_human_command', 12.0),
        'last_request_response': getattr(mm, '_last_request_response', 0.0),
        'last_id_response': getattr(mm, '_last_id_response', 0.0),
        'previous_handled_states': getattr(mm, 'previous_handled_states', {}),
        'previous_target_status': getattr(mm, 'previous_target_status', {}),
        'last_plan_send_time': getattr(mm, 'last_plan_send_time', -999.0),
        'started_planning_step': getattr(mm, 'started_planning_step', None),
        'ended_planning_step': getattr(mm, 'ended_planning_step', None),
        'ignored_targets_list': getattr(mm, 'ignored_targets_list', []),
        'timesteps_since_action_calc': getattr(mm, 'timesteps_since_action_calc', 0),
        'last_wingman_message_count': getattr(mm, 'last_wingman_message_count', 0)
    }

    # Collect wingman state from mm.wingman object
    wingman_state = {}
    if hasattr(mm, 'wingman') and mm.wingman:
        wingman_state = {
            'lat': getattr(mm.wingman, 'lat', 0.0),
            'long': getattr(mm.wingman, 'long', 0.0),
            'alt': getattr(mm.wingman, 'alt', 0.0),
            'hdg': getattr(mm.wingman, 'hdg', 0.0),
            'spd': getattr(mm.wingman, 'spd', 0.0)
        }

    # Assemble metadata
    metadata = {
        'timestamp': datetime.now().isoformat(),
        'subject_id': getattr(mm, 'user_id', 0),
        'fire_layout': getattr(mm, 'fire_layout', 0),
        'initiative_level': getattr(mm, 'initiative_level', 0.0),
        'mission_timer': getattr(mm, 'mission_timer', 0.0),
        'step_count': getattr(mm, 'step_count', 0),
        'log_file_identifier': getattr(mm, 'log_file_identifier', 0.0)
    }

    if exception_info:
        metadata['exception_info'] = exception_info

    # Assemble complete crash state
    crash_state = {
        'metadata': metadata,
        'mission_config': mission_config,
        'mission_state': mission_state,
        'targets': targets,
        'wingman': wingman_state,
        'human': human_position,
        'communication': communication,
        'planning': planning,
        'task_priorities': task_priorities,
        'target_arrays': target_arrays,
        'mm_state': mm_state
    }

    # Generate filename
    timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_id = int(metadata['log_file_identifier'])
    filename = f'crashed_mission_state_{log_id}_{timestamp_str}.json'
    filepath = os.path.join(crash_dir, filename)

    # Write to file
    try:
        with open(filepath, 'w') as f:
            json.dump(crash_state, f, indent=2, default=str)
        #print(f'[Crash Recovery] Successfully saved crash state to: {filepath}')
        print(f'\n[Crash Recovery] Saved state: timer={metadata["mission_timer"]:.1f}s, step={metadata["step_count"]}, targets={len(targets)}\n')
    except Exception as e:
        print(f'[Crash Recovery] ERROR writing crash file: {e}')
        raise

    return filepath


def restore_mission_from_crash(xpc, mm, crash_dir: str) -> Dict[str, Any]:
    """
    Load most recent crash file and restore all mission state.

    Args:
        xpc: XPlaneConnectX instance
        mm: FireWatchMM instance (already initialized)
        crash_dir: Directory path containing crash files

    Returns:
        Loaded crash state dictionary

    Raises:
        FileNotFoundError: If no crash files found
        ValueError: If crash state is invalid
    """
    print(f'\n[Crash Recovery] Restoring mission from crash...')

    # Find latest crash file
    crash_file = find_latest_crash_file(crash_dir)

    if crash_file is None:
        raise FileNotFoundError(f'No crash files found in {crash_dir}')

    print(f'[Crash Recovery] Loading crash file: {crash_file}')

    # Load JSON data
    try:
        with open(crash_file, 'r') as f:
            crash_state = json.load(f)
    except Exception as e:
        raise ValueError(f'Failed to load crash file: {e}')

    # Validate structure
    if not validate_crash_state(crash_state):
        raise ValueError('Crash state validation failed')

    # Restore all datarefs
    print(f'[Crash Recovery] Restoring datarefs...')

    # Restore mission config drefs
    for dref, value in crash_state.get('mission_config', {}).items():
        if value is not None:
            try:
                xpc.sendDREF(dref, value)
            except Exception as e:
                print(f'[Crash Recovery] Failed to restore {dref}: {e}')

    # Restore mission state drefs
    for dref, value in crash_state.get('mission_state', {}).items():
        if value is not None:
            try:
                xpc.sendDREF(dref, value)
            except Exception as e:
                print(f'[Crash Recovery] Failed to restore {dref}: {e}')

    # Restore communication drefs
    for dref, value in crash_state.get('communication', {}).items():
        if value is not None:
            try:
                xpc.sendDREF(dref, value)
            except Exception as e:
                print(f'[Crash Recovery] Failed to restore {dref}: {e}')

    # Restore planning drefs
    planning_data = crash_state.get('planning', {})
    for dref, value in planning_data.items():
        if dref not in {'udp_state', 'udp_team_plan', 'udp_agent_id_request'} and value is not None:
            try:
                xpc.sendDREF(dref, value)
            except Exception as e:
                print(f'[Crash Recovery] Failed to restore {dref}: {e}')

    if hasattr(mm, 'udp_bridge'):
        mm.udp_bridge.current_state.update(planning_data.get('udp_state', {}))
        mm.current_team_plan = planning_data.get('udp_team_plan')
        mm.udp_bridge.current_agent_id_request = planning_data.get('udp_agent_id_request', {})

    # Restore task priorities drefs
    for dref, value in crash_state.get('task_priorities', {}).items():
        if value is not None:
            try:
                xpc.sendDREF(dref, value)
            except Exception as e:
                print(f'[Crash Recovery] Failed to restore {dref}: {e}')

    # Restore wingman drefs
    for dref, value in crash_state.get('wingman', {}).items():
        if value is not None and dref.startswith('custom/haato/'):
            try:
                xpc.sendDREF(dref, value)
            except Exception as e:
                print(f'[Crash Recovery] Failed to restore {dref}: {e}')

    # Restore human position drefs
    for dref, value in crash_state.get('human', {}).items():
        # TODO HERE
        # HUMAN_POSITION_DREFS = [
        #     'sim/flightmodel/position/latitude': lat,
        #     'sim/flightmodel/position/longitude': lon,
        #     'sim/flightmodel/position/elevation': alt
        # ]
        try:
            lat = crash_state['human']['sim/flightmodel/position/latitude']
            lon = crash_state['human']['sim/flightmodel/position/longitude']
            alt = crash_state['human']['sim/flightmodel/position/elevation']
        except Exception as e:
            print(f'failed to send human pos: {e}')

        # try:
        #     xpc.sendPOSI(lat, lon, alt, -0.25221577, 4.2194324, 78.849)
        #     print(f'Sent human lla {lat}, {lon}, {alt + 500}')
        # except Exception as e:
        #     print(f'[Crash Recovery] Failed to restore {dref}: {e}')

    # Restore target array drefs
    target_arrays = crash_state.get('target_arrays', {})
    for array_name, array_values in target_arrays.items():
        for i, value in enumerate(array_values):
            if value is not None:
                try:
                    xpc.sendDREF(f'custom/haato/{array_name}[{i}]', value)
                except Exception as e:
                    print(f'[Crash Recovery] Failed to restore {array_name}[{i}]: {e}')

    # Restore Target objects
    print(f'[Crash Recovery] Restoring target objects...')
    saved_targets = crash_state.get('targets', [])
    if hasattr(mm, 'targets') and mm.targets:
        for saved_target in saved_targets:
            target_id = saved_target.get('id')
            if target_id is not None and target_id < len(mm.targets):
                target = mm.targets[target_id]
                try:
                    # Restore all attributes
                    for attr, value in saved_target.items():
                        if attr != 'id':  # Don't overwrite id
                            setattr(target, attr, value)
                except Exception as e:
                    print(f'[Crash Recovery] Failed to restore target {target_id}: {e}')

    # Restore FireWatchMM state variables
    print(f'[Crash Recovery] Restoring mission manager state...')
    mm_state = crash_state.get('mm_state', {})

    mm.mission_timer = crash_state['metadata']['mission_timer']
    mm.step_count = crash_state['metadata']['step_count']

    mm._last_human_command = mm_state.get('last_human_command', 12.0)
    mm._last_request_response = mm_state.get('last_request_response', 0.0)
    mm._last_id_response = mm_state.get('last_id_response', 0.0)
    mm.previous_handled_states = mm_state.get('previous_handled_states', {})
    mm.previous_target_status = mm_state.get('previous_target_status', {})
    mm.last_plan_send_time = mm_state.get('last_plan_send_time', -999.0)
    mm.started_planning_step = mm_state.get('started_planning_step', None)
    mm.ended_planning_step = mm_state.get('ended_planning_step', None)
    mm.ignored_targets_list = mm_state.get('ignored_targets_list', [])
    mm.timesteps_since_action_calc = mm_state.get('timesteps_since_action_calc', 0)
    mm.last_wingman_message_count = mm_state.get('last_wingman_message_count', 0)

    # Restore wingman state
    if hasattr(mm, 'wingman') and mm.wingman:
        wingman_state = crash_state.get('wingman', {})
        mm.wingman.lat = wingman_state.get('lat', 0.0)
        mm.wingman.long = wingman_state.get('long', 0.0)
        mm.wingman.alt = wingman_state.get('alt', 0.0)
        mm.wingman.hdg = wingman_state.get('hdg', 0.0)
        mm.wingman.spd = wingman_state.get('spd', 0.0)

    # Restore human_lla
    human_pos = crash_state.get('human', {})
    mm.human_lla = [
        human_pos.get('sim/flightmodel/position/latitude', 0.0),
        human_pos.get('sim/flightmodel/position/longitude', 0.0),
        human_pos.get('sim/flightmodel/position/elevation', 0.0)
    ]

    # Print summary
    metadata = crash_state['metadata']
    print(f'[Crash Recovery] Successfully restored mission state:')
    print(f'  - Subject ID: {metadata["subject_id"]}')
    print(f'  - Fire Layout: {metadata["fire_layout"]}')
    print(f'  - Initiative Level: {metadata["initiative_level"]}')
    print(f'  - Mission Timer: {metadata["mission_timer"]:.1f}s')
    print(f'  - Step Count: {metadata["step_count"]}')
    print(f'  - Targets Restored: {len(saved_targets)}')
    print(f'  - Crash Time: {metadata["timestamp"]}')

    return crash_state
