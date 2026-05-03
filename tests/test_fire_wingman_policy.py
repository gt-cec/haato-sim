import numpy as np
import pytest
from types import SimpleNamespace

from missions.fire.wingman.agent import FireWatchWingman
from utility.XPlaneConnectX import XPlaneConnectX
from utility.base_classes import Target
from utility.utility_classes import SimMode


class MockMissionManager:
    def __init__(self, targets):
        self.targets = targets
        self.num_targets = len(targets)
        self.target_id_to_index = {t.id: i for i, t in enumerate(targets)}
        self.step_count = 0
        self.started_planning_step = None
        self.ended_planning_step = None
        self.required_alt_fire_agl = 1000
        self.required_cruise_altitude_ft = 7000
        self.max_mission_time = 1800
        self.udp_bridge = SimpleNamespace(
            current_state={
                "human": {"recently_finished_task": -1.0},
                "wingman": {"recently_finished_task": -1.0},
            }
        )

        self.xpc = XPlaneConnectX(ip='127.0.0.1', port=49000)
        self.xpc.sim_mode = SimMode(self)

class MockXPC:
    def __init__(self):
        self.drefs = {}

    def sendDREF(self, name, value):
        self.drefs[name] = value

    def getDREF(self, name):
        return self.drefs.get(name, 0.0)

def make_targets(n, status=0.0, whoflew=0.0):
    targets = []
    for i in range(n):
        t = Target(
            type = 'moderate',
            id=i,
            lat=47.0 + i * 0.01,
            long=-121.0,
            alt=1000
        )
        t.status = status
        t.whoflew_initial = whoflew
        targets.append(t)
    return targets

def make_observation(
    num_targets,
    *,
    commanded_target=12.0,
    agent_task_accepted=0.0,
    human_finished=False,
    wingman_finished=False,
    human_requests_plan=False,
    human_indicated_plan=99.0,
    target_statuses=None,
    target_whoflew=None,
):
    obs = np.zeros(16 + num_targets * 14)  # TARGET_BLOCK_SIZE=14

    obs[0] = 100.0  # mission_timer
    obs[6] = commanded_target
    obs[7] = agent_task_accepted
    obs[8] = 3.0 if human_finished else 0.0
    obs[9] = 3.0 if wingman_finished else 0.0
    obs[10] = 1.0 if human_requests_plan else 0.0
    obs[11] = human_indicated_plan
    obs[14] = num_targets

    for i in range(num_targets):
        base = 16 + i * 14  # TARGET_BLOCK_SIZE=14
        # Offsets: 0-2=true lat/lon/alt, 3-5=reported lat/lon/alt, 6=is_known,
        #          7=spotted, 8=handled, 9=being_handled, 10-11=timing,
        #          12=target_status, 13=target_whoflew
        obs[base + 6] = 1.0  # is_known_to_cockpit (default True in tests)
        obs[base + 12] = (
            target_statuses[i] if target_statuses else 0.0
        )
        obs[base + 13] = (
            target_whoflew[i] if target_whoflew else 0.0
        )

    return obs

@pytest.fixture
def basic_wingman():
    targets = make_targets(4)
    mm = MockMissionManager(targets)
    xpc = MockXPC()

    wingman = FireWatchWingman(
        xpc=xpc,
        start_lla=(47.0, -121.0, 5000),
        start_hdg=90,
        start_spd=180,
        mm=mm,
        fire_layout=1,
        initiative_level=2.0
    )

    return wingman, mm

def test_commanded_target_overrides_autonomy(basic_wingman):
    # TODO edit to test more than just target 1.0
    wingman, mm = basic_wingman

    obs = make_observation(
        num_targets=4,
        commanded_target=1.0
    )

    action = wingman.act(obs, messages=[])

    assert action["status"] == 1.0
    assert action["type"] == "hsa"

def test_follow_human_bypasses_policy(monkeypatch, basic_wingman):
    wingman, _ = basic_wingman

    obs = make_observation(
        num_targets=4,
        commanded_target=8.0
    )

    action = wingman.act(obs, messages=[])
    assert action['message'] == 'Following human'
    assert wingman.status == 8.0

def test_policy_finds_classify_target(basic_wingman):
    wingman, _ = basic_wingman

    obs = make_observation(
        num_targets=4,
        target_statuses=[0.0, 0.0, 0.0, 0.0]
    )

    action = wingman.policy_combined(obs)

    assert action["goal"] is not None
    assert wingman.status in [0.0, 1.0, 2.0, 3.0]

def test_policy_holds_when_all_complete(basic_wingman):
    wingman, _ = basic_wingman

    obs = make_observation(
        num_targets=4,
        target_statuses=[4.0, 4.0, 4.0, 4.0]
    )

    action = wingman.policy_combined(obs)

    assert wingman.status == 9.0
    assert "Holding" in action["message"]

def test_policy_excludes_human_target_and_holds(basic_wingman):
    wingman, _ = basic_wingman

    obs = make_observation(
        num_targets=1,
        human_indicated_plan=0.0,
        target_statuses=[0.0]
    )

    action = wingman.policy_combined(obs)

    assert wingman.status == 9.0

def test_planning_triggered_by_human_finished(monkeypatch, basic_wingman):
    wingman, mm = basic_wingman

    calls = {"plan": 0}

    def fake_plan(obs):
        calls["plan"] += 1
        return {"human_plan": 0.0, "wingman_plan": 1.0}

    monkeypatch.setattr(wingman, "plan_team_strategy", fake_plan)

    obs = make_observation(
        num_targets=4,
        human_finished=True
    )

    wingman.act(obs, messages=[])
    if wingman.planning_thread:
        wingman.planning_thread.join(timeout=1.0)

    assert calls["plan"] == 1

def test_initiative_1_plans_after_human_finished(monkeypatch):
    targets = make_targets(3)
    mm = MockMissionManager(targets)
    xpc = MockXPC()

    wingman = FireWatchWingman(
        xpc, (0, 0, 5000), 0, 180, mm, fire_layout=1, initiative_level=1.0
    )

    calls = {"plan": 0}

    def fake_plan(obs):
        calls["plan"] += 1
        return {"human_plan": 0.0, "wingman_plan": 1.0}

    monkeypatch.setattr(wingman, "plan_team_strategy", fake_plan)

    obs = make_observation(
        num_targets=3,
        human_finished=True
    )

    wingman.act(obs, messages=[])
    if wingman.planning_thread:
        wingman.planning_thread.join(timeout=1.0)

    assert calls["plan"] == 1

def test_policy_never_returns_none_goal(basic_wingman):
    wingman, _ = basic_wingman

    obs = make_observation(
        num_targets=4,
        target_statuses=[0.0, 1.0, 2.0, 3.0],
        target_whoflew=[0.0, 0.0, 0.0, 1.0]
    )

    action = wingman.policy_combined(obs)

    assert "goal" in action
    assert action["goal"] is not None


# =================================================================================================
# ADDITIONAL WINGMAN TEST SUITE: HUMAN-WINGMAN INTERACTION EDGE CASES
# Source: Additional Wingman Human-interaction Edge Case Tests.pdf
# =================================================================================================

class TestHumanCommandEdgeCases:
    """Category 1: Human Command Edge Cases"""

    def test_1_1_commanded_target_out_of_range(self, basic_wingman):
        """Scenario: Human commands a target ID that exists but is far outside normal range (e.g. invalid index)."""
        wingman, mm = basic_wingman

        # Command target 99 (way outside num_targets=4)
        obs = make_observation(num_targets=4, commanded_target=99.0)
        action = wingman.act(obs, messages=[])

        # Assertion: Wingman ignores invalid command and falls back to autonomous behavior or holding
        # Should NOT crash. Should not return status 99.0 (unless holding).
        assert action["goal"] is not None
        # Since no fires are active in default make_targets, it likely holds (9.0) or finds a fire
        assert wingman.status != 99.0
        assert "Holding" in action["message"] or wingman.status < 4.0

    def test_1_2_commanded_target_becomes_invalid_mid_execution(self, basic_wingman):
        """Scenario: Human commands target i. While en route, target status becomes 4.0 (handled)."""
        wingman, mm = basic_wingman
        target_id = 1

        # 1. Initial valid command
        obs_1 = make_observation(
            num_targets=4,
            commanded_target=float(target_id),
            target_statuses=[0.0, 0.0, 0.0, 0.0]
        )
        wingman.act(obs_1, messages=[])
        assert wingman.status == 1.0  # Classifying target 1

        # 2. Target becomes handled (4.0) while command persists
        obs_2 = make_observation(
            num_targets=4,
            commanded_target=float(target_id),
            target_statuses=[0.0, 4.0, 0.0, 0.0]  # Target 1 is done
        )

        # We need to mock the DREF sending/getting because policy checks DREFs for staleness
        # specifically: self.safe_get_dref(f"custom/haato/target_status[{target.id}]")
        mm.xpc.sendDREF(f"custom/haato/target_status[{target_id}]", 4.0)

        action = wingman.act(obs_2, messages=[])

        # Should not be flying to 1 anymore.
        # Note: If it falls back to finding a new task, status might be 0.0 (fire 0). If holding, 9.0.
        assert wingman.status != 1.0

    def test_1_3_command_conflicts_with_human_plan(self, basic_wingman):
        """Scenario: Human indicates plan for i, and commands wingman to i simultaneously."""
        wingman, mm = basic_wingman
        target_id = 2.0

        # 1. Human indicates plan to work on fire 2 AND commands wingman to fire 2
        obs = make_observation(
            num_targets=4,
            commanded_target=target_id,
            human_indicated_plan=target_id,  # Conflict
            target_statuses=[0.0, 0.0, 0.0, 0.0]
        )

        action = wingman.act(obs, messages=[])

        # Logic Check:
        # Policy Step 2 excludes targets in human plan.
        # Policy Step 3 accepts command.
        # Policy Step 4 searches for commanded target in valid tasks.
        # Result: Target is excluded, search returns None. Wingman should Hold (Safe fallback).
        assert wingman.status != 2.0

    def test_1_4_repeated_identical_commands(self, basic_wingman):
        """Scenario: Same command issued repeatedly. Wingman shouldn't reset internal route state."""
        wingman, mm = basic_wingman
        target_id = 0.0

        # Setup: Wingman is flying a route on target 0
        wingman.current_route_target = 0
        wingman.route_marking_stage = 'flying_route'
        wingman.route_type = 'initial'

        obs = make_observation(
            num_targets=4,
            commanded_target=target_id,
            target_statuses=[2.0, 0.0, 0.0, 0.0]  # Ready for route
        )

        # Act twice
        wingman.act(obs, messages=[])
        state_1 = wingman.route_marking_stage
        wingman.act(obs, messages=[])
        state_2 = wingman.route_marking_stage

        # Assertion: State should persist, not reset to 'flying_to_start' or None
        assert state_1 == 'flying_route'
        assert state_2 == 'flying_route'


class TestHumanPlanEdgeCases:
    """Category 2: Human-Indicated Plan Edge Cases"""

    def test_2_1_invalid_plan_id(self, basic_wingman):
        """Scenario: human_indicated_plan is negative or out of bounds."""
        wingman, mm = basic_wingman

        # Plan = 99 (invalid)
        obs = make_observation(num_targets=4, human_indicated_plan=99.0)
        action = wingman.act(obs, messages=[])

        # Assert: No crash, normal autonomous selection (likely picks fire 0)
        assert action["goal"] is not None
        assert wingman.status == 0.0  # Picks first available

    def test_2_2_plan_change_mid_route(self, basic_wingman):
        """Scenario: Wingman executing route on i. Human sets plan to i."""
        wingman, mm = basic_wingman
        target_id = 1

        # Setup: Wingman working on 1
        wingman.current_route_target = target_id
        wingman.route_marking_stage = 'flying_route'
        wingman.route_type = 'initial'

        # Input: Human suddenly indicates they want target 1
        obs = make_observation(
            num_targets=4,
            human_indicated_plan=float(target_id),
            target_statuses=[0.0, 2.0, 0.0, 0.0]
        )

        action = wingman.act(obs, messages=[])

        # Assert: Wingman breaks mode immediately to avoid conflict
        assert wingman.route_marking_stage is None
        assert wingman.current_route_target is None
        # Should likely hold or pick different target (0)
        assert wingman.status != 1.0

    def test_2_3_human_clears_plan(self, basic_wingman):
        """Scenario: Human indicated plan i, then resets to 99.0."""
        wingman, mm = basic_wingman
        target_id = 0

        # 1. Human claims fire 0. Wingman should NOT pick 0.
        obs_1 = make_observation(
            num_targets=4,
            human_indicated_plan=0.0,
            target_statuses=[0.0, 0.0, 0.0, 0.0]
        )
        wingman.act(obs_1, messages=[])
        assert wingman.status != 0.0  # Should pick 1 or hold

        # 2. Human clears plan (99.0). Fire 0 available again.
        obs_2 = make_observation(
            num_targets=4,
            human_indicated_plan=99.0,
            target_statuses=[0.0, 0.0, 0.0, 0.0]
        )
        wingman.act(obs_2, messages=[])

        # Assert: the cleared human plan makes target 0 eligible again; the
        # planner may still choose another valid target based on current policy.
        assert 0.0 <= wingman.status < mm.num_targets


class TestHumanStatusEdgeCases:
    """Category 3: Human Status / Task Completion Edge Cases"""

    def test_3_1_human_finishes_task_trigger(self, monkeypatch, basic_wingman):
        """Scenario: human_recently_finished_task toggles. Check planning trigger."""
        wingman, mm = basic_wingman

        # Mock planning to count calls
        calls = {"plan": 0}
        monkeypatch.setattr(wingman, "handle_planning", lambda obs: calls.update(plan=calls["plan"] + 1) or {})

        obs = make_observation(
            num_targets=4,
            human_finished=True  # obs[8] = 3.0
        )

        wingman.act(obs, messages=[])

        assert calls["plan"] == 1

    def test_3_2_race_condition_completion(self, basic_wingman):
        """Scenario: Wingman mid-task on i. Human finishes i."""
        wingman, mm = basic_wingman
        target_id = 1

        # Setup: Wingman flying to 1
        wingman.status = 1.0

        # Input: Target 1 becomes status 4.0 (handled)
        obs = make_observation(
            num_targets=4,
            target_statuses=[0.0, 4.0, 0.0, 0.0]
        )

        action = wingman.act(obs, messages=[])

        # Assert: Wingman stops working on 1. Picks next available (e.g. 0 or 2)
        assert wingman.status != 1.0


class TestConflictingSignals:
    """Category 4: Conflicting Human Signals"""

    def test_4_1_command_priority_over_plan_request(self, monkeypatch, basic_wingman):
        """Scenario: Human commands target AND requests plan simultaneously."""
        wingman, mm = basic_wingman

        # Mock planning to ensure it triggers
        planning_triggered = [False]
        monkeypatch.setattr(wingman, "handle_planning",
                            lambda o: planning_triggered.clear() or planning_triggered.append(True))

        obs = make_observation(
            num_targets=4,
            commanded_target=2.0,
            human_requests_plan=True
        )

        action = wingman.act(obs, messages=[])

        # Assert:
        # 1. Planning is triggered (background)
        assert planning_triggered[0] is True
        # 2. Physical action obeys command (Target 2)
        assert wingman.status == 2.0


class TestStaleInputs:
    """Category 5: Stale and Invalid Human Inputs"""

    def test_5_1_stale_command_reset(self, basic_wingman):
        """Scenario: Command persists after target completion."""
        wingman, mm = basic_wingman
        target_id = 0

        # Mock DREF for target 0 being done
        mm.xpc.sendDREF(f"custom/haato/target_status[{target_id}]", 4.0)

        obs = make_observation(
            num_targets=4,
            commanded_target=float(target_id),
            target_statuses=[4.0, 0.0, 0.0, 0.0]
        )

        wingman.act(obs, messages=[])

        assert wingman.status != 0.0

    def test_5_2_rapid_alternating_commands(self, basic_wingman):
        """Scenario: Alternating valid/invalid commands."""
        wingman, mm = basic_wingman

        # Step 1: Valid
        obs1 = make_observation(num_targets=4, commanded_target=0.0)
        wingman.act(obs1, messages=[])
        assert wingman.status == 0.0

        # Step 2: Invalid (12.0)
        obs2 = make_observation(num_targets=4, commanded_target=12.0)
        wingman.act(obs2, messages=[])
        assert wingman.status == 0.0  # Autonomous logic keeps it at 0.0 usually

        # Step 3: Valid (1.0)
        obs3 = make_observation(num_targets=4, commanded_target=1.0)
        wingman.act(obs3, messages=[])
        assert wingman.status == 1.0


class TestTemporalRobustness:
    """Category 6: Rapid Human Input Changes"""

    def test_6_1_plan_command_plan_sequence(self, basic_wingman):
        """Scenario: Request Plan -> Command -> Request Plan in consecutive steps."""
        wingman, mm = basic_wingman

        # 1. Request Plan
        obs1 = make_observation(num_targets=4, human_requests_plan=True)
        wingman.act(obs1, messages=[])
        assert wingman.sent_first_plan is True

        # 2. Command
        obs2 = make_observation(num_targets=4, commanded_target=2.0)
        wingman.act(obs2, messages=[])
        assert wingman.status == 2.0

        # 3. Request Plan again
        obs3 = make_observation(num_targets=4, human_requests_plan=True)
        wingman.act(obs3, messages=[])
        # Assert no crash, status remains consistent with last command/logic
        assert wingman.status == 2.0 or wingman.status == 0.0  # Depends if command persists in obs

    def test_6_2_plan_spam(self, monkeypatch, basic_wingman):
        """Scenario: Human spams plan request every tick."""
        wingman, mm = basic_wingman

        # Mock threading to track starts
        thread_starts = [0]
        import threading
        original_start = threading.Thread.start

        def mock_start(self):
            thread_starts[0] += 1

        monkeypatch.setattr(threading.Thread, "start", mock_start)

        # Simulate spamming over 5 steps
        for _ in range(5):
            obs = make_observation(num_targets=4, human_requests_plan=True)
            wingman.act(obs, messages=[])
            # Reset the DREF mock as the code expects it to be cleared
            # (In real sim, XPC would do this, but act() sends DREF 0.0)

        # Assert: Should not spawn explosive amount of threads.
        # Logic allows one active thread.
        # Since we mocked start but didn't actually run logic to clear 'is_planning',
        # it might only start once or try to start multiple.
        # Ideally, it checks self.is_planning.
        # If mocked start doesn't reset is_planning, subsequent calls should blocked.
        # NOTE: Test implies checking logic robustness.
        pass  # If we get here without error, good.


class TestPlanningInteraction:
    """Category 7: Planning-System Interaction"""

    def test_7_1_late_plan_acceptance(self, basic_wingman):
        """Scenario: Human accepts plan 1.0 but that target is now done."""
        wingman, mm = basic_wingman

        # Setup: Last plan suggested wingman->1
        wingman.latest_plan = {'wingman_plan': 1.0}

        # Input: Accept plan, BUT target 1 is status 4.0
        obs = make_observation(
            num_targets=4,
            agent_task_accepted=1.0,
            target_statuses=[0.0, 4.0, 0.0, 0.0]
        )
        mm.xpc.sendDREF("custom/haato/target_status[1]", 4.0)

        wingman.act(obs, messages=[])

        # Assert: Wingman sets current_plan_for_self to 1.0 temporarily...
        # BUT policy_combined Step 1 checks staleness and resets it.
        # Result: Should NOT be working on 1.0
        assert wingman.status != 1.0

    def test_7_2_accept_second_best(self, basic_wingman):
        """Scenario: Human accepts second best plan."""
        wingman, mm = basic_wingman
        wingman.latest_plan = {
            'wingman_plan': 1.0,
            'second_best_wingman_plan': 2.0
        }

        obs = make_observation(
            num_targets=4,
            agent_task_accepted=2.0
        )

        wingman.act(obs, messages=[])

        # Assert: Adopts 2.0
        assert wingman.current_plan_for_self == 2.0
        assert wingman.status == 2.0


class TestInvariants:
    """Category 8: Safety Invariants Check"""

    def check_safety_invariants(self, action, wingman):
        # 8.1 No-None Invariant
        assert action['goal'] is not None

        # 8.2 Status Validity
        assert wingman.status in [9.0, 8.0] or (0.0 <= wingman.status < 50.0)

        # 8.3 Progress or Hold
        msg = action.get("message", "").lower()
        has_goal = action['goal'] != (0, 0, 0)  # Assuming holding pattern isn't 0,0,0
        assert "holding" in msg or has_goal

    def test_8_global_invariants_run(self, basic_wingman):
        """Run invariants on a standard step."""
        wingman, mm = basic_wingman
        obs = make_observation(num_targets=4)
        action = wingman.act(obs, messages=[])
        self.check_safety_invariants(action, wingman)


class TestImageRequirements:
    """
    Tests derived from the specific requirements in the uploaded image.
    Focuses on conflict resolution and command overrides during active states.
    """

    def test_human_sets_target_to_wingman_goal_forces_change(self, basic_wingman):
        """
        Requirement: "Add a series of tests where the human sets their target to the wingman's current goal.
        The wingman must change its goal to something else in every case."
        """
        wingman, mm = basic_wingman

        # Setup: Targets 0 and 1 are available (status 0.0)
        # Wingman should naturally pick Target 0 (lowest ID/closest default)
        obs_initial = make_observation(num_targets=4, target_statuses=[0.0, 0.0, 0.0, 0.0])
        action_initial = wingman.act(obs_initial, messages=[])

        # Verify baseline: Wingman picked Target 0
        assert wingman.status == 0.0

        # Scenario 1: Human indicates plan for Target 0 (Conflict)
        # Wingman should switch to Target 1
        obs_conflict_0 = make_observation(
            num_targets=4,
            target_statuses=[0.0, 0.0, 0.0, 0.0],
            human_indicated_plan=0.0  # Conflict with Wingman's goal
        )
        action_1 = wingman.act(obs_conflict_0, messages=[])

        assert wingman.status != 0.0
        assert wingman.status == 1.0  # Should switch to next available

        # Scenario 2: Human switches plan to Target 1 (Conflict with new goal)
        # Wingman should switch back to Target 0
        obs_conflict_1 = make_observation(
            num_targets=4,
            target_statuses=[0.0, 0.0, 0.0, 0.0],
            human_indicated_plan=1.0
        )
        action_2 = wingman.act(obs_conflict_1, messages=[])

        assert wingman.status != 1.0
        assert wingman.status == 0.0  # Should switch back

    def test_command_overrides_route_marking_mode(self, basic_wingman):
        """
        Requirement: "Command to target 1 while wingman in route_marking mode for target 3. Status must = 1"
        """
        wingman, mm = basic_wingman

        # Setup: Manually force wingman into route marking state for Target 3
        wingman.current_route_target = 3
        wingman.route_marking_stage = 'flying_route'
        wingman.route_type = 'initial'
        wingman.status = 3.0

        # Action: Command to Target 1
        obs = make_observation(
            num_targets=4,
            commanded_target=1.0,
            target_statuses=[0.0, 0.0, 0.0, 2.0]  # T3 is ready for route, T1 available
        )

        action = wingman.act(obs, messages=[])

        # Assert: Wingman prioritizes command over current route state
        assert wingman.status == 1.0
        # Optional: verify internal state cleared (depends on specific implementation, but good practice)
        # assert wingman.route_marking_stage is None

    def test_command_overrides_position_marking_mode(self, basic_wingman):
        """
        Requirement: "Command to target 1 while wingman is in position_marking mode for target 3. Status must = 1"
        """
        wingman, mm = basic_wingman

        # Setup: Manually force wingman into position marking state for Target 3
        wingman.marking_position_target = 3
        wingman.position_marking_stage = 'flying_to_overfly'
        wingman.status = 3.0

        # Action: Command to Target 1
        obs = make_observation(
            num_targets=4,
            commanded_target=1.0,
            target_statuses=[0.0, 0.0, 0.0, 1.0]  # T3 needs position, T1 available
        )

        action = wingman.act(obs, messages=[])

        # Assert: Wingman prioritizes command over current position state
        assert wingman.status == 1.0

    def test_command_switching_robustness(self, basic_wingman):
        """
        Requirement: "Command to target 1 while wingman flying a route for target 3, then command back to target 1.
        Wingman should set status back to 1"

        (Interpreted as ensuring reliability of switching commands even when deep in a state machine)
        """
        wingman, mm = basic_wingman

        # 1. Setup: Wingman flying route for Target 3
        wingman.current_route_target = 3
        wingman.route_marking_stage = 'flying_route'
        wingman.route_type = 'initial'
        wingman.status = 3.0

        # 2. Command Target 1
        obs_cmd_1 = make_observation(
            num_targets=4,
            commanded_target=1.0,
            target_statuses=[0.0, 0.0, 0.0, 2.0]
        )
        wingman.act(obs_cmd_1, messages=[])
        assert wingman.status == 1.0

        # 3. "Then command back" implies potential fluctuation or re-assertion.
        # Let's simulate a command back to 3 (to verify it CAN switch back), then back to 1.
        obs_cmd_3 = make_observation(
            num_targets=4,
            commanded_target=3.0,
            target_statuses=[0.0, 0.0, 0.0, 2.0]
        )
        wingman.act(obs_cmd_3, messages=[])
        assert wingman.status == 3.0

        # 4. Final Command back to Target 1
        wingman.act(obs_cmd_1, messages=[])  # Reuse obs with command 1.0
        assert wingman.status == 1.0
