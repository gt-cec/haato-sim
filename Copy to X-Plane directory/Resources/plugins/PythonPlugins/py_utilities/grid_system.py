import numpy as np
import math

# ============================================================================
# GEOGRAPHIC UTILITIES - Grid System and Calculations
# ============================================================================

class GridSystem:
    """Handles all geographic calculations and grid coordinate conversions"""

    # Grid bounds (17x17 NM area)
    # TODO init all of these when instantiating grid system in a plugin
    GRID_SW_LAT = 47.694800
    GRID_SW_LON = -121.318566
    GRID_NE_LAT = 47.978133
    GRID_NE_LON = -120.897615
    GRID_CENTER_LAT = 47.836467
    GRID_CENTER_LON = -121.108091

    GRID_SIZE = 17  # 17x17 grid
    GRID_SPACING_NM = 1.0  # Each cell is 1 NM

    lat_scale_nm = 60

    @staticmethod
    def calculate_heading(lat1, lon1, lat2, lon2):
        """Calculate bearing from point 1 to point 2 in degrees (0-360)"""
        dlon = math.radians(lon2 - lon1)
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        x = math.sin(dlon) * math.cos(lat2_rad)
        y = math.cos(lat1_rad) * math.sin(lat2_rad) - math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(dlon)
        heading = math.degrees(math.atan2(x, y))
        heading = (heading + 360) % 360
        return heading

    @staticmethod
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

    @staticmethod
    def destination_point(lat, lon, bearing, distance_nm):
        """
        Calculate destination point given start point, bearing, and distance

        Args:
            lat, lon: Starting position in degrees
            bearing: Bearing in degrees (0-360)
            distance_nm: Distance in nautical miles

        Returns:
            (lat, lon): Destination coordinates
        """
        R = 3440.065  # Earth's radius in nautical miles

        #bearing = -bearing

        lat_rad = math.radians(lat)
        lon_rad = math.radians(lon)
        bearing_rad = math.radians(bearing)

        lat2_rad = math.asin(math.sin(lat_rad) * math.cos(distance_nm / R) +
                             math.cos(lat_rad) * math.sin(distance_nm / R) * math.cos(bearing_rad))

        lon2_rad = lon_rad + math.atan2(math.sin(bearing_rad) * math.sin(distance_nm / R) * math.cos(lat_rad),
                                        math.cos(distance_nm / R) - math.sin(lat_rad) * math.sin(lat2_rad))

        return math.degrees(lat2_rad), math.degrees(lon2_rad)

    @classmethod
    def latlon_to_map_pixel_offset(cls, lat, long, aor_center_lat, aor_center_long, pixels_per_nm):
        """Given a latitude and longitude, calculate the pixel x,y to place it on the MFD moving map display, assuming the map is centered on the player's position"""
        lat_diff = lat - aor_center_lat  # Calculate offset from fixed grid center to target
        lon_diff = long - aor_center_long

        lon_scale_nm = 60 * math.cos(math.radians(aor_center_lat))

        offset_x_nm = lon_diff * lon_scale_nm  # Convert to screen offset in nautical miles
        offset_y_nm = lat_diff * cls.lat_scale_nm
        offset_x = offset_x_nm * pixels_per_nm  # Convert to pixels and add to grid center screen position
        offset_y = offset_y_nm * pixels_per_nm
        return offset_x, offset_y

    @classmethod
    def latlon_to_grid_position(cls, lat, lon):
        """
        Convert lat/lon to grid position (e.g., 'B7')

        Returns:
            Grid position string (e.g., 'B7') or 'OUT' if outside grid
        """
        # Check if outside grid
        if lat < cls.GRID_SW_LAT or lat > cls.GRID_NE_LAT or lon < cls.GRID_SW_LON or lon > cls.GRID_NE_LON:
            return 'OUTSIDE GRID'

        # Calculate normalized position within grid (0.0 to 1.0)
        lat_normalized = (lat - cls.GRID_SW_LAT) / (cls.GRID_NE_LAT - cls.GRID_SW_LAT)
        lon_normalized = (lon - cls.GRID_SW_LON) / (cls.GRID_NE_LON - cls.GRID_SW_LON)

        # Convert to grid indices (0-16)
        col_idx = int(lon_normalized * cls.GRID_SIZE)
        row_idx = int(lat_normalized * cls.GRID_SIZE)

        # Clamp to valid range
        col_idx = max(0, min(cls.GRID_SIZE - 1, col_idx))
        row_idx = max(0, min(cls.GRID_SIZE - 1, row_idx))

        # Convert to grid position string
        col_letter = chr(ord('A') + col_idx)  # 0=A, 1=B, ..., 16=Q
        row_number = row_idx + 1  # 0=1, 1=2, ..., 16=17

        return f"{col_letter}{row_number}"

    @classmethod
    def calculate_dynamic_grid_bounds(cls, human_pos, agent_pos, human_target, agent_target):
        """
        Calculate dynamic grid bounds to fit all positions within the map area.

        Args:
            human_pos: (lat, lon) tuple for human position
            agent_pos: (lat, lon) tuple for agent position
            human_target: Target object for human task
            agent_target: Target object for agent task

        Returns:
            Tuple: (grid_start_col, grid_end_col, grid_start_row, grid_end_row,
                   scale_factor, screen_offset_x, screen_offset_y)
        """
        # Grid bounds constants

        # Collect all lat/lon positions
        positions = []
        if human_pos:
            positions.append(human_pos)
        if agent_pos:
            positions.append(agent_pos)
        if human_target:
            positions.append((human_target.lat, human_target.long))
        if agent_target:
            positions.append((agent_target.lat, agent_target.long))

        if not positions:
            # Default to center area if no positions
            return (7, 11, 7, 11, 50.0, 30, 350)

        # Find min/max lat/lon
        lats = [pos[0] for pos in positions]
        lons = [pos[1] for pos in positions]

        min_lat = min(lats)
        max_lat = max(lats)
        min_lon = min(lons)
        max_lon = max(lons)

        # Add margin (10% on each side)
        lat_range = max_lat - min_lat
        lon_range = max_lon - min_lon
        margin_lat = max(0.01, lat_range * 0.1)  # At least 0.01 degrees margin
        margin_lon = max(0.01, lon_range * 0.1)

        min_lat -= margin_lat
        max_lat += margin_lat
        min_lon -= margin_lon
        max_lon += margin_lon

        # Clamp to grid bounds
        min_lat = max(cls.GRID_SW_LAT, min_lat)
        max_lat = min(cls.GRID_NE_LAT, max_lat)
        min_lon = max(cls.GRID_SW_LON, min_lon)
        max_lon = min(cls.GRID_NE_LON, max_lon)

        # Convert to grid coordinates (0-16 indices)
        lat_normalized_min = (min_lat - cls.GRID_SW_LAT) / (cls.GRID_NE_LAT - cls.GRID_SW_LAT)
        lat_normalized_max = (max_lat - cls.GRID_SW_LAT) / (cls.GRID_NE_LAT - cls.GRID_SW_LAT)
        lon_normalized_min = (min_lon - cls.GRID_SW_LON) / (cls.GRID_NE_LON - cls.GRID_SW_LON)
        lon_normalized_max = (max_lon - cls.GRID_SW_LON) / (cls.GRID_NE_LON - cls.GRID_SW_LON)

        grid_start_row = max(1, int(lat_normalized_min * 17) + 1)
        grid_end_row = min(17, int(lat_normalized_max * 17) + 1)
        grid_start_col = max(0, int(lon_normalized_min * 17))
        grid_end_col = min(16, int(lon_normalized_max * 17))

        # Calculate scale factor to fit within screen bounds
        # Screen area: x=30-700 (670 pixels wide), y=350-800 (450 pixels tall)
        map_left = 30
        map_bottom = 350
        map_width = 670
        map_height = 450

        grid_cols = grid_end_col - grid_start_col + 1
        grid_rows = grid_end_row - grid_start_row + 1

        scale_x = 0.9 * map_width / max(1, grid_cols)
        scale_y = 0.9 * map_height / max(1, grid_rows)
        scale_factor = min(scale_x, scale_y)

        # Center the grid if it doesn't fill the area
        actual_width = grid_cols * scale_factor
        actual_height = grid_rows * scale_factor
        screen_offset_x = map_left + (map_width - actual_width) / 2
        screen_offset_y = -90 + map_bottom + (map_height - actual_height) / 2

        return (grid_start_col, grid_end_col, grid_start_row, grid_end_row,
                scale_factor, screen_offset_x, screen_offset_y)

    @staticmethod
    def calculate_full_grid_bounds(map_x, map_y, map_width, map_height):
        """
        Calculate grid_params for FULL 17x17 grid (all columns A-Q, all rows 1-17).
        Similar to calculate_dynamic_grid_bounds but always shows entire grid.

        Args:
            map_x: Left edge of map area (pixels)
            map_y: Bottom edge of map area (pixels)
            map_width: Width of map area (pixels)
            map_height: Height of map area (pixels)

        Returns:
            Tuple: (grid_start_col, grid_end_col, grid_start_row, grid_end_row,
                   scale_factor, screen_offset_x, screen_offset_y)
        """
        # Full grid: columns 0-16 (A-Q), rows 0-16 (1-17)
        grid_start_col = 0
        grid_end_col = 16
        grid_start_row = 0
        grid_end_row = 16

        grid_cols = 17
        grid_rows = 17

        # Calculate scale to fit in available space (90% to leave margin)
        scale_x = 0.9 * map_width / grid_cols
        scale_y = 0.9 * map_height / grid_rows
        scale_factor = min(scale_x, scale_y)

        # Center the grid in the map area
        actual_width = grid_cols * scale_factor
        actual_height = grid_rows * scale_factor
        screen_offset_x = map_x + (map_width - actual_width) / 2
        screen_offset_y = map_y + (map_height - actual_height) / 2

        return (grid_start_col, grid_end_col, grid_start_row, grid_end_row,
                scale_factor, screen_offset_x, screen_offset_y)