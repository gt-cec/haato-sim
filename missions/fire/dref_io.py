"""Mission-specific DREF helpers."""

from __future__ import annotations

import math

from missions.fire.constants import (
    CONTROL_PREFIX_MAP,
    DREF_COMMAND_FROM_HUMAN,
    DREF_CONTROL_PREFIX,
    DREF_FIRE_LAYOUT,
    DREF_HELP_REQUEST,
    DREF_HUMAN_IN_RANGE,
    DREF_INITIATIVE_LEVEL,
    DREF_LOG_FILE_IDENTIFIER,
    DREF_PARTICIPANT_ID,
    DREF_RESET_MISSION,
    DREF_START_LOGGING,
    DREF_TARGET_CLASSIFICATION_FMT,
    DREF_TARGET_STATUS_FMT,
    DREF_TARGET_WHOFLEW_INITIAL_FMT,
    PLUGIN_DEFAULT_TARGET_CLASSIFICATION,
    PLUGIN_DEFAULT_TARGET_STATUS,
    PLUGIN_DEFAULT_TARGET_WHOFLEW_INITIAL,
    PLUGIN_RESET_DREF_DEFAULTS,
)


class FireMissionDrefIO:
    def __init__(self, mission_manager):
        self.mm = mission_manager

    def reset_plugin_managed_datarefs(self) -> None:
        for dref_path, default_value in PLUGIN_RESET_DREF_DEFAULTS:
            self.mm.safe_send_dref(dref_path, default_value, dref_path)

        for target in self.mm.targets:
            self.mm.safe_send_dref(
                DREF_TARGET_STATUS_FMT.format(target_id=target.id),
                PLUGIN_DEFAULT_TARGET_STATUS,
                f"target_status[{target.id}]",
            )
            self.mm.safe_send_dref(
                DREF_TARGET_CLASSIFICATION_FMT.format(target_id=target.id),
                PLUGIN_DEFAULT_TARGET_CLASSIFICATION,
                f"target_classification[{target.id}]",
            )
            self.mm.safe_send_dref(
                DREF_TARGET_WHOFLEW_INITIAL_FMT.format(target_id=target.id),
                PLUGIN_DEFAULT_TARGET_WHOFLEW_INITIAL,
                f"target_whoflew_initial[{target.id}]",
            )

    def set_mission_config(self) -> None:
        mm = self.mm
        mm.safe_send_dref(DREF_PARTICIPANT_ID, float(mm.user_id), "participant_id")
        mm.safe_send_dref(DREF_INITIATIVE_LEVEL, float(mm.initiative_level), "initiative_level")
        mm.safe_send_dref(DREF_RESET_MISSION, 1.0, "reset_mission")
        mm.safe_send_dref(DREF_START_LOGGING, 1.0, "start_logging")
        mm.safe_send_dref(DREF_FIRE_LAYOUT, float(mm.fire_layout), "fire_layout")
        mm.safe_send_dref(DREF_LOG_FILE_IDENTIFIER, mm.log_file_identifier, "log_file_identifier")
        mm.safe_send_dref(
            DREF_CONTROL_PREFIX,
            CONTROL_PREFIX_MAP.get(mm.control_prefix, 3.0),
            "control_prefix",
        )

    def initialize_target_datarefs(self) -> None:
        for target in self.mm.targets:
            self.mm.safe_send_dref(
                DREF_TARGET_STATUS_FMT.format(target_id=target.id),
                PLUGIN_DEFAULT_TARGET_STATUS,
                f"target_status[{target.id}]",
            )
            self.mm.safe_send_dref(
                DREF_TARGET_CLASSIFICATION_FMT.format(target_id=target.id),
                PLUGIN_DEFAULT_TARGET_CLASSIFICATION,
                f"target_classification[{target.id}]",
            )

    def initialize_single_target_dataref(self, target) -> None:
        """Initialise datarefs for a single target (used for dynamically-spawned fires)."""
        self.mm.safe_send_dref(
            DREF_TARGET_STATUS_FMT.format(target_id=target.id),
            PLUGIN_DEFAULT_TARGET_STATUS,
            f"target_status[{target.id}]",
        )
        self.mm.safe_send_dref(
            DREF_TARGET_CLASSIFICATION_FMT.format(target_id=target.id),
            PLUGIN_DEFAULT_TARGET_CLASSIFICATION,
            f"target_classification[{target.id}]",
        )
        self.mm.safe_send_dref(
            DREF_TARGET_WHOFLEW_INITIAL_FMT.format(target_id=target.id),
            PLUGIN_DEFAULT_TARGET_WHOFLEW_INITIAL,
            f"target_whoflew_initial[{target.id}]",
        )

    def apply_start_conditions(self, start_conditions: dict) -> None:
        for target in self.mm.targets:
            target_status = start_conditions["target_status"][target.id]
            target_classification = start_conditions["target_classification"][target.id]
            target_whoflew = start_conditions["target_whoflew"][target.id]
            self.mm.safe_send_dref(
                DREF_TARGET_STATUS_FMT.format(target_id=target.id),
                target_status,
                f"target_status[{target.id}]",
            )
            self.mm.safe_send_dref(
                DREF_TARGET_CLASSIFICATION_FMT.format(target_id=target.id),
                target_classification,
                f"target_classification[{target.id}]",
            )
            self.mm.safe_send_dref(
                DREF_TARGET_WHOFLEW_INITIAL_FMT.format(target_id=target.id),
                target_whoflew,
                f"target_whoflew_initial[{target.id}]",
            )

    def set_weather_conditions(self, speed: float, direction: float, visibility: float) -> None:
        self.mm.safe_send_dref("sim/weather/region/wind_speed_msl_ms[0]", speed)
        self.mm.safe_send_dref("sim/weather/region/wind_direction_degt[0]", direction)
        self.mm.safe_send_dref("custom/haato/wind_direction", direction)
        self.mm.safe_send_dref("sim/cockpit/autopilot/heading_mag", direction)
        self.mm.safe_send_dref("sim/weather/aircraft/visibility_reported_sm", visibility)
        self.mm.safe_send_dref("sim/weather/region/visibility_reported_sm", visibility)
        self.mm.safe_send_dref("sim/weather/region/update_immediately", 1)

    def set_human_airspeed(self, speed: float) -> None:
        heading_rad = math.radians(self.mm.safe_get_dref("sim/flightmodel/position/psi", 0.0, "psi"))
        velocity_ms = speed * 0.5144
        self.mm.safe_send_dref("sim/flightmodel/position/local_vx", velocity_ms * math.sin(heading_rad), "local_vx")
        self.mm.safe_send_dref("sim/flightmodel/position/local_vz", velocity_ms * -math.cos(heading_rad), "local_vz")

    def set_human_lla(self, lla: tuple[float, float, float]) -> None:
        self.mm.xpc.sendPOSI(lla[0], lla[1], lla[2], -0.25221577, 4.2194324, 78.849)

    def reset_human_command(self) -> None:
        self.mm.safe_send_dref(DREF_COMMAND_FROM_HUMAN, 12.0, "human_command")
        self.mm.safe_send_dref(DREF_HUMAN_IN_RANGE, 99.0, "human_in_range")

    def publish_help_request(self, target_id: float) -> None:
        self.mm.xpc.sendDREF(DREF_HELP_REQUEST, float(target_id))
