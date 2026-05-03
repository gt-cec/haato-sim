import math

import numpy as np
import pytest

from utility.base_classes import GeoUtils, MissionManager, Target, _REPORTED_UNSET


class _DummyXPC:
    def __init__(self):
        self.current_dref_values = {}
        self.values = {}
        self.sent = []
        self.raise_get = False
        self.raise_send = False

    def getDREF(self, path):
        if self.raise_get:
            raise RuntimeError("get failure")
        return self.values.get(path, -1.0)

    def sendDREF(self, path, value):
        if self.raise_send:
            raise RuntimeError("send failure")
        self.sent.append((path, value))


class _DummyMM(MissionManager):
    def reset(self):
        return None

    def step(self, dt, met):
        return False

    def get_state(self):
        return {}

    def get_observation(self):
        return np.zeros(1)

    def _check_mission_progress(self):
        return False, ""


def test_haversine_distance_same_point_zero():
    d = GeoUtils.haversine_distance(47.0, -121.0, 47.0, -121.0)
    assert d == pytest.approx(0.0, abs=1e-9)


def test_haversine_distance_known_pair_reasonable():
    # 1 degree latitude is about 60 NM.
    d = GeoUtils.haversine_distance(0.0, 0.0, 1.0, 0.0)
    assert d == pytest.approx(60.0, rel=0.01)


def test_haversine_distance_antipodal_half_earth():
    d = GeoUtils.haversine_distance(0.0, 0.0, 0.0, 180.0)
    assert d == pytest.approx(math.pi * GeoUtils.EARTH_RADIUS_NM, rel=1e-6)


def test_haversine_distance_crosses_antimeridian_short_path():
    d = GeoUtils.haversine_distance(0.0, 179.0, 0.0, -179.0)
    assert d == pytest.approx(120.0, rel=0.05)


def test_calculate_bearing_cardinal_directions():
    assert GeoUtils.calculate_bearing(0.0, 0.0, 1.0, 0.0) == pytest.approx(0.0, abs=1e-3)
    assert GeoUtils.calculate_bearing(0.0, 0.0, 0.0, 1.0) == pytest.approx(90.0, abs=1e-3)
    assert GeoUtils.calculate_bearing(0.0, 0.0, -1.0, 0.0) == pytest.approx(180.0, abs=1e-3)
    assert GeoUtils.calculate_bearing(0.0, 0.0, 0.0, -1.0) == pytest.approx(270.0, abs=1e-3)


def test_calculate_bearing_wraparound_near_north():
    b = GeoUtils.calculate_bearing(0.0, 0.0, 1.0, 1e-5)
    assert 0.0 <= b < 360.0
    assert min(abs(b - 0.0), abs(b - 360.0)) < 1.0


def test_project_position_and_roundtrip_distance():
    start = (47.5, -121.8)
    speed = 180.0
    seconds = 120.0
    end_lat, end_lon = GeoUtils.project_position(start[0], start[1], 90.0, speed, seconds)
    dist = GeoUtils.haversine_distance(start[0], start[1], end_lat, end_lon)
    expected = speed / 3600.0 * seconds
    assert dist == pytest.approx(expected, rel=0.02)


def test_travel_time_min_combinations_and_zero_distance():
    assert GeoUtils.travel_time_min((0.0, 0.0), (0.0, 0.0), speed_knots=180.0) == pytest.approx(0.0)
    t = GeoUtils.travel_time_min((0.0, 0.0), (1.0, 0.0), speed_knots=120.0)
    assert t == pytest.approx(30.0, rel=0.05)


def test_travel_time_min_zero_speed_guard_current_behavior():
    # Current behavior yields inf with numpy divide-by-zero semantics.
    t = GeoUtils.travel_time_min((0.0, 0.0), (1.0, 0.0), speed_knots=0.0)
    assert np.isinf(t)


def test_safe_get_dref_returns_cached_value_when_present():
    xpc = _DummyXPC()
    xpc.current_dref_values["a/b"] = {"value": 42.0}
    mm = _DummyMM(user_id=1, xpc=xpc)
    assert mm.safe_get_dref("a/b") == 42.0


def test_safe_get_dref_fallback_on_exception():
    xpc = _DummyXPC()
    xpc.raise_get = True
    mm = _DummyMM(user_id=1, xpc=xpc)
    assert mm.safe_get_dref("missing", fallback=9.0, param_name="missing") == 9.0


def test_safe_get_dref_none_without_fallback():
    xpc = _DummyXPC()
    xpc.raise_get = True
    mm = _DummyMM(user_id=1, xpc=xpc)
    assert mm.safe_get_dref("missing") is None


def test_safe_send_dref_success_and_failure_no_raise():
    xpc = _DummyXPC()
    mm = _DummyMM(user_id=1, xpc=xpc)
    assert mm.safe_send_dref("x/y", 1.0)
    xpc.raise_send = True
    assert not mm.safe_send_dref("x/y", 2.0)


def test_calculate_range_delegates_geo_utils_and_returns_tuple():
    p1 = (47.0, -121.0, 1000.0)
    p2 = (48.0, -121.0, 1200.0)
    rng, bearing, dalt = _DummyMM._calculate_range(p1, p2)
    assert rng == pytest.approx(60.0, rel=0.02)
    assert 0.0 <= bearing <= 360.0
    assert dalt == pytest.approx(200.0)


def test_target_default_fields_and_tracking_attrs():
    t = Target(type="moderate", lat=47.0, long=-121.0, alt=1000.0, id=3)
    assert t.status == 0.0
    assert t.classification == 0.0
    assert t.is_dynamic is False
    assert t.route1_start is None
    assert t.route1_end is None
    assert t.route2_start is None
    assert t.route2_end is None
    assert t.is_being_handled is False
    assert t.handling_start_time is None
    assert t.human_in_range_time == pytest.approx(0.0)
    assert t.wingman_in_range_time == pytest.approx(0.0)


def test_target_reported_unset_defaults_to_true_position_known():
    t = Target(type="severe", lat=47.1, long=-121.1, alt=1100.0, id=4, reported_lat=_REPORTED_UNSET)
    assert t.reported_lat == pytest.approx(t.lat)
    assert t.reported_long == pytest.approx(t.long)
    assert t.reported_alt == pytest.approx(t.alt)
    assert t.is_known_to_cockpit is True


def test_target_reported_none_marks_unknown_to_cockpit():
    t = Target(type="severe", lat=47.1, long=-121.1, alt=1100.0, id=5, reported_lat=None)
    assert t.reported_lat == pytest.approx(t.lat)
    assert t.is_known_to_cockpit is False
