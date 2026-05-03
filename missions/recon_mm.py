"""Competitive reconnaissance mission: human vs AI race to spot the most targets."""

import math
import numpy as np
from typing import Tuple

from utility.base_classes import MissionManager, Wingman, Target, GeoUtils


class ReconMissionMM(MissionManager):
    """Human and AI race to spot the most targets before time runs out."""

    def __init__(self, user_id, xpc, verbose=False, dev_mode=False):
        super().__init__(user_id, xpc, dev_mode, num_wingmen=1)

        self.max_mission_time = 480  # 8 minutes
        self.detection_range = 1.5   # nautical miles
        self.inv_earth_radius_nm = 1.0 / 3440.065

        self.human_spawn_lla = (47.90, -122.28, 300)
        self.ai_spawn_lla    = (47.90, -122.26, 1200)

        self.targets = [
            Target("poi", 47.93, -122.30, 1200, 0),
            Target("poi", 47.92, -122.24, 1200, 1),
            Target("poi", 47.88, -122.31, 1200, 2),
            Target("poi", 47.87, -122.23, 1200, 3),
            Target("poi", 47.95, -122.27, 1200, 4),
            Target("poi", 47.86, -122.28, 1200, 5),
        ]

        self.human_score = 0
        self.ai_score    = 0
        self.human_lla   = self.human_spawn_lla
        self.human_hdg   = 0.0
        self.human_spd   = 200.0

    def reset(self):
        self.mission_timer = 0
        self.human_score   = 0
        self.ai_score      = 0
        for t in self.targets:
            t.spotted = 0
        self.human_lla = self.human_spawn_lla
        self.wingman = CompetitiveScoutWingman(
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
            if human_range <= self.detection_range:
                t.spotted = 1
                self.human_score += 1
                print(f"[Recon] Human spotted target {t.id}. Score — Human: {self.human_score}, AI: {self.ai_score}")
            elif ai_range <= self.detection_range:
                t.spotted = 1
                self.ai_score += 1
                print(f"[Recon] AI spotted target {t.id}. Score — Human: {self.human_score}, AI: {self.ai_score}")

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
        return {
            'mission_timer':     self.mission_timer,
            'human_score':       self.human_score,
            'ai_score':          self.ai_score,
            'targets_remaining': sum(1 for t in self.targets if not t.spotted),
        }

    def _check_mission_progress(self) -> Tuple[bool, str]:
        if all(t.spotted for t in self.targets):
            winner = ('human' if self.human_score > self.ai_score
                      else 'ai' if self.ai_score > self.human_score else 'tie')
            print(f"[Recon] All targets found. Winner: {winner} ({self.human_score} vs {self.ai_score})")
            self.xpc.sendDREF(self.mission_status_dref, 1.0)
            return True, f'complete_{winner}'
        if self.mission_timer >= self.max_mission_time:
            winner = ('human' if self.human_score > self.ai_score
                      else 'ai' if self.ai_score > self.human_score else 'tie')
            print(f"[Recon] Timeout. Winner: {winner} ({self.human_score} vs {self.ai_score})")
            self.xpc.sendDREF(self.mission_status_dref, -1.0)
            return True, f'timeout_{winner}'
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

        dist_nm      = self.wingman.spd * (dt / 3600.0)
        bearing_rad  = math.radians(self.wingman.hdg)
        lat_rad      = math.radians(self.wingman.lat)
        lon_rad      = math.radians(self.wingman.long)
        ang          = dist_nm * self.inv_earth_radius_nm

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


class CompetitiveScoutWingman(Wingman):
    """Greedy competitive scout: always flies toward the closest unspotted target."""

    def __init__(self, xpc, start_lla, start_hdg, start_spd, mm):
        super().__init__(xpc, start_lla, start_hdg, start_spd, mm)
        self.default_spd = 250

    def act(self, observation, commands):
        unspotted = [t for t in self.mm.targets if not t.spotted]
        if not unspotted:
            return {'type': 'hsa', 'goal': (self.hdg, self.default_spd, self.alt), 'request': 'none'}

        target = min(unspotted, key=lambda t: GeoUtils.haversine_distance(self.lat, self.long, t.lat, t.long))
        hdg    = GeoUtils.calculate_bearing(self.lat, self.long, target.lat, target.long)
        return {'type': 'hsa', 'goal': (hdg, self.default_spd, target.alt), 'request': 'none'}
