-- Create custom datarefs
define_shared_DataRef("custom/haato/participant_id", "Float")
define_shared_DataRef("custom/haato/log_file_identifier", "Float")
define_shared_DataRef("custom/haato/fire_layout", "Float") -- 1.0, 2.0, 3.0. Will use 1.0 for now
define_shared_DataRef("custom/haato/initiative_level", "Float") -- 0.0=Low, 1.0=Medium, 2.0=High
define_shared_DataRef("custom/haato/wind_direction", "Float") -- Current wind direction. Shifts periodically
define_shared_DataRef("custom/haato/control_prefix", "Float")
set("custom/haato/participant_id", 99.0)
set("custom/haato/log_file_identifier", 0.0)
set("custom/haato/fire_layout", 99.0)
set("custom/haato/initiative_level", 99.0)
set("custom/haato/wind_direction", 150.0)
set("custom/haato/control_prefix", 99.0)

define_shared_DataRef("custom/haato/show_primary_screen", "Float")
define_shared_DataRef("custom/haato/current_screen", "Float")
define_shared_DataRef("custom/haato/change_screen", "Float")
set("custom/haato/show_primary_screen", 0.0)
set("custom/haato/change_screen", -1.0)
set("custom/haato/current_screen", -1.0)

define_shared_DataRef("custom/haato/reset_mission", "Float")
define_shared_DataRef("custom/haato/start_logging", "Float")
define_shared_DataRef("custom/haato/map_zoom_range", "Float")
set("custom/haato/reset_mission", 0.0)
set("custom/haato/start_logging", 0.0)
set("custom/haato/map_zoom_range", -1.0)

define_shared_DataRef("custom/haato/reset_wingman", "Float")
set("custom/haato/reset_wingman", 0.0)

define_shared_DataRef("custom/haato/command_from_human", "Float") -- 12 = no command, 8.0 = follow, 0-7: Go to target i
define_shared_DataRef("custom/haato/human_requests_plan_suggestion", "Float") -- 0.0 false, 1.0 true
set_array("custom/haato/command_from_human", 0, 99.0)
set("custom/haato/human_requests_plan_suggestion", 0.0)

-- Define datarefs to control targets
-- Array size is 16 (indices 0-15) to support up to 8 static fires + up to 8 dynamic fires.
-- Indices 0-7 are reserved for static fires; indices 8-15 for dynamic fires spawned mid-mission.
target_status = create_dataref_table("custom/haato/target_status", "FloatArray") -- 0.0=unknown, 1.0=classified, 2.0=position marked, 3.0=initial route flown, 4.0=refined route flown
target_classification = create_dataref_table("custom/haato/target_classification", "FloatArray") -- 0.0=none, 1.0=moderate, 2.0=severe
target_whoflew_initial = create_dataref_table("custom/haato/target_whoflew_initial", "FloatArray") -- -1.0=not flown, 1.0=human, 2.0=wingman
for i = 0, 15 do -- Initialize all 16 slots
    target_status[i] = 0.0
    target_classification[i] = 0.0
    target_whoflew_initial[i] = -1.0
end

define_shared_DataRef("custom/haato/human_in_range_of_target", "Float") -- 0.0 - 7.0 if human is in range of target 0 - 7, or 99.0 if not
set("custom/haato/human_in_range_of_target", 99.0)

