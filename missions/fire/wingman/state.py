"""Wingman runtime state helpers."""

from dataclasses import dataclass, field

from missions.fire.types import PlanningRuntimeState, PositionMarkingState, RouteMarkingState


@dataclass
class WingmanRuntimeState:
    status: float = 99.0
    last_status: str = "none"
    action: dict | None = None
    last_action: dict = field(default_factory=lambda: {"type": "none", "goal": (0.0, 0.0, 0.0), "request": "none"})
    current_target: int | None = None
    request_response: float = 0.0
    requesting_help: bool = False
    latest_human_command: float | None = None
    latest_human_message: object | None = None
    auto_spot: bool = False
    route: RouteMarkingState = field(default_factory=RouteMarkingState)
    position: PositionMarkingState = field(default_factory=PositionMarkingState)
    planning: PlanningRuntimeState = field(default_factory=PlanningRuntimeState)
