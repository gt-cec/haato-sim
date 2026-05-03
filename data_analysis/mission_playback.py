"""
Mission Playback Visualization Tool

Loads mission logs and plays back the mission with a top-down view showing
targets, human aircraft, and wingman positions over time.
"""

import tkinter as tk
from tkinter import ttk, filedialog
import csv
import json
import re
import math
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
from pathlib import Path


@dataclass
class Target:
    """Represents a fire/target location"""
    id: int
    lat: float
    lon: float
    alt: float
    target_type: str  # 'moderate' or 'severe'


@dataclass
class MissionStep:
    """A single timestep of mission data"""
    elapsed_seconds: float
    step_number: int
    wingman_lat: float
    wingman_lon: float
    wingman_hdg: float
    human_lat: float
    human_lon: float
    human_hdg: float
    target_statuses: List[float]  # status for each target (0.0-4.0)
    target_classifications: List[float]


@dataclass
class TimelineEvent:
    """An event or message for the timeline"""
    elapsed_seconds: float
    event_type: str  # 'event' or 'message'
    text: str
    raw_data: dict


class MissionData:
    """Container for all loaded mission data"""
    def __init__(self):
        self.targets: List[Target] = []
        self.steps: List[MissionStep] = []
        self.events: List[TimelineEvent] = []
        self.wind_direction: float = 0.0
        self.mission_duration: float = 600.0

    def load_mission_log(self, filepath: str):
        """Load mission log CSV file"""
        self.targets = []
        self.steps = []

        with open(filepath, 'r') as f:
            lines = f.readlines()

        # Parse metadata header (first 32 lines)
        num_targets = 8
        for i, line in enumerate(lines[:32]):
            line = line.strip()

            # Parse num targets
            if line.startswith('num targets:'):
                num_targets = int(line.split(':')[1].strip())

            # Parse target info
            target_match = re.match(r'\s*target (\d+) lat, long, alt: \(([-\d.]+), ([-\d.]+), ([-\d.]+)\)', line)
            if target_match:
                target_id = int(target_match.group(1))
                lat = float(target_match.group(2))
                lon = float(target_match.group(3))
                alt = float(target_match.group(4))
                # Look for type on next non-empty line
                target_type = 'moderate'
                if i + 1 < len(lines):
                    type_line = lines[i + 1].strip()
                    type_match = re.match(r'\s*target \d+ type: (\w+)', type_line)
                    if type_match:
                        target_type = type_match.group(1)
                self.targets.append(Target(target_id, lat, lon, alt, target_type))

        # Parse CSV data (starting at line 33 for header, 34+ for data)
        header_line = 32  # 0-indexed, so line 33
        reader = csv.DictReader(lines[header_line:])

        for row in reader:
            try:
                # Parse target statuses
                target_statuses = []
                target_classifications = []
                for i in range(num_targets):
                    status_key = f'target{i}status'
                    class_key = f'target{i}classification'
                    target_statuses.append(float(row.get(status_key, 0.0)))
                    target_classifications.append(float(row.get(class_key, 0.0)))

                step = MissionStep(
                    elapsed_seconds=float(row['elapsed_seconds']),
                    step_number=int(row['step_number']),
                    wingman_lat=float(row['wingman_lat']),
                    wingman_lon=float(row['wingman_long']),
                    wingman_hdg=float(row['wingman_hdg']),
                    human_lat=float(row['human_lat']),
                    human_lon=float(row['human_long']),
                    human_hdg=float(row['human_hdg']),
                    target_statuses=target_statuses,
                    target_classifications=target_classifications
                )
                self.steps.append(step)
            except (ValueError, KeyError) as e:
                continue  # Skip malformed rows

        if self.steps:
            self.mission_duration = self.steps[-1].elapsed_seconds

    def load_experiment_log(self, filepath: str):
        """Load experiment log JSONL file"""
        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)

                    # Extract wind direction from metadata
                    if data.get('metadata') == 'start':
                        self.wind_direction = float(data.get('wind_setting', 0.0))
                        continue

                    # Process events
                    event_type = data.get('event_type', '')
                    met = data.get('met')
                    if met is not None and event_type:
                        # Convert MET (countdown) to elapsed seconds
                        elapsed = 600.0 - float(met)

                        # Format event text based on type
                        text = self._format_event_text(event_type, data)

                        self.events.append(TimelineEvent(
                            elapsed_seconds=elapsed,
                            event_type='event',
                            text=text,
                            raw_data=data
                        ))
                except json.JSONDecodeError:
                    continue

    def _format_event_text(self, event_type: str, data: dict) -> str:
        """Format event data into human-readable text"""
        if event_type == 'agent_send_plan':
            human_plan = data.get('plan_for_human', '?')
            agent_plan = data.get('plan_for_agent', '?')
            return f"Plan proposed: Human->Fire {int(human_plan)}, Wingman->Fire {int(agent_plan)}"

        elif event_type == 'human_plan_response':
            accept_h = data.get('accept_human', False)
            accept_a = data.get('accept_agent', False)
            status = "Accepted" if (accept_h and accept_a) else "Modified"
            return f"Plan {status}"

        elif event_type == 'classify':
            player = data.get('player', '?')
            fire_id = data.get('fire_id', '?')
            marked = data.get('classification_marked', '?')
            correct = data.get('correct', False)
            result = "correct" if correct else "incorrect"
            return f"{player.title()} classified Fire {fire_id} as {marked} ({result})"

        elif event_type == 'classify_agent':
            fire_id = data.get('fire_id', '?')
            classification = data.get('classification', '?')
            return f"Wingman classified Fire {fire_id} as {classification}"

        elif event_type == 'mark_position':
            player = data.get('player', '?')
            fire_id = data.get('fire_id', '?')
            return f"{player.title()} marked position for Fire {fire_id}"

        elif event_type == 'route_start':
            player = data.get('player', '?')
            fire_id = data.get('fire_id', '?')
            return f"{player.title()} started route recording for Fire {fire_id}"

        elif event_type == 'route_end':
            player = data.get('player', '?')
            fire_id = data.get('fire_id', '?')
            return f"{player.title()} completed route for Fire {fire_id}"

        else:
            return f"{event_type}: {str(data)[:50]}"

    def load_messages(self, filepath: str):
        """Load mission messages CSV file, filtering duplicates"""
        last_status_value = None

        with open(filepath, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    mission_time = float(row['mission_time'])
                    msg_type = row['type']
                    sender = row['sender']
                    payload_str = row['payload_json']

                    try:
                        payload = json.loads(payload_str)
                    except json.JSONDecodeError:
                        payload = {}

                    # Filter consecutive duplicate status messages
                    if msg_type == 'status':
                        status_value = payload.get('status_value')
                        if status_value == last_status_value:
                            continue  # Skip duplicate
                        last_status_value = status_value
                        text = f"Wingman status: {self._decode_wingman_status(status_value)}"
                    elif msg_type == 'response':
                        resp_type = payload.get('response_type', '?')
                        resp_value = payload.get('response_value', '?')
                        text = f"Human response: {resp_type} = {resp_value}"
                    elif msg_type == 'command':
                        text = f"Human command: {payload}"
                    elif msg_type == 'request':
                        text = f"Wingman request: {payload}"
                    else:
                        text = f"{msg_type}: {payload}"

                    self.events.append(TimelineEvent(
                        elapsed_seconds=mission_time,
                        event_type='message',
                        text=text,
                        raw_data=row
                    ))

                except (ValueError, KeyError):
                    continue

        # Sort all events by time
        self.events.sort(key=lambda e: e.elapsed_seconds)

    def _decode_wingman_status(self, status: float) -> str:
        """Decode wingman status value to human-readable text"""
        if status is None:
            return "Unknown"

        status = int(status)
        num_targets = 8

        if 0 <= status < num_targets:
            return f"Flying to Fire {status} to classify"
        elif num_targets <= status < 2 * num_targets:
            return f"Classifying Fire {status - num_targets}"
        elif 2 * num_targets <= status < 3 * num_targets:
            return f"Flying to Fire {status - 2*num_targets} to extinguish"
        elif 3 * num_targets <= status < 4 * num_targets:
            return f"Extinguishing Fire {status - 3*num_targets}"
        elif 4 * num_targets <= status < 5 * num_targets:
            return f"Requesting help for Fire {status - 4*num_targets}"
        elif 5 * num_targets <= status < 6 * num_targets:
            return f"Meeting human at Fire {status - 5*num_targets}"
        elif 6 * num_targets <= status < 7 * num_targets:
            return f"Flying to Fire {status - 6*num_targets}"
        elif status == 7 * num_targets:
            return "Following human"
        elif status == 7 * num_targets + 1:
            return "No valid fires, holding"
        elif status == 7 * num_targets + 2:
            return "Flying to waypoint"
        else:
            return f"Status {status}"


class MissionPlaybackApp:
    """Main application window for mission playback"""

    # Map bounds
    LAT_MIN = 47.674800
    LAT_MAX = 48.07
    LON_MIN = -121.508566
    LON_MAX = -120.887615

    # Canvas dimensions
    MAP_WIDTH = 700
    MAP_HEIGHT = 660
    TIMELINE_WIDTH = 350

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Mission Playback")
        self.root.geometry("1100x750")

        self.mission_data = MissionData()
        self.current_step_index = 0
        self.playing = False
        self.playback_speed = 1.0
        self.last_update_time = 0
        self._updating_slider = False  # Flag to prevent recursive slider updates

        self._setup_ui()
        self._bind_keys()

    def _setup_ui(self):
        """Create the main UI layout"""
        # Main container
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Left side: Map and controls
        left_frame = ttk.Frame(main_frame)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Map canvas
        self.map_canvas = tk.Canvas(
            left_frame,
            width=self.MAP_WIDTH,
            height=self.MAP_HEIGHT,
            bg='#f0f0f0',
            highlightthickness=1,
            highlightbackground='black'
        )
        self.map_canvas.pack(padx=5, pady=5)

        # Controls frame
        controls_frame = ttk.Frame(left_frame)
        controls_frame.pack(fill=tk.X, padx=5, pady=5)

        # Playback buttons
        btn_frame = ttk.Frame(controls_frame)
        btn_frame.pack(side=tk.TOP, pady=5)

        self.btn_step_back = ttk.Button(btn_frame, text="<<", width=4, command=self._step_back_10)
        self.btn_step_back.pack(side=tk.LEFT, padx=2)

        self.btn_prev = ttk.Button(btn_frame, text="<", width=3, command=self._step_back)
        self.btn_prev.pack(side=tk.LEFT, padx=2)

        self.btn_play = ttk.Button(btn_frame, text="Play", width=6, command=self._toggle_play)
        self.btn_play.pack(side=tk.LEFT, padx=2)

        self.btn_next = ttk.Button(btn_frame, text=">", width=3, command=self._step_forward)
        self.btn_next.pack(side=tk.LEFT, padx=2)

        self.btn_step_fwd = ttk.Button(btn_frame, text=">>", width=4, command=self._step_forward_10)
        self.btn_step_fwd.pack(side=tk.LEFT, padx=2)

        # Speed controls
        speed_frame = ttk.Frame(controls_frame)
        speed_frame.pack(side=tk.TOP, pady=5)

        ttk.Label(speed_frame, text="Speed:").pack(side=tk.LEFT, padx=5)

        speeds = [0.5, 1, 2, 4, 8]
        self.speed_var = tk.DoubleVar(value=1.0)
        for speed in speeds:
            rb = ttk.Radiobutton(
                speed_frame,
                text=f"{speed}x",
                value=speed,
                variable=self.speed_var,
                command=self._update_speed
            )
            rb.pack(side=tk.LEFT, padx=3)

        # Time display
        time_frame = ttk.Frame(controls_frame)
        time_frame.pack(side=tk.TOP, pady=5)

        self.time_label = ttk.Label(time_frame, text="Time: 00:00 / 10:00", font=('Consolas', 11))
        self.time_label.pack(side=tk.LEFT, padx=10)

        # Time slider
        self.time_slider = ttk.Scale(
            controls_frame,
            from_=0,
            to=100,
            orient=tk.HORIZONTAL,
            command=self._on_slider_change
        )
        self.time_slider.pack(fill=tk.X, padx=10, pady=5)

        # Load button
        load_frame = ttk.Frame(controls_frame)
        load_frame.pack(side=tk.TOP, pady=5)

        self.btn_load = ttk.Button(load_frame, text="Load Mission...", command=self._load_mission)
        self.btn_load.pack(side=tk.LEFT, padx=5)

        # Right side: Timeline
        right_frame = ttk.Frame(main_frame, width=self.TIMELINE_WIDTH)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, padx=5, pady=5)
        right_frame.pack_propagate(False)

        ttk.Label(right_frame, text="Event Timeline", font=('Arial', 11, 'bold')).pack(pady=5)

        # Timeline listbox with scrollbar
        timeline_container = ttk.Frame(right_frame)
        timeline_container.pack(fill=tk.BOTH, expand=True)

        self.timeline_scrollbar = ttk.Scrollbar(timeline_container)
        self.timeline_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.timeline_text = tk.Text(
            timeline_container,
            width=40,
            wrap=tk.WORD,
            yscrollcommand=self.timeline_scrollbar.set,
            font=('Consolas', 9),
            state=tk.DISABLED
        )
        self.timeline_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.timeline_scrollbar.config(command=self.timeline_text.yview)

        # Configure text tags for coloring
        self.timeline_text.tag_configure('past', foreground='gray')
        self.timeline_text.tag_configure('current', foreground='blue')
        self.timeline_text.tag_configure('future', foreground='black')
        self.timeline_text.tag_configure('time', foreground='#666666', font=('Consolas', 8))

        # Legend
        legend_frame = ttk.LabelFrame(left_frame, text="Legend")
        legend_frame.pack(fill=tk.X, padx=5, pady=5)

        legend_items = [
            ("Gray Square", "Unclassified (0.0)", "#808080"),
            ("Red Circle", "Classified (1.0)", "#FF0000"),
            ("Red+Black", "Position Marked (2.0)", "#FF0000"),
            ("Cyan+Lines", "Initial Route (3.0)", "#00FFFF"),
            ("Blue+Lines", "Refined Route (4.0)", "#0000FF"),
        ]

        legend_canvas = tk.Canvas(legend_frame, height=30, bg='white')
        legend_canvas.pack(fill=tk.X, padx=5, pady=5)

        x = 10
        for name, desc, color in legend_items:
            legend_canvas.create_text(x, 15, text=f"{name}: {desc}", anchor='w', font=('Arial', 8))
            x += 130

    def _bind_keys(self):
        """Bind keyboard shortcuts"""
        self.root.bind('<space>', lambda e: self._toggle_play())
        self.root.bind('<Left>', lambda e: self._step_back())
        self.root.bind('<Right>', lambda e: self._step_forward())
        self.root.bind('<Home>', lambda e: self._goto_start())
        self.root.bind('<End>', lambda e: self._goto_end())

    def _load_mission(self):
        """Open file dialog and load mission data"""
        filepath = filedialog.askopenfilename(
            title="Select Mission Log",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialdir="./analysis_test"
        )

        if not filepath:
            return

        # Determine base path to find related files
        path = Path(filepath)
        directory = path.parent

        # Load mission log
        self.mission_data = MissionData()
        self.mission_data.load_mission_log(filepath)

        # Try to find and load experiment log (look for experiment_log*.jsonl)
        for f in directory.glob("events*.jsonl"):
            self.mission_data.load_experiment_log(str(f))
            break

        # Try to find and load messages file
        for f in directory.glob("messages*.csv"):
            self.mission_data.load_messages(str(f))
            break

        # Reset playback
        self.current_step_index = 0
        self.playing = False
        self.btn_play.config(text="Play")

        # Update slider range
        if self.mission_data.steps:
            self.time_slider.config(to=len(self.mission_data.steps) - 1)

        # Initial render
        self._render_current_frame()
        self._update_timeline()

        self.root.title(f"Mission Playback - {path.name}")

    def _toggle_play(self):
        """Toggle play/pause state"""
        self.playing = not self.playing
        self.btn_play.config(text="Pause" if self.playing else "Play")

        if self.playing:
            self.last_update_time = 0
            self._playback_loop()

    def _playback_loop(self):
        """Main playback loop"""
        if not self.playing or not self.mission_data.steps:
            return

        # Advance to next step
        if self.current_step_index < len(self.mission_data.steps) - 1:
            self.current_step_index += 1
            self._render_current_frame()
            self._update_timeline()

            # Schedule next frame based on actual time difference and speed
            current_step = self.mission_data.steps[self.current_step_index]
            if self.current_step_index > 0:
                prev_step = self.mission_data.steps[self.current_step_index - 1]
                time_diff = current_step.elapsed_seconds - prev_step.elapsed_seconds
                delay_ms = max(10, int((time_diff / self.playback_speed) * 1000))
            else:
                delay_ms = 100

            self.root.after(delay_ms, self._playback_loop)
        else:
            # Reached end
            self.playing = False
            self.btn_play.config(text="Play")

    def _step_forward(self):
        """Step forward one frame"""
        if self.mission_data.steps and self.current_step_index < len(self.mission_data.steps) - 1:
            self.current_step_index += 1
            self._render_current_frame()
            self._update_timeline()

    def _step_back(self):
        """Step back one frame"""
        if self.mission_data.steps and self.current_step_index > 0:
            self.current_step_index -= 1
            self._render_current_frame()
            self._update_timeline()

    def _step_forward_10(self):
        """Step forward 10 frames"""
        if self.mission_data.steps:
            self.current_step_index = min(self.current_step_index + 10, len(self.mission_data.steps) - 1)
            self._render_current_frame()
            self._update_timeline()

    def _step_back_10(self):
        """Step back 10 frames"""
        if self.mission_data.steps:
            self.current_step_index = max(self.current_step_index - 10, 0)
            self._render_current_frame()
            self._update_timeline()

    def _goto_start(self):
        """Go to start of mission"""
        self.current_step_index = 0
        self._render_current_frame()
        self._update_timeline()

    def _goto_end(self):
        """Go to end of mission"""
        if self.mission_data.steps:
            self.current_step_index = len(self.mission_data.steps) - 1
            self._render_current_frame()
            self._update_timeline()

    def _update_speed(self):
        """Update playback speed from radio buttons"""
        self.playback_speed = self.speed_var.get()

    def _on_slider_change(self, value):
        """Handle time slider changes"""
        if self._updating_slider:
            return  # Prevent recursive calls
        if self.mission_data.steps:
            self.current_step_index = int(float(value))
            self._render_current_frame()
            self._update_timeline()

    def _lat_lon_to_canvas(self, lat: float, lon: float) -> Tuple[int, int]:
        """Convert lat/lon to canvas coordinates"""
        lat_rel = (lat - self.LAT_MIN) / (self.LAT_MAX - self.LAT_MIN)
        lon_rel = (lon - self.LON_MIN) / (self.LON_MAX - self.LON_MIN)
        x = int(lon_rel * self.MAP_WIDTH)
        y = int((1 - lat_rel) * self.MAP_HEIGHT)
        return x, y

    def _render_current_frame(self):
        """Render the current frame to the map canvas"""
        self.map_canvas.delete("all")

        if not self.mission_data.steps:
            self.map_canvas.create_text(
                self.MAP_WIDTH // 2, self.MAP_HEIGHT // 2,
                text="No mission loaded\nClick 'Load Mission...' to begin",
                font=('Arial', 14),
                justify=tk.CENTER
            )
            return

        step = self.mission_data.steps[self.current_step_index]

        # Draw grid lines
        self._draw_grid()

        # Draw targets
        self._draw_targets(step)

        # Draw aircraft trails (last 50 steps)
        self._draw_trails()

        # Draw aircraft
        self._draw_aircraft(step.human_lat, step.human_lon, step.human_hdg, "green", "Human")
        self._draw_aircraft(step.wingman_lat, step.wingman_lon, step.wingman_hdg, "purple", "Wingman")

        # Update time display
        elapsed = step.elapsed_seconds
        total = self.mission_data.mission_duration
        elapsed_str = f"{int(elapsed // 60):02d}:{int(elapsed % 60):02d}"
        total_str = f"{int(total // 60):02d}:{int(total % 60):02d}"
        self.time_label.config(text=f"Time: {elapsed_str} / {total_str}")

        # Update slider (with flag to prevent recursive callback)
        self._updating_slider = True
        self.time_slider.set(self.current_step_index)
        self._updating_slider = False

    def _draw_grid(self):
        """Draw background grid"""
        # Draw light grid lines
        for i in range(11):
            # Vertical lines
            x = int(i * self.MAP_WIDTH / 10)
            self.map_canvas.create_line(x, 0, x, self.MAP_HEIGHT, fill='#e0e0e0', width=1)
            # Horizontal lines
            y = int(i * self.MAP_HEIGHT / 10)
            self.map_canvas.create_line(0, y, self.MAP_WIDTH, y, fill='#e0e0e0', width=1)

    def _draw_targets(self, step: MissionStep):
        """Draw all targets based on their current status"""
        wind_angle = self.mission_data.wind_direction

        for i, target in enumerate(self.mission_data.targets):
            x, y = self._lat_lon_to_canvas(target.lat, target.lon)
            status = step.target_statuses[i] if i < len(step.target_statuses) else 0.0

            if status == 0.0:
                # Gray square for unclassified
                size = 8
                self.map_canvas.create_rectangle(
                    x - size, y - size, x + size, y + size,
                    fill='gray', outline='black', width=1
                )

            elif status == 1.0:
                # Red circle for classified
                size = 10
                self.map_canvas.create_oval(
                    x - size, y - size, x + size, y + size,
                    fill='red', outline='darkred', width=2
                )

            elif status == 2.0:
                # Red circle with concentric black circle for position marked
                size = 10
                self.map_canvas.create_oval(
                    x - size, y - size, x + size, y + size,
                    fill='red', outline='darkred', width=2
                )
                inner_size = 4
                self.map_canvas.create_oval(
                    x - inner_size, y - inner_size, x + inner_size, y + inner_size,
                    fill='black', outline='black'
                )

            elif status == 3.0:
                # Cyan circle with wind direction lines for initial route
                size = 10
                self.map_canvas.create_oval(
                    x - size, y - size, x + size, y + size,
                    fill='cyan', outline='darkcyan', width=2
                )
                self._draw_wind_lines(x, y, wind_angle, 'cyan', 'darkcyan')

            elif status == 4.0:
                # Blue circle with wind direction lines for refined route
                size = 10
                self.map_canvas.create_oval(
                    x - size, y - size, x + size, y + size,
                    fill='blue', outline='darkblue', width=2
                )
                self._draw_wind_lines(x, y, wind_angle, 'blue', 'darkblue')

            # Draw target label
            self.map_canvas.create_text(
                x, y - 18,
                text=f"F{target.id}",
                font=('Arial', 8, 'bold'),
                fill='black'
            )

    def _draw_wind_lines(self, x: int, y: int, wind_angle: float, fill_color: str, outline_color: str):
        """Draw two lines extending from center at wind angle"""
        line_length = 25
        # Convert wind angle to radians (0 = North, clockwise)
        # Canvas: 0 degrees points right, counter-clockwise
        # So we need to convert: canvas_angle = 90 - wind_angle
        rad = math.radians(wind_angle - 90)  # Adjust for canvas coordinates

        # Line in wind direction
        x1 = x + line_length * math.cos(rad)
        y1 = y + line_length * math.sin(rad)
        self.map_canvas.create_line(x, y, x1, y1, fill=outline_color, width=2)

        # Line opposite to wind direction
        x2 = x - line_length * math.cos(rad)
        y2 = y - line_length * math.sin(rad)
        self.map_canvas.create_line(x, y, x2, y2, fill=outline_color, width=2)

    def _draw_trails(self):
        """Draw aircraft trails for recent history"""
        trail_length = 500
        start_idx = max(0, self.current_step_index - trail_length)

        # Human trail
        human_points = []
        for i in range(start_idx, self.current_step_index + 1):
            step = self.mission_data.steps[i]
            x, y = self._lat_lon_to_canvas(step.human_lat, step.human_lon)
            human_points.extend([x, y])

        if len(human_points) >= 4:
            self.map_canvas.create_line(*human_points, fill='lightgreen', width=2, smooth=True)

        # Wingman trail
        wingman_points = []
        for i in range(start_idx, self.current_step_index + 1):
            step = self.mission_data.steps[i]
            x, y = self._lat_lon_to_canvas(step.wingman_lat, step.wingman_lon)
            wingman_points.extend([x, y])

        if len(wingman_points) >= 4:
            self.map_canvas.create_line(*wingman_points, fill='plum', width=2, smooth=True)

    def _draw_aircraft(self, lat: float, lon: float, heading: float, color: str, label: str):
        """Draw an aircraft icon at the given position"""
        x, y = self._lat_lon_to_canvas(lat, lon)
        size = 8

        # Draw aircraft body (circle)
        self.map_canvas.create_oval(
            x - size, y - size, x + size, y + size,
            fill=color, outline='black', width=2
        )

        # Draw heading indicator (line pointing in direction of travel)
        rad = math.radians(heading - 90)  # Adjust for canvas coordinates
        arrow_length = 15
        x2 = x + arrow_length * math.cos(rad)
        y2 = y + arrow_length * math.sin(rad)
        self.map_canvas.create_line(x, y, x2, y2, fill='black', width=2, arrow=tk.LAST)

        # Draw label
        self.map_canvas.create_text(
            x, y + 20,
            text=label,
            font=('Arial', 9, 'bold'),
            fill=color
        )

    def _update_timeline(self):
        """Update the timeline panel with events colored by timing"""
        if not self.mission_data.steps:
            return

        current_time = self.mission_data.steps[self.current_step_index].elapsed_seconds

        self.timeline_text.config(state=tk.NORMAL)
        self.timeline_text.delete('1.0', tk.END)

        current_event_line = None
        line_num = 1

        for event in self.mission_data.events:
            time_diff = event.elapsed_seconds - current_time

            # Determine color tag
            if time_diff < -10:
                tag = 'past'
            elif time_diff > 10:
                tag = 'future'
            else:
                tag = 'current'
                if current_event_line is None:
                    current_event_line = line_num

            # Format time
            mins = int(event.elapsed_seconds // 60)
            secs = int(event.elapsed_seconds % 60)
            time_str = f"[{mins:02d}:{secs:02d}] "

            # Insert time with time tag, then event text with appropriate tag
            self.timeline_text.insert(tk.END, time_str, 'time')
            self.timeline_text.insert(tk.END, event.text + "\n", tag)
            line_num += 1

        self.timeline_text.config(state=tk.DISABLED)

        # Auto-scroll to show current events
        if current_event_line:
            self.timeline_text.see(f"{current_event_line}.0")


def main():
    root = tk.Tk()
    app = MissionPlaybackApp(root)

    # Auto-load if analysis_test folder exists with files
    analysis_path = Path("../analysis_test")
    if analysis_path.exists():
        mission_logs = list(analysis_path.glob("timeseries*.csv"))
        if mission_logs:
            # Load the first mission log found
            app.mission_data.load_mission_log(str(mission_logs[0]))

            # Load experiment log
            for f in analysis_path.glob("events*.jsonl"):
                app.mission_data.load_experiment_log(str(f))
                break

            # Load messages
            for f in analysis_path.glob("messages*.csv"):
                app.mission_data.load_messages(str(f))
                break

            # Update UI
            if app.mission_data.steps:
                app.time_slider.config(to=len(app.mission_data.steps) - 1)
            app._render_current_frame()
            app._update_timeline()
            app.root.title(f"Mission Playback - {mission_logs[0].name}")

    root.mainloop()


if __name__ == "__main__":
    main()
