"""Typed state and result containers for the fire mission."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from queue import Queue
from threading import Lock, Thread
from typing import Any

from utility.message_queue import Message


@dataclass
class MissionConfig:
    path: Path
    human_spawn_lla: tuple[float, float, float]
    human_spawn_spd: float
    human_spawn_hdg: float
    ai_spawn_lla: tuple[float, float, float]
    required_cruise_altitude_ft: float
    required_alt_fire_agl: float
    wind_direction: float
    mag_declination: float
    required_drop_route_length: float
    wingman_active: bool
    targets: list[Any]
    dynamic_event_configs: list[dict] = field(default_factory=list)


@dataclass
class TargetSnapshot:
    target_id: int
    lat: float           # true position
    lon: float
    alt: float
    reported_lat: float  # reported (MFD) position
    reported_lon: float
    reported_alt: float
    is_known: float      # 1.0 if known to cockpit, 0.0 if unknown
    spotted: float
    handled: float
    being_handled: float
    human_in_range_time: float
    wingman_in_range_time: float
    target_status: float
    target_whoflew_initial: float


@dataclass
class ParsedObservation:
    mission_timer: float
    human_lat: float
    human_lon: float
    human_alt: float
    human_hdg: float
    human_spd: float
    command_from_human: float
    agent_task_accepted: float
    human_recently_finished_task: float
    wingman_recently_finished_task: float
    human_requests_plan: float
    human_indicated_plan: float
    wingman_status: float
    plan_for_wingman: float
    num_targets: int
    targets: list[TargetSnapshot]


@dataclass
class TeamPlan:
    human_plan: float = 99.0
    wingman_plan: float = 99.0
    second_best_human_plan: float = 99.0
    second_best_wingman_plan: float = 99.0
    best_followon_human: float = 99.0
    best_followon_wingman: float = 99.0
    second_best_followon_human: float = 99.0
    second_best_followon_wingman: float = 99.0
    rationale: str = "default"
    planning_mode: str = "default"
    show_plan: float = 0.0

    def to_dict(self) -> dict[str, float | str]:
        return {
            "human_plan": self.human_plan,
            "wingman_plan": self.wingman_plan,
            "second_best_human_plan": self.second_best_human_plan,
            "second_best_wingman_plan": self.second_best_wingman_plan,
            "best_followon_human": self.best_followon_human,
            "best_followon_wingman": self.best_followon_wingman,
            "second_best_followon_human": self.second_best_followon_human,
            "second_best_followon_wingman": self.second_best_followon_wingman,
            "rationale": self.rationale,
            "planning_mode": self.planning_mode,
            "show_plan": self.show_plan,
        }


@dataclass
class WingmanAction:
    action_type: str
    goal: tuple[float, float, float]
    status: float
    subtask: float = 0.0
    message: str = ""
    outgoing_messages: list[Message] = field(default_factory=list)
    plan: TeamPlan | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": self.action_type,
            "goal": self.goal,
            "status": self.status,
            "subtask": self.subtask,
            "message": self.message,
            "outgoing_messages": self.outgoing_messages,
        }
        if self.plan is not None:
            payload.update(self.plan.to_dict())
        return payload


@dataclass
class MissionRuntimeState:
    start_time_offset: float = 0.0
    mission_timer: float = 0.0
    step_count: int = 0
    human_has_taken_off: bool = False
    last_human_command: float = 12.0
    last_request_response: float = 0.0
    last_id_response: float = 0.0
    last_plan_send_time: float = -999.0
    active_team_plan_signature: tuple[Any, ...] | None = None
    last_answered_plan_signature: tuple[Any, ...] | None = None
    last_answered_plan_time: float = -999.0
    cached_wingman_action: dict[str, Any] | None = None
    timesteps_since_action_calc: int = 0
    last_wingman_message_count: int = 0
    started_planning_step: int | None = None
    ended_planning_step: int | None = None


@dataclass
class PlanningRuntimeState:
    sent_first_plan: bool = False
    current_plan_for_self: float = 99.0
    latest_human_plan_sent: float | None = None
    latest_plan: dict[str, Any] | None = None
    lookahead_count: int = 0
    planning_thread: Thread | None = None
    planning_queue: Queue = field(default_factory=lambda: Queue(maxsize=1))
    planning_lock: Lock = field(default_factory=Lock)
    is_planning: bool = False
    cached_plans: dict[str, Any] = field(default_factory=lambda: {"human_plan": None, "wingman_plan": None})
    lookahead_cache: dict[Any, Any] = field(default_factory=dict)
    cache_stats: dict[str, int] = field(default_factory=lambda: {"hits": 0, "misses": 0})


@dataclass
class RouteMarkingState:
    current_route_target: int | None = None
    route_marking_stage: str | None = None
    route_type: str | None = None
    route_start_time: float | None = None


@dataclass
class PositionMarkingState:
    marking_position_target: int | None = None
    position_marking_stage: str | None = None
