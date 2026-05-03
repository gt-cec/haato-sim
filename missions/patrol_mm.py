"""Collaborative ISR patrol mission: human + AI must together cover 10 targets."""

import math
import numpy as np
from typing import Tuple

from utility.base_classes import MissionManager, Wingman, Target, GeoUtils


class PatrolMissionMM(MissionManager):
    """Cooperative ISR: 10 targets spread over an area too large for one aircraft alone."""

    def __init__(self, user_id, xpc, verbose=False, dev_mode=False):
        super().__init__(user_id, xpc, dev_mode, num_wingmen=1)

        self.max_mission_time = 600  # 10 minutes
        self.detection_range  = 1.5  # nautical miles
        self.inv_earth_radius_nm = 1.0 / 3440.065

        self.human_spawn_lla = (47.80, -122.28, 300)
        self.ai_spawn_lla    = (47.80, -122.26, 1200)

        # 10 targets spread ~15 NM apart — one aircraft cannot cover all within 600 s
        self.targets = [
            Target("poi", 47.83, -122.30, 1200, 0),
            Target("poi", 47.85, -122.25, 1200, 1),
            Target("poi", 47.78, -122.32, 1200, 2),
            Target("poi", 47.76, -122.24, 1200, 3),
            Target("poi", 47.88, -122.28, 1200, 4),
            Target("poi", 47.74, -122.27, 1200, 5),
            Target("poi", 47.91, -122.31, 1200, 6),
            Target("poi", 47.72, -122.22, 1200, 7),
            Target("poi", 47.93, -122.23, 1200, 8),
            Target("poi", 47.70, -122.30, 1200, 9),
        ]

        self.human_lla = self.human_spawn_lla
        self.human_hdg = 0.0
        self.human_spd = 200.0

    def reset(self):
        self.mission_timer = 0
        for t in self.targets:
            t.spotted = 0
        self.human_lla = self.human_spawn_lla
        self.wingman = CoopPatrolWingman(
            self.xpc, self.ai_spawn_lla, 90, 200, self
        )
        self.xpc.sendDREF(self.mission_status_dref, 0.0)

    def step(self, dt, met):
        self.mission_timer = met
        self._get_human_lla()

        obs    = self.get_observation()
        action = self.wingman.act(obs, None)
        self._move_wingman(action['goal'], dt)

        for t in self.targets:
            if t.spotted:
                continue
            human_range, _, _ = self._calculate_range(
                self.human_lla, (t.lat, t.long, t.alt)
            )
            ai_range, _, _ = self._calculate_range(
                (self.wingman.lat, self.wingman.long, self.wingman.alt),
                (t.lat, t.long, t.alt)
            )
            if human_range <= self.detection_range or ai_range <= self.detection_range:
                t.spotted = 1
                spotter  = 'Human' if human_range <= self.detection_range else 'AI'
                progress = sum(1 for t2 in self.targets if t2.spotted)
                print(f"[Patrol] {spotter} spotted target {t.id}. Progress: {progress}/{len(self.targets)}")

        complete, reason = self._check_mission_progress()
        return complete

    def get_observation(self):
        obs = np.array([
            self.mission_timer,
            self.human_lla[0], self.human_lla[1], self.human_lla[2],
            self.human_hdg, self.human_spd,
        ])
        for t in self.targets:
            obs = np.concatenate([obs, [t.lat, t.long, t.alt, float(t.spotted)]])
        return obs

    def get_state(self):
        spotted = sum(1 for t in self.targets if t.spotted)
        return {
            'mission_timer':   self.mission_timer,
            'targets_spotted': spotted,
            'total_targets':   len(self.targets),
        }

    def _check_mission_progress(self) -> Tuple[bool, str]:
        if all(t.spotted for t in self.targets):
            print(f"[Patrol] Mission complete! All {len(self.targets)} targets spotted.")
            self.xpc.sendDREF(self.mission_status_dref, 1.0)
            return True, 'success'
        if self.mission_timer >= self.max_mission_time:
            spotted = sum(1 for t in self.targets if t.spotted)
            print(f"[Patrol] Timeout. Spotted {spotted}/{len(self.targets)} targets.")
            self.xpc.sendDREF(self.mission_status_dref, -1.0)
            return True, 'timeout'
        return False, 'in_progress'

    def _get_human_lla(self):
        lat = self.safe_get_dref('sim/flightmodel/position/latitude')
        lon = self.safe_get_dref('sim/flightmodel/position/longitude')
        alt = self.safe_get_dref('sim/flightmodel/position/elevation')
        hdg = self.safe_get_dref('sim/flightmodel/position/true_psi')
        if lat is not None: self.human_lla = (lat, self.human_lla[1], self.human_lla[2])
        if lon is not None: self.human_lla = (self.human_lla[0], lon, self.human_lla[2])
        if alt is not None: self.human_lla = (self.human_lla[0], self.human_lla[1], alt)
        if hdg is not None: self.human_hdg = hdg

    def _move_wingman(self, action: Tuple[float, float, float], dt):
        goal_hdg, goal_spd, goal_alt = action
        hdg_rate, spd_rate, alt_rate = 3.0, 5.0, 10.0

        d_hdg = (goal_hdg - self.wingman.hdg + 180) % 360 - 180
        self.wingman.hdg = (self.wingman.hdg + max(-hdg_rate * dt, min(hdg_rate * dt, d_hdg))) % 360
        self.wingman.spd = max(0, self.wingman.spd + max(-spd_rate * dt, min(spd_rate * dt, goal_spd - self.wingman.spd)))
        self.wingman.alt += max(-alt_rate * dt, min(alt_rate * dt, goal_alt - self.wingman.alt))

        dist_nm     = self.wingman.spd * (dt / 3600.0)
        bearing_rad = math.radians(self.wingman.hdg)
        lat_rad     = math.radians(self.wingman.lat)
        lon_rad     = math.radians(self.wingman.long)
        ang         = dist_nm * self.inv_earth_radius_nm

        new_lat_rad = math.asin(
            math.sin(lat_rad) * math.cos(ang)
            + math.cos(lat_rad) * math.sin(ang) * math.cos(bearing_rad)
        )
        new_lon_rad = lon_rad + math.atan2(
            math.sin(bearing_rad) * math.sin(ang) * math.cos(lat_rad),
            math.cos(ang) - math.sin(lat_rad) * math.sin(new_lat_rad)
        )
        self.wingman.lat  = math.degrees(new_lat_rad)
        self.wingman.long = math.degrees(new_lon_rad)


class CoopPatrolWingman(Wingman):
    """Spatial partition agent: covers the far half of targets, leaving the near half to the human."""

    def __init__(self, xpc, start_lla, start_hdg, start_spd, mm):
        super().__init__(xpc, start_lla, start_hdg, start_spd, mm)
        self.default_spd = 200

        # Assign the farthest half of targets (by distance from AI spawn)
        sorted_by_dist = sorted(
            mm.targets,
            key=lambda t: GeoUtils.haversine_distance(start_lla[0], start_lla[1], t.lat, t.long)
        )
        half = len(sorted_by_dist) // 2
        self.assigned = sorted_by_dist[half:]
        self.idx = 0

    def act(self, observation, commands):
        # Advance past already-spotted assigned targets
        while self.idx < len(self.assigned) and self.assigned[self.idx].spotted:
            self.idx += 1

        if self.idx < len(self.assigned):
            target = self.assigned[self.idx]
        else:
            # All assigned targets covered — help with any remaining
            remaining = [t for t in self.mm.targets if not t.spotted]
            if not remaining:
                return {'type': 'hsa', 'goal': (self.hdg, self.default_spd, self.alt), 'request': 'none'}
            target = min(remaining, key=lambda t: GeoUtils.haversine_distance(self.lat, self.long, t.lat, t.long))

        hdg = GeoUtils.calculate_bearing(self.lat, self.long, target.lat, target.long)
        return {'type': 'hsa', 'goal': (hdg, self.default_spd, target.alt), 'request': 'none'}
