from __future__ import annotations

import json

from dev.run_preflight_planning import (
    build_hold_step,
    build_plan_payload,
    fire_step_label,
    load_planner_layout,
    save_plan_payload,
    sequence_step_label,
)


def test_load_planner_layout_uses_reported_positions_for_layout_one():
    layout = load_planner_layout(1)

    assert layout.fire_layout == 1
    assert len(layout.fires) == 8
    assert layout.fires[0].fire_id == 0
    assert layout.fires[0].latitude == 47.9748
    assert layout.fires[0].longitude == -121.258566


def test_load_planner_layout_supports_legacy_practice_layout():
    layout = load_planner_layout(4)

    assert layout.fire_layout == 4
    assert len(layout.fires) == 2
    assert [fire.fire_id for fire in layout.fires] == [0, 1]
    assert layout.fires[1].longitude == -121.187566


def test_build_hold_step_returns_structured_payload():
    hold_step = build_hold_step(owner="human", lat=47.81, lon=-121.12, until_fire_id=4)

    assert hold_step["type"] == "hold"
    assert hold_step["location"] == {"lat": 47.81, "lon": -121.12}
    assert hold_step["until"] == {"event": "initial_route_marked", "fire_id": 4}
    assert "fire 4 initial route is marked" in hold_step["label"]


def test_build_plan_payload_preserves_mixed_sequence_types():
    human_sequence = [fire_step_label(1), build_hold_step("human", 47.8, -121.1, 3)]
    wingman_sequence = [fire_step_label(2)]

    payload = build_plan_payload(
        fire_layout=2,
        human_sequence=human_sequence,
        wingman_sequence=wingman_sequence,
        plan_instructions="watch spacing",
        saved_at="2026-04-01T12:00:00",
    )

    assert payload["fire_layout"] == 2
    assert payload["saved_at"] == "2026-04-01T12:00:00"
    assert payload["human_sequence"][0] == "fire 1"
    assert payload["human_sequence"][1]["type"] == "hold"
    assert payload["wingman_sequence"] == ["fire 2"]
    assert payload["plan_instructions"] == "watch spacing"


def test_save_plan_payload_writes_json_file(tmp_path):
    payload = build_plan_payload(
        fire_layout=3,
        human_sequence=["fire 1"],
        wingman_sequence=["fire 2"],
        plan_instructions="appendix",
        saved_at="2026-04-01T12:00:00",
    )

    path = save_plan_payload(payload, save_dir=tmp_path)

    assert path.parent == tmp_path
    assert path.name.startswith("preflight_layout3_")

    saved_payload = json.loads(path.read_text(encoding="utf-8"))
    assert saved_payload == payload


def test_sequence_step_label_handles_string_and_hold():
    assert sequence_step_label("fire 5") == "fire 5"
    hold_step = build_hold_step(owner="wingman", lat=47.83, lon=-121.2, until_fire_id=6)
    assert sequence_step_label(hold_step) == hold_step["label"]
