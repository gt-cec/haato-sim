import pytest

from missions.fire import mission_manager as mission_manager_module
from missions.fire.constants import (
    DREF_COMMAND_FROM_HUMAN,
    DREF_FIRE_LAYOUT,
    DREF_HUMAN_IN_RANGE,
    DREF_INITIATIVE_LEVEL,
    DREF_LOG_FILE_IDENTIFIER,
    DREF_PARTICIPANT_ID,
    DREF_RESET_MISSION,
    DREF_START_LOGGING,
    DREF_TARGET_CLASSIFICATION_FMT,
    DREF_TARGET_STATUS_FMT,
    DREF_TARGET_WHOFLEW_INITIAL_FMT,
    PLUGIN_DEFAULT_COMMAND_FROM_HUMAN,
    PLUGIN_DEFAULT_TARGET_CLASSIFICATION,
    PLUGIN_DEFAULT_TARGET_STATUS,
    PLUGIN_DEFAULT_TARGET_WHOFLEW_INITIAL,
)


class FakeVoice:
    def speak(self, text):
        return False


class FakeMessageLogger:
    def __init__(self, *args, **kwargs):
        self.records = []

    def log(self, message):
        self.records.append(message)


class FakeUDPBridge:
    def __init__(self, logger=None):
        self.logger = logger
        self.current_team_plan = None
        self.current_agent_id_request = {"active": False, "target_id": None, "mission_time": 0.0}
        self.current_state = {
            "wingman": {
                "lat": 0.0,
                "lon": 0.0,
                "alt_msl_m": 0.0,
                "status": 99.0,
                "subtask": 0.0,
                "recently_finished_task": -1.0,
                "hdg": 0.0,
                "spd": 0.0,
                "goal_hdg": 0.0,
                "goal_spd": 0.0,
                "goal_alt": 0.0,
            },
            "human": {
                "recently_finished_task": -1.0,
                "indicated_plan": -1.0,
                "recording_route": False,
            },
            "settings": {
                "auto_spot": False,
            },
            "mission_time": 0.0,
            "mission_time_left": 0.0,
            "mission_status": "not complete",
            "sequence_reason": "reset",
        }
        self.current_plan_response = {
            "human_response": -1.0,
            "agent_response": -1.0,
            "selected_variant": "none",
            "source_screen": "",
            "mission_time": 0.0,
        }

    def start(self):
        return None

    def stop(self):
        return None

    def poll_events(self):
        return []

    def send_agent_requests_id(self, payload):
        self.current_agent_id_request = payload

    def send_shared_mission_state(self, payload):
        if "sequence_reason" in payload:
            self.current_state["sequence_reason"] = payload["sequence_reason"]

    def send_team_plan_suggestion(self, payload):
        self.current_team_plan = payload


class FakeWingman:
    def __init__(self, xpc, start_lla, start_hdg, start_spd, mm, fire_layout, initiative_level=1.0):
        self.xpc = xpc
        self.mm = mm
        self.lat = start_lla[0]
        self.long = start_lla[1]
        self.alt = start_lla[2]
        self.hdg = start_hdg
        self.spd = start_spd
        self.current_plan_for_self = 99.0

    def reset(self):
        return None


class FakeXPC:
    def __init__(self):
        self.sim_mode = None
        self.current_dref_values = {}
        self.drefs = {}
        self.sent_drefs = []
        self.commands = []
        self.subscriptions = []
        self.posi_calls = []

    def subscribeDREFs(self, drefs):
        self.subscriptions.append(drefs)
        for dref_path, _freq in drefs:
            self.current_dref_values[dref_path] = {"value": self.drefs.get(dref_path, 0.0), "timestamp": None}

    def sendDREF(self, dref, value):
        self.sent_drefs.append((dref, value))
        self.drefs[dref] = value
        if dref in self.current_dref_values:
            self.current_dref_values[dref]["value"] = value

    def getDREF(self, dref):
        return self.drefs.get(dref, 0.0)

    def sendCMND(self, command):
        self.commands.append(command)

    def sendPOSI(self, lat, lon, elev, phi, theta, psi_true):
        self.posi_calls.append((lat, lon, elev, phi, theta, psi_true))


@pytest.fixture
def fire_mm(monkeypatch):
    monkeypatch.setattr(mission_manager_module, "HaatoUDPBridge", FakeUDPBridge)
    monkeypatch.setattr(mission_manager_module, "PiperTTSVoice", FakeVoice)
    monkeypatch.setattr(mission_manager_module, "MessageLogger", FakeMessageLogger)
    monkeypatch.setattr(mission_manager_module, "FireWatchWingman", FakeWingman)

    xpc = FakeXPC()
    mm = mission_manager_module.FireWatchMM(
        user_id=17,
        xpc=xpc,
        fire_layout=1,
        initiative_level=2.0,
        log_file_identifier=31415.0,
        noreset=False,
    )
    return mm


def test_reset_avoids_flywithlua_reload_and_keeps_reset_to_runway(fire_mm):
    fire_mm.reset()

    assert "sim/operation/reset_to_runway" in fire_mm.xpc.commands
    assert "FlyWithLua/debugging/reload_scripts" not in fire_mm.xpc.commands


def test_reset_writes_plugin_defaults_before_mission_ready_overrides(fire_mm):
    fire_mm.reset()

    command_writes = [value for dref, value in fire_mm.xpc.sent_drefs if dref == DREF_COMMAND_FROM_HUMAN]
    assert PLUGIN_DEFAULT_COMMAND_FROM_HUMAN in command_writes
    assert command_writes[-1] == 12.0

    target_id = fire_mm.targets[0].id
    whoflew_writes = [
        value
        for dref, value in fire_mm.xpc.sent_drefs
        if dref == DREF_TARGET_WHOFLEW_INITIAL_FMT.format(target_id=target_id)
    ]
    assert PLUGIN_DEFAULT_TARGET_WHOFLEW_INITIAL in whoflew_writes
    assert fire_mm.xpc.drefs[DREF_TARGET_WHOFLEW_INITIAL_FMT.format(target_id=target_id)] == (
        PLUGIN_DEFAULT_TARGET_WHOFLEW_INITIAL
    )


def test_reset_applies_expected_mission_ready_values(fire_mm):
    fire_mm.reset()

    assert fire_mm.xpc.drefs[DREF_PARTICIPANT_ID] == 17.0
    assert fire_mm.xpc.drefs[DREF_INITIATIVE_LEVEL] == 2.0
    assert fire_mm.xpc.drefs[DREF_FIRE_LAYOUT] == 1.0
    assert fire_mm.xpc.drefs[DREF_LOG_FILE_IDENTIFIER] == 31415.0
    assert fire_mm.xpc.drefs[DREF_RESET_MISSION] == 1.0
    assert fire_mm.xpc.drefs[DREF_START_LOGGING] == 1.0
    assert fire_mm.xpc.drefs[DREF_COMMAND_FROM_HUMAN] == 12.0
    assert fire_mm.xpc.drefs[DREF_HUMAN_IN_RANGE] == 99.0


def test_reset_restores_all_target_default_values(fire_mm):
    fire_mm.reset()

    for target in fire_mm.targets:
        status_dref = DREF_TARGET_STATUS_FMT.format(target_id=target.id)
        classification_dref = DREF_TARGET_CLASSIFICATION_FMT.format(target_id=target.id)
        whoflew_dref = DREF_TARGET_WHOFLEW_INITIAL_FMT.format(target_id=target.id)

        assert fire_mm.xpc.drefs[status_dref] == PLUGIN_DEFAULT_TARGET_STATUS
        assert fire_mm.xpc.drefs[classification_dref] == PLUGIN_DEFAULT_TARGET_CLASSIFICATION
        assert fire_mm.xpc.drefs[whoflew_dref] == PLUGIN_DEFAULT_TARGET_WHOFLEW_INITIAL
