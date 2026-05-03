"""Glue between UDP events, in-memory messages, and DREF publications."""

from __future__ import annotations

from copy import deepcopy

from missions.fire.constants import DREF_COMMAND_FROM_HUMAN, NO_COMMAND, NO_ID_REQUEST, NO_RECENT_TASK
from utility.message_queue import Message


class FireMessageBridge:
    def __init__(self, mission_manager):
        self.mm = mission_manager
        self._shared_state_send_count = 0

    def poll_human_messages(self) -> None:
        try:
            for event in self.mm.udp_bridge.poll_events():
                payload = event["payload"]
                if event["type"] == "human_plan_response":
                    self.mm.runtime.last_request_response = payload["agent_response"]
                    self.mm.runtime.last_answered_plan_signature = self.mm.runtime.active_team_plan_signature
                    self.mm.runtime.last_answered_plan_time = self.mm.mission_timer
                    self.mm.runtime.active_team_plan_signature = None
                    self.mm.current_team_plan = None
                    self.mm.udp_bridge.current_team_plan = None
                elif event["type"] == "human_id_response":
                    current_id_response = payload["response"]
                    if current_id_response != self.mm.runtime.last_id_response and current_id_response != NO_ID_REQUEST:
                        msg = Message(
                            msg_type="response",
                            sender="human",
                            recipient="wingman_0",
                            payload={
                                "response_type": "id_request",
                                "response_value": current_id_response,
                                "target_id": payload.get("target_id"),
                            },
                            timestamp=self.mm.mission_timer,
                        )
                        self.mm.message_queue.send(msg)
                        self.mm.runtime.last_id_response = current_id_response
                        if current_id_response in (2.0, 3.0, 1.0):
                            self.mm.udp_bridge.send_agent_requests_id(
                                {"active": False, "target_id": None, "mission_time": self.mm.mission_timer}
                            )

            current_command = self.mm.safe_get_dref(DREF_COMMAND_FROM_HUMAN, NO_COMMAND)
            if current_command != self.mm.runtime.last_human_command and current_command != NO_COMMAND:
                msg = Message(
                    msg_type="command",
                    sender="human",
                    recipient="wingman_0",
                    payload={"command_value": current_command},
                    timestamp=self.mm.mission_timer,
                )
                self.mm.message_queue.send(msg)
                self.mm.runtime.last_human_command = current_command
        except Exception as exc:
            self.mm.log(f"[mm.step] Error polling human messages: {exc}")

    def send_shared_state(self, reason: str = "periodic") -> None:
        human_state = deepcopy(self.mm.udp_bridge.current_state["human"])
        payload = {
            "wingman": {
                "lat": float(self.mm.wingman.lat),
                "lon": float(self.mm.wingman.long),
                "alt_msl_m": float(self.mm.wingman.alt),
                "status": float(self.mm.udp_bridge.current_state["wingman"]["status"]),
                "subtask": float(self.mm.udp_bridge.current_state["wingman"]["subtask"]),
                "recently_finished_task": float(self.mm.udp_bridge.current_state["wingman"]["recently_finished_task"]),
                "hdg": float(getattr(self.mm.wingman, "hdg", 0.0)),
                "spd": float(getattr(self.mm.wingman, "spd", 0.0)),
                "goal_hdg": float(getattr(self.mm, "_wingman_goal_hdg", 0.0)),
                "goal_spd": float(getattr(self.mm, "_wingman_goal_spd", 0.0)),
                "goal_alt": float(getattr(self.mm, "_wingman_goal_alt", 0.0)),
            },
            "human": human_state,
            "settings": {
                "auto_spot": bool(self.mm.udp_bridge.current_state["settings"]["auto_spot"]),
            },
            "mission_time": float(self.mm.mission_timer),
            "mission_time_left": float(self.mm.max_mission_time - self.mm.mission_timer),
            "mission_status": getattr(self.mm, "_mission_status", "not complete"),
            "sequence_reason": reason,
        }
        self._shared_state_send_count += 1
        if self._shared_state_send_count <= 5 or reason != "periodic" or self._shared_state_send_count % 60 == 0:
            protocol = getattr(self.mm.udp_bridge, "protocol", None)
            self.mm.log(
                "[shared_state send] "
                f"count={self._shared_state_send_count} "
                f"bridge_id={id(self.mm.udp_bridge)} protocol_id={getattr(protocol, 'instance_id', 'n/a')} "
                f"reason={reason} mt={payload['mission_time']:.1f} left={payload['mission_time_left']:.1f} "
                f"mission_status={payload['mission_status']} "
                f"wingman=({payload['wingman']['lat']:.5f},{payload['wingman']['lon']:.5f}) "
                f"wingman_status={payload['wingman']['status']}"
            )
        self.mm.udp_bridge.send_shared_mission_state(payload)

    def publish_messages_to_datarefs(self) -> None:
        status_messages = self.mm.message_queue.get_messages("human", msg_type="status", mark_processed=False)
        if status_messages:
            latest_status = status_messages[-1]
            status_value = latest_status.payload.get("status_value", "placeholder")
            self.mm.xpc.sendDREF(self.mm.status_message_dref, status_value)
            if status_value != self.mm._last_spoken_status:
                voice_text = self.mm._wingman_status_to_voice(status_value)
                if voice_text:
                    self.mm._speak(voice_text)
                self.mm._last_spoken_status = status_value
            for msg in status_messages:
                msg.mark_processed(self.mm.mission_timer)

        request_messages = self.mm.message_queue.get_messages("human", msg_type="request", mark_processed=False)
        if request_messages:
            latest_request = request_messages[-1]
            request_type = latest_request.payload.get("request_type", "none")
            if request_type == "assist":
                self.mm.dref_io.publish_help_request(latest_request.payload.get("target_id", 99.0))
            else:
                self.mm.dref_io.publish_help_request(99.0)
            for msg in request_messages:
                msg.mark_processed(self.mm.mission_timer)

    def send_mission_init(self) -> None:
        """Send initial known-fire positions to the cockpit plugin at mission start."""
        fires = []
        for t in self.mm.targets:
            if t.is_known_to_cockpit:
                fires.append({
                    "id": t.id,
                    "reported_lat": t.reported_lat,
                    "reported_lon": t.reported_long,
                    "reported_alt": t.reported_alt,
                    "type": t.type,
                    "image_path": t.image_path,
                    "image_res": t.image_res,
                })
        self.mm.udp_bridge.send_mission_init({"fires": fires})

    def send_fire_spawn_event(self, target) -> None:
        """Notify cockpit that a dynamic fire has been spawned."""
        self.mm.udp_bridge.send_fire_spawn_event({
            "id": target.id,
            "type": target.type,
            "image_path": target.image_path,
            "image_res": target.image_res,
            "reported_lat": target.reported_lat,
            "reported_lon": target.reported_long,
            "reported_alt": target.reported_alt,
            "is_known": target.is_known_to_cockpit,
        })

    def send_fire_discovered(self, target) -> None:
        """Notify cockpit that a previously-unknown fire has come within visual range."""
        self.mm.udp_bridge.send_fire_discovered({
            "id": target.id,
            "reported_lat": target.reported_lat,
            "reported_lon": target.reported_long,
            "reported_alt": target.reported_alt,
        })

    def reset_shared_state(self) -> None:
        self.mm.udp_bridge.current_state["wingman"].update(
            {
                "lat": 0.0,
                "lon": 0.0,
                "alt_msl_m": 0.0,
                "status": 99.0,
                "subtask": 0.0,
                "recently_finished_task": -1.0,
            }
        )
        self.mm.udp_bridge.current_state["human"].update(
            {
                "recently_finished_task": NO_RECENT_TASK,
                "indicated_plan": -1.0,
                "recording_route": False,
            }
        )
        self.mm.udp_bridge.current_state["settings"]["auto_spot"] = False
        self.mm.udp_bridge.send_agent_requests_id({"active": False, "target_id": None, "mission_time": 0.0})
        self.send_shared_state("reset")
