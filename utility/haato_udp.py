import json
import queue
import socket
import threading
import time
from copy import deepcopy

from utility.config_loader import get_config as _get_config

HAATO_UDP_VERSION = "1.0"


class HaatoUDPProtocol:
    def __init__(self, host="127.0.0.1", send_port=None, recv_port=None, logger=None):
        _net = _get_config()["network"]
        if send_port is None:
            send_port = _net["haato_udp_send_port"]
        if recv_port is None:
            recv_port = _net["haato_udp_recv_port"]
        self.instance_id = id(self)
        self.host = host
        self.send_port = send_port
        self.recv_port = recv_port
        self.logger = logger
        self.enabled = True

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.sock.bind((self.host, self.recv_port))
            self.sock.settimeout(0.1)
        except OSError as exc:
            self.enabled = False
            self.log(f"[haato_udp] failed to bind recv port {self.recv_port}: {exc}")
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        self.handlers = {}
        self.running = False
        self.thread = None
        self.seq = 0
        self.last_seq_by_sender = {}
        self.sent_count = 0
        self.recv_count = 0

        if self.enabled:
            self.log(
                f"[haato_udp] python protocol id={self.instance_id} recv bound on "
                f"{self.host}:{self.recv_port}, send->{self.send_port}"
            )

    def log(self, message):
        if self.logger:
            self.logger(message)
        else:
            print(message)

    def register_handler(self, msg_type, callback):
        self.handlers[msg_type] = callback

    def start(self):
        if self.running or not self.enabled:
            if not self.enabled:
                self.log("[haato_udp] python bridge not starting recv loop because bind is unavailable")
            return
        self.running = True
        self.thread = threading.Thread(target=self._recv_loop, daemon=True)
        self.thread.start()
        self.log("[haato_udp] python recv loop started")

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=1.0)
        try:
            self.sock.close()
        except OSError:
            pass

    def send(self, msg_type, payload, sender):
        if not self.sock:
            return
        self.seq += 1
        message = {
            "version": HAATO_UDP_VERSION,
            "seq": self.seq,
            "sender": sender,
            "msg_type": msg_type,
            "timestamp": time.time(),
            "payload": payload,
        }
        encoded = json.dumps(message).encode("utf-8")
        try:
            self.sock.sendto(encoded, (self.host, self.send_port))
            self.sent_count += 1
            should_log = self.sent_count <= 5
            if msg_type in {"team_plan_suggestion", "agent_requests_id"}:
                should_log = True
            if msg_type == "shared_mission_state":
                should_log = self.sent_count <= 5 or self.sent_count % 60 == 0
            if should_log:
                payload_summary = ""
                if msg_type == "shared_mission_state":
                    wingman = payload.get("wingman", {})
                    payload_summary = (
                        " "
                        f"mt={float(payload.get('mission_time', 0.0)):.1f} "
                        f"left={float(payload.get('mission_time_left', 0.0)):.1f} "
                        f"status={payload.get('mission_status', 'n/a')} "
                        f"reason={payload.get('sequence_reason', 'n/a')} "
                        f"wingman=({float(wingman.get('lat', 0.0)):.5f},{float(wingman.get('lon', 0.0)):.5f})"
                    )
                self.log(
                    f"[haato_udp] python protocol id={self.instance_id} sent #{self.sent_count} "
                    f"type={msg_type} seq={self.seq} send={self.host}:{self.send_port}{payload_summary}"
                )
        except OSError as exc:
            self.log(f"[haato_udp] send error: {exc}")

    def _recv_loop(self):
        while self.running:
            try:
                data, _ = self.sock.recvfrom(1024 * 1024)
            except socket.timeout:
                continue
            except OSError:
                break

            try:
                message = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue

            sender = str(message.get("sender") or "unknown")
            seq = int(message.get("seq") or 0)
            last_seq = self.last_seq_by_sender.get(sender, 0)
            if seq <= last_seq:
                continue
            self.last_seq_by_sender[sender] = seq
            self.recv_count += 1

            msg_type = message.get("msg_type")
            if self.recv_count <= 5 or msg_type in {"human_plan_response", "human_id_response"}:
                self.log(
                    f"[haato_udp] python protocol id={self.instance_id} recv #{self.recv_count} "
                    f"type={msg_type} seq={seq} sender={sender}"
                )
            handler = self.handlers.get(msg_type)
            if handler:
                try:
                    handler(message.get("payload") or {})
                except Exception as exc:
                    self.log(f"[haato_udp] handler error for {msg_type}: {exc}")


class HaatoUDPBridge:
    def __init__(self, logger=None):
        self.protocol = HaatoUDPProtocol(logger=logger)
        self.logger = logger
        self.instance_id = id(self)

        self.inbound_events = queue.SimpleQueue()
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
        self.current_id_response = {
            "response": 0.0,
            "target_id": None,
            "mission_time": 0.0,
        }

        self.protocol.register_handler("shared_mission_state", self._handle_shared_mission_state)
        self.protocol.register_handler("human_plan_response", self._handle_human_plan_response)
        self.protocol.register_handler("human_id_response", self._handle_human_id_response)
        self.log(
            f"[haato_udp] python bridge initialized id={self.instance_id} "
            f"protocol_id={self.protocol.instance_id}"
        )

    def log(self, message):
        if self.logger:
            self.logger(message)

    def start(self):
        self.protocol.start()

    def stop(self):
        self.protocol.stop()

    def poll_events(self):
        events = []
        while True:
            try:
                events.append(self.inbound_events.get_nowait())
            except queue.Empty:
                return events

    def _merge_state(self, payload):
        for section in ("wingman", "human", "settings"):
            values = payload.get(section)
            if isinstance(values, dict):
                self.current_state.setdefault(section, {}).update(values)
        if "mission_time" in payload:
            self.current_state["mission_time"] = float(payload["mission_time"])
        if "sequence_reason" in payload:
            self.current_state["sequence_reason"] = str(payload["sequence_reason"])
        if "mission_time_left" in payload:
            self.current_state["mission_time_left"] = float(payload["mission_time_left"])
        if "mission_status" in payload:
            self.current_state["mission_status"] = str(payload["mission_status"])

    def _handle_shared_mission_state(self, payload):
        self._merge_state(payload)
        self.log(
            f"[haato_udp] python bridge id={self.instance_id} shared state "
            f"reason={self.current_state['sequence_reason']} "
            f"left={self.current_state['mission_time_left']:.1f} "
            f"mission_status={self.current_state['mission_status']} "
            f"wingman=({self.current_state['wingman']['lat']:.5f},"
            f"{self.current_state['wingman']['lon']:.5f}) "
            f"status={self.current_state['wingman']['status']}"
        )
        self.inbound_events.put({"type": "shared_mission_state", "payload": deepcopy(payload)})

    def _handle_human_plan_response(self, payload):
        self.current_plan_response = {
            "human_response": float(payload.get("human_response", -1.0)),
            "agent_response": float(payload.get("agent_response", -1.0)),
            "selected_variant": str(payload.get("selected_variant", "none")),
            "source_screen": str(payload.get("source_screen", "")),
            "mission_time": float(payload.get("mission_time", 0.0)),
        }
        self.log(
            "[haato_udp] python got human_plan_response "
            f"human={self.current_plan_response['human_response']} "
            f"agent={self.current_plan_response['agent_response']} "
            f"variant={self.current_plan_response['selected_variant']}"
        )
        self.inbound_events.put({"type": "human_plan_response", "payload": deepcopy(self.current_plan_response)})

    def _handle_human_id_response(self, payload):
        target_id = payload.get("target_id")
        self.current_id_response = {
            "response": float(payload.get("response", 0.0)),
            "target_id": None if target_id is None else int(target_id),
            "mission_time": float(payload.get("mission_time", 0.0)),
        }
        self.log(
            "[haato_udp] python got human_id_response "
            f"response={self.current_id_response['response']} target={self.current_id_response['target_id']}"
        )
        self.inbound_events.put({"type": "human_id_response", "payload": deepcopy(self.current_id_response)})

    def send_shared_mission_state(self, payload):
        self._merge_state(payload)
        self.protocol.send("shared_mission_state", payload, sender="python")

    def send_team_plan_suggestion(self, payload):
        self.current_team_plan = deepcopy(payload)
        self.protocol.send("team_plan_suggestion", payload, sender="python")

    def send_agent_requests_id(self, payload):
        self.current_agent_id_request = deepcopy(payload)
        self.protocol.send("agent_requests_id", payload, sender="python")

    def send_mission_init(self, payload: dict) -> None:
        """Send initial fire state to cockpit at mission start.

        Payload: {"fires": [{"id", "reported_lat", "reported_lon", "reported_alt",
                              "type", "image_path", "image_res"}, ...]}
        Only fires that are known to the cockpit at mission start are included.
        """
        self.protocol.send("mission_init", payload, sender="python")

    def send_fire_spawn_event(self, payload: dict) -> None:
        """Notify cockpit that a dynamic fire has spawned.

        Payload: {"id", "type", "image_path", "image_res",
                  "reported_lat", "reported_lon", "reported_alt", "is_known"}
        """
        self.protocol.send("fire_spawn_event", payload, sender="python")

    def send_fire_discovered(self, payload: dict) -> None:
        """Notify cockpit that a previously-unknown fire has been discovered.

        Payload: {"id", "reported_lat", "reported_lon", "reported_alt"}
        """
        self.protocol.send("fire_discovered", payload, sender="python")
