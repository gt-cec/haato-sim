import math

# ============================================================================
# Coordinate transforms between LLA, X-Plane world coords, and X-Plane local coords
# ============================================================================

def get_relative_local_position(aircraft_x, aircraft_y, aircraft_z,
                                heading, direction, distance, height):
    """
    Given the aircraft's position and heading, calculate the local x,y,z coordinates of an object given its relative direction, distance, and height

    Args:
        aircraft_x, aircraft_y, aircraft_z: Aircraft position in local coords
        heading: Aircraft heading in degrees (0=North)
        direction: Relative direction in degrees (0=forward, 90=right)
        distance: Distance from aircraft in meters
        height: Height offset in meters

    Returns:
        tuple: (x, y, z) world coordinates
    """
    total_angle_rad = math.radians(heading + direction)

    offset_x = distance * math.sin(total_angle_rad)
    offset_z = -distance * math.cos(total_angle_rad)
    offset_y = height

    return (
        aircraft_x + offset_x,
        aircraft_y + offset_y,
        aircraft_z + offset_z
    )