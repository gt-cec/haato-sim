import math

# ============================================================================
# Navigation utilities
# ============================================================================

# def calculate_heading(lat1, lon1, lat2, lon2):
#     """Calculate bearing from point 1 to point 2 in degrees (0-360)"""
#     dlon = math.radians(lon2 - lon1)
#     lat1_rad = math.radians(lat1)
#     lat2_rad = math.radians(lat2)
#     x = math.sin(dlon) * math.cos(lat2_rad)
#     y = math.cos(lat1_rad) * math.sin(lat2_rad) - math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(dlon)
#     heading = math.degrees(math.atan2(x, y))
#     heading = (heading + 360) % 360
#     return heading

def calculate_distance(lat1, lon1, lat2, lon2):
    """Calculate distance between two lat/lon points in nautical miles using haversine formula"""
    R = 3440.065  # Earth's radius in nautical miles

    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = math.sin(dlat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))

    return R * c


def calculate_slant_range(lat1, lon1, alt1, lat2, lon2, alt2):
    """Calculate distance between two LLA points.

    Args:
        lat1, lon1: First point coordinates in decimal degrees
        alt1: First point altitude in meters
        lat2, lon2: Second point coordinates in decimal degrees
        alt2: Second point altitude in meters

    Returns:
        Distance in nautical miles
    """
    # Earth radius in meters (mean radius)
    R = 6371000

    # Convert latitude and longitude from degrees to radians
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    lon1_rad = math.radians(lon1)
    lon2_rad = math.radians(lon2)

    # Convert LLA to ECEF (Earth-Centered, Earth-Fixed) coordinates
    # X, Y, Z coordinates for point 1
    x1 = (R + alt1) * math.cos(lat1_rad) * math.cos(lon1_rad)
    y1 = (R + alt1) * math.cos(lat1_rad) * math.sin(lon1_rad)
    z1 = (R + alt1) * math.sin(lat1_rad)

    # X, Y, Z coordinates for point 2
    x2 = (R + alt2) * math.cos(lat2_rad) * math.cos(lon2_rad)
    y2 = (R + alt2) * math.cos(lat2_rad) * math.sin(lon2_rad)
    z2 = (R + alt2) * math.sin(lat2_rad)

    # Calculate Euclidean distance in 3D space
    distance_meters = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2 + (z2 - z1) ** 2)

    # Convert meters to nautical miles (1 nautical mile = 1852 meters)
    distance_nm = distance_meters / 1852
    return distance_nm
