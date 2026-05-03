-- Combined Target Rendering Script for FlyWithLua with Dynamic Wingman Icon
-- Automatically detects VR mode and uses appropriate rendering method
-- Works in both 2D mode (direct screen rendering) and VR mode (floating window)
-- Enhanced wingman icon shows heading, relative position, and altitude difference
-- Created by Claude based on draw_targets.lua

require("graphics")

-- Minimal JSON parser for simple structures (arrays, objects, strings, numbers, booleans)
local function parse_json(str)
  local pos = 1
  local function skip_whitespace()
    while pos <= #str and str:sub(pos, pos):match("%s") do pos = pos + 1 end
  end
  local function parse_value()
    skip_whitespace()
    local c = str:sub(pos, pos)
    if c == '"' then
      -- Parse string
      pos = pos + 1
      local start = pos
      while pos <= #str and str:sub(pos, pos) ~= '"' do
        if str:sub(pos, pos) == '\\' then pos = pos + 1 end
        pos = pos + 1
      end
      local value = str:sub(start, pos - 1)
      pos = pos + 1
      return value
    elseif c == '{' then
      -- Parse object
      pos = pos + 1
      local obj = {}
      skip_whitespace()
      if str:sub(pos, pos) == '}' then pos = pos + 1; return obj end
      while true do
        skip_whitespace()
        local key = parse_value()
        skip_whitespace()
        pos = pos + 1  -- Skip ':'
        obj[key] = parse_value()
        skip_whitespace()
        if str:sub(pos, pos) == '}' then pos = pos + 1; break end
        pos = pos + 1  -- Skip ','
      end
      return obj
    elseif c == '[' then
      -- Parse array
      pos = pos + 1
      local arr = {}
      skip_whitespace()
      if str:sub(pos, pos) == ']' then pos = pos + 1; return arr end
      while true do
        arr[#arr + 1] = parse_value()
        skip_whitespace()
        if str:sub(pos, pos) == ']' then pos = pos + 1; break end
        pos = pos + 1  -- Skip ','
      end
      return arr
    elseif c == 't' then
      pos = pos + 4; return true
    elseif c == 'f' then
      pos = pos + 5; return false
    elseif c == 'n' then
      pos = pos + 4; return nil
    else
      -- Parse number
      local start = pos
      while pos <= #str and str:sub(pos, pos):match("[%d%.%-eE%+]") do pos = pos + 1 end
      return tonumber(str:sub(start, pos - 1))
    end
  end
  return parse_value()
end

-- Track mission number for reload detection
local last_fire_layout = nil

-- Function to load fire targets from JSON file
local function load_fire_targets(mission_num)
  local targets = {}
  local json_path = SYSTEM_DIRECTORY .. "Resources/plugins/HAATO_assets/fire_targets_mission" .. mission_num .. ".json"

  local file = io.open(json_path, "r")
  if not file then
    logMsg("FlyWithLua Target Renderer: Could not open " .. json_path)
    return nil
  end

  local content = file:read("*all")
  file:close()

  local data = parse_json(content)
  if not data or not data.dataPoints then
    logMsg("FlyWithLua Target Renderer: Failed to parse JSON or missing dataPoints")
    return nil
  end

  for i, point in ipairs(data.dataPoints) do
    targets[#targets + 1] = {
      lat = point.latitude,
      lon = point.longitude,
      alt = point.altitude,
      type = point.type,
      object_type = "target",
      tid = tostring(i - 1)
    }
  end

  logMsg("FlyWithLua Target Renderer: Loaded " .. #targets .. " targets from mission " .. mission_num)
  return targets
end

-- CONFIG: Define different types of objects to render
local render_objects = {
  -- Targets/Fires (loaded dynamically from JSON based on fire_layout)
  targets = {},

  -- Static Points of Interest (always visible)
  static_pois = {
    -- Skykomish Airport
    { lat = 47.71044513620272, lon = -121.34287916904042, alt = 299.4, type = "airport", object_type = "airport", name = "Skykomish Airport" },
  }
}

-- Access array datarefs using bracket notation
-- These are now FloatArray datarefs created in custom_datarefs.lua
local status_dref = dataref_table("custom/haato/target_status")
local classification_dref = dataref_table("custom/haato/target_classification")

-- Bind to the aircraft's local OpenGL coordinates
dataref("plane_x", "sim/flightmodel/position/local_x", "readonly")
dataref("plane_y", "sim/flightmodel/position/local_y", "readonly")
dataref("plane_z", "sim/flightmodel/position/local_z", "readonly")
dataref("plane_lat", "sim/flightmodel/position/latitude", "readonly")
dataref("plane_lon", "sim/flightmodel/position/longitude", "readonly")
dataref("plane_alt", "sim/flightmodel/position/elevation", "readonly")
dataref("plane_heading", "sim/flightmodel/position/psi", "readonly")  -- Human's heading

dataref("icons_visible", "custom/haato/icons_visible", "readonly")
dataref("fire_layout", "custom/haato/fire_layout", "readonly")

-- VR detection dataref
dataref("vr_enabled", "sim/graphics/VR/enabled", "readonly")

-- Screen dimensions (for non-VR mode)
dataref("window_w", "sim/graphics/view/window_width", "readonly")
dataref("window_h", "sim/graphics/view/window_height", "readonly")

-- Transform matrices - bind as arrays
local world_matrix = dataref_table("sim/graphics/view/world_matrix")
local proj_matrix = dataref_table("sim/graphics/view/projection_matrix_3d")

-- Head pose datarefs for VR counter-rotation
dataref("pilot_head_psi", "sim/graphics/view/pilots_head_psi", "readonly")
dataref("pilot_head_the", "sim/graphics/view/pilots_head_the", "readonly")
dataref("pilot_head_phi", "sim/graphics/view/pilots_head_phi", "readonly")

-- Wingman datarefs
dataref("wingman_heading", "custom/haato/wingman_hdg", "readonly")  -- Wingman's heading

-- Global variables for window management (VR mode)
local vr_window = nil
local vr_window_width = 2560
local vr_window_height = 2560
local current_mode = nil  -- Track current rendering mode
local last_vr_state = nil  -- Track previous VR state for change detection

-- Precompute world coordinates for all objects
local objects_world = {
  targets = {},
  static_pois = {}
}

-- Helper function to convert lat/lon to local X-Plane coordinates
local function latlon_to_local(target_lat, target_lon, target_alt)
  local earth_radius = 6378137.0 -- meters

  -- Convert to radians
  local lat1 = math.rad(plane_lat)
  local lon1 = math.rad(plane_lon)
  local lat2 = math.rad(target_lat)
  local lon2 = math.rad(target_lon)

  -- Calculate differences
  local dlat = lat2 - lat1
  local dlon = lon2 - lon1

  -- Convert to local meters (approximate for small distances)
  local dx = dlon * earth_radius * math.cos(lat1)  -- East (positive X in OpenGL)
  local dz = -dlat * earth_radius                  -- North (negative Z in OpenGL)
  local dy = target_alt - get("sim/flightmodel/position/elevation") -- Up (positive Y)

  -- Add to current aircraft position to get world coordinates
  local world_x = plane_x + dx
  local world_y = plane_y + dy
  local world_z = plane_z + dz

  return world_x, world_y, world_z
end

-- 4x4 matrix multiplication with vec4
local function mult_matrix_vec4(m, v)
  local result = {}
  result[1] = v[1]*m[0] + v[2]*m[4] + v[3]*m[8]  + v[4]*m[12]
  result[2] = v[1]*m[1] + v[2]*m[5] + v[3]*m[9]  + v[4]*m[13]
  result[3] = v[1]*m[2] + v[2]*m[6] + v[3]*m[10] + v[4]*m[14]
  result[4] = v[1]*m[3] + v[2]*m[7] + v[3]*m[11] + v[4]*m[15]
  return result
end

-- Transform world coordinates to screen coordinates
local function world_to_screen(world_x, world_y, world_z, win_w, win_h)
  -- Use window dimensions if provided, otherwise use global screen dimensions
  local screen_w = win_w or window_w
  local screen_h = win_h or window_h

  -- Create world position vector
  local world_pos = {world_x, world_y, world_z, 1.0}

  -- Transform through model-view matrix
  local eye_pos = mult_matrix_vec4(world_matrix, world_pos)

  -- Transform through projection matrix
  local clip_pos = mult_matrix_vec4(proj_matrix, eye_pos)

  -- Perspective divide
  if clip_pos[4] == 0 then return nil end
  local w_inv = 1.0 / clip_pos[4]
  local ndc_x = clip_pos[1] * w_inv
  local ndc_y = clip_pos[2] * w_inv
  local ndc_z = clip_pos[3] * w_inv

  -- Check if point is behind camera or outside frustum
  if ndc_z < -1.0 or ndc_z > 1.0 then return nil end
  if ndc_x < -1.2 or ndc_x > 1.2 or ndc_y < -1.2 or ndc_y > 1.2 then return nil end

  -- Convert NDC to screen coordinates
  local screen_x = screen_w * (ndc_x * 0.5 + 0.5)
  local screen_y = screen_h * (ndc_y * 0.5 + 0.5)

  return screen_x, screen_y
end

local function update_world_coordinates()
  -- Update target world coordinates
  for i, obj in ipairs(render_objects.targets) do
    local wx, wy, wz = latlon_to_local(obj.lat, obj.lon, obj.alt)
    objects_world.targets[i] = {
      x = wx, y = wy, z = wz,
      type = obj.type,
      object_type = obj.object_type
    }
  end

  -- Update static POI world coordinates
  for i, obj in ipairs(render_objects.static_pois) do
    local wx, wy, wz = latlon_to_local(obj.lat, obj.lon, obj.alt)
    objects_world.static_pois[i] = {
      x = wx, y = wy, z = wz,
      type = obj.type,
      object_type = obj.object_type,
      name = obj.name
    }
  end
end

-- Helper function to get roll angle for VR counter-rotation
-- Returns the roll angle in degrees
local function get_vr_roll_angle()
  -- In VR, use the pilot's head roll (phi = roll around longitudinal axis)
  -- Negative because we want to counter-rotate
  return pilot_head_phi
end

-- Helper function to rotate a point around a center by an angle
-- angle_deg: rotation angle in degrees (positive = counter-clockwise)
-- Returns rotated x, y coordinates
local function rotate_point(x, y, center_x, center_y, angle_deg)
  -- Convert angle to radians
  local angle_rad = math.rad(angle_deg)

  -- Translate point to origin
  local translated_x = x - center_x
  local translated_y = y - center_y

  -- Apply rotation
  local cos_angle = math.cos(angle_rad)
  local sin_angle = math.sin(angle_rad)
  local rotated_x = translated_x * cos_angle - translated_y * sin_angle
  local rotated_y = translated_x * sin_angle + translated_y * cos_angle

  -- Translate back
  return rotated_x + center_x, rotated_y + center_y
end

-- Helper function to calculate distance between two lat/lon points
local function calculate_distance(lat1, lon1, alt1, lat2, lon2, alt2)
  local earth_radius = 6378137.0 -- meters

  -- Convert to radians
  local lat1_rad = math.rad(lat1)
  local lon1_rad = math.rad(lon1)
  local lat2_rad = math.rad(lat2)
  local lon2_rad = math.rad(lon2)

  -- Haversine formula for great circle distance
  local dlat = lat2_rad - lat1_rad
  local dlon = lon2_rad - lon1_rad

  local a = math.sin(dlat/2)^2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)^2
  local c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
  local horizontal_distance = earth_radius * c

  -- Calculate altitude difference
  local alt_diff = alt2 - alt1

  -- Calculate 3D distance
  local distance_3d = math.sqrt(horizontal_distance^2 + alt_diff^2)

  return distance_3d
end

-- Helper function to calculate bearing from point 1 to point 2
-- Returns bearing in degrees (0-360, where 0 = North, 90 = East)
local function calculate_bearing(lat1, lon1, lat2, lon2)
  -- Convert to radians
  local lat1_rad = math.rad(lat1)
  local lon1_rad = math.rad(lon1)
  local lat2_rad = math.rad(lat2)
  local lon2_rad = math.rad(lon2)

  local dlon = lon2_rad - lon1_rad

  -- Calculate bearing using atan2
  local y = math.sin(dlon) * math.cos(lat2_rad)
  local x = math.cos(lat1_rad) * math.sin(lat2_rad) -
            math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(dlon)

  local bearing_rad = math.atan2(y, x)
  local bearing_deg = math.deg(bearing_rad)

  -- Normalize to 0-360
  bearing_deg = (bearing_deg + 360) % 360

  return bearing_deg
end

-- Helper function to normalize angle difference to -180 to +180
local function normalize_angle_diff(angle)
  while angle > 180 do
    angle = angle - 360
  end
  while angle < -180 do
    angle = angle + 360
  end
  return angle
end

-- Function to get color and visibility based on object type and status
local function get_rendering_properties(object_type, marker_type, status)
  if object_type == "target" then
    if status == 0.0 then
      return 0.4, 0.4, 0.4, 1.0 -- Grey for unspotted
    elseif status >= 1.0 and status < 2.0 then
      -- Progress-based coloring for active targets
      if status >= 1.75 then
        return 1.0, 1.0, 0.2, 1.0   -- Bright yellow for nearly complete
      elseif status >= 1.5 then
        return 1.0, 1.0, 0.0, 1.0   -- Yellow for half complete
      elseif status >= 1.25 then
        return 1.0, 0.8, 0.0, 1.0   -- Orange-yellow for quarter complete
      else
        if marker_type == "severe" then
          return 1.0, 0.0, 0.0, 1.0    -- Red for severe fires just started
        else
          return 1.0, 0.65, 0.0, 1.0   -- Orange for moderate fires just started
        end
      end
    elseif status == 2.0 then
      return 0.0, 0.6, 1.0, 1.0      -- Blue for extinguished
    else
      return 0.4, 0.4, 0.4, 0.5      -- Gray with transparency
    end
  elseif object_type == "airport" then
    return 0.0, 1.0, 0.0, 1.0        -- Green for airports
  elseif object_type == "helipad" then
    return 0.0, 0.8, 1.0, 1.0        -- Cyan for helipads
  elseif object_type == "waypoint" then
    return 1.0, 1.0, 0.0, 1.0        -- Yellow for waypoints
  elseif object_type == "base" then
    return 0.5, 0.0, 1.0, 1.0        -- Purple for bases
  elseif object_type == "wingman" then
    return 0.0, 0.8, 0.2, 1.0        -- Bright green for wingman
  else
    return 0.8, 0.8, 0.8, 1.0        -- Light gray for unknown types
  end
end

-- Alternative progress arc using triangular segments
local function draw_progress_arc(px, py, radius, progress, r, g, b, a)
  if progress <= 0 then return end

  progress = math.max(0, math.min(1, progress))
  graphics.set_color(r, g, b, a)

  -- Number of segments for smooth arc
  local segments = math.max(3, math.floor(progress * 32))
  local angle_per_segment = (2 * math.pi * progress) / segments
  local start_angle_rad = math.rad(270) -- Start from top

  -- Draw triangular segments to create filled arc
  for i = 0, segments - 1 do
    local angle1 = start_angle_rad + (i * angle_per_segment)
    local angle2 = start_angle_rad + ((i + 1) * angle_per_segment)

    local x1 = px + radius * math.cos(angle1)
    local y1 = py + radius * math.sin(angle1)
    local x2 = px + radius * math.cos(angle2)
    local y2 = py + radius * math.sin(angle2)

    -- Draw triangle from center to arc edge
    glBegin_TRIANGLES()
    glVertex2f(px, py)      -- Center point
    glVertex2f(x1, y1)      -- First arc point
    glVertex2f(x2, y2)      -- Second arc point
    glEnd()
  end
end

-- Function to draw dynamic wingman aircraft icon with orientation and altitude indicators
-- px, py: screen position
-- r, g, b, a: color
-- rotation_angle: VR counter-rotation angle
-- wingman_heading_angle: wingman's actual heading (for rotating the aircraft icon)
-- relative_bearing_angle: direction TO the wingman from human (for position indicator)
-- altitude_diff: altitude difference in meters (positive = wingman above, negative = below)
local function draw_wingman_dynamic(px, py, r, g, b, a, rotation_angle, wingman_heading_angle, relative_bearing_angle, altitude_diff)
  rotation_angle = rotation_angle or 0
  wingman_heading_angle = wingman_heading_angle or 0
  relative_bearing_angle = relative_bearing_angle or 0
  altitude_diff = altitude_diff or 0

  -- Combined rotation: wingman's heading relative to human + VR counter-rotation
  local total_rotation = wingman_heading_angle + rotation_angle

  -- === DRAW RELATIVE POSITION INDICATOR (Outer Chevron/Arc) ===
  -- This shows WHERE the wingman is relative to you
  graphics.set_color(r * 0.6, g * 0.6, b * 0.6, a)  -- Dimmer color for outer indicator
  graphics.set_width(3)

  local bearing_rotation = relative_bearing_angle + rotation_angle
  local chevron_distance = 25  -- Distance from center to chevron point
  local chevron_width = 8      -- Half-width of chevron

  -- Calculate chevron points (pointing toward wingman's position)
  local chevron_tip_x, chevron_tip_y = rotate_point(px, py - chevron_distance, px, py, bearing_rotation)
  local chevron_left_x, chevron_left_y = rotate_point(px - chevron_width, py - chevron_distance + 6, px, py, bearing_rotation)
  local chevron_right_x, chevron_right_y = rotate_point(px + chevron_width, py - chevron_distance + 6, px, py, bearing_rotation)

  graphics.draw_line(chevron_left_x, chevron_left_y, chevron_tip_x, chevron_tip_y)
  graphics.draw_line(chevron_right_x, chevron_right_y, chevron_tip_x, chevron_tip_y)

  -- === DRAW ALTITUDE INDICATOR ===
  -- Show if wingman is above or below with triangles
  local alt_indicator_offset = 30  -- Distance from center
  local alt_threshold_meters = 30  -- Minimum altitude difference to show indicator (about 100 feet)

  if math.abs(altitude_diff) > alt_threshold_meters then
    local alt_color_intensity = math.min(1.0, math.abs(altitude_diff) / 300)  -- Scale up to 300m difference
    graphics.set_color(1.0, 1.0, 0.0, alt_color_intensity)  -- Yellow with variable intensity
    graphics.set_width(2)

    if altitude_diff > 0 then
      -- Wingman is ABOVE - draw upward triangle
      local tri_top_x, tri_top_y = px, py - alt_indicator_offset
      local tri_left_x, tri_left_y = px - 5, py - alt_indicator_offset + 7
      local tri_right_x, tri_right_y = px + 5, py - alt_indicator_offset + 7

      graphics.draw_line(tri_left_x, tri_left_y, tri_top_x, tri_top_y)
      graphics.draw_line(tri_right_x, tri_right_y, tri_top_x, tri_top_y)
      graphics.draw_line(tri_left_x, tri_left_y, tri_right_x, tri_right_y)
    else
      -- Wingman is BELOW - draw downward triangle
      local tri_bottom_x, tri_bottom_y = px, py + alt_indicator_offset
      local tri_left_x, tri_left_y = px - 5, py + alt_indicator_offset - 7
      local tri_right_x, tri_right_y = px + 5, py + alt_indicator_offset - 7

      graphics.draw_line(tri_left_x, tri_left_y, tri_bottom_x, tri_bottom_y)
      graphics.draw_line(tri_right_x, tri_right_y, tri_bottom_x, tri_bottom_y)
      graphics.draw_line(tri_left_x, tri_left_y, tri_right_x, tri_right_y)
    end
  end

  -- === DRAW AIRCRAFT ICON (showing wingman's heading) ===
  graphics.set_color(0, 0, 0, 1)  -- black outline
  graphics.set_width(3)

  -- Draw aircraft body (main fuselage line) - rotated to wingman's heading
  local body_x1, body_y1 = rotate_point(px, py-18, px, py, total_rotation)
  local body_x2, body_y2 = rotate_point(px, py+18, px, py, total_rotation)
  graphics.draw_line(body_x1, body_y1, body_x2, body_y2)

  -- Draw wings (horizontal line) - rotated to wingman's heading
  local wing_x1, wing_y1 = rotate_point(px-15, py-3, px, py, total_rotation)
  local wing_x2, wing_y2 = rotate_point(px+15, py-3, px, py, total_rotation)
  graphics.draw_line(wing_x1, wing_y1, wing_x2, wing_y2)

  -- Draw tail (smaller horizontal line at back) - rotated to wingman's heading
  local tail_x1, tail_y1 = rotate_point(px-8, py+15, px, py, total_rotation)
  local tail_x2, tail_y2 = rotate_point(px+8, py+15, px, py, total_rotation)
  graphics.draw_line(tail_x1, tail_y1, tail_x2, tail_y2)

  -- Draw nose cone (small triangle at front) - rotated to wingman's heading
  local nose_x1, nose_y1 = rotate_point(px-3, py-18, px, py, total_rotation)
  local nose_x2, nose_y2 = rotate_point(px, py-22, px, py, total_rotation)
  local nose_x3, nose_y3 = rotate_point(px+3, py-18, px, py, total_rotation)
  graphics.draw_line(nose_x1, nose_y1, nose_x2, nose_y2)
  graphics.draw_line(nose_x3, nose_y3, nose_x2, nose_y2)

  -- Now draw the colored version on top
  graphics.set_color(r, g, b, a)
  graphics.set_width(2)

  -- Aircraft body - rotated to wingman's heading
  local body2_x1, body2_y1 = rotate_point(px, py-17, px, py, total_rotation)
  local body2_x2, body2_y2 = rotate_point(px, py+17, px, py, total_rotation)
  graphics.draw_line(body2_x1, body2_y1, body2_x2, body2_y2)

  -- Wings - rotated to wingman's heading
  local wing2_x1, wing2_y1 = rotate_point(px-14, py-3, px, py, total_rotation)
  local wing2_x2, wing2_y2 = rotate_point(px+14, py-3, px, py, total_rotation)
  graphics.draw_line(wing2_x1, wing2_y1, wing2_x2, wing2_y2)

  -- Tail - rotated to wingman's heading
  local tail2_x1, tail2_y1 = rotate_point(px-7, py+15, px, py, total_rotation)
  local tail2_x2, tail2_y2 = rotate_point(px+7, py+15, px, py, total_rotation)
  graphics.draw_line(tail2_x1, tail2_y1, tail2_x2, tail2_y2)

  -- Nose - rotated to wingman's heading
  local nose2_x1, nose2_y1 = rotate_point(px-2, py-17, px, py, total_rotation)
  local nose2_x2, nose2_y2 = rotate_point(px, py-21, px, py, total_rotation)
  local nose2_x3, nose2_y3 = rotate_point(px+2, py-17, px, py, total_rotation)
  graphics.draw_line(nose2_x1, nose2_y1, nose2_x2, nose2_y2)
  graphics.draw_line(nose2_x3, nose2_y3, nose2_x2, nose2_y2)

  -- Add center dot for visibility (circles don't need rotation)
  graphics.set_color(1, 1, 1, 1)  -- white center
  graphics.draw_filled_circle(px, py, 3)
  graphics.set_color(r, g, b, a)  -- colored border
  graphics.draw_circle(px, py, 3, 1)
end

-- Function to draw wingman aircraft icon (legacy version for backward compatibility)
local function draw_wingman(px, py, r, g, b, a, rotation_angle)
  rotation_angle = rotation_angle or 0
  graphics.set_color(0, 0, 0, 1)  -- black outline
  graphics.set_width(3)

  -- Draw aircraft body (main fuselage line) - rotated
  local body_x1, body_y1 = rotate_point(px, py-18, px, py, rotation_angle)
  local body_x2, body_y2 = rotate_point(px, py+18, px, py, rotation_angle)
  graphics.draw_line(body_x1, body_y1, body_x2, body_y2)

  -- Draw wings (horizontal line) - rotated
  local wing_x1, wing_y1 = rotate_point(px-15, py-3, px, py, rotation_angle)
  local wing_x2, wing_y2 = rotate_point(px+15, py-3, px, py, rotation_angle)
  graphics.draw_line(wing_x1, wing_y1, wing_x2, wing_y2)

  -- Draw tail (smaller horizontal line at back) - rotated
  local tail_x1, tail_y1 = rotate_point(px-8, py+15, px, py, rotation_angle)
  local tail_x2, tail_y2 = rotate_point(px+8, py+15, px, py, rotation_angle)
  graphics.draw_line(tail_x1, tail_y1, tail_x2, tail_y2)

  -- Draw nose cone (small triangle at front) - rotated
  local nose_x1, nose_y1 = rotate_point(px-3, py-18, px, py, rotation_angle)
  local nose_x2, nose_y2 = rotate_point(px, py-22, px, py, rotation_angle)
  local nose_x3, nose_y3 = rotate_point(px+3, py-18, px, py, rotation_angle)
  graphics.draw_line(nose_x1, nose_y1, nose_x2, nose_y2)
  graphics.draw_line(nose_x3, nose_y3, nose_x2, nose_y2)

  -- Now draw the colored version on top
  graphics.set_color(r, g, b, a)
  graphics.set_width(2)

  -- Aircraft body - rotated
  local body2_x1, body2_y1 = rotate_point(px, py-17, px, py, rotation_angle)
  local body2_x2, body2_y2 = rotate_point(px, py+17, px, py, rotation_angle)
  graphics.draw_line(body2_x1, body2_y1, body2_x2, body2_y2)

  -- Wings - rotated
  local wing2_x1, wing2_y1 = rotate_point(px-14, py-3, px, py, rotation_angle)
  local wing2_x2, wing2_y2 = rotate_point(px+14, py-3, px, py, rotation_angle)
  graphics.draw_line(wing2_x1, wing2_y1, wing2_x2, wing2_y2)

  -- Tail - rotated
  local tail2_x1, tail2_y1 = rotate_point(px-7, py+15, px, py, rotation_angle)
  local tail2_x2, tail2_y2 = rotate_point(px+7, py+15, px, py, rotation_angle)
  graphics.draw_line(tail2_x1, tail2_y1, tail2_x2, tail2_y2)

  -- Nose - rotated
  local nose2_x1, nose2_y1 = rotate_point(px-2, py-17, px, py, rotation_angle)
  local nose2_x2, nose2_y2 = rotate_point(px, py-21, px, py, rotation_angle)
  local nose2_x3, nose2_y3 = rotate_point(px+2, py-17, px, py, rotation_angle)
  graphics.draw_line(nose2_x1, nose2_y1, nose2_x2, nose2_y2)
  graphics.draw_line(nose2_x3, nose2_y3, nose2_x2, nose2_y2)

  -- Add center dot for visibility (circles don't need rotation)
  graphics.set_color(1, 1, 1, 1)  -- white center
  graphics.draw_filled_circle(px, py, 3)
  graphics.set_color(r, g, b, a)  -- colored border
  graphics.draw_circle(px, py, 3, 1)
end

-- Function to draw different object types
-- rotation_angle: counter-rotation angle in degrees for VR (0 = no rotation)
local function draw_object(px, py, object_type, marker_type, r, g, b, a, status, rotation_angle)
  rotation_angle = rotation_angle or 0  -- Default to no rotation
  graphics.set_color(r, g, b, a)

  if object_type == "target" then
    if status == 2 then
      -- extinguished targets - render with blue styling and X mark (smaller size)
      graphics.set_color(0, 0, 0, 1)  -- black outline
      graphics.draw_circle(px, py, 10, 2)

      graphics.set_color(r, g, b, a)  -- blue fill
      graphics.draw_filled_circle(px, py, 8)

      -- add "X" mark to indicate extinguished (smaller)
      graphics.set_color(1, 1, 1, 1)  -- white X
      graphics.set_width(2)
      -- Rotate X mark coordinates if needed
      local x1_1, y1_1 = rotate_point(px-5, py-5, px, py, rotation_angle)
      local x1_2, y1_2 = rotate_point(px+5, py+5, px, py, rotation_angle)
      local x2_1, y2_1 = rotate_point(px-5, py+5, px, py, rotation_angle)
      local x2_2, y2_2 = rotate_point(px+5, py-5, px, py, rotation_angle)
      graphics.draw_line(x1_1, y1_1, x1_2, y1_2)
      graphics.draw_line(x2_1, y2_1, x2_2, y2_2)
    elseif status >= 1.0 and status < 2.0 then
      -- Active targets with progress fill
      -- Draw outer black outline
      graphics.set_color(0, 0, 0, 1)
      graphics.draw_circle(px, py, 15, 2)

      -- Draw empty background (gray)
      graphics.set_color(0.3, 0.3, 0.3, 1.0)
      graphics.draw_filled_circle(px, py, 13)

      -- Calculate progress from status value
      local progress = (status - 1.0) / 0.75  -- Convert 1.0-1.75 range to 0-1
      progress = math.max(0, math.min(1, progress))  -- Clamp to 0-1 range

      -- Draw progress arc, ignore errors
      pcall(draw_progress_arc, px, py, 13, progress, r, g, b, a)

      -- Draw white center dot for visibility
      graphics.set_color(1, 1, 1, 1)
      graphics.draw_filled_circle(px, py, 3)
    else
      -- Undetected or other states - simple filled circle
      graphics.set_color(0, 0, 0, 1)  -- black outline
      graphics.draw_circle(px, py, 15, 2)

      graphics.set_color(r, g, b, a)  -- colored fill
      graphics.draw_filled_circle(px, py, 13)

      graphics.set_color(1, 1, 1, 1)  -- white center dot
      graphics.draw_filled_circle(px, py, 3)
    end
  elseif object_type == "wingman" then
    draw_wingman(px, py, r, g, b, a, rotation_angle)
  elseif object_type == "airport" then
    -- Draw airport as diamond
    graphics.set_color(0, 0, 0, 1)  -- black outline
    graphics.set_width(2)
    -- Rotate diamond coordinates
    local d1_x, d1_y = rotate_point(px, py-15, px, py, rotation_angle)
    local d2_x, d2_y = rotate_point(px+12, py, px, py, rotation_angle)
    local d3_x, d3_y = rotate_point(px, py+15, px, py, rotation_angle)
    local d4_x, d4_y = rotate_point(px-12, py, px, py, rotation_angle)
    graphics.draw_line(d1_x, d1_y, d2_x, d2_y)
    graphics.draw_line(d2_x, d2_y, d3_x, d3_y)
    graphics.draw_line(d3_x, d3_y, d4_x, d4_y)
    graphics.draw_line(d4_x, d4_y, d1_x, d1_y)

    graphics.set_color(r, g, b, a)  -- green fill
    -- Rotate triangle coordinates
    local t1_x1, t1_y1 = rotate_point(px, py-13, px, py, rotation_angle)
    local t1_x2, t1_y2 = rotate_point(px+10, py, px, py, rotation_angle)
    local t1_x3, t1_y3 = rotate_point(px, py+13, px, py, rotation_angle)
    local t2_x3, t2_y3 = rotate_point(px-10, py, px, py, rotation_angle)
    graphics.draw_triangle(t1_x1, t1_y1, t1_x2, t1_y2, t1_x3, t1_y3)
    graphics.draw_triangle(t1_x1, t1_y1, t1_x3, t1_y3, t2_x3, t2_y3)
  else
    -- Default rendering for other types
    graphics.set_color(0, 0, 0, 1)  -- black outline
    graphics.draw_circle(px, py, 12, 2)

    graphics.set_color(r, g, b, a)  -- colored fill
    graphics.draw_filled_circle(px, py, 10)
  end
end

-- Core rendering logic (shared between VR and non-VR modes)
function render_targets(base_x, base_y, is_vr_mode)
  -- Update world coordinates
  update_world_coordinates()

  -- Determine screen dimensions and text drawing function
  local screen_w, screen_h
  if is_vr_mode then
    screen_w = vr_window_width
    screen_h = vr_window_height
  else
    screen_w = window_w
    screen_h = window_h
  end

  -- Get roll angle for VR counter-rotation
  local roll_angle = 0
  if is_vr_mode then
    roll_angle = get_vr_roll_angle()
  end

  -- Draw targets with dynamic status
  for i, target in ipairs(objects_world.targets) do
    -- Access array elements using 0-based indexing (i-1 because ipairs is 1-based)
    local status = status_dref[i-1]
    local classification = classification_dref[i-1]

    -- Determine display type based on classification dataref
    local display_type = target.type  -- Default to true type
    if classification == 1.0 then
      display_type = "moderate"
    elseif classification == 2.0 then
      display_type = "severe"
    end

    local r, g, b, a = get_rendering_properties(target.object_type, display_type, status)

    if r then  -- Only draw if visible
      local screen_x, screen_y = world_to_screen(target.x, target.y, target.z, screen_w, screen_h)

      if screen_x and screen_y then
        -- Convert to final screen coordinates
        local final_x = base_x + screen_x
        local final_y = base_y + screen_y

        -- Pass rotation angle to draw_object for VR counter-rotation
        local obj_rotation = 0
        if is_vr_mode and roll_angle ~= 0 then
          obj_rotation = roll_angle
        end

        draw_object(final_x, final_y, target.object_type, display_type, r, g, b, a, status, obj_rotation)

        -- Display progress information
        local distance = calculate_distance(plane_lat, plane_lon, plane_alt,
                                  render_objects.targets[i].lat,
                                  render_objects.targets[i].lon,
                                  render_objects.targets[i].alt)
        local distance_nmi = distance / (1000*1.852)

        -- Show progress percentage for active targets
        local text = "error"

        -- Format distance with appropriate precision
        local dist_format = distance_nmi < 0.5 and "%.2fmi" or "%.1fmi"

        if status >= 1.0 and status < 2.0 then
          local progress = (status - 1.0) / 0.75 * 100  -- Convert to percentage

          -- Use classification dataref instead of true fire type
          if classification == 2.0 then
            text = string.format("T%d: %.0f%% (" .. dist_format .. ") SVR (2 req'd)", i-1, progress, distance_nmi)
          elseif classification == 1.0 then
            text = string.format("T%d: %.0f%% (" .. dist_format .. ") MODRT (1 req'd)", i-1, progress, distance_nmi)
          elseif classification == 0.0 then
            text = string.format("T%d: %.0f%% (" .. dist_format .. ") unclassified", i-1, progress, distance_nmi)
          else
            text = string.format("T%d: %.0f%% (" .. dist_format .. ") type unknown", i-1, progress, distance_nmi)
          end
        elseif status == 0.0 then
          text = string.format("T%d: unknown (" .. dist_format .. ")", i-1, distance_nmi)
        elseif status == 2.0 then
          text = ""--string.format("done (%.1fmi)", distance_nmi)
        else
          text = status --string.format("(%.1fmi) error", distance_nmi)
        end

        -- Calculate text position (no rotation to keep text upright in VR)
        local text_x = final_x + 18
        local text_y = final_y - 5

        if is_vr_mode then
          draw_string(text_x, text_y, text, 0, 0, 0)
        else
          graphics.draw_string_Helvetica_18(text_x, text_y, text, "black")
        end
      end
    end
  end

  -- Draw static POIs (always visible)
  for i, poi in ipairs(objects_world.static_pois) do
    local r, g, b, a = get_rendering_properties(poi.object_type, poi.type, 1.0)

    if r then
      local screen_x, screen_y = world_to_screen(poi.x, poi.y, poi.z, screen_w, screen_h)

      if screen_x and screen_y then
        -- Convert to final screen coordinates
        local final_x = base_x + screen_x
        local final_y = base_y + screen_y

        -- Pass rotation angle to draw_object for VR counter-rotation
        local obj_rotation = 0
        if is_vr_mode and roll_angle ~= 0 then
          obj_rotation = roll_angle
        end

        draw_object(final_x, final_y, poi.object_type, poi.type, r, g, b, a, 1.0, obj_rotation)

        local distance = calculate_distance(plane_lat, plane_lon, plane_alt,
                                  render_objects.static_pois[i].lat,
                                  render_objects.static_pois[i].lon,
                                  render_objects.static_pois[i].alt)
        local distance_nmi = distance / (1000*1.852)
        local text = string.format("%s (%.1fmi)", poi.name, distance_nmi)

        -- Calculate text position (no rotation to keep text upright in VR)
        local text_x = final_x + 18
        local text_y = final_y - 5

        if is_vr_mode then
          draw_string(text_x, text_y, text, 0, 0, 0)
        else
          graphics.draw_string_Helvetica_18(text_x, text_y, text, "black")
        end
      end
    end
  end

  -- === DRAW DYNAMIC WINGMAN WITH ORIENTATION AND POSITION INDICATORS ===
  local wingman_lat = get("custom/haato/wingman_lat")
  local wingman_lon = get("custom/haato/wingman_long")
  local wingman_alt = get("custom/haato/wingman_alt")

  -- Only render if we have valid coordinates (non-zero)
  if wingman_lat ~= 0.0 and wingman_lon ~= 0.0 then
    local wx, wy, wz = latlon_to_local(wingman_lat, wingman_lon, wingman_alt)
    local screen_x, screen_y = world_to_screen(wx, wy, wz, screen_w, screen_h)

    if screen_x and screen_y then
      -- Convert to final screen coordinates
      local final_x = base_x + screen_x
      local final_y = base_y + screen_y

      -- Calculate wingman's heading relative to human's heading
      local wingman_hdg = get("custom/haato/wingman_hdg")
      local human_hdg = plane_heading
      local relative_heading = normalize_angle_diff(wingman_hdg - human_hdg)

      -- Calculate bearing from human to wingman
      local bearing_to_wingman = calculate_bearing(plane_lat, plane_lon, wingman_lat, wingman_lon)
      local relative_bearing = normalize_angle_diff(bearing_to_wingman - human_hdg)

      -- Calculate altitude difference
      local altitude_diff = wingman_alt - plane_alt

      -- VR counter-rotation
      local obj_rotation = 0
      if is_vr_mode and roll_angle ~= 0 then
        obj_rotation = roll_angle
      end

      local r, g, b, a = get_rendering_properties("wingman", "wingman", 1.0)

      -- Use the new dynamic wingman drawing function
      draw_wingman_dynamic(final_x, final_y, r, g, b, a, obj_rotation, relative_heading, relative_bearing, altitude_diff)

      local distance = calculate_distance(plane_lat, plane_lon, plane_alt, wingman_lat, wingman_lon, wingman_alt)
      local distance_nmi = distance / (1000*1.852)

      -- Enhanced text with altitude information
      local alt_diff_ft = altitude_diff * 3.28084  -- Convert meters to feet
      local alt_text = ""
      if math.abs(alt_diff_ft) > 100 then  -- Only show if difference > 100ft
        if alt_diff_ft > 0 then
          alt_text = string.format(" ▲%.0fft", alt_diff_ft)
        else
          alt_text = string.format(" ▼%.0fft", math.abs(alt_diff_ft))
        end
      end

      local text = string.format("Wingman (%.1fmi%s)", distance_nmi, alt_text)

      -- Calculate text position (no rotation to keep text upright in VR)
      local text_x = final_x + 35  -- Further offset due to larger icon
      local text_y = final_y - 5

      if is_vr_mode then
        draw_string(text_x, text_y, text, 0, 250, 0)
      else
        graphics.draw_string_Helvetica_18(text_x, text_y, text, "green")
      end
    end
  end
end

-- Unified drawing function that works in both VR and non-VR
function draw_targets_unified()
  local is_vr = (vr_enabled == 1)

  if is_vr then
    -- In VR mode, drawing is handled by the floating window callback
    -- This function doesn't need to do anything
  else
    -- In 2D mode, render directly to screen
    render_targets(0, 0, false)
  end
end

-- VR window drawing callback
function draw_vr_window(wnd, x, y)
  -- Use the existing render_targets function but for the floating window
  -- x, y are the absolute screen coordinates of the window's lower left corner
  render_targets(x, y, true) -- true indicates VR mode
end

-- VR Mode: Initialize VR mode with floating window
function initialize_vr_mode()
  logMsg("FlyWithLua Target Renderer: Initializing VR mode with floating window")

  -- Create floating window for VR
  vr_window = float_wnd_create(vr_window_width, vr_window_height, 0, false)
  float_wnd_set_title(vr_window, "Target Display")
  float_wnd_set_position(vr_window, 300, 300)
  float_wnd_set_ondraw(vr_window, "draw_vr_window")

  -- Set window for VR mode (positioning mode 5 = xplm_WindowVR)
  float_wnd_set_positioning_mode(vr_window, 5, -1)


end

-- Cleanup VR mode
function cleanup_vr_mode()
  logMsg("FlyWithLua Target Renderer: Cleaning up VR mode")
  if vr_window then
    -- Window will be automatically cleaned up when script reloads
    float_wnd_destroy(vr_window)
    vr_window = nil


  end
end

-- Mode detection and switching logic
function check_and_switch_mode()
  local vr_active = (vr_enabled == 1)

  -- Only switch modes if VR state has actually changed
  if vr_active ~= last_vr_state then
    if vr_active and current_mode ~= "vr" then
      -- Switch to VR mode
      logMsg("FlyWithLua Target Renderer: Switching to VR mode")
      current_mode = "vr"
      initialize_vr_mode()
    elseif not vr_active and current_mode ~= "normal" then
      -- Switch to normal mode
      logMsg("FlyWithLua Target Renderer: Switching to normal mode")
      current_mode = "normal"
      cleanup_vr_mode()
    end
    last_vr_state = vr_active
  end
end

-- Initialize the system
function initialize_targets()
  -- Check if mission number changed and reload targets if needed
  local current_mission = math.floor(fire_layout)
  if current_mission ~= last_fire_layout then
    local loaded_targets = load_fire_targets(current_mission)
    if loaded_targets then
      render_objects.targets = loaded_targets
      -- Clear and rebuild world coordinates cache
      objects_world.targets = {}
    else
      logMsg("FlyWithLua Target Renderer: Failed to load targets for mission " .. current_mission .. ", keeping previous targets")
    end
    last_fire_layout = current_mission
  end

  -- Initialize world coordinates
  update_world_coordinates()

  -- Set initial mode and register callbacks
  last_vr_state = (vr_enabled == 1)
  check_and_switch_mode()

  -- Register unified drawing callback that works in both VR and non-VR
  if icons_visible == 1.0 then
    --do_every_draw("draw_targets_unified()")
    draw_targets_unified()
  end

  -- Register mode checking (check every second)
  do_often("check_and_switch_mode()")
end

-- Initialize the targets system
do_every_draw("initialize_targets()")
--initialize_targets()
