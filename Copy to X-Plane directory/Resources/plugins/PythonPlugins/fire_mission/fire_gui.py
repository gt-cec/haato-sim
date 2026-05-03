import math
import traceback
import xp
import numpy as np
from XPPython3 import xpgl
from XPPython3.xpgl import Colors
from XPPython3.utils.datarefs import find_dataref
from OpenGL import GL
import py_utilities.rendering as rendering
from py_utilities.grid_system import GridSystem
from fire_classes import PositionRecording, RouteRecording

def render_plan_suggestion_MFD(plugin, data, wingman_screen_x, wingman_screen_y, grid_offset_x, grid_offset_y):
    """Render the MFD portion of the plan suggestion screen"""
    if plugin.show_best_plan:
        human_task_type, human_target_id = plugin.parse_task_float(plugin.team_plan_dataref[1])
        agent_task_type, agent_target_id = plugin.parse_task_float(plugin.team_plan_dataref[2])

        best_followon_human_task, best_followon_human_id = plugin.parse_task_float(plugin.team_plan_dataref[5])
        best_followon_wingman_task, best_followon_wingman_id = plugin.parse_task_float(plugin.team_plan_dataref[6])

    else:  # Show second best
        human_task_type, human_target_id = plugin.parse_task_float(plugin.team_plan_dataref[3])
        agent_task_type, agent_target_id = plugin.parse_task_float(plugin.team_plan_dataref[4])

        best_followon_human_task, best_followon_human_id = plugin.parse_task_float(plugin.team_plan_dataref[7])
        best_followon_wingman_task, best_followon_wingman_id = plugin.parse_task_float(plugin.team_plan_dataref[8])

    if agent_target_id is not None:
        wingman_target_pos = plugin.get_target_screen_position(agent_target_id, grid_offset_x, grid_offset_y)

        try:
            xpgl.drawLine(wingman_screen_x, wingman_screen_y, wingman_target_pos[0], wingman_target_pos[1],
                          color=Colors['cyan'], thickness=8)
        except Exception:
            pass
    else:
        wingman_target_pos = None

    if human_target_id is not None:
        human_target_pos = plugin.get_target_screen_position(human_target_id, grid_offset_x, grid_offset_y)
        xpgl.drawLine(plugin.screen_width / 2 + 65, plugin.screen_height / 2 - 20, human_target_pos[0],
                      human_target_pos[1], color=Colors['green'], thickness=8)
    else:
        human_target_pos = None

    if best_followon_human_id is not None:
        followon_human_target_pos = plugin.get_target_screen_position(best_followon_human_id, grid_offset_x,
                                                                    grid_offset_y)
        if human_target_pos is not None and followon_human_target_pos is not None:
            xpgl.drawLine(human_target_pos[0], human_target_pos[1], followon_human_target_pos[0],
                          followon_human_target_pos[1], color=(0, 0.8, 0), thickness=4)

    if best_followon_wingman_id is not None:
        followon_wingman_target_pos = plugin.get_target_screen_position(best_followon_wingman_id, grid_offset_x,
                                                                      grid_offset_y)
        if wingman_target_pos is not None and followon_wingman_target_pos is not None:
            xpgl.drawLine(wingman_target_pos[0], wingman_target_pos[1], followon_wingman_target_pos[0],
                          followon_wingman_target_pos[1], color=(0, 0.8, 0.8), thickness=4)





def draw_drop_route(plugin, lat, long, color):
    """
    Draws two thin 2-nautical-mile-long rectangles aligned with wind direction.
    One rectangle starts 2 NM upwind and ends at the target position.
    The second rectangle starts at the target position and ends 2 NM downwind.

    Args:
        lat: Target latitude
        long: Target longitude
        color: Color of the drop route
    """
    # Constants
    ROUTE_LENGTH_NM = plugin.required_drop_route_length
    ROUTE_WIDTH_NM = 0.2

    # Calculate grid offsets based on player position
    player_lat, player_lon = plugin.lat_dataref.value, plugin.lon_dataref.value

    grid_lat_diff = plugin.aor_center_lat - player_lat
    grid_lon_diff = plugin.aor_center_long - player_lon
    grid_offset_x = grid_lon_diff * plugin.lon_scale_nm * plugin.pixels_per_nm
    grid_offset_y = grid_lat_diff * plugin.lat_scale_nm * plugin.pixels_per_nm

    # Calculate route endpoints
    # Upwind rectangle: from 2 NM upwind to target
    upwind_start_lat, upwind_start_lon = GridSystem.destination_point(lat, long, plugin.wind_dir, ROUTE_LENGTH_NM/2)

    # Downwind rectangle: from target to 2 NM downwind
    downwind_bearing = (plugin.wind_dir + 180) % 360
    downwind_end_lat, downwind_end_lon = GridSystem.destination_point(lat, long, downwind_bearing, ROUTE_LENGTH_NM)

    # Helper function to convert lat/lon to screen coordinates
    def latlon_to_screen(target_lat, target_lon):
        target_lat_diff = target_lat - plugin.aor_center_lat
        target_lon_diff = target_lon - plugin.aor_center_long

        target_offset_x_nm = target_lon_diff * plugin.lon_scale_nm
        target_offset_y_nm = target_lat_diff * plugin.lat_scale_nm

        offset_x = target_offset_x_nm * plugin.pixels_per_nm
        offset_y = target_offset_y_nm * plugin.pixels_per_nm

        screen_x = plugin.mfd_center_x + grid_offset_x + offset_x
        screen_y = plugin.mfd_center_y + grid_offset_y + offset_y

        return screen_x, screen_y

    # Convert all points to screen coordinates
    target_x, target_y = latlon_to_screen(lat, long)
    upwind_start_x, upwind_start_y = latlon_to_screen(upwind_start_lat, upwind_start_lon)
    downwind_end_x, downwind_end_y = latlon_to_screen(downwind_end_lat, downwind_end_lon)

    # Calculate perpendicular offset for rectangle width
    wind_rad = math.radians(plugin.wind_dir)
    half_width_pixels = (ROUTE_WIDTH_NM * plugin.pixels_per_nm) / 2.0

    # Perpendicular vector (90 degrees to wind direction)
    perp_x = -math.cos(wind_rad) * half_width_pixels
    perp_y = math.sin(wind_rad) * half_width_pixels

    r, g, b = color

    # Draw upwind rectangle
    rendering.draw_rotated_rectangle(upwind_start_x, upwind_start_y, target_x, target_y, perp_x, perp_y, r, g, b, 0.6)

    # Draw downwind rectangle
    rendering.draw_rotated_rectangle(target_x, target_y, downwind_end_x, downwind_end_y, perp_x, perp_y, r, g, b, 0.4)

    xpgl.drawCircle(upwind_start_x, upwind_start_y, 8, isFilled=True, num_vertices=8, color=Colors['black'])
    xpgl.drawCircle(downwind_end_x, downwind_end_y, 8, isFilled=True, num_vertices=8, color=Colors['black'])




def draw_grid_on_mfd(plugin, lat, lon, center_x, center_y, pixels_per_nm, thickness=4.0, alpha=0.6):
    """
    Draws a 1nm x 1nm grid overlay on the MFD moving map, fixed to a geographic region.
    Grid is anchored to specific lat/lon coordinates and translates as player moves.

    Args:
        lat: Fixed grid center latitude (plugin.aor_center_lat)
        lon: Fixed grid center longitude (plugin.aor_center_long)
        center_x: Screen X coordinate where grid center should appear (pixels)
        center_y: Screen Y coordinate where grid center should appear (pixels)
        pixels_per_nm: Scale factor for the map (pixels per nautical mile)
    """

    # --- 1. Define Viewport Bounds ---
    clip_x_min = 153
    clip_x_max = plugin.screen_width
    clip_y_min = 30
    clip_y_max = plugin.screen_height - 55

    # Calculate width and height for glScissor
    clip_width = clip_x_max - clip_x_min
    clip_height = clip_y_max - clip_y_min

    # --- 2. Enable Clipping ---
    GL.glEnable(GL.GL_SCISSOR_TEST)

    # glScissor takes (x, y, width, height).
    # Note: 'x, y' specify the lower-left corner of the box.
    GL.glScissor(int(clip_x_min), int(clip_y_min), int(clip_width), int(clip_height))

    # Grid configuration for 17x17 NM AOR
    grid_spacing_nm = 1.0  # Grid squares are 1nm x 1nm
    grid_size = 17  # 17 rows x 17 columns (A-Q, 1-17)

    # Calculate lat/lon spacing between grid lines
    # 17nm / 17 cells = 1nm per cell, so 1 degree = 60nm means spacing is 1/60 degrees
    lat_spacing_deg = grid_spacing_nm / plugin.lat_scale_nm
    lon_spacing_deg = grid_spacing_nm / plugin.lon_scale_nm

    # Set OpenGL state for semi-transparent white lines
    GL.glEnable(GL.GL_BLEND)
    GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
    GL.glColor4f(1.0, 1.0, 1.0, alpha)  # White with 40% opacity
    GL.glLineWidth(thickness)

    # Draw vertical grid lines (constant longitude) - Columns A through Q
    GL.glBegin(GL.GL_LINES)
    for col_index in range(grid_size + 1):  # 0-17 inclusive for 17 columns
        # Calculate the actual longitude of this grid line
        # Column A is at the western edge, Column Q is at the eastern edge
        grid_line_lon = plugin.GRID_SW_LON + (col_index * lon_spacing_deg)

        # Calculate screen X position relative to grid center
        lon_diff_from_center = grid_line_lon - plugin.GRID_CENTER_LON
        offset_x_nm = lon_diff_from_center * plugin.lon_scale_nm
        screen_x = center_x + (offset_x_nm * pixels_per_nm)

        # Draw vertical line - extend beyond grid to cover visible area
        # Line spans from south to north edges of grid
        lat_diff_south = plugin.GRID_SW_LAT - plugin.GRID_CENTER_LAT
        lat_diff_north = plugin.GRID_NE_LAT - plugin.GRID_CENTER_LAT
        y_min = center_y + (lat_diff_south * plugin.lat_scale_nm * pixels_per_nm)
        y_max = center_y + (lat_diff_north * plugin.lat_scale_nm * pixels_per_nm)

        GL.glVertex2f(screen_x, y_min)
        GL.glVertex2f(screen_x, y_max)
    GL.glEnd()

    # Draw horizontal grid lines (constant latitude) - Rows 1 through 17
    GL.glBegin(GL.GL_LINES)
    for row_index in range(grid_size + 1):  # 0-17 inclusive for 17 rows
        # Calculate the actual latitude of this grid line
        # Row 1 is at the southern edge, Row 17 is at the northern edge
        grid_line_lat = plugin.GRID_SW_LAT + (row_index * lat_spacing_deg)

        # Calculate screen Y position relative to grid center
        lat_diff_from_center = grid_line_lat - plugin.GRID_CENTER_LAT
        offset_y_nm = lat_diff_from_center * plugin.lat_scale_nm
        screen_y = center_y + (offset_y_nm * pixels_per_nm)

        # Draw horizontal line - extend from west to east edges of grid
        lon_diff_west = plugin.GRID_SW_LON - plugin.GRID_CENTER_LON
        lon_diff_east = plugin.GRID_NE_LON - plugin.GRID_CENTER_LON
        x_min = center_x + (lon_diff_west * plugin.lon_scale_nm * pixels_per_nm)
        x_max = center_x + (lon_diff_east * plugin.lon_scale_nm * pixels_per_nm)

        GL.glVertex2f(x_min, screen_y)
        GL.glVertex2f(x_max, screen_y)
    GL.glEnd()

    # Draw grid labels
    label_font = plugin.grid_fonts[plugin.current_range_level]
    # Column labels (A-Q) along the top edge
    for col_index in range(grid_size):  # 0-16 for columns A-Q
        col_center_lon = plugin.GRID_SW_LON + ((col_index + 0.5) * lon_spacing_deg)

        lon_diff_from_center = col_center_lon - plugin.GRID_CENTER_LON
        offset_x_nm = lon_diff_from_center * plugin.lon_scale_nm
        screen_x = center_x + (offset_x_nm * pixels_per_nm)

        # Position label at top and bottom edges
        lat_diff_north = plugin.GRID_NE_LAT - plugin.GRID_CENTER_LAT
        top_y = center_y + (lat_diff_north * plugin.lat_scale_nm * pixels_per_nm) + 10
        lat_diff_south = plugin.GRID_SW_LAT - plugin.GRID_CENTER_LAT
        bottom_y = center_y + (lat_diff_south * plugin.lat_scale_nm * pixels_per_nm) - 40

        # Label with actual column letter A-Q
        label = chr(ord('A') + col_index)
        xpgl.drawText(label_font, int(screen_x), int(top_y), label, alignment="C", color=Colors['white'])
        xpgl.drawText(label_font, int(screen_x), int(bottom_y), label, alignment="C", color=Colors['white'])

    # Row labels (1-17) along the left edge
    for row_index in range(grid_size):  # 0-16 for rows 1-17
        # Calculate the latitude of this row's CENTER (between grid lines)
        row_center_lat = plugin.GRID_SW_LAT + ((row_index + 0.5) * lat_spacing_deg)

        # Calculate screen position
        lat_diff_from_center = row_center_lat - plugin.GRID_CENTER_LAT
        offset_y_nm = lat_diff_from_center * plugin.lat_scale_nm
        screen_y = center_y + (offset_y_nm * pixels_per_nm)

        # Position label just left of the western edge
        lon_diff_west = plugin.GRID_SW_LON - plugin.GRID_CENTER_LON
        left_x = center_x + (lon_diff_west * plugin.lon_scale_nm * pixels_per_nm) - 20
        right_x = center_x - (lon_diff_west * plugin.lon_scale_nm * pixels_per_nm) + 20

        # Label with actual row number 1-17 (from bottom to top)
        label = str(row_index + 1)
        xpgl.drawText(label_font, int(left_x), int(screen_y - 5), label, alignment="C", color=Colors['white'])
        xpgl.drawText(label_font, int(right_x), int(screen_y - 5), label, alignment="C", color=Colors['white'])

    # Disable blending
    GL.glDisable(GL.GL_BLEND)


# Helper methods for route recording


def render_control_reference_screen(plugin, data):
    try:
        page = data.get('page', plugin.control_reference_page)
        if page == 0: # Control reference
            xpgl.drawTexture(plugin.control_reference_image, 0, 0, width=1024, height=768)
        elif page == 1: # fire workflow
            xpgl.drawTexture(plugin.fire_workflow_image, 0, 0, width=1024, height=768)
    except Exception as e:
        plugin.log(e)
        plugin.log(traceback.format_exc())
        rendering.draw_waiting_for_datarefs(plugin.font_big)



def render_splashscreen(plugin, data):
    try:
        xpgl.drawTexture(data.get('image', plugin.splashscreen_image), 0, 0, width=1024, height=768)
    except Exception as e:
        plugin.log(e)
        plugin.log(traceback.format_exc())
        rendering.draw_waiting_for_datarefs(plugin.font_big)



def render_primary_screen(plugin, data):
    try:
        xp.setGraphicsState(0, 1)

        current_heading = data.get(
            'current_heading',
            (int(find_dataref('sim/flightmodel/position/true_psi').value) - plugin.mag_declination) % 360,
        )
        xpgl.drawRectangle(plugin.screen_width / 2 - 85, 340, 80, 45, color=Colors['black'])
        xpgl.drawText(plugin.font_big, plugin.screen_width / 2 - 80, 345, f'{current_heading}', color=Colors['white'])

        hint_x, hint_y = 650, 30
        hint_width, hint_height = 370, 160
        xpgl.drawRectangle(hint_x, hint_y, hint_width, hint_height, color=Colors['black'])

        xpgl.drawRectangle(hint_x+5, hint_y + 95, hint_width - 20, 55, color=Colors['white'])
        xpgl.drawRectangle(hint_x+5, hint_y + 15, hint_width - 20, 55, color=Colors['white'])

        xpgl.drawText(plugin.font_big, hint_x + 10, hint_y + 110, "RIGHT: SET TGT", alignment="L", color=(0, 0.8, 0))
        xpgl.drawText(plugin.font_big, hint_x + 10, hint_y + 25, "LFT: CMD WNGMN", alignment="L", color=(0, 0.8, 0.8))

        # Check if datarefs are initialized
        if plugin.dataref_mission_time_left is None:
            plugin.log(f"DEBUG: Datarefs not initialized. mission_time_left={plugin.dataref_mission_time_left}, wingman_status={plugin.dataref_wingman_status}")
            xpgl.drawText(plugin.font, 512, 384, "Waiting for datarefs...", alignment="C", color=Colors['white'])
            return


        if plugin.dev_mode:
            xpgl.drawRectangle(300, 570, 300, 180, color=Colors['gray'])
            xpgl.drawText(plugin.font_medium, 320, 640, f'Since reset: {plugin.step}', alignment="L",color=Colors['black'])

            joystick_values = plugin.input_manager.joystick_values if plugin.input_manager else []
            if joystick_values:
                for i in range(len(joystick_values)):
                    if plugin.safe_array_access(joystick_values, i, 0) == 1:
                        xpgl.drawText(plugin.font_big, 320, 660, f'Joystick: {i}', alignment="L", color=Colors['black'])
                        break # Exit after finding nonzero value

            xpgl.drawText(plugin.font_medium, 320, 590,
                          f"Config: {plugin.control_prefix}",
                          alignment="L", color=Colors['black'])

            if plugin.experiment_log_file is None:
                xpgl.drawRectangle(100, 600, 110, 50, color=Colors['red'])
                xpgl.drawText(plugin.font, 100, 630, f'NO LOG FILE', alignment="C",color=Colors['white'])


            if plugin.target_in_overfly_range is not None:
                xpgl.drawText(plugin.font, 915, 600, f'overflying {plugin.target_in_overfly_range}', alignment="C", color=Colors['black'])
            if plugin.at_drop_route1_start is not None:
                xpgl.drawText(plugin.font, 915, 600, f'route1 start {plugin.at_drop_route1_start}', alignment="C",color=Colors['black'])
            if plugin.at_drop_route1_end is not None:
                xpgl.drawText(plugin.font, 915, 560, f'route1 end {plugin.at_drop_route1_end}', alignment="C",color=Colors['black'])

            if plugin.at_drop_route2_start is not None:
                xpgl.drawText(plugin.font, 915, 600, f'route1 start {plugin.at_drop_route2_start}', alignment="C",color=Colors['black'])
            if plugin.at_drop_route2_end is not None:
                xpgl.drawText(plugin.font, 915, 560, f'route1 end {plugin.at_drop_route2_end}', alignment="C",color=Colors['black'])


            if plugin.mic_press_time:
                xpgl.drawText(plugin.font_small, 950, 500, 'MIC KEYED', alignment="C", color=Colors['black'])

            if plugin.mic_press_time:
                xpgl.drawText(plugin.font_small, 950, 490, f'pressed {plugin.mic_press_time-plugin.mission_start_time}', alignment="C", color=Colors['black'])

            if plugin.mic_release_time:
                xpgl.drawText(plugin.font_small, 950, 480, f'released {plugin.mic_release_time-plugin.mission_start_time}', alignment="C", color=Colors['black'])

        # Draw mission time left
        time_remaining = data.get('time_remaining', plugin.dataref_mission_time_left.value)
        if time_remaining > 60:
            xpgl.drawRectangle(0, 714, 1024, 70, color=(0.13, 0.13, 0.13))
            xpgl.drawText(plugin.font_big, 220, 725, f"TIME REMAINING: {int(time_remaining // 60)}:{int(time_remaining % 60):02d}",alignment="C", color=Colors['white'])

        elif time_remaining > 10:
            xpgl.drawRectangle(0, 714, 1024, 70, color=(0.13, 0.13, 0.13))
            xpgl.drawText(plugin.font_big, 220, 725, f"TIME REMAINING: {int(time_remaining // 60)}:{int(time_remaining % 60):02d}",alignment="C", color=Colors['red'])

        elif 0 < time_remaining <= 10:
            xpgl.drawRectangle((1024 - 300) // 2, (768 - 80) // 2, 300, 80, color=Colors['white'])
            xpgl.drawText(plugin.font60, 1024 // 2, 768 // 2 - 10, f"{int(time_remaining // 60)}:{int(time_remaining % 60):02d}", alignment="C", color=Colors['red'])
        else:
            xpgl.drawRectangle((1024 - 630) // 2, (768 - 80) // 2, 650, 100, color=Colors['white'])
            xpgl.drawText(plugin.font60, 1024 // 2, 768 // 2 - 10, f"MISSION COMPLETE", alignment="C", color=Colors['black'])

        current_alt = data.get(
            'current_alt',
            find_dataref("sim/cockpit/pressure/cabin_altitude_actual_ft").value,
        )
        xpgl.drawText(plugin.font_big, 820, 725, f"ALT: {int(current_alt)} ft", alignment="C", color=Colors['white'])


        ###################################### Draw saved recordings subwindow #####################################

        plugin.selected_recording_index = max(0, min(plugin.selected_recording_index, len(plugin.saved_recordings) - 1)) # TODO remove
        show_review_prompt, show_recording_in_progress = False, False
        if len(plugin.saved_recordings) > 0:
            if isinstance(plugin.saved_recordings[0], PositionRecording):
                show_review_prompt = True
            elif isinstance(plugin.saved_recordings[0], RouteRecording):
                if plugin.saved_recordings[0].end_pos is not None:
                    show_review_prompt = True
                else: # Route recording in progress
                    show_recording_in_progress = True

            recordings_x, recordings_y = 850, 600-70
            recordings_width, recordings_height = 170, 100

            if show_review_prompt:
                xpgl.drawRectangle(plugin.screen_width / 6 - 50, plugin.screen_height / 3, 780, 250, color=Colors['orange'])
                xpgl.drawText(plugin.font_reallybig, plugin.screen_width / 2, plugin.screen_height / 2, f'REVIEW RECORDING', alignment="C", color=Colors['black'])
                xpgl.drawText(plugin.font_reallybig, plugin.screen_width / 2, plugin.screen_height / 2 - 100, f'(PULL TRIGGER)', alignment="C", color=Colors['black'])

            if show_recording_in_progress:
                xpgl.drawCircle(recordings_x+80, recordings_y+100, 60, isFilled=True, num_vertices=16, color=Colors['black'])
                xpgl.drawCircle(recordings_x+80, recordings_y + 100, 45, isFilled=True, num_vertices=16, color=Colors['red'])
                xpgl.drawText(plugin.font, recordings_x + 85, recordings_y + 15, f'RECORD IN', alignment="C", color=Colors['red'])
                xpgl.drawText(plugin.font, recordings_x + 85, recordings_y - 10, f'PROGRESS', alignment="C", color=Colors['red'])

        ############################## Draw wingman status #########################################################

        if plugin.show_wingman_status:
            xpgl.drawRectangle(680, 25, 344, 180-30, color=Colors['gray'])
            xpgl.drawText(plugin.font_big, 820, 170-30, "WINGMAN", alignment="C", color=Colors['black'])
            xpgl.drawLine(680, 165-30, 1024, 165-30, color=Colors['black'])

            wingman_status = plugin.dataref_wingman_status.value
            wingman_position = GridSystem.latlon_to_grid_position(plugin.wingman_lat_dref.value, plugin.wingman_long_dref.value)

            task_dict = {
                0.0: 'CLASSIFY',
                1.0: 'MARK POS',
                2.0: 'ROUTE',
                3.0: 'REFINE',
                4.0: 'NO TASK (JUST COMPLETED)'
            }

            if wingman_status == 99.0:
                fire_grid = GridSystem.latlon_to_grid_position(plugin.targets[-1].lat, plugin.targets[-1].long)
                wingman_task = 'TASK UNKNOWN'
                text_color = Colors['red']
            elif wingman_status == 9.0:
                fire_grid = ''
                wingman_task = 'AWAITING CMD'
                text_color = Colors['red']
            else:
                fire_id = plugin.safe_int_conversion(wingman_status, 99)
                target = plugin.safe_target_access(fire_id)
                if target:
                    fire_grid = GridSystem.latlon_to_grid_position(target.lat, target.long)
                    wingman_task = task_dict.get(target.status, 'UNKNOWN')
                    whoflew = plugin.safe_array_access(plugin.dataref_target_whoflew_list, fire_id, 0.0)
                    if wingman_task == 'REFINE ROUTE' and whoflew == 2.0: # Hack to prevent wingman from saying it will refine a fire it just flew
                        fire_grid, wingman_task = 'RECALCULATING', ''
                    text_color = Colors['black']
                else:
                    fire_grid = 'ERROR'
                    wingman_task = 'INVALID TARGET'
                    text_color = Colors['red']
                    plugin.log(f"Cannot access target {fire_id} for wingman status display")

            text1 = f'LOCATION: {wingman_position}'
            text2 = 'STATUS: ' + wingman_task + '-' + fire_grid
            xpgl.drawText(plugin.font, 855, 130-30, text1, alignment="C", color=Colors['black'])
            xpgl.drawText(plugin.font, 855, 85-30, text2, alignment="C", color=text_color)

            request = 99.0 if plugin.dataref_help_request is None else plugin.dataref_help_request.value
            if request != 99.0:  # 99.0 = no request
                request_text = f'REQUEST: FIRE {int(request)}'
                xpgl.drawRectangle(685, 35, 335, 60, color=Colors['red'])
                xpgl.drawText(plugin.font_big, 850, 50, request_text, alignment="C", color=Colors['white'])
                # Add hint text for rejection
                xpgl.drawText(plugin.font, 850, 100, "Press R to REJECT", alignment="C", color=Colors['white'])

            # Draw auto ID icon
            if plugin.dataref_auto_spot.value == 1.0:
                xpgl.drawText(plugin.font_medium, 970, 149, 'AUTO ID', alignment="C", color=Colors['blue'])


        ############################## Draw fire statuses (bottom left) ##############################
        target_statuses = []
        for i in range(plugin.num_targets):
            target_statuses.append(plugin.dataref_target_statuses[i])

        xpgl.drawRectangle(0, 25, 330, 175, color=Colors['black'])  # Draw gray background rectangle
        xpgl.drawText(plugin.font_big, 150, 210, "FIRES", alignment="C", color=Colors['white'])  # Draw "FIRES" label above the rectangle
        square_size = 70 # Draw 2x4 grid of 30x30 squares (8 total fires)
        padding = 10
        start_x = 10
        start_y = 35

        for i in range(plugin.num_targets):
            x, y = start_x + (i // 2) * (square_size + padding), start_y + (i % 2) * (square_size + padding)
            if plugin.targets[i].status == 4.0: # Totally done
                square_color = (.3, .3, .3)
                text_color = Colors['white']
                xpgl.drawRectangle(x, y, square_size, square_size, color=square_color)
            elif plugin.targets[i].status == 3.0: # Initial route marked
                square_color = Colors['cyan'] if plugin.dataref_target_whoflew_list[i] == 2.0 else Colors['green']
                text_color = Colors['black']
                xpgl.drawCircle(x + square_size/2, y + square_size/2, square_size/2, isFilled=True, num_vertices=16, color=square_color)

            elif plugin.targets[i].status == 2.0: # Position marked
                square_color = (0.7, 0.0, 0.0) #Colors['red']
                xpgl.drawCircle(x + square_size/2, y + square_size/2, square_size/2, isFilled=True, num_vertices=16, color=square_color)
                xpgl.drawCircle(x + square_size/2, y + square_size/2, square_size/2*.85, isFilled=False, thickness=5, num_vertices=16, color=Colors['black'])
                text_color = Colors['white']
            elif plugin.targets[i].status == 1.0: # Classified
                square_color = (0.7, 0.0, 0.0) #Colors['red']
                text_color = Colors['white']
                xpgl.drawCircle(x + square_size/2, y + square_size/2, square_size/2, isFilled=True, num_vertices=16, color=square_color)
            else:
                square_color = (0.7, 0.0, 0.0) #Colors['red']
                text_color = Colors['white']
                xpgl.drawRectangle(x, y, square_size, square_size, color=square_color)

            text_x, text_y = x + square_size // 2, y + square_size // 2 - 10
            xpgl.drawText(plugin.font_firestatuses, text_x, text_y, plugin.targets[i].grid_position, alignment="C", color=text_color)

            # Draw highlight around indicated fire plans
            highlight_x, highlight_y = text_x, text_y + 10
            if int(plugin.human_indicated_plan_dataref.value) == i:
                plugin.draw_target_marker(highlight_x, highlight_y, Colors['green'], 'H', linewidth=6.0, marker_size = 40, label_offset_y=-45)

            if int(plugin.dataref_wingman_status.value) == i: #
                plugin.draw_target_marker(highlight_x, highlight_y, Colors['cyan'], 'W', linewidth=6.0, marker_size = 40, label_offset_y=-45)

        # Render callouts for human actions (top center of screen)
        callout_y = 660
        text = None
        show_callout = False
        try:
            if len(plugin.saved_recordings) > 0:
                if isinstance(plugin.saved_recordings[0], RouteRecording):
                    show_callout = False
            else:
                show_callout = True
        except:
            show_callout = True

        if plugin.target_in_overfly_range is not None:
            text = "PRESS MISSILE RLS TO MARK POS"

        elif plugin.at_drop_route1_start is not None:
            text = "PRESS MISSILE RLS TO START ROUTE"

        elif plugin.at_drop_route1_end is not None:
            text = "PRESS MISSILE RLS TO END ROUTE"

        elif plugin.at_drop_route2_start is not None:
            text = "PRESS MISSILE RLS TO START ROUTE"

        elif plugin.at_drop_route2_end is not None:
            text = "PRESS MISSILE RLS TO END ROUTE"

        if text is not None and show_callout:
            xpgl.drawRectangle(150, callout_y, 750, 50, color=Colors['orange'])
            xpgl.drawText(plugin.font_big, 512, callout_y + 10, text, alignment="C", color=Colors['black'])

        if plugin.dev_mode:
            callout_y = 650
            if plugin.target_in_overfly_range is not None:
                xpgl.drawRectangle(300, callout_y, 424, 50, color=Colors['orange'])
                xpgl.drawText(plugin.font_big, 512, callout_y + 10, "IN OVERFLY RANGE", alignment="C", color=Colors['black'])

            elif plugin.at_drop_route1_start is not None:
                xpgl.drawRectangle(250, callout_y, 524, 50, color=Colors['orange'])
                xpgl.drawText(plugin.font_big, 512, callout_y + 10, "AT DROP ROUTE START", alignment="C", color=Colors['white'])

            elif plugin.at_drop_route1_end is not None:
                xpgl.drawRectangle(250, callout_y, 524, 50, color=Colors['orange'])
                xpgl.drawText(plugin.font_big, 512, callout_y + 10, "AT DROP ROUTE END", alignment="C", color=Colors['white'])

            elif plugin.at_drop_route2_start is not None:
                xpgl.drawRectangle(200, callout_y, 624, 50, color=Colors['orange'])
                xpgl.drawText(plugin.font_big, 512, callout_y + 10, "(REFINE) AT DROP ROUTE START", alignment="C", color=Colors['black'])

            elif plugin.at_drop_route2_end is not None:
                xpgl.drawRectangle(250, callout_y, 524, 50, color=Colors['orange'])
                xpgl.drawText(plugin.font_big, 512, callout_y + 10, "(REFINE) AT DROP ROUTE END", alignment="C", color=Colors['white'])

    except Exception as e:
        plugin.log(e)
        plugin.log(traceback.format_exc())
        rendering.draw_waiting_for_datarefs(plugin.font_big)




def render_commands_screen(plugin, data):
    try:
        xp.setGraphicsState(0, 1)
        plugin.render_task_assignment_screen(version=data['version'], map_side=data['map_side'])

    except Exception as e:
        plugin.log('Error in commands screen:')
        plugin.log(e)
        plugin.log(traceback.format_exc())
        rendering.draw_waiting_for_datarefs(plugin.font_big)



def render_human_plan_screen(plugin, data):
    """Render the human plan screen for fire selection"""
    try:
        xp.setGraphicsState(0, 1)
        plugin.render_task_assignment_screen(version=data['version'], map_side=data['map_side'])

    except Exception as e:
        plugin.log(f'Error in render_human_plan_screen: {e}')
        plugin.log(traceback.format_exc())



def render_task_assignment_screen(plugin, data, version:str, map_side:str):
    """
    TODO DOCSTRING OUTDATED
    member: 'human' or 'wingman'. If 'human', this lets human specify their current task and send it over the "human_indicated_plan" dataref.
    if 'wingman', this lets the human command the wingman.
    map side: 'right' or 'left'. Which side of the screen to put the map. The command buttons go on the other side
    """
    try:
        xp.setGraphicsState(0, 1)

        # Draw background
        xpgl.drawRectangle(0, 0, 1024, 768, color=(0.0, 0.0, 0.0))
        if version in ['human_plan', 'command_wingman']:
            xpgl.drawText(plugin.font_big, 150, 50, f"CLEAR {'YOUR PLAN' if version == 'human_plan' else 'COMMANDS'}: STICK FRONT", color=Colors['red'])

        # Calculate layout based on map_side parameter
        if map_side == 'right':
            button_x = 130
            button_width = 200
            map_x = 512 - 50
            map_width = 512
        else:  # map_side == 'left'
            map_x = 50
            map_width = 512
            button_x = 512 + 100 + 50
            button_width = 200

        map_y = 0
        map_height = 768

        # --- DRAW MAP SECTION ---
        # Calculate grid_params for FULL 17x17 grid
        grid_params = GridSystem.calculate_full_grid_bounds(map_x, map_y, map_width, map_height)
        grid_start_col, grid_end_col, grid_start_row, grid_end_row, scale_factor, offset_x, offset_y = grid_params

        # Draw grid lines (horizontal and vertical)
        grid_width_px = (grid_end_col - grid_start_col + 1) * scale_factor
        grid_height_px = (grid_end_row - grid_start_row + 1) * scale_factor

        # Vertical lines (column boundaries)
        for col_idx in range(grid_start_col, grid_end_col + 2):
            x = offset_x + (col_idx - grid_start_col) * scale_factor
            xpgl.drawLine(x, offset_y, x, offset_y + grid_height_px, color=Colors['white'])

        # Horizontal lines (row boundaries)
        for row_idx in range(grid_start_row, grid_end_row + 2):
            y = offset_y + (row_idx - grid_start_row) * scale_factor
            xpgl.drawLine(offset_x, y, offset_x + grid_width_px, y, color=Colors['white'])

        # Column letters (A-Q) along bottom
        for col_idx in range(grid_start_col, grid_end_col + 1):
            x = offset_x + (col_idx - grid_start_col) * scale_factor + scale_factor / 2
            col_letter = chr(ord('A') + col_idx)
            xpgl.drawText(plugin.font_grid, x, offset_y + grid_height_px + 5, col_letter,
                          alignment="C", color=(0.5, 0.5, 0.5))

        # Row numbers (1-17) along left
        for row_idx in range(grid_start_row, grid_end_row + 1):
            y = offset_y + (row_idx - grid_start_row) * scale_factor + scale_factor / 2 - 9
            xpgl.drawText(plugin.font_grid, offset_x - 15, y, str(row_idx + 1),
                          alignment="C", color=(0.5, 0.5, 0.5))

        # Draw all targets using draw_target_for_task()
        for target in plugin.targets:
            if target.id != 99:
                # Use 'classify' task type for simple red square display
                task_type = 'classify' if target.status == 0.0 else 'mark position' if target.status == 1.0 else 'initial route' if target.status == 2.0 else 'refined route' if target.status == 3.0 else 'done'
                plugin.draw_target_for_task(task_type, target, grid_params, 'none')

        # --- DRAW AIRCRAFT POSITIONS ---
        def lat_lon_to_grid(lat, long):
            lat_normalized = (lat - plugin.GRID_SW_LAT) / (plugin.GRID_NE_LAT - plugin.GRID_SW_LAT)
            lon_normalized = (long - plugin.GRID_SW_LON) / (plugin.GRID_NE_LON - plugin.GRID_SW_LON)
            col_idx = int(lon_normalized * 17)
            row_idx = int(lat_normalized * 17)
            screen_x = offset_x + (col_idx - grid_start_col) * scale_factor
            screen_y = offset_y + (row_idx - grid_start_row) * scale_factor
            return screen_x, screen_y

        # Draw human position
        human_lat = plugin.lat_dataref.value
        human_lon = plugin.lon_dataref.value
        human_x, human_y = lat_lon_to_grid(human_lat, human_lon)
        xpgl.drawCircle(int(human_x), int(human_y), 10, isFilled=True, num_vertices=8, color=Colors['green'])
        xpgl.drawText(plugin.font, human_x + 12, human_y - 5, "H", alignment="L", color=Colors['green'])

        # Draw wingman position
        wingman_lat = plugin.wingman_lat_dref.value
        wingman_lon = plugin.wingman_long_dref.value
        wingman_x, wingman_y = lat_lon_to_grid(wingman_lat, wingman_lon)
        xpgl.drawCircle(int(wingman_x), int(wingman_y), 10, isFilled=True, num_vertices=8, color=Colors['cyan'])
        xpgl.drawText(plugin.font, wingman_x + 12, wingman_y - 5, "W", alignment="L", color=Colors['cyan'])

        # --- DRAW BUTTON SECTION ---
        # Filter active targets
        active_targets = [t for t in plugin.targets if t.id != 99]

        # Determine selected row based on which screen is rendering
        if version == 'command_wingman':
            task_selected_row = plugin.commands_grid.selected_row if plugin.commands_grid else 0
        else:
            task_selected_row = plugin.human_plan_grid.selected_row if plugin.human_plan_grid else 0

        # Draw title
        if version == 'human_plan':
            title = "HUMAN - SELECT TARGET"
            color = Colors['green']
        elif version == 'command_wingman':
            title = "COMMAND WINGMAN"
            color = Colors['cyan']
        else:
            title = "WINGMAN SUGGESTS THIS PLAN"
            color = Colors['white']
        title_x = 300 if version == 'human_plan' else 750
        xpgl.drawText(plugin.font_morebig, title_x, 700, title, alignment="C", color=color)

        # Draw colored border around screen
        border_color = Colors['cyan'] if version == 'command_wingman' else Colors['green']
        plugin.draw_border_around_screen(border_color, 10, flashing=False)

        # Button specifications
        button_padding = 16
        button_inner_width = button_width - (2 * button_padding)
        button_height = 65
        button_spacing = 10
        start_y = 630

        # Draw buttons
        for i in range(len(active_targets)):
            btn_y = start_y - (i * (button_height + button_spacing))
            btn_x = button_x + button_padding

            # Determine colors based on selection
            if i == task_selected_row:
                bg_color = Colors['white']
                text_color = (0.0, 0.0, 0.0)  # Black
            else:
                bg_color = (0.3, 0.3, 0.3)  # Dark gray
                text_color = Colors['white']

            # Draw button background
            xpgl.drawRectangle(btn_x, btn_y, button_inner_width, button_height, color=bg_color)
            label_x = btn_x + button_inner_width // 2
            label_y = btn_y + button_height // 2 - 10

            # Draw button label (grid position)
            text = active_targets[i].grid_position

            xpgl.drawText(plugin.font_big, label_x, label_y, text, alignment="C", color=text_color)

        # --- DRAW HIGHLIGHT ON MAP ---
        # Draw highlight box around selected target
        if task_selected_row < len(active_targets):
            selected_target = active_targets[task_selected_row]

            # Convert target lat/lon to screen position (same math as draw_target_for_task)
            lat_normalized = (selected_target.lat - plugin.GRID_SW_LAT) / (plugin.GRID_NE_LAT - plugin.GRID_SW_LAT)
            lon_normalized = (selected_target.long - plugin.GRID_SW_LON) / (plugin.GRID_NE_LON - plugin.GRID_SW_LON)

            target_col_idx = int(lon_normalized * 17)
            target_row_idx = int(lat_normalized * 17)

            screen_x = offset_x + (target_col_idx - grid_start_col) * scale_factor + scale_factor / 2
            screen_y = offset_y + (target_row_idx - grid_start_row) * scale_factor + scale_factor / 2

            # Choose color based on member
            highlight_color = Colors['cyan'] if version == 'command_wingman' else Colors['green']

            # Draw marker using existing function
            label = 'W' if version == 'command_wingman' else 'H'
            plugin.draw_target_marker(screen_x, screen_y, highlight_color, label)

    except Exception as e:
        plugin.log(f'Error in render_task_assignment_screen: {e}')
        plugin.log(traceback.format_exc())
        rendering.draw_waiting_for_datarefs(plugin.font_big)




def render_task_notification(plugin, data):
    """A variant of the plan suggestion screen that just notifies the human of the task the wingman has calculated for itself. Used in plugin-managing mode"""
    try:
        xp.setGraphicsState(0, 1)

        # Parse plan dref
        team_plan = {}
        team_plan['show_plan'] = plugin.team_plan_dataref[0]
        team_plan['wingman_plan']= plugin.team_plan_dataref[2]
        team_plan['second_best_wingman_plan']= plugin.team_plan_dataref[4]
        team_plan['best_followon_wingman']= plugin.team_plan_dataref[6]
        team_plan['second_best_followon_wingman']= plugin.team_plan_dataref[8]
        team_plan['rationale']= plugin.team_plan_dataref[9]
        team_plan['planning_mode']= plugin.team_plan_dataref[10]

        agent_pos, agent_target = None, None

        # Read task strings from datarefs
        if team_plan['show_plan'] == 1.0:
            agent_task_type, agent_target_id = plugin.parse_task_float(team_plan['wingman_plan'])
        else:
            # TODO test
            agent_task_type, agent_target_id = plugin.parse_task_float(float(plugin.dataref_wingman_status.value))

        show_agent_task = False if team_plan['wingman_plan'] == 99.0 else True

        if show_agent_task:
            for target in plugin.targets:
                if target.id == agent_target_id:
                    agent_target = target
                    break

        # --- BACKGROUND ---
        xpgl.drawRectangle(0, 0, 1024, 768, color=(0.0, 0.1, 0.0)) # Dark green background
        xpgl.drawText(plugin.font60, 480, 650, "WINGMAN SELECTED TASK", alignment="C", color=Colors['white'])

        # --- TASK DISPLAY (right side) ---
        task_display_x, task_display_y = 312, 650

        # Agent task
        try:
            if show_agent_task and agent_target is not None:
                agent_task = str(agent_task_type) + ' ' + str(agent_target.grid_position)
                #xpgl.drawText(plugin.font60, task_display_x, task_display_y - 0, "WINGMAN", alignment="L", color=Colors['cyan'])
                xpgl.drawText(plugin.font60, task_display_x, task_display_y - 120, agent_task, alignment="L", color=Colors['cyan'])
            else:
                agent_task = 'Task unknown'
        except:
            pass

        # --- ACKNOWLEDGE BUTTON ---
        button_text = "ACKNOWLEDGE"
        button_width = 450
        button_height = 100
        buttons_x = 312-50  # Center buttons (1024/2 - 400/2 = 312)
        button_y = 120
        button_color = (0.0, 0.5, 0)
        text_color = (1.0, 1.0, 1.0)
        text_x = buttons_x + button_width / 2
        font = plugin.font60

        xpgl.drawRectangle(buttons_x, button_y, button_width, button_height, color=button_color)
       # xpgl.drawLine(buttons_x + button_width + 10, button_y + button_height, buttons_x + button_width + 40, button_y + button_height/2, color=Colors['green'], thickness=20)
       # xpgl.drawLine(buttons_x + button_width + 10, button_y, buttons_x + button_width + 40, button_y + button_height / 2, color=Colors['green'], thickness=20)
        xpgl.drawText(font, text_x, button_y + button_height / 2 - 14, button_text, alignment="C", color=text_color)

        plugin.draw_border_around_screen(Colors['red'], thickness=20, flashing=True)

    except Exception as e:
        plugin.log('Error in plan_suggestion screen:')
        plugin.log(e)
        plugin.log(traceback.format_exc())
        rendering.draw_waiting_for_datarefs(plugin.font_big)




def render_plan_suggestion(plugin, data):
    """Render the plan suggestion screen with map and task descriptions"""
    try:
        xp.setGraphicsState(0, 1)

        # Parse plan dref
        team_plan = {}
        team_plan['show_plan'] = plugin.team_plan_dataref[0]
        team_plan['human_plan'] = plugin.team_plan_dataref[1]
        team_plan['wingman_plan']= plugin.team_plan_dataref[2]
        team_plan['second_best_human_plan']= plugin.team_plan_dataref[3]
        team_plan['second_best_wingman_plan']= plugin.team_plan_dataref[4]
        team_plan['best_followon_human']= plugin.team_plan_dataref[5]
        team_plan['best_followon_wingman']= plugin.team_plan_dataref[6]
        team_plan['second_best_followon_human']= plugin.team_plan_dataref[7]
        team_plan['second_best_followon_wingman']= plugin.team_plan_dataref[8]
        team_plan['rationale']= plugin.team_plan_dataref[9]
        team_plan['planning_mode']= plugin.team_plan_dataref[10]

        human_pos, human_target = None, None
        agent_pos, agent_target = None, None

        # Read task strings from datarefs
        if plugin.show_best_plan:# or (team_plan['second_best_human_plan'] != 99 and team_plan['second_best_wingman_plan'] != 99):
            human_task_type, human_target_id = plugin.parse_task_float(team_plan['human_plan'])
            agent_task_type, agent_target_id = plugin.parse_task_float(team_plan['wingman_plan'])
        else:
            human_task_type, human_target_id = plugin.parse_task_float(team_plan['second_best_human_plan'])
            agent_task_type, agent_target_id = plugin.parse_task_float(team_plan['second_best_wingman_plan'])

        show_human_task = False if team_plan['human_plan'] == 99.0 else True
        show_agent_task = False if team_plan['wingman_plan'] == 99.0 else True

        if show_human_task:
            #human_pos = (plugin.lat_dataref.value, plugin.lon_dataref.value)
            for target in plugin.targets:
                if target.id == human_target_id:
                    human_target = target
                    break

        if show_agent_task:
            #agent_pos = (plugin.wingman_lat_dref.value, plugin.wingman_long_dref.value)
            for target in plugin.targets:
                if target.id == agent_target_id:
                    agent_target = target
                    break

        #xp.log(f'Human target is {human_target}, agent target is {agent_target}')

        # --- BACKGROUND ---
        xpgl.drawRectangle(0, 0, 1024, 768, color=(0.0, 0.1, 0.0)) # Dark green background
        xpgl.drawText(plugin.font50, 420, 720, "WINGMAN SUGGESTS THIS PLAN:", alignment="C", color=Colors['white'])
        xpgl.drawText(plugin.font50, 460, 30, "THUMBSTICK L/R: TOGGLE PLAN 1/2", alignment="C",
                      color=Colors['white'])

        # --- MAP SECTION (x: 30-700, y: 350-800) --- (REMOVED)
        #map_x, map_y = 20, 0
        #map_width, map_height = 512, 768
        #grid_params = GridSystem.calculate_full_grid_bounds(map_x, map_y, map_width, map_height)
        #grid_start_col, grid_end_col, grid_start_row, grid_end_row, scale_factor, offset_x, offset_y = grid_params
        #scale_factor = scale_factor * 1.2
        #offset_y = offset_y - 50


        # --- TASK DISPLAY (right side) ---
        task_display_x, task_display_y = 620, 640

        # Human task
        if show_human_task and human_target is not None:
            try:
                human_task = 'NO CHANGE' if human_target_id == plugin.human_indicated_plan_dataref.value else str(human_task_type) + ' ' + str(human_target.grid_position)
                xpgl.drawText(plugin.font60, task_display_x, task_display_y - 190, "HUMAN", alignment="L", color=Colors['green'])
                xpgl.drawText(plugin.font50, task_display_x, task_display_y - 250, human_task, alignment="L", color=Colors['white'])
            except:
                pass


        # Agent task
        try:
            if show_agent_task and agent_target is not None:
                agent_task = str(agent_task_type) + ' ' + str(agent_target.grid_position)
                xpgl.drawText(plugin.font50, task_display_x, task_display_y - 0, "WINGMAN", alignment="L", color=Colors['cyan'])
                xpgl.drawText(plugin.font50, task_display_x, task_display_y - 50, agent_task, alignment="L", color=Colors['white'])
            else:
                agent_task = 'Task unknown'
        except:
            pass

        # --- BUTTONS (below grid) ---
        button_width = 320
        button_height = 100
        button_spacing = 50
        buttons_x = 650  # Center buttons (1024/2 - 400/2 = 312)
        button_y_start = 240

        buttons = []
        #button_actions = []  # Track what each button does

        if plugin.show_best_plan:
            buttons.append("ACCEPT #1")
            buttons.append("REJECT")
        else:
            buttons.append("ACCEPT #2")
            buttons.append("REJECT")


        # Render buttons
        for i, button_label in enumerate(buttons):
            button_y = button_y_start - i * (button_height + button_spacing)

            if button_label in ['ACCEPT #1','ACCEPT #2']:
                if plugin.plan_grid.selected_row == i:
                    button_color = (0, 1, 0)
                    text_color = (0.0, 0.0, 0.0)
                else:
                    button_color = (0, 0.2, 0)
                    text_color = (1.0, 1.0, 1.0)

            elif button_label == 'REJECT':
                if plugin.plan_grid.selected_row == i:
                    button_color = (1, 0, 0)
                    text_color = (0.0, 0.0, 0.0)
                else:
                    button_color = (0.2, 0, 0)
                    text_color = (1.0, 1.0, 1.0)
            else:
                button_color = (0.5, 0, 0.5)
                text_color = (1.0, 0.0, 1.0)

            # Draw button
            text_x = buttons_x + button_width / 2
            font = plugin.font60
            xpgl.drawRectangle(buttons_x, button_y, button_width, button_height, color=button_color)

            if button_label.startswith('ACCEPT'):
                xpgl.drawLine(buttons_x + button_width + 10, button_y + button_height, buttons_x + button_width + 40, button_y + button_height/2, color=Colors['green'], thickness=20)
                xpgl.drawLine(buttons_x + button_width + 10, button_y, buttons_x + button_width + 40, button_y + button_height / 2, color=Colors['green'], thickness=20)
            xpgl.drawText(font, text_x, button_y + button_height / 2 - 14, button_label, alignment="C", color=text_color)

        plugin.draw_border_around_screen(Colors['red'], thickness=20, flashing=True)

    except Exception as e:
        plugin.log('Error in plan_suggestion screen:')
        plugin.log(e)
        plugin.log(traceback.format_exc())
        rendering.draw_waiting_for_datarefs(plugin.font_big)




def render_classify_screen(plugin, data):
    """Render the fire classification screen when human is in range of a target"""
    try:
        xp.setGraphicsState(0, 1)
        # Read the target ID we're classifying
        target_id = data.get('target_id', plugin.target_in_classify_range)

        if target_id is None:
            plugin.set_screen('primary')
            return

        # Safety check - if not in range, force back to primary screen
        if target_id == 99 or target_id < 0 or target_id > 7:
            plugin.set_screen('primary')
            return

        image_width = plugin.screen_width * 0.55
        image_height = plugin.screen_height * 0.655
        image_x = plugin.screen_width / 4  # Bottom right corner
        image_y = plugin.screen_height / 3
        header_text_x, header_text_y = 1024 / 2, 710
        button_width = 250
        button_height = 150
        button_spacing = 50
        button_spacing_under_image = 70

        xpgl.drawRectangle(0, 0, plugin.screen_width, plugin.screen_height, color=Colors['black'])

        # Use pre-loaded image from plugin.fire_images
        fire_image = data.get('fire_image', plugin.fire_images.get(target_id))
        if fire_image:
            xpgl.drawTexture(fire_image, image_x, image_y, width=image_width, height=image_height)

        # Draw title text
        xpgl.drawText(plugin.font60, header_text_x, header_text_y, f"CLASSIFY FIRE", alignment="C", color=Colors['white'])

        # Draw classification buttons below the image
        # Two square buttons: MODERATE (yellow/gold) and SEVERE (red)
        buttons_y = image_y - button_height - button_spacing_under_image  # 30 pixels below the image

        # Calculate button positions to center them horizontally below the image
        total_width = 2 * button_width + button_spacing
        start_x = image_x + (image_width - total_width) // 2

        # MODERATE button (left, index 0)
        moderate_x = start_x
        moderate_y = buttons_y

        selected_col = data.get('selected_col', plugin.classify_grid.selected_col)

        if selected_col == 0:
            moderate_color = (1.0, 0.84, 0.0)  # Gold/yellow when selected
            moderate_text_color = Colors['black']
        else:
            moderate_color = (0.25, 0.21, 0.0)  # Darker gold when not selected
            moderate_text_color = (0.5, 0.5, 0.5)

        xpgl.drawRectangle(moderate_x, moderate_y, button_width, button_height, color=moderate_color)
        xpgl.drawText(plugin.font60, moderate_x + button_width // 2, moderate_y + button_height // 2 - 15, "MODRT", alignment="C", color=moderate_text_color)

        # SEVERE button (right, index 1)
        severe_x = start_x + button_width + button_spacing
        severe_y = buttons_y

        if selected_col == 1:
            severe_color = Colors['red']  # Bright red when selected
            severe_text_color = Colors['white']
        else:
            severe_color = (0.25, 0.0, 0.0)  # Dark red when not selected
            severe_text_color = (0.5, 0.5, 0.5)

        xpgl.drawRectangle(severe_x, severe_y, button_width, button_height, color=severe_color)
        xpgl.drawText(plugin.font60, severe_x + button_width // 2, severe_y + button_height // 2 - 15,
                     "SEVERE", alignment="C", color=severe_text_color)

        plugin.draw_border_around_screen(Colors['red'], thickness = 20, flashing=True)

    except Exception as e:
        plugin.log('Error in classify screen:')
        plugin.log(e)
        plugin.log(traceback.format_exc())
        rendering.draw_waiting_for_datarefs(plugin.font_big)



def render_review_recording_screen(plugin, data):
    """
    Renders the recorded route/position for review. Shows a line from start to end position (for routes),
    displays length and heading, and provides three buttons: "Relay", "Erase", and "Exit".
    """
    try:
        xp.setGraphicsState(0, 1)

        xpgl.drawRectangle(0,  0, 1024, 768, color=(0.2, 0.2, 0.2))

        recording = data.get('recording')
        if recording is None:
            plugin.set_screen('primary')
            return

        # Draw title
        title_text = f"REVIEW RECORDING - FIRE at {plugin.targets[-1 if recording.fire_id == 99 else recording.fire_id].grid_position}"
        xpgl.drawText(plugin.font60, 512, 680, title_text, alignment="C", color=Colors['white'])

        # Display different content based on recording type
        route_incomplete = True
        if isinstance(recording, PositionRecording):
            # For position recordings, just show the position info
            route_incomplete = False
            rec_time = recording.timestamp
            timestamp_str = f"{int(rec_time // 60)}:{int(rec_time % 60):02d}"
            xpgl.drawText(plugin.font_big, 512, 620, f"Recorded at: {timestamp_str}", alignment="C", color=Colors['white'])
            #xpgl.drawText(plugin.font_big, 512, 560, f"Location: {recording.position[0]:.3f}, {recording.position[1]:.3f}", alignment="C", color=Colors['white'])
            xpgl.drawText(plugin.font_big, 512, 560, f"Recording MSL: {recording.position[2]*plugin.m_to_ft:.1f}", alignment="C", color=Colors['white'])
            xpgl.drawText(plugin.font_big, 512, 500, f"Fire MSL: {plugin.targets[recording.fire_id].alt*plugin.m_to_ft:.1f}", alignment="C", color=Colors['white'])

        elif isinstance(recording, RouteRecording):
            # For route recordings, show start/end positions and calculate bearing/distance
            type_label = "INITIAL ROUTE" if recording.type == 'initial' else "REFINED ROUTE"
            xpgl.drawText(plugin.font_big, 512, 620, f"{type_label}", alignment="C", color=Colors['white'])

            if recording.end_pos:
                # Calculate bearing between start and end
                route_incomplete = False

                bearings = []
                for i in range(len(recording.trajectory_points) - 1):
                    lat1, lon1, alt1 = recording.trajectory_points[i]
                    lat2, lon2, alt2 = recording.trajectory_points[i + 1]

                    bearing = GridSystem.calculate_heading(lat1, lon1, lat2, lon2)
                    bearings.append(bearing)
                if bearings:
                    average_bearing = sum(bearings) / len(bearings)
                    average_bearing = (average_bearing + 360) % 360 # TODO maybe remove the declination subtraction #  - plugin.mag_declination
                else:
                    average_bearing = 999.0

                # Calculate distance
                start_lat, start_lon, start_alt = recording.start_pos
                end_lat, end_lon, end_alt = recording.end_pos
                distance_nm = GridSystem.calculate_distance(start_lat, start_lon, end_lat, end_lon)

                xpgl.drawText(plugin.font_big, 712, 560, f"Length: {distance_nm:.2f} NM",alignment="C", color=Colors['white'])
                xpgl.drawText(plugin.font_big, 712, 500, f"Heading: {average_bearing:.0f} deg",alignment="C", color=Colors['white'])
                average_msl = np.mean([point[2] for point in recording.trajectory_points])
                xpgl.drawText(plugin.font_big, 712, 440, f"Average MSL: {average_msl*plugin.m_to_ft:.0f}ft", alignment="C", color=Colors['white'])
                xpgl.drawText(plugin.font_big, 712, 380, f"Fire MSL: {plugin.targets[recording.fire_id].alt*plugin.m_to_ft:.0f}ft", alignment="C", color=Colors['white'])


                # Draw route visualization
                map_center_x, map_center_y = 512-200, 380
                map_size = 400
                xpgl.drawRectangle(map_center_x - map_size // 2, map_center_y - map_size // 2,
                                   map_size, map_size, color=(0.2, 0.2, 0.3))

                # NEW: Calculate bounds for all trajectory points
                if len(recording.trajectory_points) >= 2:
                    # Find min/max lat/lon to determine scale
                    lats = [p[0] for p in recording.trajectory_points]
                    lons = [p[1] for p in recording.trajectory_points]
                    min_lat, max_lat = min(lats), max(lats)
                    min_lon, max_lon = min(lons), max(lons)

                    # Calculate center of trajectory
                    mid_lat = (min_lat + max_lat) / 2
                    mid_lon = (min_lon + max_lon) / 2

                    # Calculate range in NM
                    lat_range_nm = (max_lat - min_lat) * 60
                    lon_range_nm = (max_lon - min_lon) * 60 * math.cos(math.radians(mid_lat))
                    max_range_nm = max(lat_range_nm, lon_range_nm)

                    # Calculate scale to fit in map with padding
                    if max_range_nm > 0:
                        scale = (map_size * 0.7) / max_range_nm
                    else:
                        scale = map_size * 0.7

                    # NEW: Draw trajectory as connected line segments
                    for i in range(len(recording.trajectory_points) - 1):
                        lat1, lon1, alt1 = recording.trajectory_points[i]
                        lat2, lon2, alt2 = recording.trajectory_points[i + 1]

                        # Convert to screen coordinates relative to trajectory center
                        dx1_nm = (lon1 - mid_lon) * 60 * math.cos(math.radians((lat1 + mid_lat) / 2))
                        dy1_nm = (lat1 - mid_lat) * 60
                        dx2_nm = (lon2 - mid_lon) * 60 * math.cos(math.radians((lat2 + mid_lat) / 2))
                        dy2_nm = (lat2 - mid_lat) * 60

                        x1 = map_center_x + (dx1_nm * scale)
                        y1 = map_center_y + (dy1_nm * scale)
                        x2 = map_center_x + (dx2_nm * scale)
                        y2 = map_center_y + (dy2_nm * scale)

                        # Draw line segment
                        xpgl.drawLine(x1, y1, x2, y2, thickness = 3.0, color=Colors['green'])

                    # Draw start marker (green) at first point
                    first_lat, first_lon, first_alt = recording.trajectory_points[0]
                    dx_nm = (first_lon - mid_lon) * 60 * math.cos(math.radians((first_lat + mid_lat) / 2))
                    dy_nm = (first_lat - mid_lat) * 60
                    start_x = map_center_x + (dx_nm * scale)
                    start_y = map_center_y + (dy_nm * scale)

                    marker_size = 12
                    xpgl.drawRectangle(start_x - marker_size // 2, start_y - marker_size // 2,
                                       marker_size, marker_size, color=Colors['green'])

                    # Draw end marker (red) at last point
                    last_lat, last_lon, last_alt = recording.trajectory_points[-1]
                    dx_nm = (last_lon - mid_lon) * 60 * math.cos(math.radians((last_lat + mid_lat) / 2))
                    dy_nm = (last_lat - mid_lat) * 60
                    end_x = map_center_x + (dx_nm * scale)
                    end_y = map_center_y + (dy_nm * scale)

                    xpgl.drawRectangle(end_x - marker_size // 2, end_y - marker_size // 2,
                                       marker_size, marker_size, color=Colors['red'])

                scale = map_size * 0.7

                # Draw target
                # for target in plugin.targets:
                #     if target.id == recording.fire_id:
                #         break
                #
                # if target:
                #     target_lat, target_lon = target.lat, target.long
                #     lat1, lon1, alt1 = recording.start_pos
                #     lat2, lon2, alt2 = recording.end_pos
                #     route_mid_lat = (lat1 + lat2) / 2 # Calculate target position relative to route midpoint
                #     route_mid_lon = (lon1 + lon2) / 2
                #     dx_target_nm = (target_lon - route_mid_lon) * 60 * math.cos(math.radians((target_lat + route_mid_lat) / 2))
                #     dy_target_nm = (target_lat - route_mid_lat) * 60
                #     target_x = map_center_x + (dx_target_nm * scale)
                #     target_y = map_center_y + (dy_target_nm * scale)
                #     target_marker_size = 20
                #     offset = target_marker_size // 2
                #     xpgl.drawLine(target_x - offset, target_y - offset,
                #                   target_x + offset, target_y + offset,
                #                   color=(1.0, 0.3, 0.0))  # Orange-red
                #     xpgl.drawLine(target_x - offset, target_y + offset,
                #                   target_x + offset, target_y - offset,
                #                   color=(1.0, 0.3, 0.0))  # Orange-red
                #
                #     # Draw circle around target to make it more visible
                #     circle_radius = 15
                #     num_segments = 16
                #     for i in range(num_segments):
                #         angle1 = (i * 2 * math.pi) / num_segments
                #         angle2 = ((i + 1) * 2 * math.pi) / num_segments
                #         x1 = target_x + circle_radius * math.cos(angle1)
                #         y1 = target_y + circle_radius * math.sin(angle1)
                #         x2 = target_x + circle_radius * math.cos(angle2)
                #         y2 = target_y + circle_radius * math.sin(angle2)
                #         xpgl.drawLine(x1, y1, x2, y2, color=(1.0, 0.3, 0.0))
                #
                #     # Label the target
                #     xpgl.drawText(plugin.font_small, target_x, target_y + 30,
                #                   f"FIRE {recording.fire_id}",
                #                   alignment="C", color=(1.0, 0.3, 0.0))

            else:
                xpgl.drawText(plugin.font, 512, 580, "Route incomplete - no end position", alignment="C", color=Colors['red'])
                route_incomplete = True

        # Draw 2 buttons: RELAY, ERASE
        button_width = 300
        button_height = 90
        button_spacing = 40
        buttons_y = 50

        # Calculate button positions to center them
        total_width = 3 * button_width + 2 * button_spacing
        start_x = 200

        # RELAY button (left, index 0)
        relay_x = start_x
        relay_y = buttons_y

        if plugin.review_grid.selected_col == 0:
            relay_color = Colors['green']
            relay_text_color = Colors['white']
        else:
            relay_color = (0.0, 0.2, 0.0)  # Dark green
            relay_text_color = Colors['white']

        xpgl.drawRectangle(relay_x, relay_y, button_width, button_height, color=relay_color)

        try:
            text = "BACK" if route_incomplete else 'RELAY'
        except:
            text = "RELAY"
        xpgl.drawText(plugin.font_big, relay_x + button_width // 2, relay_y + button_height // 2 - 12, text, alignment="C", color=relay_text_color)

        # ERASE button (middle, index 1)
        erase_x = start_x + button_width + button_spacing
        erase_y = buttons_y

        if plugin.review_grid.selected_col == 1:
            erase_color = Colors['red']
            erase_text_color = Colors['white']
        else:
            erase_color = (0.2, 0.0, 0.0)  # Dark red
            erase_text_color = Colors['white']

        xpgl.drawRectangle(erase_x, erase_y, button_width, button_height, color=erase_color)
        xpgl.drawText(plugin.font_big, erase_x + button_width // 2, erase_y + button_height // 2 - 12,"ERASE", alignment="C", color=erase_text_color)

        # Draw navigation hint
        xpgl.drawText(plugin.font, 512, 15, "THUMB SWITCH TO NAVIGATE  TRIGGER TO SELECT",alignment="C", color=Colors['white'])

        #if plugin.initiative_level == 2.0 and recording_is_complete:
            #plugin.render_wingman_suggestion_for_recording(recording)


    except Exception as e:
        plugin.log('Error in review_recording screen:')
        plugin.log(str(e))
        plugin.log(traceback.format_exc())
        plugin.set_screen('primary')




def render_classify_agent_screen(plugin, data):
    """
    Renders the agent ID request screen - shown when an agent requests help identifying a fire.
    Similar to classify screen but with three options: MODRT, AUTO, SEVERE
    """
    try:

        xp.setGraphicsState(0, 1)
        # Read the target ID the agent is requesting help with
        target_id_raw = data.get('target_id_raw', plugin.agent_id_request_dataref.value)
        target_id = data.get('target_id', int(target_id_raw))

        # Safety check - if no agent request, force back to primary screen
        if target_id_raw == 99.0 or target_id < 0 or target_id > 7:
            plugin.set_screen("primary")
            return

        # Display pre-loaded fire image
        plugin.screen_width = 1024
        plugin.screen_height = 768

        image_width = plugin.screen_width * 0.6
        image_height = plugin.screen_height * 0.6
        image_x = plugin.screen_width / 4 - 50
        image_y = plugin.screen_height / 3
        header_text_x, header_text_y = 1024/2, 730
        button_width = 250
        button_height = 130
        button_spacing = 50
        button_spacing_under_image = 60

        xpgl.drawRectangle(0, 0, plugin.screen_width, plugin.screen_height, color=Colors['black'])

        # Use pre-loaded image from plugin.fire_images
        fire_image = data.get('fire_image', plugin.fire_images.get(target_id))
        if fire_image:
            xpgl.drawTexture(fire_image, image_x, image_y, width=image_width, height=image_height)

        # Draw title text
        fire_grid = plugin.targets[target_id].grid_position
        xpgl.drawText(plugin.font_big, header_text_x, header_text_y, f"WINGMAN REQUESTS CLASSIFY FIRE AT {fire_grid}", alignment="C", color=Colors['white'])

        # Navigation hint
        xpgl.drawText(plugin.font, header_text_x, 20, f"{plugin.dpad_name} left/right to navigate, {plugin.select_button_name} to select",
                      alignment="C", color=Colors['white'])

        # Draw three classification buttons below the image: MODRT, AUTO, SEVERE
        buttons_y = image_y - button_height - button_spacing_under_image

        # Calculate button positions to center them horizontally below the image
        total_width = 3 * button_width + 2 * button_spacing
        start_x = image_x + (image_width - total_width) // 2 - 20

        # MODRT button (left, index 0)
        modrt_x = start_x
        modrt_y = buttons_y

        selected_col = data.get('selected_col', plugin.classify_agent_grid.selected_col)

        if selected_col == 0:
            modrt_color = (1.0, 0.84, 0.0)  # Gold/yellow when selected
            modrt_text_color = Colors['black']
        else:
            modrt_color = (0.25, 0.21, 0.0)  # Darker gold when not selected
            modrt_text_color = (0.5, 0.5, 0.5)

        xpgl.drawRectangle(modrt_x, modrt_y, button_width, button_height, color=modrt_color)
        xpgl.drawText(plugin.font60, modrt_x + button_width // 2, modrt_y + button_height // 2 - 15, "MODRT", alignment="C", color=modrt_text_color)

        # AUTO button (middle, index 1)
        auto_x = start_x + button_width + button_spacing
        auto_y = buttons_y

        if selected_col == 1:
            auto_color = (0.0, 0.7, 1.0)  # Bright cyan when selected
            auto_text_color = Colors['black']
        else:
            auto_color = (0.0, 0.17, 0.25)  # Dark cyan when not selected
            auto_text_color = (0.5, 0.5, 0.5)

        xpgl.drawRectangle(auto_x, auto_y, button_width, button_height, color=auto_color)
        xpgl.drawText(plugin.font60, auto_x + button_width // 2, auto_y + button_height // 2 - 15, "AUTO", alignment="C", color=auto_text_color)

        # SEVERE button (right, index 2)
        severe_x = start_x + 2 * (button_width + button_spacing)
        severe_y = buttons_y

        if selected_col == 2:
            severe_color = Colors['red']  # Bright red when selected
            severe_text_color = Colors['white']
        else:
            severe_color = (0.25, 0.0, 0.0)  # Dark red when not selected
            severe_text_color = (0.5, 0.5, 0.5)

        xpgl.drawRectangle(severe_x, severe_y, button_width, button_height, color=severe_color)
        xpgl.drawText(plugin.font60, severe_x + button_width // 2, severe_y + button_height // 2 - 15, "SEVERE", alignment="C", color=severe_text_color)

        plugin.draw_border_around_screen(Colors['red'], thickness=20, flashing=True)


    except Exception as e:
        plugin.log('Error in classifyagent screen:')
        plugin.log(e)
        plugin.log(traceback.format_exc())
        rendering.draw_waiting_for_datarefs(plugin.font_big)




def draw_target_for_task(plugin, task_type, target, grid_params, member, xy_override=None):
    """
    Draw target visualization based on task type.

    Args:
        task_type: "classify" or "route"
        target: Target object
        grid_params: Tuple from calculate_dynamic_grid_bounds
    """
    xp.setGraphicsState(0, 1)
    if not target or not task_type:
        return

    grid_start_col, grid_end_col, grid_start_row, grid_end_row, scale_factor, offset_x, offset_y = grid_params

    # Calculate grid offset based on player position (needed for lat/lon to screen conversion)
    player_lat, player_lon = plugin.lat_dataref.value, plugin.lon_dataref.value
    grid_offset_x = (plugin.aor_center_long - player_lon) * plugin.lon_scale_nm * plugin.pixels_per_nm
    grid_offset_y = (plugin.aor_center_lat - player_lat) * plugin.lat_scale_nm * plugin.pixels_per_nm

    if xy_override:
        x_pos, y_pos = xy_override

    else:
        # Convert target lat/lon to grid indices
        lat_normalized = (target.lat - plugin.GRID_SW_LAT) / (plugin.GRID_NE_LAT - plugin.GRID_SW_LAT)
        lon_normalized = (target.long - plugin.GRID_SW_LON) / (plugin.GRID_NE_LON - plugin.GRID_SW_LON)

        target_col_idx = int(lon_normalized * 17)
        target_row_idx = int(lat_normalized * 17)
        x_pos = offset_x + (target_col_idx - grid_start_col) * scale_factor
        y_pos = offset_y + (target_row_idx - grid_start_row) * scale_factor


    if task_type == "classify":
        # Draw red square covering grid cell
        xpgl.drawRectangle(x_pos, y_pos, scale_factor, scale_factor, color=(1.0, 0.0, 0.0))

    elif task_type == 'mark position':
        xpgl.drawCircle(x_pos, y_pos, 10, isFilled=True, num_vertices=8, color=(1.0, 0.0, 0.0))

    elif task_type in ["initial route", "refined route", "done"]:

        # Draw drop route lines if wind dataref available
        wind_dir = plugin.wind_dir
        wind_rad = math.radians(wind_dir)

        # Route extends 0.5 NM upwind and downwind
        route_length_nm = 1.5
        lat_scale_nm = 60.0
        lon_scale_nm = 60.0 * math.cos(math.radians(target.lat))

        # Calculate upwind and downwind positions
        # TODO consolidate with lat_lon_to_plan_grid()
        upwind_lat = target.lat + (route_length_nm / lat_scale_nm) * math.cos(wind_rad)
        upwind_lon = target.long + (route_length_nm / lon_scale_nm) * math.sin(wind_rad)
        downwind_lat = target.lat - (route_length_nm / lat_scale_nm) * math.cos(wind_rad)
        downwind_lon = target.long - (route_length_nm / lon_scale_nm) * math.sin(wind_rad)

        # Convert to screen coordinates
        upwind_lat_norm = (upwind_lat - plugin.GRID_SW_LAT) / (plugin.GRID_NE_LAT - plugin.GRID_SW_LAT)
        upwind_lon_norm = (upwind_lon - plugin.GRID_SW_LON) / (plugin.GRID_NE_LON - plugin.GRID_SW_LON)
        downwind_lat_norm = (downwind_lat - plugin.GRID_SW_LAT) / (plugin.GRID_NE_LAT - plugin.GRID_SW_LAT)
        downwind_lon_norm = (downwind_lon - plugin.GRID_SW_LON) / (plugin.GRID_NE_LON - plugin.GRID_SW_LON)

        upwind_col_idx = upwind_lon_norm * 17
        upwind_row_idx = upwind_lat_norm * 17
        downwind_col_idx = downwind_lon_norm * 17
        downwind_row_idx = downwind_lat_norm * 17

        upwind_x = offset_x + (upwind_col_idx - grid_start_col) * scale_factor
        upwind_y = offset_y + (upwind_row_idx - grid_start_row) * scale_factor
        downwind_x = offset_x + (downwind_col_idx - grid_start_col) * scale_factor
        downwind_y = offset_y + (downwind_row_idx - grid_start_row) * scale_factor

        radius = scale_factor * 0.15
        xpgl.drawCircle(x_pos, y_pos, radius, isFilled=True, num_vertices=16, color=(1.0, 0.0, 0.0)) # TODO fix placement

        # Draw route line
        whoflew = plugin.dataref_target_whoflew_list[target.id]
        if task_type == 'done':
            line_color = (0.3, 0.3, 0.3)
        elif task_type == 'initial route':
            line_color = (1.0, 0.0, 0.0)
        elif whoflew == 1.0: # Human
            line_color = (0.5, 1.0, 0.5)
        elif whoflew == 2.0: # Wingman
            line_color = (0.0, 1.0, 1.0) #if target.route1_recorder == 'wingman'
        else:
            line_color = (1.0, 1.0, 1.0)

        GL.glColor3f(line_color[0], line_color[1], line_color[2])
        GL.glLineWidth(5.0)
        GL.glBegin(GL.GL_LINES)
        GL.glVertex2f(upwind_x, upwind_y)
        GL.glVertex2f(downwind_x, downwind_y)
        GL.glEnd()




def draw_target_marker(plugin, screen_x, screen_y, color, label, linewidth=6.0, marker_size=20, label_offset_y = 25):
    """
    Draw a marker around a target position with a label.

    Args:
        screen_x: Screen X coordinate of the target
        screen_y: Screen Y coordinate of the target
        color: RGB tuple for the marker color (e.g., Colors['yellow'])
        label: Text label to display (e.g., 'H' for human, 'W' for wingman)
        marker_size: Size of the square marker
        label_offset_y: Offset for label below the marker
    """
    #marker_size = 20  # Size of the square marker
    #label_offset_y = 25  # Offset for label below the marker

    # Draw square outline around target
    GL.glColor3f(*color)
    GL.glLineWidth(linewidth)
    GL.glBegin(GL.GL_LINE_LOOP)
    GL.glVertex2f(screen_x - marker_size, screen_y - marker_size)
    GL.glVertex2f(screen_x + marker_size, screen_y - marker_size)
    GL.glVertex2f(screen_x + marker_size, screen_y + marker_size)
    GL.glVertex2f(screen_x - marker_size, screen_y + marker_size)
    GL.glEnd()
    GL.glLineWidth(1.0)  # Reset line width

    # Draw label below the marker
    xpgl.drawText(plugin.font_small, int(screen_x), int(screen_y - label_offset_y),
                  label, alignment="C", color=color)



def draw_border_around_screen(plugin, color, thickness, flashing=False, flash_interval=100):
    # Initialize frame counter if it doesn't exist
    if not hasattr(plugin, '_border_flash_counter'):
        plugin._border_flash_counter = 0

    # Increment counter on each call
    plugin._border_flash_counter += 1

    # Determine if border should show based on flash interval
    show_border = (plugin._border_flash_counter // flash_interval) % 2 == 0

    if flashing and not show_border:
        return
    else:
        xpgl.drawLine(0, 0, 0, plugin.screen_height, thickness=thickness, color=color)
        xpgl.drawLine(plugin.screen_width, 0, plugin.screen_width, plugin.screen_height, thickness=thickness, color=color)

        xpgl.drawLine(0, 0, plugin.screen_width, 0, thickness=thickness, color=color)
        xpgl.drawLine(0, plugin.screen_height, plugin.screen_width, plugin.screen_height, thickness=thickness, color=color)
        return



