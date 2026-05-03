"""
Data logger - CSV format.

Storage notes:
    * CSV format is more compact and easier to analyze than JSON
    * Generates one row per time step with all metrics as columns
"""

import csv
import logging
import time
from datetime import datetime
import os

from utility.config_loader import get_config as _get_config

logger = logging.getLogger(__name__)

class DataLogger:
    def __init__(self, xpc, mm, user_id, verbose, wingman_initiative_level, fire_layout, log_freq, config, trial, log_file_identifier, notes="", log_dir="./logs"):
        self.xpc = xpc
        self.user_id = user_id
        self.mm = mm
        self.notes = notes
        self.verbose = verbose
        self.log_dir = log_dir
        self.start_time = datetime.now()
        self.log_freq = log_freq
        self.log_file_identifier = int(log_file_identifier)

        _m = _get_config()["missions"][fire_layout]
        self.wind_direction = _m["wind_direction"]
        self.required_altitude = _m["required_altitude_ft_msl"]
        self.required_drop_route_length = _m["required_drop_route_length"]
        self.latin_square_group = config
        self.trial_number = trial

        self.wingman_initiative_level = int(wingman_initiative_level)
        self.fire_layout = fire_layout

        # Create log directory if it doesn't exist
        try:
            os.makedirs(self.log_dir, exist_ok=True)
        except Exception as e:
            logger.warning(f"Could not create log directory {self.log_dir}: {e}. Falling back to current directory.")
            self.log_dir = "."

        # Generate output filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.out_file_name = os.path.join(self.log_dir, f"timeseries_p{user_id}_initiative{wingman_initiative_level}_layout{self.fire_layout}_{timestamp}_id{log_file_identifier}.csv")

        logger.info(f"DataLogger initialized for user {user_id}. Log: {self.out_file_name}")

        # Define CSV headers
        self.headers = [
            "timestamp",
            "step_number",
            "elapsed_seconds",
            # Wingman state
            "wingman_lat",
            "wingman_long",
            "wingman_alt",
            "wingman_hdg",
            "wingman_spd",
            "wingman_action",
            "wingman_status",
            # Human state
            "human_lat",
            "human_long",
            "human_alt",
            "human_hdg",
            "human_spd",
            "human_phi",
            "human_pitch_ang",
            "human_yaw_ang",
            "human_roll_ang",
            "human_roll_rate",
            "human_pitch_rate",
            # Commands
            "command_from_human"
        ]

        # Add verbose wingman mode columns if needed
        if self.verbose:
            self.headers.extend([
                "wingman_auto_spot",
            ])

        # Add target status columns (dynamic based on number of targets)
        self.num_targets = len(self.mm.targets) if hasattr(self.mm, 'targets') else 0
        for i in range(self.num_targets):
            self.headers.extend([
                f'target{i}status',
                f'target{i}classification'
            ])

        # Write metadata to file
        self.write_metadata()


    def write_metadata(self):
        """ Write metadata to a separate text file"""

        try:
            with open(self.out_file_name, 'w', newline='') as f:
                f.write(f"Participant ID: {self.user_id}\n")
                f.write(f"Latin square group: {self.latin_square_group}\n")
                f.write(f"trial: {self.trial_number}\n")
                f.write(f"initiative_level: {self.wingman_initiative_level}\n")
                f.write(f"fire_layout: {self.fire_layout}\n")
                f.write(f"Required altitude during cruise: {self.required_altitude}\n")
                f.write(f"Required altitude when marking position/route: 500ft AGL\n")
                f.write(f"Required drop route length: {self.required_drop_route_length}\n")
                f.write(f"Wind direction: {self.wind_direction}\n")
                f.write(f"Mission start time: {self.start_time.isoformat()}\n")
                f.write(f"Log frequency (hz): {self.log_freq}\n")
                f.write(f"Notes: {self.notes}\n")

                # Wingman information
                if hasattr(self.mm, 'wingman'):
                    f.write(f"wingman type: {getattr(self.mm.wingman, 'type', 'N/A')}\n")
                    f.write(f"wingman max speed: {getattr(self.mm.wingman, 'max_speed', 'N/A')}\n")
                    f.write(f"wingman default speed: {getattr(self.mm.wingman, 'default_spd', 'N/A')}\n")

                # Target information
                f.write(f"num targets: {len(self.mm.targets)}\n")
                for i, target in enumerate(self.mm.targets):
                    f.write(f"  target {i} lat, long, alt: ({target.lat}, {target.long}, {target.alt})\n")
                    f.write(f"  target {i} type: {target.type}\n")
                    f.write(f"\n")

                writer = csv.writer(f)
                writer.writerow(self.headers)

        except Exception as e:
            logger.error(f"Error writing metadata: {e}")


    def log_step_data(self, step_number):
        """
        Log current step data as a single CSV row
        """
        #step_number = self._get_current_step_number()
        elapsed = (datetime.now() - self.start_time).total_seconds()

        # Build row data in the same order as headers
        row = [
            datetime.now().isoformat(),
            step_number,
            elapsed
        ]

        # Wingman state data
        if hasattr(self.mm, 'wingman'):
            row.extend([
                self.mm.wingman.lat,
                self.mm.wingman.long,
                self.mm.wingman.alt,
                self.mm.wingman.hdg,
                self.mm.wingman.spd,
                getattr(self.mm.wingman, 'last_action', ''),
                getattr(self.mm.wingman, 'status', '')
            ])
        else:
            row.extend([''] * 7)  # Empty values for wingman columns

        # Human state data
        try:
            row.extend([
                self.mm.human_lla[0] if isinstance(self.mm.human_lla, (list, tuple)) else self.mm.human_lla,
                self.mm.human_lla[1] if isinstance(self.mm.human_lla, (list, tuple)) else '',
                self.mm.human_lla[2] if isinstance(self.mm.human_lla, (list, tuple)) and len(self.mm.human_lla) > 2 else '',
                self.mm.human_hdg,
                self.mm.human_spd,
                self.mm.human_roll_ang,
                self.mm.human_pitch_ang,
                self.mm.human_yaw_ang,
                self.mm.human_roll_ang,
                self.mm.human_roll_rate,
                self.mm.human_pitch_rate,
            ])
        except (AttributeError, IndexError) as e:
            logger.warning(f"Error accessing human data: {e}")
            row.extend([''] * 11)

        # Latest human command
        command_from_human = self.xpc.getDREF("custom/haato/command_from_human")
        row.append(command_from_human)

        # Verbose wingman mode information
        if self.verbose and hasattr(self.mm, 'wingman'):
            row.extend([
                self.mm.wingman.auto_spot,
            ])

        # Target status updates
        for i in range(self.num_targets):
            if i < len(self.mm.targets):
                target = self.mm.targets[i]
                row.extend([
                    target.status,
                    target.classification
                ])
            else:
                row.extend([''] * 3)

        # Write row to CSV
        self._write_row(row)

    def _get_current_step_number(self):
        """Get the current step number by counting existing rows"""
        try:
            with open(self.out_file_name, 'r') as f:
                return sum(1 for _ in f)
        except Exception:
            return 1

    def _write_row(self, row):
        """Append a row to the CSV file"""
        try:
            with open(self.out_file_name, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(row)
        except Exception as e:
            logger.error(f"Error writing row to CSV: {e}")


    def close(self):
        """Close any open file handles"""
        if hasattr(self, 'file') and self.file:
            self.file.close()