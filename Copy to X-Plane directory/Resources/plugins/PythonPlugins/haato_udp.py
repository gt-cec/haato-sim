import json
import os
import socket
import time
import traceback
from copy import deepcopy

try:
    import xp
except ImportError:  # pragma: no cover
    class MockXP:
        @staticmethod
        def log(message):
            print(message)
    xp = MockXP()


HAATO_UDP_VERSION = "1.0"


class CockpitHaatoUDPProtocol:
    def __init__(self, send_host="127.0.0.1", bind_host="0.0.0.0", send_port=48200, recv_port=48100):
        self.instance_id = id(self)
        self.send_host = send_host
        self.bind_host = bind_host
        self.send_port = send_port
        self.recv_port = recv_port
        self.handlers = {}
        self.seq = 0
        self.last_seq_by_sender = {}
        self.enabled = True
        self.last_rebind_attempt = 0.0
        self.sent_count = 0
        self.recv_count = 0
        self.flight_loop_calls = 0

        xp.log(
            f"[haato_udp] protocol create id={self.instance_id} pid={os.getpid()} "
            f"bind={self.bind_host}:{self.recv_port} send={self.send_host}:{self.send_port}"
        )
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._configure_socket(self.sock)
        self._bind_recv_socket()

    def _configure_socket(self, sock):
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except OSError as exc:
            xp.log(f"[haato_udp] failed to enable SO_REUSEADDR: {exc}")

    def _validate_bind_target(self):
        if not isinstance(self.bind_host, str) or not self.bind_host:
            raise ValueError(f"invalid bind_host={self.bind_host!r}")
        if not isinstance(self.recv_port, int) or not (0 < self.recv_port < 65536):
            raise ValueError(f"invalid recv_port={self.recv_port!r}")

    def _bind_recv_socket(self):
        try:
            self._validate_bind_target()
            xp.log(
                f"[haato_udp] protocol id={self.instance_id} attempting bind "
                f"{self.bind_host}:{self.recv_port}"
            )
            self.sock.bind((self.bind_host, self.recv_port))
            self.sock.setblocking(False)
            self.enabled = True
            xp.log(
                f"[haato_udp] protocol id={self.instance_id} recv bound on "
                f"{self.bind_host}:{self.recv_port}, send->{self.send_host}:{self.send_port}"
            )
        except (OSError, ValueError) as exc:
            self.enabled = False
            traceback.print_exc()
            xp.log(
                f"[haato_udp] protocol id={self.instance_id} failed to bind recv on "
                f"{self.bind_host}:{self.recv_port} (send->{self.send_host}:{self.send_port}): {exc}"
            )
            xp.log("[haato_udp] bridge running in degraded send-only mode")
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._configure_socket(self.sock)

    def maybe_rebind(self):
        if self.enabled:
            return
        now = time.time()
        if now - self.last_rebind_attempt < 2.0:
            return
        self.last_rebind_attempt = now
        xp.log(
            f"[haato_udp] protocol id={self.instance_id} retrying recv bind on "
            f"{self.bind_host}:{self.recv_port}"
        )
        self._bind_recv_socket()
        if self.enabled:
            xp.log(
                f"[haato_udp] protocol id={self.instance_id} recv bind recovered on "
                f"{self.bind_host}:{self.recv_port}"
            )

    def register_handler(self, msg_type, callback):
        self.handlers[msg_type] = callback

    def stop(self):
        self.enabled = False
        xp.log(f"[haato_udp] protocol id={self.instance_id} stop called")
        if self.sock:
            try:
                self.sock.close()
                xp.log(f"[haato_udp] protocol id={self.instance_id} cockpit socket closed")
            except OSError as exc:
                xp.log(f"[haato_udp] protocol id={self.instance_id} cockpit socket close error: {exc}")
            finally:
                self.sock = None

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
            self.sock.sendto(encoded, (self.send_host, self.send_port))
            self.sent_count += 1
            if self.sent_count <= 5:
                xp.log(
                    f"[haato_udp] protocol id={self.instance_id} cockpit sent #{self.sent_count} "
                    f"type={msg_type} seq={self.seq} to={self.send_host}:{self.send_port}"
                )
        except OSError as exc:
            xp.log(f"[haato_udp] send error: {exc}")

    def flight_loop_callback(self):
        self.flight_loop_calls += 1
        if self.flight_loop_calls <= 5 or self.flight_loop_calls % 300 == 0:
            xp.log(
                f"[haato_udp] protocol id={self.instance_id} flight_loop call={self.flight_loop_calls} "
                f"enabled={self.enabled} sock={'yes' if self.sock else 'no'} recv_count={self.recv_count}"
            )
        self.maybe_rebind()
        if not self.enabled or not self.sock:
            return
        while True:
            try:
                data, _ = self.sock.recvfrom(1024 * 1024)
            except BlockingIOError:
                return
            except OSError as exc:
                xp.log(f"[haato_udp] socket error: {exc}")
                return

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
            if (
                self.recv_count <= 5
                or msg_type in {"team_plan_suggestion", "agent_requests_id"}
                or (msg_type == "shared_mission_state" and self.recv_count % 60 == 0)
            ):
                payload = message.get("payload") or {}
                wingman = payload.get("wingman", {})
                payload_summary = ""
                if msg_type == "shared_mission_state":
                    payload_summary = (
                        " "
                        f"left={float(payload.get('mission_time_left', 0.0)):.1f} "
                        f"mission_status={payload.get('mission_status', 'n/a')} "
                        f"reason={payload.get('sequence_reason', 'n/a')} "
                        f"wingman=({float(wingman.get('lat', 0.0)):.5f},{float(wingman.get('lon', 0.0)):.5f})"
                    )
                xp.log(
                    f"[haato_udp] protocol id={self.instance_id} cockpit recv #{self.recv_count} "
                    f"type={msg_type} seq={seq} sender={sender}{payload_summary}"
                )

            handler = self.handlers.get(msg_type)
            if handler:
                try:
                    handler(message.get("payload") or {})
                except Exception as exc:
                    xp.log(f"[haato_udp] handler error: {exc}")


class CockpitHaatoUDPBridge:
    def __init__(self):
        self.protocol = CockpitHaatoUDPProtocol()
        self.enabled = self.protocol.enabled
        self.instance_id = id(self)
        self.shared_state_count = 0

        # Pending fire events consumed by the plugin's flight loop
        self.pending_mission_init = None
        self.pending_fire_spawn_events = []
        self.pending_fire_discovered = []

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
        self.current_team_plan = None
        self.current_agent_id_request = {
            "active": False,
            "target_id": None,
            "mission_time": 0.0,
        }
        self.current_plan_response = {
            "human_response": -1.0,
            "agent_response": -1.0,
            "selected_variant": "none",
            "source_screen": "",
            "mission_time": 0.0,
        }

        self.protocol.register_handler("shared_mission_state", self._handle_shared_mission_state)
        self.protocol.register_handler("team_plan_suggestion", self._handle_team_plan_suggestion)
        self.protocol.register_handler("agent_requests_id", self._handle_agent_requests_id)
        self.protocol.register_handler("mission_init", self._handle_mission_init)
        self.protocol.register_handler("fire_spawn_event", self._handle_fire_spawn_event)
        self.protocol.register_handler("fire_discovered", self._handle_fire_discovered)
        xp.log(
            f"[haato_udp] cockpit bridge initialized id={self.instance_id} "
            f"protocol_id={self.protocol.instance_id} enabled={self.enabled}"
        )

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
        self.shared_state_count += 1
        xp.log(
            f"[haato_udp] cockpit bridge id={self.instance_id} shared state "
            f"count={self.shared_state_count} protocol_id={self.protocol.instance_id} "
            f"left={self.current_state['mission_time_left']:.1f} "
            f"mission_status={self.current_state['mission_status']} "
            f"reason={self.current_state['sequence_reason']} "
            f"wingman=({self.current_state['wingman']['lat']:.5f},"
            f"{self.current_state['wingman']['lon']:.5f}) "
            f"status={self.current_state['wingman']['status']}"
        )

    def _handle_team_plan_suggestion(self, payload):
        self.current_team_plan = deepcopy(payload)
        xp.log(
            "[haato_udp] cockpit team plan "
            f"human={payload.get('human_plan', 99.0)} wingman={payload.get('wingman_plan', 99.0)}"
        )

    def _handle_agent_requests_id(self, payload):
        target_id = payload.get("target_id")
        self.current_agent_id_request = {
            "active": bool(payload.get("active", False)),
            "target_id": None if target_id is None else int(target_id),
            "mission_time": float(payload.get("mission_time", 0.0)),
        }
        xp.log(
            "[haato_udp] cockpit agent_requests_id "
            f"active={self.current_agent_id_request['active']} "
            f"target={self.current_agent_id_request['target_id']}"
        )

    def _handle_mission_init(self, payload):
        """Store mission_init payload for the plugin's flight loop to consume."""
        self.pending_mission_init = payload
        xp.log(f"[haato_udp] cockpit mission_init received fires={len(payload.get('fires', []))}")

    def _handle_fire_spawn_event(self, payload):
        """Queue a dynamic fire spawn for the plugin's flight loop to consume."""
        self.pending_fire_spawn_events.append(payload)
        xp.log(f"[haato_udp] cockpit fire_spawn_event id={payload.get('id')} known={payload.get('is_known')}")

    def _handle_fire_discovered(self, payload):
        """Queue a fire-discovered update for the plugin's flight loop to consume."""
        self.pending_fire_discovered.append(payload)
        xp.log(f"[haato_udp] cockpit fire_discovered id={payload.get('id')}")

    def flight_loop_callback(self):
        self.protocol.flight_loop_callback()

    def stop(self):
        self.protocol.stop()

    def send_human_plan_response(self, payload):
        self.current_plan_response = deepcopy(payload)
        self.protocol.send("human_plan_response", payload, sender="xppython3")

    def send_human_id_response(self, payload):
        self.protocol.send("human_id_response", payload, sender="xppython3")

    def send_human_state_update(self, human=None, settings=None, mission_time=0.0, sequence_reason="ui_update"):
        payload = {
            "human": human or {},
            "settings": settings or {},
            "mission_time": mission_time,
            "sequence_reason": sequence_reason,
        }
        self._merge_state(payload)
        self.protocol.send("shared_mission_state", payload, sender="xppython3")
