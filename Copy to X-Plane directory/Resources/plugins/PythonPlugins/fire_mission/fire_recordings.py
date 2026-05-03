import json
import os
from collections import defaultdict
import numpy as np
import xp
from py_utilities.grid_system import GridSystem
from fire_classes import PositionRecording, RouteRecording

def _find_closest_fire(plugin, lat, lon):
    """Return the id of the fire closest to (lat, lon)."""
    closest_id, min_dist = None, float('inf')
    for target in plugin.targets:
        dist = GridSystem.calculate_distance(lat, lon, target.lat, target.long)
        if dist < min_dist:
            min_dist = dist
            closest_id = target.id
    return closest_id


def handle_recording(plugin):
    marked_position = (plugin.human_lat_dref.value, plugin.human_long_dref.value, plugin.human_alt_dref.value)
    if plugin.recording_mode == 'position':
        fire_id = _find_closest_fire(plugin, marked_position[0], marked_position[1])
        plugin._handle_position_recording(fire_id, marked_position)
    elif plugin.recording_mode == 'route':
        if plugin.active_route_recording is None:
            plugin._handle_route_start(marked_position)
        else:
            plugin._handle_route_end(marked_position)



def _find_route_recording(plugin, fire_id, route_type):
    """Find existing route recording by fire_id and type ('initial' or 'refined')"""
    for recording in plugin.saved_recordings:
        if recording.fire_id == fire_id and recording.type == route_type:
            return recording
    return None



def _get_route_heading(plugin, fire_id, from_position):
    """Calculate heading from given position to target fire"""
    lat1, lon1, alt1 = from_position
    lat2, lon2 = plugin.targets[fire_id].lat, plugin.targets[fire_id].long
    return GridSystem.calculate_heading(lat1, lon1, lat2, lon2)



def _build_position_log_data(plugin, fire_id, recording, marked_position):
    """Build experiment log data dictionary for position marking"""
    return {
        'event_type': 'mark_position',
        'recording_id': id(recording),
        'player': 'human',
        'fire_id': fire_id,
        'lat_marked': marked_position[0],
        'lon_marked': marked_position[1],
        'alt_marked_m': plugin.human_alt_dref.value,
        'required_alt_m': plugin.targets[fire_id].alt + 1000*plugin.ft_to_m,
        'alt_error_m':  plugin.targets[fire_id].alt + 1000*plugin.ft_to_m - plugin.human_alt_dref.value,
        'lat_true': plugin.targets[fire_id].lat,
        'lon_true': plugin.targets[fire_id].long,
    }



def _build_route_log_data(plugin, fire_id, recording, position, heading, event_type, route_type=None):
    """Build experiment log data dictionary for route recording"""
    log_data = {
        'event_type': event_type,
        'recording_id': id(recording),
        'player': 'human',
        'fire_id': fire_id,
        'heading_to_target': heading,
        'wind_dir': plugin.wind_dir
    }

    if event_type == 'route_start':
        log_data['start_lat'] = position[0]
        log_data['start_lon'] = position[1]
        route_start_lat, route_start_long = GridSystem.destination_point(plugin.targets[fire_id].lat, plugin.targets[fire_id].long, (plugin.wind_dir + 180) % 360, plugin.required_drop_route_length)
        log_data['start_pos_error'] = GridSystem.calculate_distance(position[0], position[1], route_start_lat, route_start_long)

        log_data['start_alt_m'] = position[2]
        log_data['required_alt_m'] = plugin.targets[fire_id].alt + 1000*plugin.ft_to_m
        log_data['start_alt_error'] = log_data['required_alt_m'] - log_data['start_alt_m']


    elif event_type == 'route_end':
        log_data['end_lat'] = position[0]
        log_data['end_lon'] = position[1]
        log_data['end_alt_m'] = position[2]

        log_data['required_alt_m'] = plugin.targets[fire_id].alt + 1000*plugin.ft_to_m
        log_data['end_alt_error'] = log_data['required_alt_m'] - log_data['end_alt_m']

        try:
            log_data['average_altitude_m'] = np.mean([point[2] for point in recording.trajectory_points])
            log_data['average_altitude_m_error'] = log_data['end_alt_m_required'] - log_data['average_altitude_m']
        except Exception as e:
            xp.log(f'failed to calculate average altitude using trajectory points: {e}')
        log_data['route_length'] = GridSystem.calculate_distance(position[0], position[1], recording.start_pos[0], recording.start_pos[1])
        log_data['length_error'] = plugin.required_drop_route_length*1.5  - log_data['route_length']
        try:
            log_data['trajectory_points'] = recording.trajectory_points
        except Exception as e:
            xp.log(f'failed to log trajectory points: {e}')

    if route_type:
        log_data['route_type'] = route_type

    return log_data



def _handle_position_recording(plugin, fire_id, marked_position):
    """Handle position marking workflow"""
    plugin.targets[fire_id].marked_position = marked_position
    wingman_pos_at_time = (plugin.wingman_lat_dref.value, plugin.wingman_long_dref.value)
    recording = PositionRecording('position', fire_id, marked_position, plugin.dataref_mission_time_left.value, wingman_pos_at_time)
    plugin.saved_recordings.append(recording)
    plugin.update_external_recordings_list()

    log_data = plugin._build_position_log_data(fire_id, recording, marked_position)
    plugin.log_experiment_data(log_data)
    plugin._log_recording_success('Recorded fire position')




def _handle_route_start(plugin, marked_position):
    """Handle route start recording. Fire is inferred at route end from center point."""
    # Create recording with fire_id=None — assigned when route ends
    recording = RouteRecording('initial', None, marked_position, plugin.dataref_mission_time_left.value)
    plugin.saved_recordings.append(recording)
    plugin.active_route_recording = recording
    plugin.update_external_recordings_list()

    if plugin.fire_layout == 4 and not plugin.has_played_route_hint_2:
        xp.speakString("Now fly to the end position, then press the missile release button once to end recording.")
        plugin.has_played_route_hint_2 = True

    log_data = {
        'event_type': 'route_start',
        'recording_id': id(recording),
        'player': 'human',
        'fire_id': None,
        'start_lat': marked_position[0],
        'start_lon': marked_position[1],
        'start_alt_m': marked_position[2],
        'wind_dir': plugin.wind_dir,
    }
    plugin.log_experiment_data(log_data)
    plugin._log_recording_success('Recorded drop route start position')
    xp.log('Started recording route start')



def _handle_route_end(plugin, marked_position):
    """Handle route end recording. Infers fire from center point of trajectory."""
    recording = plugin.active_route_recording
    if recording is None:
        plugin.log('User tried to record route end but no active route recording found.')
        return

    # Finalise trajectory
    recording.end_pos = marked_position
    if not recording.trajectory_points or recording.trajectory_points[-1] != marked_position:
        recording.trajectory_points.append(marked_position)

    # Infer fire from center point of trajectory
    pts = recording.trajectory_points
    center_lat = np.mean([p[0] for p in pts])
    center_lon = np.mean([p[1] for p in pts])
    fire_id = _find_closest_fire(plugin, center_lat, center_lon)

    # Determine route type: 'refined' if a complete route already exists for this fire
    route_type = 'initial'
    for r in plugin.saved_recordings:
        if isinstance(r, RouteRecording) and r.fire_id == fire_id and r.end_pos is not None and r is not recording:
            route_type = 'refined'
            break

    # Assign inferred values to recording
    recording.fire_id = fire_id
    recording.type = route_type

    # Update target
    if route_type == 'initial':
        plugin.targets[fire_id].route1_start = recording.start_pos
        plugin.targets[fire_id].route1_end = marked_position
    else:
        plugin.targets[fire_id].route2_start = recording.start_pos
        plugin.targets[fire_id].route2_end = marked_position

    plugin.active_route_recording = None
    plugin.update_external_recordings_list()

    heading = plugin._get_route_heading(fire_id, recording.start_pos)
    log_data = plugin._build_route_log_data(fire_id, recording, marked_position, heading, 'route_end', route_type)
    plugin.log_experiment_data(log_data)
    plugin._log_recording_success('Recorded drop route end position')
    xp.log('Finished recording route end')



def cleanup_recordings(plugin):
    from collections import defaultdict

    # Group recordings by type and fire_id
    route_recordings = defaultdict(list)
    position_recordings = defaultdict(list)
    other_recordings = []

    for recording in plugin.saved_recordings:
        if isinstance(recording, RouteRecording):
            route_recordings[recording.fire_id].append(recording)
        elif isinstance(recording, PositionRecording):
            position_recordings[recording.fire_id].append(recording)
        else:
            other_recordings.append(recording)

    # Process RouteRecordings
    kept_routes = []
    for fire_id, routes in route_recordings.items():
        if len(routes) == 1:
            kept_routes.append(routes[0])
        else:
            # Check if any have end_pos != None
            with_end_pos = [r for r in routes if r.end_pos is not None]

            if with_end_pos:
                # Keep only one with end_pos (the first one we find)
                kept_routes.append(with_end_pos[0])
            else:
                # All have end_pos == None, keep the one with smallest timestamp
                kept_routes.append(min(routes, key=lambda r: r.timestamp))

    # Process PositionRecordings
    kept_positions = []
    for fire_id, positions in position_recordings.items():
        if len(positions) == 1:
            kept_positions.append(positions[0])
        else:
            # Keep the one with largest timestamp
            kept_positions.append(max(positions, key=lambda p: p.timestamp))

    # Rebuild the list
    plugin.saved_recordings = kept_routes + kept_positions + other_recordings
    plugin.update_external_recordings_list()



def update_external_recordings_list(plugin):
    """Save all recordings to external JSON file."""

    # Create the file if it doesn't exist
    try:
        if not os.path.exists(plugin.saved_recordings_file_path):
            with open(plugin.saved_recordings_file_path, 'w') as f:
                json.dump([], f)
            print(f"Created new file at: {plugin.saved_recordings_file_path}")

        recordings_data = []

        for recording in plugin.saved_recordings:
            # Create a dictionary with all attributes
            recording_dict = {'unique_id': recording.unique_id, 'fire_id': recording.fire_id, 'type': recording.type, 'sent_to_ground': recording.sent_to_ground, 'timestamp': recording.timestamp}

            # Add attributes specific to PositionRecording
            if hasattr(recording, 'position'):
                recording_dict['position'] = recording.position
                recording_dict['wingman_pos_at_time'] = recording.wingman_pos_at_time

            # Add attributes specific to RouteRecording
            if hasattr(recording, 'start_pos'):
                recording_dict['start_pos'] = recording.start_pos
                recording_dict['end_pos'] = recording.end_pos
                recording_dict['trajectory_points'] = recording.trajectory_points

            recordings_data.append(recording_dict)

        # Write to JSON file
        with open(plugin.saved_recordings_file_path, 'w') as f:
            json.dump(recordings_data, f, indent=2)
    except Exception as e:
        xp.log(f'Failed to writ to external recordings list: {e}')



def load_external_recordings_list(plugin):
    """Load recordings from external JSON file back into plugin.saved_recordings."""

    # Check if file exists
    if not os.path.exists(plugin.saved_recordings_file_path):
        xp.log(f"No backup file {plugin.saved_recordings_file_path} found, starting with empty recordings list.")
        plugin.saved_recordings = []
        return

    try:
        with open(plugin.saved_recordings_file_path, 'r') as f:
            recordings_data = json.load(f)

        plugin.saved_recordings = []

        for recording_dict in recordings_data:
            # Determine which type of recording to create based on attributes
            if 'position' in recording_dict:
                # This is a PositionRecording
                recording = PositionRecording(
                    type=recording_dict['type'],
                    fire_id=recording_dict['fire_id'],
                    position=recording_dict['position'],
                    timestamp=recording_dict['timestamp'],
                    wingman_pos_at_time=recording_dict['wingman_pos_at_time']
                )
            elif 'start_pos' in recording_dict:
                # This is a RouteRecording
                recording = RouteRecording(
                    type=recording_dict['type'],
                    fire_id=recording_dict['fire_id'],
                    start_pos=recording_dict['start_pos'],
                    timestamp=recording_dict['timestamp']
                )
                # Set additional RouteRecording attributes
                plugin.targets[recording_dict['fire_id']].route1_start = recording_dict.get('start_pos', None)
                plugin.targets[recording_dict['fire_id']].route1_start = recording_dict.get('end_pos', None)
                recording.end_pos = recording_dict.get('end_pos')
                recording.trajectory_points = recording_dict.get('trajectory_points', [recording_dict['start_pos']])
            else:
                xp.log(f"Warning: Unknown recording type, skipping entry")
                continue

            # Set common attributes that are set after initialization
            recording.unique_id = recording_dict.get('unique_id')
            recording.sent_to_ground = recording_dict.get('sent_to_ground', False)
            plugin.saved_recordings.append(recording)
        xp.log(f"Loaded {len(plugin.saved_recordings)} recordings from backup file.")

    except Exception as e:
        xp.log(f"Error loading recordings: {e}")
        plugin.saved_recordings = []



