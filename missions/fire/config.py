"""Mission configuration loading for the fire mission."""

from __future__ import annotations

from pathlib import Path

from utility.base_classes import Target
from utility.config_loader import get_config

from missions.fire.types import MissionConfig

_CONFIG_PATH = (
    Path(__file__).resolve().parents[2]
    / "Copy to X-Plane directory"
    / "Resources"
    / "plugins"
    / "HAATO_assets"
    / "config.yaml"
)


def load_fire_mission_config(fire_layout: int, testing_wingman: bool = False) -> MissionConfig:
    data = get_config()["missions"].get(fire_layout)
    if data is None:
        raise KeyError(f"No mission config for fire_layout={fire_layout}")

    targets: list[Target] = []
    dynamic_event_configs: list[dict] = []

    if "fires" in data:
        # New schema: fires / fires_reported / dynamic_events
        fires_reported_map: dict[int, dict] = {
            int(rp["id"]): rp for rp in data.get("fires_reported", [])
        }

        for p in data["fires"]:
            fid = int(p["id"])
            rp = fires_reported_map.get(fid)  # None → unknown fire (no reported position)
            targets.append(
                Target(
                    lat=float(p["latitude"]),
                    long=float(p["longitude"]),
                    alt=float(p["altitude"]),
                    type=p.get("type", "unknown"),
                    id=fid,
                    reported_lat=float(rp["latitude"]) if rp else None,
                    reported_long=float(rp["longitude"]) if rp else None,
                    reported_alt=float(rp["altitude"]) if rp else None,
                    image_path=str(p.get("image_path", "")),
                    image_res=list(p["image_res"]) if "image_res" in p else None,
                )
            )

        for de in data.get("dynamic_events", []):
            has_reported = "reported_latitude" in de
            dynamic_event_configs.append({
                "id": int(de["id"]),
                "trigger_time_s": float(de["trigger_time_s"]),
                "true_lat": float(de["true_latitude"]),
                "true_long": float(de["true_longitude"]),
                "true_alt": float(de["true_altitude"]),
                "type": str(de.get("type", "moderate")),
                "image_path": str(de.get("image_path", "")),
                "image_res": list(de["image_res"]) if "image_res" in de else [512, 512],
                "reported_lat": float(de["reported_latitude"]) if has_reported else None,
                "reported_long": float(de["reported_longitude"]) if has_reported else None,
                "reported_alt": float(de["reported_altitude"]) if has_reported else None,
            })

    elif "data_points" in data:
        # Legacy schema: data_points (perfect information — reported == true)
        raw_targets = data["data_points"]
        if not raw_targets:
            raise KeyError(f"'data_points' is empty for fire_layout={fire_layout}")
        for index, p in enumerate(raw_targets):
            targets.append(
                Target(
                    lat=float(p.get("latitude", 0.0)),
                    long=float(p.get("longitude", 0.0)),
                    alt=float(p.get("altitude", 0.0)),
                    type=p.get("type", "unknown"),
                    id=index,
                    # No reported_* → defaults to true position, is_known_to_cockpit=True
                    image_path=str(p.get("image_path", "")),
                    image_res=list(p["image_res"]) if "image_res" in p else None,
                )
            )
    else:
        raise KeyError(
            f"Neither 'fires' nor 'data_points' found for fire_layout={fire_layout}"
        )

    if not targets:
        raise ValueError(f"No valid targets loaded for fire_layout={fire_layout}")

    if testing_wingman:
        human_spawn_lla = (47.71044513620272, -121.34287916904042, 299.319856278361)
        human_spawn_spd = 0.0
        human_spawn_hdg = 75.0
    else:
        human_spawn_lla = tuple(data["human_start_lla"])
        human_spawn_spd = float(data["human_start_spd"])
        human_spawn_hdg = float(data["human_start_hdg"])

    return MissionConfig(
        path=_CONFIG_PATH,
        human_spawn_lla=human_spawn_lla,
        human_spawn_spd=human_spawn_spd,
        human_spawn_hdg=human_spawn_hdg,
        ai_spawn_lla=tuple(data["agent_start_lla"]),
        required_cruise_altitude_ft=float(data["required_altitude_ft_msl"]),
        required_alt_fire_agl=float(data["required_altitude_fire_agl_ft"]),
        wind_direction=float(data["wind_direction"]),
        mag_declination=float(data["magnetic_declination"]),
        required_drop_route_length=float(data["required_drop_route_length"]),
        wingman_active=bool(data["wingman_active"]),
        targets=targets,
        dynamic_event_configs=dynamic_event_configs,
    )
