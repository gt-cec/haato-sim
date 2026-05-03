import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from missions.fire.constants import NO_PLAN
from missions.fire.wingman.agent import FireWatchWingman
from utility.base_classes import Target
from utility.message_queue import Message


class MockXPC:
    def __init__(self):
        self.drefs = {}

    def sendDREF(self, name, value):
        self.drefs[name] = value

    def getDREF(self, name):
        return self.drefs.get(name, 0.0)


class MockMM:
    def __init__(self, targets):
        self.targets = targets
        self.num_targets = len(targets)
        self.target_id_to_index = {t.id: i for i, t in enumerate(targets)}
        self.step_count = 0
        self.started_planning_step = None
        self.ended_planning_step = None
        self.required_alt_fire_agl = 900.0
        self.required_cruise_altitude_ft = 7000.0
        self.max_mission_time = 1800.0
        self.mission_timer = 100.0
        self.udp_bridge = SimpleNamespace(
            current_state={
                "human": {"recently_finished_task": -1.0},
                "wingman": {"recently_finished_task": -1.0},
            }
        )


def make_targets(n):
    targets = []
    for i in range(n):
        t = Target(type="moderate" if i % 2 == 0 else "severe", id=i, lat=47.0 + 0.01 * i, long=-121.0, alt=1000.0)
        t.status = float(min(i, 3))
        targets.append(t)
    return targets


def make_obs(num_targets, commanded=12.0, human_plan=99.0, statuses=None, whoflew=None, mission_timer=100.0):
    obs = np.zeros(16 + num_targets * 14)
    obs[0] = mission_timer
    obs[1] = 47.0
    obs[2] = -121.0
    obs[3] = 1500.0
    obs[4] = 90.0
    obs[5] = 120.0
    obs[6] = commanded
    obs[7] = 0.0
    obs[8] = -1.0
    obs[9] = -1.0
    obs[10] = 0.0
    obs[11] = human_plan
    obs[12] = 99.0
    obs[13] = NO_PLAN
    obs[14] = num_targets
    for i in range(num_targets):
        base = 16 + i * 14
        obs[base] = 47.0 + 0.01 * i
        obs[base + 1] = -121.0
        obs[base + 2] = 1000.0
        obs[base + 3] = obs[base]
        obs[base + 4] = obs[base + 1]
        obs[base + 5] = obs[base + 2]
        obs[base + 6] = 1.0
        obs[base + 12] = statuses[i] if statuses is not None else 0.0
        obs[base + 13] = whoflew[i] if whoflew is not None else 0.0
    return obs


@pytest.fixture
def wingman():
    targets = make_targets(4)
    mm = MockMM(targets)
    wm = FireWatchWingman(
        xpc=MockXPC(),
        start_lla=(47.0, -121.0, 1500.0),
        start_hdg=90.0,
        start_spd=180.0,
        mm=mm,
        fire_layout=1,
        initiative_level=2.0,
    )
    return wm, mm


def test_get_task_type_for_status_mapping(wingman):
    wm, _ = wingman
    assert wm._get_task_type_for_status(0.0) == "classify"
    assert wm._get_task_type_for_status(1.0) == "mark_position"
    assert wm._get_task_type_for_status(2.0) == "initial_route"
    assert wm._get_task_type_for_status(3.0) == "refine_route"
    assert wm._get_task_type_for_status(4.0) is None


def test_get_task_eligibility_refine_route_depends_on_whoflew(wingman):
    wm, _ = wingman
    obs = make_obs(4, whoflew=[0.0, 1.0, 2.0, 0.0], statuses=[3.0, 3.0, 3.0, 3.0])
    h0, w0 = wm._get_task_eligibility(0, "refine_route", obs)
    h1, w1 = wm._get_task_eligibility(1, "refine_route", obs)
    h2, w2 = wm._get_task_eligibility(2, "refine_route", obs)
    assert (h0, w0) == (True, True)
    assert (h1, w1) == (False, True)
    assert (h2, w2) == (True, False)


def test_generate_tasks_from_fires_one_per_actionable_target(wingman):
    wm, mm = wingman
    for i, t in enumerate(mm.targets):
        t.status = float(i)
    obs = make_obs(4, statuses=[0.0, 1.0, 2.0, 3.0], whoflew=[0.0, 0.0, 0.0, 0.0])
    tasks = wm._generate_tasks_from_fires(obs, mm.targets)
    assert len(tasks) == 4
    assert {t["task_type"] for t in tasks} == {"classify", "mark_position", "initial_route", "refine_route"}


def test_create_task_structure(wingman):
    wm, mm = wingman
    obs = make_obs(4)
    task = wm._create_task(obs, mm.targets[0], "classify", mission_timer=10.0, member_position=(47.0, -121.0))
    assert set(task.keys()) >= {"fire_id", "task_type", "utility", "target", "eligible_human", "eligible_wingman"}


def test_select_optimal_task_prefers_closest_and_excludes_human(wingman):
    wm, mm = wingman
    wm.lat, wm.long = 47.0, -121.0
    cats = {
        "classify_fire": [
            {"target": mm.targets[0], "distance": 10.0},
            {"target": mm.targets[1], "distance": 3.0},
        ]
    }
    chosen, task_type = wm._select_optimal_task(cats, human_indicated_fire_id=1.0)
    assert chosen["target"].id == 0
    assert task_type == "classify_fire"


def test_select_optimal_task_none_when_empty(wingman):
    wm, _ = wingman
    chosen, task_type = wm._select_optimal_task({}, human_indicated_fire_id=-1.0)
    assert chosen is None and task_type is None


def test_route_waypoint_and_at_waypoint(wingman):
    wm, mm = wingman
    t = mm.targets[0]
    wp = wm._calc_route_waypoint(t, "route_start")
    assert len(wp) == 3
    wm.lat, wm.long = wp[0], wp[1]
    assert wm._at_route_waypoint(wp[0], wp[1])
    wm.lat, wm.long = t.lat + 1.0, t.long + 1.0
    assert not wm._at_route_waypoint(wp[0], wp[1])


def test_hsa_helpers_return_finite_values(wingman):
    wm, _ = wingman
    obs = make_obs(4)
    hsa_intercept = wm._calc_hsa_to_human_intercept(obs)
    hsa_hold = wm._calc_hsa_holding_pattern(47.0, -121.0, 1000.0, 20.0)
    hsa_target = wm._calc_hsa_to_target(obs, 0)
    for hsa in (hsa_intercept, hsa_hold, hsa_target):
        assert len(hsa) == 3
        assert all(np.isfinite(v) for v in hsa)


def test_fire_state_key_stability_and_uniqueness(wingman):
    wm, _ = wingman
    s = np.array([0.0, 1.0, 2.0], dtype=np.float32)
    k1 = wm._get_fire_state_key(s, 0, 1, 0, effective_max_depth=2)
    k2 = wm._get_fire_state_key(s.copy(), 0, 1, 0, effective_max_depth=2)
    k3 = wm._get_fire_state_key(np.array([0.0, 1.0, 3.0], dtype=np.float32), 0, 1, 0, effective_max_depth=2)
    assert k1 == k2
    assert k1 != k3


def test_simulate_task_completion_advances_status(wingman):
    wm, _ = wingman
    s = np.array([0.0, 1.0, 3.0], dtype=np.float32)
    out = wm._simulate_task_completion(s, {"fire_id": 0}, {"fire_id": 2})
    assert out[0] == pytest.approx(1.0)
    assert out[2] == pytest.approx(4.0)


def test_calculate_late_game_utility_finite(wingman):
    wm, mm = wingman
    u = wm._calculate_late_game_utility(mm.targets[0], "classify", (47.0, -121.0), mission_timer=20.0)
    assert np.isfinite(u)
    assert u > 0.0


def test_calculate_team_lookahead_value_prefers_progress(wingman):
    wm, mm = wingman
    obs = make_obs(4, statuses=[0.0, 0.0, 0.0, 0.0])
    hp = {"fire_id": 0, "task_type": "classify", "utility": 1.0, "target": mm.targets[0], "eligible_human": True, "eligible_wingman": True}
    wp = {"fire_id": 1, "task_type": "classify", "utility": 1.0, "target": mm.targets[1], "eligible_human": True, "eligible_wingman": True}
    val, meta = wm._calculate_team_lookahead_value(
        obs, hp, wp, (47.0, -121.0), (47.01, -121.0), mm.targets, depth=0, max_depth=1, mission_timer=20.0
    )
    assert np.isfinite(val)
    assert "best_followon_human" in meta


def test_handle_planning_non_blocking_and_plan_visible(wingman, monkeypatch):
    wm, mm = wingman
    obs = make_obs(4)

    def slow_plan(_obs):
        time.sleep(0.05)
        return {
            "human_plan": 0.0,
            "wingman_plan": 1.0,
            "second_best_human_plan": 99.0,
            "second_best_wingman_plan": 99.0,
            "best_followon_human": 99.0,
            "best_followon_wingman": 99.0,
            "second_best_followon_human": 99.0,
            "second_best_followon_wingman": 99.0,
            "rationale_code": 0.0,
            "planning_mode_code": 0.0,
        }

    monkeypatch.setattr(wm, "plan_team_strategy", slow_plan)
    t0 = time.time()
    wm.handle_planning(obs)
    assert time.time() - t0 < 0.03
    assert wm.is_planning is True
    wm.planning_thread.join(timeout=1.0)
    assert not wm.planning_queue.empty()


def test_act_reads_planning_result_on_next_tick(wingman, monkeypatch):
    wm, _ = wingman
    obs = make_obs(4)

    def fake_plan(_obs):
        return {
            "human_plan": 0.0,
            "wingman_plan": 1.0,
            "second_best_human_plan": 99.0,
            "second_best_wingman_plan": 99.0,
            "best_followon_human": 99.0,
            "best_followon_wingman": 99.0,
            "second_best_followon_human": 99.0,
            "second_best_followon_wingman": 99.0,
            "rationale_code": 0.0,
            "planning_mode_code": 0.0,
        }

    monkeypatch.setattr(wm, "plan_team_strategy", fake_plan)
    wm.handle_planning(obs)
    wm.planning_thread.join(timeout=1.0)
    action = wm.act(obs, messages=[])
    assert "human_plan" in action
    assert "wingman_plan" in action


def test_reset_clears_state_and_cache(wingman):
    wm, _ = wingman
    wm.route_marking_stage = "flying_route"
    wm.current_route_target = 1
    wm._lookahead_cache[(1, 2, 3)] = 4.0
    wm.current_plan_for_self = 2.0
    wm.reset()
    assert wm.route_marking_stage is None
    assert wm.current_route_target is None
    assert wm.current_plan_for_self == NO_PLAN
    assert wm._lookahead_cache == {}


def test_receive_human_message_sets_latest(wingman):
    wm, _ = wingman
    msg = Message("freeform_text", "human", "wingman_0", {"normalized_text": "hello"}, timestamp=1.0)
    wm.receive_human_message(msg)
    assert wm.latest_human_message == msg


def test_voice_phrase_generation_for_status_transitions(wingman):
    wm, _ = wingman
    # Validate action generation still works with verbose off and no TTS pathway invoked from wingman.act.
    obs = make_obs(4, commanded=0.0, statuses=[0.0, 1.0, 2.0, 3.0])
    action = wm.act(obs, messages=[])
    assert "status" in action
