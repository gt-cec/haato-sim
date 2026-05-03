import threading
from types import SimpleNamespace

from missions.fire.wingman.agent import FireWatchWingman
from utility.message_queue import Message, MessageQueue

import run_mission


class FakeMessageLogger:
    def __init__(self):
        self.records = []

    def log(self, message):
        self.records.append(message)


class FakeMissionManager:
    def __init__(self):
        self.mission_timer = 42.5
        self.message_queue = MessageQueue(max_size=10)
        self.message_logger = FakeMessageLogger()
        self.logged = []
        self.latest_human_message_text = ""

    def log(self, message, log_file="./logs/debug_log.txt", debug_prefix=None):
        self.logged.append(message)


def test_receive_human_message_enqueues_freeform_message():
    mm = FakeMissionManager()

    run_mission.FireWatchMM.receive_human_message(mm, "  check the ridge fire  ", source="voice_input")

    messages = mm.message_queue.get_messages("wingman_0", mark_processed=False)
    assert len(messages) == 1
    message = messages[0]
    assert message.type == "freeform_text"
    assert message.payload["text"] == "check the ridge fire"
    assert message.payload["normalized_text"] == "check the ridge fire"
    assert message.payload["source"] == "voice_input"
    assert mm.latest_human_message_text == "check the ridge fire"
    assert mm.message_logger.records == [message]


def test_receive_human_message_ignores_blank_text():
    mm = FakeMissionManager()

    run_mission.FireWatchMM.receive_human_message(mm, "   ")

    assert mm.message_queue.get_messages("wingman_0", mark_processed=False) == []
    assert mm.message_logger.records == []


def test_wingman_receive_human_message_stores_latest_message():
    wingman = FireWatchWingman.__new__(FireWatchWingman)
    wingman.latest_human_message = None
    wingman.log = lambda *args, **kwargs: None
    message = Message(
        msg_type="freeform_text",
        sender="human",
        recipient="wingman_0",
        payload={"normalized_text": "say again your plan"},
        timestamp=12.0,
    )

    wingman.receive_human_message(message)

    assert wingman.latest_human_message is message


def test_voice_input_loop_forwards_transcript(monkeypatch):
    captured = []

    class FakeVoiceInputManager:
        def __init__(self, *args, **kwargs):
            self.wait_calls = 0

        def wait_for_pilot(self, timeout=None):
            self.wait_calls += 1
            return True

        def listen_until_release(self):
            return "  wingman check in  "

        def cleanup(self):
            return None

    class FakeMM:
        def receive_human_message(self, text, source="voice_input"):
            captured.append((text, source))
            runtime.voice_stop_event.set()

    runtime = SimpleNamespace(
        mm=FakeMM(),
        xpc=object(),
        args=SimpleNamespace(verbose=False),
        voice_stop_event=threading.Event(),
    )

    monkeypatch.setattr(run_mission, "VoiceInputManager", FakeVoiceInputManager)

    run_mission.voice_input_loop(runtime)

    assert captured == [("wingman check in", "voice_input")]
