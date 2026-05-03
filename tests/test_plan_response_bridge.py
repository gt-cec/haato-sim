import sys
import types
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BRIDGE_PATH = REPO_ROOT / "missions" / "fire" / "message_bridge.py"


def _load_message_bridge_module():
    constants_module = types.ModuleType("missions.fire.constants")
    constants_module.DREF_COMMAND_FROM_HUMAN = "custom/haato/command_from_human"
    constants_module.NO_COMMAND = 12.0
    constants_module.NO_ID_REQUEST = 0.0
    constants_module.NO_RECENT_TASK = -1.0

    class DummyMessage:
        def __init__(self, msg_type, sender, recipient, payload, timestamp):
            self.msg_type = msg_type
            self.sender = sender
            self.recipient = recipient
            self.payload = payload
            self.timestamp = timestamp

    message_queue_module = types.ModuleType("utility.message_queue")
    message_queue_module.Message = DummyMessage

    previous_modules = {
        "missions.fire.constants": sys.modules.get("missions.fire.constants"),
        "utility.message_queue": sys.modules.get("utility.message_queue"),
    }
    sys.modules["missions.fire.constants"] = constants_module
    sys.modules["utility.message_queue"] = message_queue_module
    try:
        module = types.ModuleType("test_message_bridge_module")
        module.__file__ = str(BRIDGE_PATH)
        source = BRIDGE_PATH.read_text(encoding="utf-8")
        exec(compile(source, str(BRIDGE_PATH), "exec"), module.__dict__)
        return module
    finally:
        for name, previous in previous_modules.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


class FakeUDPBridge:
    def __init__(self, events):
        self._events = list(events)
        self.current_team_plan = {"human_plan": 2.0, "wingman_plan": 5.0, "show_plan": True}

    def poll_events(self):
        return list(self._events)

    def send_agent_requests_id(self, payload):
        self.last_agent_request_payload = payload


def test_human_plan_response_clears_active_plan_state():
    module = _load_message_bridge_module()

    mm = types.SimpleNamespace()
    mm.udp_bridge = FakeUDPBridge(
        [{"type": "human_plan_response", "payload": {"agent_response": 1.0}}]
    )
    mm.runtime = types.SimpleNamespace(
        last_request_response=0.0,
        active_team_plan_signature=("sig",),
        last_answered_plan_signature=None,
        last_answered_plan_time=-999.0,
        last_human_command=12.0,
        last_id_response=0.0,
    )
    mm.mission_timer = 123.0
    mm.current_team_plan = {"human_plan": 2.0}
    mm.message_queue = types.SimpleNamespace(send=lambda msg: None)
    mm.safe_get_dref = lambda *args, **kwargs: 12.0
    mm.log = lambda *args, **kwargs: None

    bridge = module.FireMessageBridge(mm)
    bridge.poll_human_messages()

    assert mm.runtime.last_request_response == 1.0
    assert mm.runtime.last_answered_plan_signature == ("sig",)
    assert mm.runtime.active_team_plan_signature is None
    assert mm.runtime.last_answered_plan_time == 123.0
    assert mm.current_team_plan is None
    assert mm.udp_bridge.current_team_plan is None
