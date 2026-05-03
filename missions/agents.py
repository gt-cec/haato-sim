"""Reusable agent library — generic Wingman subclasses compatible with any HAATO mission."""

import random
import numpy as np

from utility.base_classes import Wingman, GeoUtils


class PassiveWingman(Wingman):
    """Do-nothing baseline: holds spawn position indefinitely."""

    def __init__(self, xpc, start_lla, start_hdg, start_spd, mm):
        super().__init__(xpc, start_lla, start_hdg, start_spd, mm)
        self._hold_lat = start_lla[0]
        self._hold_lon = start_lla[1]
        self._hold_alt = start_lla[2]

    def act(self, observation, commands):
        dist = GeoUtils.haversine_distance(self.lat, self.long, self._hold_lat, self._hold_lon)
        if dist > 0.1:
            hdg = GeoUtils.calculate_bearing(self.lat, self.long, self._hold_lat, self._hold_lon)
            spd = self.default_spd
        else:
            hdg, spd = self.hdg, 0.0
        return {'type': 'hsa', 'goal': (hdg, spd, self._hold_alt), 'request': 'none'}


class GreedyWingman(Wingman):
    """Rule-based baseline: always flies to the closest unhandled/unspotted target."""

    def __init__(self, xpc, start_lla, start_hdg, start_spd, mm):
        super().__init__(xpc, start_lla, start_hdg, start_spd, mm)

    def act(self, observation, commands):
        target = self._pick_target()
        if target is None:
            return {'type': 'hsa', 'goal': (self.hdg, self.default_spd, self.alt), 'request': 'none'}
        hdg = GeoUtils.calculate_bearing(self.lat, self.long, target.lat, target.long)
        return {'type': 'hsa', 'goal': (hdg, self.default_spd, target.alt), 'request': 'none'}

    def _pick_target(self):
        candidates = [t for t in self.mm.targets if not t.spotted and not t.handled]
        if not candidates:
            candidates = [t for t in self.mm.targets if not t.handled]
        if not candidates:
            return None
        return min(candidates, key=lambda t: GeoUtils.haversine_distance(self.lat, self.long, t.lat, t.long))


class RandomWingman(Wingman):
    """Stochastic baseline: picks a random unhandled target each time the current one is resolved."""

    def __init__(self, xpc, start_lla, start_hdg, start_spd, mm, seed=None):
        super().__init__(xpc, start_lla, start_hdg, start_spd, mm)
        self._rng = random.Random(seed)
        self._current_target = None

    def act(self, observation, commands):
        if self._current_target is None or self._current_target.spotted or self._current_target.handled:
            candidates = [t for t in self.mm.targets if not t.spotted and not t.handled]
            if not candidates:
                candidates = [t for t in self.mm.targets if not t.handled]
            self._current_target = self._rng.choice(candidates) if candidates else None

        if self._current_target is None:
            return {'type': 'hsa', 'goal': (self.hdg, self.default_spd, self.alt), 'request': 'none'}

        hdg = GeoUtils.calculate_bearing(self.lat, self.long, self._current_target.lat, self._current_target.long)
        return {'type': 'hsa', 'goal': (hdg, self.default_spd, self._current_target.alt), 'request': 'none'}


class MLWingman(Wingman):
    """RL-ready stub: loads a .npy policy lookup table; falls back to greedy if policy not found.

    The policy file should be a 2-D numpy array of shape (N_states, N_actions) where each row
    is a probability (or Q-value) distribution over target indices.  At runtime the observation
    is hashed to an integer row index and argmax selects the action.  Replace this stub with a
    real neural-network forward pass once a trained policy is available.
    """

    def __init__(self, xpc, start_lla, start_hdg, start_spd, mm, policy_path=None):
        super().__init__(xpc, start_lla, start_hdg, start_spd, mm)
        self.policy = None
        self._greedy = GreedyWingman(xpc, start_lla, start_hdg, start_spd, mm)

        if policy_path:
            try:
                self.policy = np.load(policy_path)
                print(f"[MLWingman] Loaded policy from {policy_path}, shape={self.policy.shape}")
            except Exception as e:
                print(f"[MLWingman] Could not load policy '{policy_path}': {e}. Using greedy fallback.")

    def act(self, observation, commands):
        self._sync_greedy()

        if self.policy is not None:
            obs_idx    = int(abs(hash(observation.tobytes())) % len(self.policy))
            action_idx = int(np.argmax(self.policy[obs_idx]))
            candidates = [t for t in self.mm.targets if not t.handled]
            if candidates:
                target = candidates[action_idx % len(candidates)]
                hdg    = GeoUtils.calculate_bearing(self.lat, self.long, target.lat, target.long)
                return {'type': 'hsa', 'goal': (hdg, self.default_spd, target.alt), 'request': 'none'}

        return self._greedy.act(observation, commands)

    def _sync_greedy(self):
        self._greedy.lat, self._greedy.long, self._greedy.alt = self.lat, self.long, self.alt
        self._greedy.hdg, self._greedy.spd = self.hdg, self.spd
