import math

import xp
from XPPython3 import xpgl
from XPPython3.xpgl import Colors
from XPPython3.utils.datarefs import find_dataref
from XPPython3.utils import commands
from OpenGL import GL


# ============================================================================
# UI COMPONENTS - Rendering utilities
# ============================================================================

def draw_refresh_reminder(font):
    """Helper method to display 'waiting for datarefs' message with white background"""
    xpgl.drawRectangle((1024 - 600) // 2, (768 - 100) // 2, 600, 100, color=Colors['black'])
    xpgl.drawText(font, 1024 // 2, 768 // 2 - 10, "Please wait...", alignment="C", color=Colors['green'])

def draw_waiting_for_datarefs(font):
    """Helper method to display 'waiting for datarefs' message with white background"""
    xpgl.drawRectangle((1024 - 400) // 2, (768 - 100) // 2, 400, 100, color=Colors['white'])
    xpgl.drawText(font, 1024 // 2, 768 // 2 - 10, "waiting for datarefs", alignment="C", color=Colors['black'])

def draw_wind_arrow(x, y, length, wind_direction, font):
    xpgl.drawRectangle(x, y, 150, 100, color=Colors['black'])

    # Arrow position (bottom right corner)
    arrow_center_x = x + 50
    arrow_center_y = y + 30
    draw_arrow(arrow_center_x, arrow_center_y, length, wind_direction + 180)

    # Manually adjust arrow placement for 95deg arrow due to clipping
    if wind_direction == 95:
        wind_x, wind_y = arrow_center_x + 42, arrow_center_y + 10
    else:
        wind_x, wind_y = arrow_center_x + 42, arrow_center_y - 10

    xpgl.drawText(font, wind_x, wind_y, f"{int((wind_direction + 360) % 360)}", alignment="C",
                  color=Colors['white'])

def draw_angled_triangle(x, y, size, orientation, color=Colors['cyan']):
    heading_rad = math.radians(orientation)  # Convert heading to radians (0° = North, clockwise)
    nose_x = x + size * math.sin(heading_rad)  # Vertex 1: nose (pointing in heading direction)
    nose_y = y + size * math.cos(heading_rad)
    base_offset = size * 0.6
    perp_angle_left = heading_rad - math.radians(90)
    perp_angle_right = heading_rad + math.radians(90)
    base_left_x = x + base_offset * math.sin(perp_angle_left) - size * 0.3 * math.sin(
        heading_rad)
    base_left_y = y + base_offset * math.cos(perp_angle_left) - size * 0.3 * math.cos(
        heading_rad)
    base_right_x = x + base_offset * math.sin(perp_angle_right) - size * 0.3 * math.sin(
        heading_rad)
    base_right_y = y + base_offset * math.cos(perp_angle_right) - size * 0.3 * math.cos(
        heading_rad)

    # Draw filled cyan triangle with black outline
    xpgl.drawTriangle(nose_x, nose_y, base_left_x, base_left_y, base_right_x, base_right_y, color=color)

def draw_arrow(arrow_center_x, arrow_center_y, arrow_length, arrow_direction):
    # Convert wind direction to radians (wind is "from" direction, arrow points "from")
    # 0 degrees = North, 90 = East, 180 = South, 270 = West
    dir_rad = math.radians(arrow_direction)
    # Calculate arrow tip (pointing in wind "from" direction)
    tip_x = arrow_center_x + arrow_length * math.sin(dir_rad)
    tip_y = arrow_center_y + arrow_length * math.cos(dir_rad)
    tail_x = arrow_center_x - arrow_length * 0.5 * math.sin(dir_rad)  # Calculate arrow tail
    tail_y = arrow_center_y - arrow_length * 0.5 * math.cos(dir_rad)

    # Calculate arrow head wings
    wing_angle = math.radians(30)  # 30 degree wings
    wing_length = 20
    left_wing_x = tip_x - wing_length * math.sin(dir_rad - wing_angle)
    left_wing_y = tip_y - wing_length * math.cos(dir_rad - wing_angle)
    right_wing_x = tip_x - wing_length * math.sin(dir_rad + wing_angle)
    right_wing_y = tip_y - wing_length * math.cos(dir_rad + wing_angle)

    # Draw arrow shaft
    GL.glColor3f(1.0, 1.0, 1.0)  # White
    GL.glLineWidth(7.0)
    GL.glBegin(GL.GL_LINES)
    GL.glVertex2f(tail_x, tail_y)
    GL.glVertex2f(tip_x, tip_y)
    GL.glEnd()

    # Draw arrow head
    GL.glBegin(GL.GL_LINES)
    GL.glVertex2f(tip_x, tip_y)
    GL.glVertex2f(left_wing_x, left_wing_y)
    GL.glVertex2f(tip_x, tip_y)
    GL.glVertex2f(right_wing_x, right_wing_y)
    GL.glEnd()

def draw_rotated_rectangle(x1, y1, x2, y2, perp_x, perp_y, r, g, b, alpha):
    """
    Draws a rotated rectangle from point (x1,y1) to (x2,y2) with given width.
    perp_x, perp_y: perpendicular offset vector for width
    r, g, b, alpha: color components (0.0 to 1.0)
    """
    # Calculate 4 corners of the rectangle
    corner1_x = x1 + perp_x
    corner1_y = y1 + perp_y
    corner2_x = x1 - perp_x
    corner2_y = y1 - perp_y
    corner3_x = x2 - perp_x
    corner3_y = y2 - perp_y
    corner4_x = x2 + perp_x
    corner4_y = y2 + perp_y

    # Draw filled quad with transparency
    GL.glEnable(GL.GL_BLEND)
    GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
    GL.glColor4f(r, g, b, alpha)
    GL.glBegin(GL.GL_QUADS)
    GL.glVertex2f(corner1_x, corner1_y)
    GL.glVertex2f(corner2_x, corner2_y)
    GL.glVertex2f(corner3_x, corner3_y)
    GL.glVertex2f(corner4_x, corner4_y)
    GL.glEnd()
    GL.glDisable(GL.GL_BLEND)