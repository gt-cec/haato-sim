"""Observation schema helpers for the fire mission."""

from __future__ import annotations

import numpy as np

from missions.fire.constants import NO_PLAN
from missions.fire.types import ParsedObservation, TargetSnapshot

BASE_OBSERVATION_SIZE = 16
TARGET_BLOCK_SIZE = 14  # was 10; added reported_lat, reported_long, reported_alt, is_known

# Per-target block layout (offsets relative to block start):
#  0: true lat
#  1: true long
#  2: true alt
#  3: reported lat
#  4: reported long
#  5: reported alt
#  6: is_known_to_cockpit (1.0 / 0.0)
#  7: spotted
#  8: handled
#  9: is_being_handled
# 10: human_in_range_time
# 11: wingman_in_range_time
# 12: target_status (from DREF)
# 13: target_whoflew_initial (from DREF)


def build_wingman_observation(mm) -> np.ndarray:
    human_indicated_plan = mm.udp_bridge.current_state["human"]["indicated_plan"]
    if not mm.is_valid_for_human(human_indicated_plan):
        human_indicated_plan = -1.0
        mm.udp_bridge.current_state["human"]["indicated_plan"] = -1.0

    total_size = BASE_OBSERVATION_SIZE + (mm.num_targets * TARGET_BLOCK_SIZE)
    obs = np.zeros(total_size, dtype=np.float64)

    obs[0] = mm.mission_timer
    obs[1] = mm.human_lla[0]
    obs[2] = mm.human_lla[1]
    obs[3] = mm.human_lla[2]
    obs[4] = mm.human_hdg
    obs[5] = mm.human_spd
    obs[6] = mm.safe_get_dref("custom/haato/command_from_human", fallback=12.0)
    obs[7] = mm.udp_bridge.current_plan_response["agent_response"]
    obs[8] = mm.udp_bridge.current_state["human"]["recently_finished_task"]
    obs[9] = mm.udp_bridge.current_state["wingman"]["recently_finished_task"]
    obs[10] = mm.safe_get_dref("custom/haato/human_requests_plan_suggestion", fallback=1.0)
    obs[11] = human_indicated_plan
    obs[12] = mm.udp_bridge.current_state["wingman"]["status"]
    obs[13] = getattr(mm.wingman, "current_plan_for_self", NO_PLAN)
    obs[14] = float(mm.num_targets)
    obs[15] = 0.0

    for index, target in enumerate(mm.targets):
        start_idx = BASE_OBSERVATION_SIZE + (index * TARGET_BLOCK_SIZE)
        target_status = mm.safe_get_dref(f"custom/haato/target_status[{target.id}]", fallback=0.0)
        target_whoflew = mm.safe_get_dref(f"custom/haato/target_whoflew_initial[{target.id}]", fallback=0.0)
        obs[start_idx:start_idx + TARGET_BLOCK_SIZE] = [
            target.lat,
            target.long,
            target.alt,
            target.reported_lat,
            target.reported_long,
            target.reported_alt,
            1.0 if target.is_known_to_cockpit else 0.0,
            1.0 if target.spotted else 0.0,
            1.0 if target.handled else 0.0,
            1.0 if target.is_being_handled else 0.0,
            target.human_in_range_time,
            target.wingman_in_range_time,
            target_status,
            target_whoflew,
        ]

    return obs


def parse_wingman_observation(obs: np.ndarray) -> ParsedObservation:
    num_targets = int(obs[14])
    targets: list[TargetSnapshot] = []
    for index in range(num_targets):
        start_idx = BASE_OBSERVATION_SIZE + (index * TARGET_BLOCK_SIZE)
        targets.append(
            TargetSnapshot(
                target_id=index,
                lat=float(obs[start_idx]),
                lon=float(obs[start_idx + 1]),
                alt=float(obs[start_idx + 2]),
                reported_lat=float(obs[start_idx + 3]),
                reported_lon=float(obs[start_idx + 4]),
                reported_alt=float(obs[start_idx + 5]),
                is_known=float(obs[start_idx + 6]),
                spotted=float(obs[start_idx + 7]),
                handled=float(obs[start_idx + 8]),
                being_handled=float(obs[start_idx + 9]),
                human_in_range_time=float(obs[start_idx + 10]),
                wingman_in_range_time=float(obs[start_idx + 11]),
                target_status=float(obs[start_idx + 12]),
                target_whoflew_initial=float(obs[start_idx + 13]),
            )
        )

    return ParsedObservation(
        mission_timer=float(obs[0]),
        human_lat=float(obs[1]),
        human_lon=float(obs[2]),
        human_alt=float(obs[3]),
        human_hdg=float(obs[4]),
        human_spd=float(obs[5]),
        command_from_human=float(obs[6]),
        agent_task_accepted=float(obs[7]),
        human_recently_finished_task=float(obs[8]),
        wingman_recently_finished_task=float(obs[9]),
        human_requests_plan=float(obs[10]),
        human_indicated_plan=float(obs[11]),
        wingman_status=float(obs[12]),
        plan_for_wingman=float(obs[13]),
        num_targets=num_targets,
        targets=targets,
    )
