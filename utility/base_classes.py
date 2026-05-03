"""Core HAATO base classes and geospatial utilities."""
import numpy as np
from abc import ABC, abstractmethod
from typing import Tuple, Union


# ===================================================================================================
# GEOSPATIAL UTILITIES
# ===================================================================================================

class GeoUtils:
    """Vectorized geospatial calculation utilities using numpy"""

    EARTH_RADIUS_NM = 3440.065  # Earth radius in nautical miles
    EARTH_RADIUS_M = 6371000.0  # Earth radius in meters

    @staticmethod
    def to_radians(degrees: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        """Convert degrees to radians (vectorized)"""
        return np.deg2rad(degrees)

    @staticmethod
    def to_degrees(radians: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        """Convert radians to degrees (vectorized)"""
        return np.rad2deg(radians)

    @staticmethod
    def travel_time_min(posA, posB, speed_knots=180):
        dist = GeoUtils.haversine_distance(posA[0], posA[1], posB[0], posB[1])
        return (dist / speed_knots) * 60.0

    @staticmethod
    def haversine_distance(lat1: Union[float, np.ndarray],
                          lon1: Union[float, np.ndarray],
                          lat2: Union[float, np.ndarray],
                          lon2: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        """
        Calculate great circle distance using Haversine formula (vectorized).

        Args:
            lat1, lon1: Starting position(s) in degrees
            lat2, lon2: Ending position(s) in degrees

        Returns:
            Distance in nautical miles

        Note: All inputs can be scalars or numpy arrays for batch processing
        """
        # Convert to radians
        lat1_rad = np.deg2rad(lat1)
        lat2_rad = np.deg2rad(lat2)
        lon1_rad = np.deg2rad(lon1)
        lon2_rad = np.deg2rad(lon2)

        # Haversine formula
        dlat = lat2_rad - lat1_rad
        dlon = lon2_rad - lon1_rad

        a = np.sin(dlat / 2) ** 2 + np.cos(lat1_rad) * np.cos(lat2_rad) * np.sin(dlon / 2) ** 2
        c = 2 * np.arcsin(np.sqrt(a))

        return GeoUtils.EARTH_RADIUS_NM * c

    @staticmethod
    def calculate_bearing(lat1: Union[float, np.ndarray],
                         lon1: Union[float, np.ndarray],
                         lat2: Union[float, np.ndarray],
                         lon2: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        """
        Calculate initial bearing from point 1 to point 2 (vectorized).

        Args:
            lat1, lon1: Starting position(s) in degrees
            lat2, lon2: Ending position(s) in degrees

        Returns:
            Bearing in degrees (0-360)
        """
        # Convert to radians
        lat1_rad = np.deg2rad(lat1)
        lat2_rad = np.deg2rad(lat2)
        lon1_rad = np.deg2rad(lon1)
        lon2_rad = np.deg2rad(lon2)

        dlon = lon2_rad - lon1_rad

        y = np.sin(dlon) * np.cos(lat2_rad)
        x = np.cos(lat1_rad) * np.sin(lat2_rad) - np.sin(lat1_rad) * np.cos(lat2_rad) * np.cos(dlon)

        bearing_rad = np.arctan2(y, x)
        bearing_deg = np.rad2deg(bearing_rad)

        # Normalize to 0-360
        return (bearing_deg + 360) % 360

    @staticmethod
    def calculate_range_bearing_alt(pos1: Tuple[float, float, float],
                                     pos2: Union[Tuple[float, float, float], np.ndarray]) -> Tuple[Union[float, np.ndarray], Union[float, np.ndarray], Union[float, np.ndarray]]:
        """
        Calculate range (NM), bearing (degrees), and altitude difference (m) between positions.
        Optimized version of _calculate_range from MissionManager.

        Args:
            pos1: Single position as (lat, lon, alt) in degrees and meters
            pos2: Single position or array of positions
                  If array, shape should be (N, 3) or can be tuple of (lat, lon, alt)

        Returns:
            range_nm: Distance in nautical miles
            bearing_deg: Bearing in degrees (0-360)
            d_alt: Altitude difference in meters
        """
        lat1, lon1, alt1 = pos1

        if isinstance(pos2, np.ndarray):
            lat2 = pos2[:, 0]
            lon2 = pos2[:, 1]
            alt2 = pos2[:, 2]
        else:
            lat2, lon2, alt2 = pos2

        range_nm = GeoUtils.haversine_distance(lat1, lon1, lat2, lon2)
        bearing_deg = GeoUtils.calculate_bearing(lat1, lon1, lat2, lon2)
        d_alt = alt2 - alt1

        return range_nm, bearing_deg, d_alt

    @staticmethod
    def project_position(lat: float, lon: float, heading_deg: float,
                        speed_knots: float, time_seconds: float) -> Tuple[float, float]:
        """
        Project a position forward in time given heading and speed.
        Optimized version using numpy.

        Args:
            lat, lon: Starting position in degrees
            heading_deg: Heading in degrees
            speed_knots: Speed in knots
            time_seconds: Time to project forward in seconds

        Returns:
            (new_lat, new_lon) in degrees
        """
        # Convert speed from knots to nautical miles per second
        speed_nm_per_sec = speed_knots / 3600.0
        distance_nm = speed_nm_per_sec * time_seconds

        # Convert to radians
        lat_rad = np.deg2rad(lat)
        lon_rad = np.deg2rad(lon)
        heading_rad = np.deg2rad(heading_deg)

        # Angular distance
        d_over_r = distance_nm / GeoUtils.EARTH_RADIUS_NM

        # Calculate new latitude
        new_lat_rad = np.arcsin(
            np.sin(lat_rad) * np.cos(d_over_r) +
            np.cos(lat_rad) * np.sin(d_over_r) * np.cos(heading_rad)
        )

        # Calculate new longitude
        new_lon_rad = lon_rad + np.arctan2(
            np.sin(heading_rad) * np.sin(d_over_r) * np.cos(lat_rad),
            np.cos(d_over_r) - np.sin(lat_rad) * np.sin(new_lat_rad)
        )

        # Convert back to degrees
        new_lat = np.rad2deg(new_lat_rad)
        new_lon = np.rad2deg(new_lon_rad)

        return new_lat, new_lon


# ===================================================================================================
# BASE CLASSES
# ===================================================================================================

class MissionManager(ABC):
    """Base class for all mission managers (optimized with numpy)"""

    def __init__(self, user_id, xpc, dev_mode=False, num_wingmen=1):
        self.user_id = user_id
        self.xpc = xpc
        self.dev_mode = dev_mode

        self.targets = []
        self.mission_timer = 0

        self.wingman = None

        self.mission_status_dref = "custom/haato/mission_status"
        self.human_command_dref = "custom/haato/command_from_human"
        self.wingman_lat_dref = "custom/haato/wingman_lat"
        self.wingman_long_dref = "custom/haato/wingman_long"
        self.wingman_alt_dref = "custom/haato/wingman_alt"
        self.mission_timer_dref = "custom/haato/mission_time_left"
        self.request_response_dref = "custom/haato/request_response"
        self.status_message_dref = "custom/haato/wingman_status"

    @abstractmethod
    def reset(self):
        """Reset mission state - must be implemented by subclasses"""
        pass

    @abstractmethod
    def step(self, dt, met):
        """Execute one simulation step - must be implemented by subclasses
        args:
            dt: Time passed since the last step (computed by MissionTimer)
            met: Mission elapsed time (seconds)
        """
        pass

    @abstractmethod
    def get_state(self):
        pass

    @abstractmethod
    def get_observation(self):
        pass

    @abstractmethod
    def _check_mission_progress(self) -> Tuple[bool, str]:
        pass

    def _check_for_human_commands(self):
        """Should read from custom dataREF /custom/haato/command_from_human/ that is hosted by a script PI_wingman_commands.py
        PI_wingman_commands.py will handle writing to the DREF, so this method just needs to read its current value

        Dataref values:
            0.0-7.0: Meet me at target[i]
            8.0: Follow me
            9.0: No command

        """
        human_command = self.xpc.getDREF(self.human_command_dref)
        self.wingman.store_latest_command(human_command)

    def safe_get_dref(self, dref_path, fallback=None, param_name=None):
        """Safely get DREF value with optional fallback"""
        try:
            if dref_path in self.xpc.current_dref_values:
                dref = self.xpc.current_dref_values[dref_path]['value']
            else:
                dref = self.xpc.getDREF(dref_path)
            return dref

        except Exception:
            if fallback is not None:
                if getattr(self, 'verbose', False):
                    print(f'ERROR getting dref {param_name}, using previous value')
                return fallback
            else:
                if getattr(self, 'verbose', False):
                    print(f'ERROR getting {param_name or dref_path}')
                return None

    def safe_send_dref(self, dref_path, value, param_name=None):
        """Safely send DREF value with error handling"""
        try:
            self.xpc.sendDREF(dref_path, value)
            return True
        except Exception as e:
            if getattr(self, 'verbose', False):
                print(f'Error sending {param_name or dref_path}={value}: {e}')
            return False

    @staticmethod
    def _calculate_range(pos1: Tuple[float, float, float], pos2: Tuple[float, float, float]):
        """Calculate range (NM), bearing angle (degrees), and difference in altitude (m) between two LLA positions

        NOTE: This now uses the optimized GeoUtils class for better performance
        """
        return GeoUtils.calculate_range_bearing_alt(pos1, pos2)


class Wingman(ABC):
    """Base class for wingman agents (optimized with numpy)"""

    def __init__(self, xpc, start_lla, start_hdg, start_spd, mm):
        self.xpc = xpc
        self.mm = mm

        self.type = 'N/A'

        self.lat = start_lla[0]
        self.long = start_lla[1]
        self.alt = start_lla[2]
        self.hdg = start_hdg
        self.spd = 400

        self.max_speed = 500  # The max speed the agent can command
        self.default_spd = 400

        # Debug print settings - defaults to False for performance
        self.debug_calc_hsa = False
        self.debug_intercept = False
        self.debug_holding = False

    @abstractmethod
    def act(self, observation, commands) -> Tuple[float, float, float]:
        """
        Inputs:
            observation: numpy array containing:
                mission_timer,
                human_lat,
                human_long,
                human_alt,
                human_hdg,
                human_spd,
                for target in targets:
                    target.lat, target.long, target.alt, target.spotted_by_user, target.handled

            commands: Tuple of command values from human

        :return: dict containing:
            'type' (str): Type of action (HSA or LLA)
            'goal' (tuple): e.g. (desired_hdg, desired_spd, desired_alt)
            'request' (str): Agent's request to pass to the human, if any. 'none' if not.

        """
        pass

    def store_latest_command(self, command):
        self.latest_human_command = command

    def receive_human_message(self, message):
        self.latest_human_message = message

    ####################################################################################################################
    #################################### Helper functions ##############################################################
    ####################################################################################################################

    def safe_get_dref(self, dref_path, fallback=None, param_name=None):
        """Safely get DREF value with optional fallback"""
        try:
            if dref_path in self.xpc.current_dref_values:
                dref = self.xpc.current_dref_values[dref_path]['value']
            else:
                dref = self.xpc.getDREF(dref_path)
            return dref

        except Exception:
            if fallback is not None:
                if getattr(self, 'verbose', False):
                    print(f'ERROR getting dref {param_name}, using previous value')
                return fallback
            else:
                if getattr(self, 'verbose', False):
                    print(f'ERROR getting {param_name or dref_path}')
                return None

    def safe_send_dref(self, dref_path, value, param_name=None):
        """Safely send DREF value with error handling"""
        try:
            self.xpc.sendDREF(dref_path, value)
            return True
        except Exception as e:
            if getattr(self, 'verbose', False):
                print(f'Error sending {param_name or dref_path}={value}: {e}')
            return False

    def _calc_hsa_to_target(self, observation, target_to_fly_to) -> Tuple[float, float, float]:
        """
        Calculate the heading, speed, and altitude required to get to the target.
        OPTIMIZED: Uses numpy-based calculations and reduced debug overhead.
        """
        # Validate target index
        target_data = observation[6:]
        num_targets = len(target_data) // 8

        if target_to_fly_to >= num_targets:
            if self.debug_calc_hsa:
                print(f"ERROR: Target index {target_to_fly_to} out of range (max: {num_targets - 1})")
            return self.hdg, self.spd, self.alt

        # Extract target position from observation (optimized indexing)
        #print(f'Obs = {observation}, target_to_fly_to = {target_to_fly_to}')
        i = 16 + (target_to_fly_to * 14)  # TARGET_BLOCK_SIZE=14

        target_lat = observation[i]
        target_lon = observation[i + 1]
        target_alt = observation[i + 2]
        #print(f'        calc_hsa_to_target({target_lat}, {target_lon}, {target_alt})')

        # Calculate bearing and distance using optimized GeoUtils
        distance_nm = GeoUtils.haversine_distance(self.lat, self.long, target_lat, target_lon)
        desired_hdg = GeoUtils.calculate_bearing(self.lat, self.long, target_lat, target_lon)

        # Debug output (only if enabled)
        if self.debug_calc_hsa:
            print(f"\n=== _calc_hsa_to_target (target {target_to_fly_to}) ===")
            print(f"Wingman pos: ({self.lat:.4f}, {self.long:.4f}, {self.alt:.0f})")
            print(f"Target pos: ({target_lat:.4f}, {target_lon:.4f}, {target_alt:.0f})")
            print(f"Distance: {distance_nm:.3f} NM, Bearing: {desired_hdg:.1f}°")

        # Altitude management (simplified logic)
        alt_diff = abs(self.alt - target_alt)
        if alt_diff > 200:
            desired_alt = target_alt + 200
        else:
            desired_alt = self.alt

        # Speed management
        desired_spd = self.max_speed if distance_nm > 5 else self.default_spd

        if self.debug_calc_hsa:
            print(f"Commanded HSA: hdg={desired_hdg:.1f}°, spd={desired_spd:.1f}, alt={desired_alt:.0f}\n")

        return desired_hdg, desired_spd, desired_alt

    def _calc_hsa_to_human_intercept(self, observation) -> Tuple[float, float, float]:
        """
        Calculate heading, speed, altitude to intercept the human.
        OPTIMIZED: Uses analytical solution instead of iterative approach.
        """
        human_lat = observation[1]
        human_lon = observation[2]
        human_alt = observation[3]
        human_hdg = observation[4]
        human_spd = observation[5]

        # Calculate current distance to human
        distance_to_human = GeoUtils.haversine_distance(self.lat, self.long, human_lat, human_lon)

        if self.debug_intercept:
            print(f"\n=== _calc_hsa_to_human_intercept ===")
            print(f"Distance to human: {distance_to_human:.3f} NM")

        # If very close, just match their course
        if distance_to_human < 0.5:
            return human_hdg, human_spd, human_alt

        # Analytical intercept solution using law of sines
        # This is more accurate and faster than the iterative approach

        # Convert speeds to nm/s
        human_speed_nm_s = human_spd / 3600.0
        wingman_speed_nm_s = self.max_speed / 3600.0

        # Calculate bearing to human's current position
        bearing_to_human = GeoUtils.calculate_bearing(self.lat, self.long, human_lat, human_lon)

        # Calculate relative heading (angle between human's heading and bearing to wingman)
        # This is the angle at the human's vertex in our intercept triangle
        rel_heading = np.deg2rad((bearing_to_human - human_hdg + 180) % 360)

        # Use law of sines to solve intercept triangle
        # sin(wingman_angle) / human_speed = sin(rel_heading) / wingman_speed
        speed_ratio = human_speed_nm_s / wingman_speed_nm_s

        # Check if intercept is possible
        sin_arg = speed_ratio * np.sin(rel_heading)
        if abs(sin_arg) > 1.0:
            # Intercept impossible, fly toward current position
            intercept_time = distance_to_human / wingman_speed_nm_s
        else:
            wingman_angle = np.arcsin(sin_arg)
            # Calculate time to intercept using law of sines
            intercept_angle = np.pi - rel_heading - wingman_angle
            intercept_time = distance_to_human * np.sin(rel_heading) / (wingman_speed_nm_s * np.sin(intercept_angle))

        # Project human's future position
        intercept_lat, intercept_lon = GeoUtils.project_position(
            human_lat, human_lon, human_hdg, human_spd, intercept_time
        )

        # Calculate heading to intercept point
        desired_hdg = GeoUtils.calculate_bearing(self.lat, self.long, intercept_lat, intercept_lon)
        desired_spd = self.max_speed
        desired_alt = human_alt

        if self.debug_intercept:
            print(f"Intercept time: {intercept_time:.1f}s")
            print(f"Intercept point: ({intercept_lat:.4f}, {intercept_lon:.4f})")
            print(f"Commanded: hdg={desired_hdg:.1f}°, spd={desired_spd:.1f}, alt={desired_alt:.0f}\n")

        return desired_hdg, desired_spd, desired_alt

    def _calc_hsa_holding_pattern(self, target_lat, target_lon, target_alt, mission_timer) -> Tuple[float, float, float]:
        """
        Calculate heading, speed, and altitude for a circular holding pattern.
        OPTIMIZED: Simplified calculations using numpy.
        """
        # Holding pattern parameters
        pattern_radius = 0.15  # Nautical miles
        pattern_speed = self.default_spd * 0.8
        pattern_period = 40  # seconds for complete circle

        # Calculate angle in pattern based on time
        time_in_cycle = mission_timer % pattern_period
        angle_rad = (time_in_cycle / pattern_period) * 2 * np.pi
        circle_heading = np.rad2deg(angle_rad)

        # Calculate desired position on circle
        desired_lat, desired_lon = GeoUtils.project_position(
            target_lat, target_lon, circle_heading, pattern_radius * 3440.065, 1.0
        )

        # Calculate distances
        distance_to_desired = GeoUtils.haversine_distance(self.lat, self.long, desired_lat, desired_lon)

        # Determine heading: fly toward circle or tangent to it
        if distance_to_desired > 0.1:
            desired_hdg = GeoUtils.calculate_bearing(self.lat, self.long, desired_lat, desired_lon)
        else:
            # Fly tangent to circle
            desired_hdg = (circle_heading + 90) % 360

        # Altitude management
        alt_diff = abs(self.alt - target_alt)
        if alt_diff > 500:
            desired_alt = self.alt + np.sign(target_alt - self.alt) * 200
        else:
            desired_alt = target_alt

        if self.debug_holding:
            print(f"[HOLDING] hdg={desired_hdg:.1f}°, spd={pattern_speed:.1f}, alt={desired_alt:.0f}")

        return desired_hdg, pattern_speed, desired_alt

    # Legacy methods for backward compatibility (now use GeoUtils)
    @staticmethod
    def _project_position(lat, lon, heading, speed, time_seconds):
        """Legacy method - redirects to GeoUtils.project_position"""
        return GeoUtils.project_position(lat, lon, heading, speed, time_seconds)

    @staticmethod
    def _calculate_distance(lat1, lon1, lat2, lon2):
        """Legacy method - redirects to GeoUtils.haversine_distance"""
        return GeoUtils.haversine_distance(lat1, lon1, lat2, lon2)

    def _calculate_bearing(self, lat1, lon1, lat2, lon2):
        """Legacy method - redirects to GeoUtils.calculate_bearing"""
        return GeoUtils.calculate_bearing(lat1, lon1, lat2, lon2)


# Sentinel distinguishing "caller did not pass a reported position" from
# "caller explicitly passed None to mark this fire as unknown to the cockpit".
_REPORTED_UNSET = object()


class Target:
    """Target class - unchanged from original"""

    def __init__(self, type, lat, long, alt, id,
                 reported_lat=_REPORTED_UNSET, reported_long=_REPORTED_UNSET, reported_alt=_REPORTED_UNSET,
                 image_path="", image_res=None,
                 is_dynamic=False, trigger_time_s=None):
        # True (physics/detection) position
        self.lat = lat  # Latitude
        self.long = long  # Longitude
        self.alt = alt

        # Reported (MFD) position — what the cockpit displays.
        #
        # Sentinel (_REPORTED_UNSET) = caller did not specify a reported position.
        #   → Legacy / perfect-information behaviour: reported == true, fire is KNOWN.
        # None = caller explicitly marks this fire as UNKNOWN to the cockpit.
        #   → reported position defaults to true position but is_known_to_cockpit=False.
        # float value = fire is KNOWN at the given reported position.
        if reported_lat is _REPORTED_UNSET:
            self.reported_lat = lat
            self.reported_long = long
            self.reported_alt = alt
            self.is_known_to_cockpit = True
        elif reported_lat is None:
            self.reported_lat = lat    # placeholder; may be updated on discovery
            self.reported_long = long
            self.reported_alt = alt
            self.is_known_to_cockpit = False
        else:
            self.reported_lat = float(reported_lat)
            self.reported_long = float(reported_long) if reported_long is not _REPORTED_UNSET else long
            self.reported_alt = float(reported_alt) if reported_alt is not _REPORTED_UNSET else alt
            self.is_known_to_cockpit = True

        # Preserved for resetting between mission runs
        self._initially_known = self.is_known_to_cockpit

        # Image metadata consumed by the X-Plane plugin renderer
        self.image_path = image_path
        self.image_res = image_res if image_res is not None else [512, 512]

        # Dynamic fire metadata
        self.is_dynamic = is_dynamic
        self.trigger_time_s = trigger_time_s

        self.id = id
        self.type = type  # moderate or severe
        self.spotted = 0  # 0 or 1
        self.handled = False
        self.human_in_range_time = 0.0
        self.progress = 0.0
        self.wingman_in_range_time = 0.0
        self.wingman_observation_time = 0.0  # Time wingman has observed a misclassified fire
        self.handling_start_time = None
        self.is_being_handled = False
        self.position_recorded_by_wingman = False

        self.status = 0.0
        self.classification = 0.0

        # Drop route tracking
        self.route1_start = None
        self.route1_end = None
        self.route1_recorder = None  # 'human' or 'wingman_0'

        self.route2_start = None
        self.route2_end = None
        self.route2_recorder = None

        self.marked_position = None
        self.initial_drop_route_complete = False
        self.refined_drop_route_complete = False
