import numpy as np
import pytest

from missions.fire import mission_manager as mission_manager_module
from utility.message_queue import Message


class FakeVoice:
    def speak(self, text):
        return False

    def close(self):
        return None


class FakeMessageLogger:
    def __init__(self, *args, **kwargs):
        self.records = []

    def log(self, message):
        self.records.append(message)


class FakeUDPBridge:
    def __init__(self, logger=None):
        self.logger = logger
        self.current_agent_id_request = {"active": False, "target_id": None, "mission_time": 0.0}
        self.current_id_response = {"response": 0.0}
        self.sent_shared = []
        self.current_state = {
            "wingman": {"status": 99.0, "subtask": 0.0, "recently_finished_task": -1.0},
            "human": {"recently_finished_task": -1.0, "indicated_plan": -1.0, "recording_route": False},
            "settings": {"auto_spot": False},
        }
        self.current_plan_response = {"agent_response": -1.0}

    def start(self):
        return None

    def send_agent_requests_id(self, payload):
        self.current_agent_id_request = payload

    def send_shared_mission_state(self, payload):
        self.sent_shared.append(payload)


class FakeMessageBridge:
    def __init__(self, mm):
        self.mm = mm
        self.spawned = []

    def reset_shared_state(self):
        return None

    def send_mission_init(self):
        return None

    def send_fire_spawn_event(self, target):
        self.spawned.append(target.id)

    def send_fire_discovered(self, target):
        return None

    def poll_human_messages(self):
        return None

    def send_shared_state(self, reason):
        return None

    def publish_messages_to_datarefs(self):
        return None


class FakeDrefIO:
    def __init__(self, mm):
        self.mm = mm
        self.initialized_single = []

    def reset_plugin_managed_datarefs(self):
        return None

    def set_mission_config(self):
        return None

    def set_weather_conditions(self, speed, direction, visibility):
        return None

    def set_human_lla(self, lla):
        return None

    def set_human_airspeed(self, speed):
        return None

    def reset_human_command(self):
        return None

    def initialize_target_datarefs(self):
        return None

    def initialize_single_target_dataref(self, target):
        self.initialized_single.append(target.id)


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


class FakeSimMode:
    def __init__(self):
        self.dref_dict = {}


class FakeXPC:
    def __init__(self):
        self.sim_mode = None
        self.current_dref_values = {"sim/flightmodel/position/true_psi": {"value": 90.0}}
        self.drefs = {}
        self.sent_drefs = []
        self.posi_calls = []
        self.subscriptions = []

    def subscribeDREFs(self, drefs):
        self.subscriptions.append(drefs)

    def sendDREF(self, dref, value):
        self.sent_drefs.append((dref, value))
        self.drefs[dref] = value

    def getDREF(self, dref):
        return self.drefs.get(dref, 0.0)

    def sendCMND(self, command):
        return None

    def sendPOSI(self, lat, lon, elev, phi, theta, psi_true):
        self.posi_calls.append((lat, lon, elev, phi, theta, psi_true))


@pytest.fixture
def fire_mm(monkeypatch):
    monkeypatch.setattr(mission_manager_module, "HaatoUDPBridge", FakeUDPBridge)
    monkeypatch.setattr(mission_manager_module, "PiperTTSVoice", FakeVoice)
    monkeypatch.setattr(mission_manager_module, "MessageLogger", FakeMessageLogger)
    monkeypatch.setattr(mission_manager_module, "FireMissionDrefIO", FakeDrefIO)
    monkeypatch.setattr(mission_manager_module, "FireMessageBridge", FakeMessageBridge)
    monkeypatch.setattr(mission_manager_module, "FireWatchWingman", FakeWingman)
    xpc = FakeXPC()
    mm = mission_manager_module.FireWatchMM(
        user_id=99,
        xpc=xpc,
        fire_layout=1,
        initiative_level=2.0,
        log_file_identifier=1.0,
        noreset=True,
    )
    mm.reset()
    return mm


def test_reset_layouts_have_distinct_target_configs(monkeypatch):
    monkeypatch.setattr(mission_manager_module, "HaatoUDPBridge", FakeUDPBridge)
    monkeypatch.setattr(mission_manager_module, "PiperTTSVoice", FakeVoice)
    monkeypatch.setattr(mission_manager_module, "MessageLogger", FakeMessageLogger)
    monkeypatch.setattr(mission_manager_module, "FireMissionDrefIO", FakeDrefIO)
    monkeypatch.setattr(mission_manager_module, "FireMessageBridge", FakeMessageBridge)
    monkeypatch.setattr(mission_manager_module, "FireWatchWingman", FakeWingman)
    fingerprints = []
    for layout in [1, 2, 3, 4, 5]:
        mm = mission_manager_module.FireWatchMM(
            user_id=99,
            xpc=FakeXPC(),
            fire_layout=layout,
            initiative_level=1.0,
            log_file_identifier=1.0,
            noreset=True,
        )
        fingerprints.append((layout, len(mm.targets), tuple((t.lat, t.long) for t in mm.targets[:2])))
    assert len(set(fingerprints)) == len(fingerprints)


def test_setup_sim_mode_writes_human_position_to_sim_drefs(fire_mm):
    fire_mm.xpc.sim_mode = FakeSimMode()
    fire_mm.human_lla = (47.1, -121.2, 1234.0)
    fire_mm.setup_sim_mode()
    assert fire_mm.xpc.sim_mode.dref_dict["sim/flightmodel/position/latitude"] == pytest.approx(47.1)
    assert fire_mm.xpc.sim_mode.dref_dict["sim/flightmodel/position/longitude"] == pytest.approx(-121.2)
    assert fire_mm.xpc.sim_mode.dref_dict["sim/flightmodel/position/elevation"] == pytest.approx(1234.0)


def test_load_mission_config_invalid_layout_raises(monkeypatch):
    monkeypatch.setattr(mission_manager_module, "load_fire_mission_config", lambda *args, **kwargs: (_ for _ in ()).throw(KeyError("bad layout")))
    monkeypatch.setattr(mission_manager_module, "HaatoUDPBridge", FakeUDPBridge)
    monkeypatch.setattr(mission_manager_module, "PiperTTSVoice", FakeVoice)
    monkeypatch.setattr(mission_manager_module, "MessageLogger", FakeMessageLogger)
    monkeypatch.setattr(mission_manager_module, "FireMissionDrefIO", FakeDrefIO)
    monkeypatch.setattr(mission_manager_module, "FireMessageBridge", FakeMessageBridge)
    monkeypatch.setattr(mission_manager_module, "FireWatchWingman", FakeWingman)
    with pytest.raises(KeyError):
        mission_manager_module.FireWatchMM(
            user_id=99, xpc=FakeXPC(), fire_layout=99, initiative_level=1.0, log_file_identifier=1.0, noreset=True
        )


def test_wingman_classify_targets_threshold_and_status_gate(fire_mm):
    t0 = fire_mm.targets[0]
    fire_mm.num_targets = 1
    fire_mm.targets = [t0]
    fire_mm._init_vectorized_arrays()
    fire_mm.wingman.lat = t0.lat
    fire_mm.wingman.long = t0.long
    fire_mm.udp_bridge.current_state["settings"]["auto_spot"] = True
    t0.status = 0.0
    fire_mm._wingman_classify_targets(dt=0.1)
    assert t0.status == 1.0

    t0.status = 1.0
    fire_mm._wingman_classify_targets(dt=0.1)
    assert t0.status == 1.0


def test_mission_progress_current_strings(fire_mm):
    for t in fire_mm.targets:
        t.status = 4.0
    done, reason = fire_mm._check_mission_progress()
    assert done and reason == "all fires extinguished"

    fire_mm.targets[0].status = 0.0
    fire_mm.mission_timer = fire_mm.max_mission_time + 1.0
    done, reason = fire_mm._check_mission_progress()
    assert done and reason == "out of time"

    fire_mm.mission_timer = 1.0
    done, reason = fire_mm._check_mission_progress()
    assert not done and reason == "not complete"


def test_move_ai_hsa_ramps_and_wraps_heading(fire_mm):
    fire_mm.wingman.hdg = 350.0
    fire_mm.wingman.spd = 100.0
    fire_mm.wingman.alt = 1000.0
    fire_mm._move_ai_hsa((10.0, 130.0, 1200.0), dt=1.0)
    assert fire_mm.wingman.hdg >= 350.0 or fire_mm.wingman.hdg <= 20.0
    assert fire_mm.wingman.spd > 100.0
    assert fire_mm.wingman.alt > 1000.0


def test_calculate_ranges_vectorized_returns_expected_and_updates_cache(fire_mm):
    first = fire_mm.targets[0]
    observer = (first.lat, first.long, first.alt)
    ranges, _, _ = fire_mm._calculate_ranges_vectorized(observer, update_cache=True)
    assert len(ranges) == fire_mm.num_targets
    assert ranges[0] == pytest.approx(0.0, abs=1e-9)
    assert np.array_equal(fire_mm.ranges_to_targets, ranges)


def test_dynamic_fire_trigger_spawns_and_extends_arrays(fire_mm):
    fire_mm.pending_dynamic_events = [{
        "id": 77,
        "trigger_time_s": 5.0,
        "true_lat": fire_mm.targets[0].lat + 0.02,
        "true_long": fire_mm.targets[0].long + 0.02,
        "true_alt": fire_mm.targets[0].alt,
        "type": "severe",
        "image_path": "",
        "image_res": [512, 512],
        "reported_lat": None,
        "reported_long": None,
        "reported_alt": None,
    }]
    before = fire_mm.num_targets
    fire_mm.mission_timer = 6.0
    fire_mm._check_dynamic_fire_triggers()
    assert fire_mm.num_targets == before + 1
    assert fire_mm.targets[-1].id == 77
    assert fire_mm.targets[-1].status == 0.0
    assert fire_mm.target_positions.shape[0] == fire_mm.num_targets
    obs = fire_mm.get_observation()
    assert int(obs[14]) == fire_mm.num_targets


def test_receive_human_message_enqueues_with_source_tag(fire_mm):
    fire_mm.receive_human_message("check ridge fire", source="voice_input")
    msgs = fire_mm.message_queue.get_messages("wingman_0", mark_processed=False)
    assert len(msgs) == 1
    assert msgs[0].payload["source"] == "voice_input"

