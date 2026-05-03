"""
Wizard of Oz (WoZ) GUI for User Study Experimentation
Allows experimenters to manually control initial mission conditions and real-time target status
"""
import os
import time
import tkinter as tk
import traceback
from datetime import datetime
from tkinter import ttk, messagebox
import math
import queue
import json
import threading
from utility import crash_recovery
from utility.crash_recovery import save_crash_state

class WizardOfOzGUI:
    def __init__(self, xpc, mm, input_queue=None, output_queue=None, start_ready_event=None):
        """
        Initialize WoZ GUI for user study control

        Args:
            xpc: XPlaneConnectX instance
            mm: MissionManager (FireWatchMM) instance
            input_queue: Queue for receiving state updates from mission thread (optional)
            output_queue: Queue for sending commands to mission thread (optional)
            start_ready_event: Threading event to signal pre-mission config complete (optional)
        """
        self.xpc = xpc
        self.mm = mm
        self.input_queue = input_queue
        self.output_queue = output_queue
        self.start_ready_event = start_ready_event

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.crash_dir = './logs/crashed_mission_files/'
        self.wingman_debug_state_json_path = f'./logs/wingman_debug_states/wingman_debug_state_{timestamp}.json'


        # State cache for change detection
        self._cached_state = None
        self._last_drawn_state = {}

        self._dref_cache = {}  # {dref_path: {'value': value, 'timestamp': time}}
        self._dref_cache_ttl = 1.0  # Cache time-to-live in seconds

        self.verbose = False

        # Create main window FIRST (before any tk variables)
        self.root = tk.Tk()
        self.root.title("WoZ Experimenter Control")
        self.root.geometry("750x850+50+50")
        self.root.configure(bg='#2c2c2c')

        # State management (after root window is created)
        self.pre_mission_complete = False
        self.mission_start_var = tk.IntVar(value=0)
        self.start_conditions = {}
        self.queued_target_changes = {}  # {target_id: {'status': value, 'whoflew': value}}

        # Button grid references for Section 2
        self.target_status_buttons = {}   # {target_id: {status_value: Button widget}}
        self.target_whoflew_buttons = {}  # {target_id: {whoflew_value: Button widget}}
        self.target_status_window_ids = {}   # {target_id: {status_value: canvas_window_id}}
        self.target_whoflew_window_ids = {}  # {target_id: {whoflew_value: canvas_window_id}}
        self.buttons_created = False      # Track if buttons have been initialized
        self.last_target_count = 0        # Track number of targets to detect changes

        self.refresh_ms = 100

        # Selected team plan
        self.selected_human_plan = None
        self.selected_wingman_plan = None

        # Map interaction state
        self.selected_human_pos = None
        self.selected_wingman_pos = None

        # Last sent commands
        self.last_command_from_human = 12.0
        self.last_wingman_status = 0.0

        # AOR parameters
        self.aor_center = (47.836467, -121.108091)
        self.aor_size = 17  # NM per side

        # Calculate AOR bounds
        lat_deg_per_nm = 1.0 / 60.0
        lon_deg_per_nm = 1.0 / (60.0 * math.cos(math.radians(self.aor_center[0])))

        half_size = self.aor_size / 2.0
        self.aor_lat_min = self.aor_center[0] - (half_size * lat_deg_per_nm)
        self.aor_lat_max = self.aor_center[0] + (half_size * lat_deg_per_nm)
        self.aor_lon_min = self.aor_center[1] - (half_size * lon_deg_per_nm)
        self.aor_lon_max = self.aor_center[1] + (half_size * lon_deg_per_nm)

        # Configure grid weights for layout (Section 1 will be separate window)
        self.root.grid_rowconfigure(0, weight=1)  # Section 2 top / Section 3
        self.root.grid_rowconfigure(1, weight=1)  # Section 2 bottom / Section 4
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_columnconfigure(1, weight=1)

        # Add window close handler
        self.root.protocol("WM_DELETE_WINDOW", self._on_main_window_close)

        # Create Sections 2-4 only (Section 1 will be created as separate window)
        self._create_main_window_sections()

    def _create_main_window_sections(self):
        """Create sections 2-4 in main window (Section 1 will be separate)"""
        # Section 2: Target status control (left side, spans rows 0-1)
        self.section2_frame = tk.LabelFrame(self.root, text="Target Status Control",
                                           bg='#d97230', fg='white',
                                           font=('Arial', 12, 'bold'))
        self.section2_frame.grid(row=0, column=0, rowspan=2, sticky='nsew', padx=2, pady=2)
        self._create_section2(self.section2_frame)

        # Section 3: Team plan control (top right, row 0)
        self.section3_frame = tk.LabelFrame(self.root, text="Team Plan Recommendations",
                                           bg='#2e7d32', fg='white',
                                           font=('Arial', 12, 'bold'))
        self.section3_frame.grid(row=0, column=1, sticky='nsew', padx=2, pady=2)
        self._create_section3(self.section3_frame)

        # Section 4: Manual command control (bottom right, row 1)
        self.section4_frame = tk.LabelFrame(self.root, text="Manual Commands",
                                           bg='#5e35b1', fg='white',
                                           font=('Arial', 12, 'bold'))
        self.section4_frame.grid(row=1, column=1, sticky='nsew', padx=2, pady=2)
        self._create_section4(self.section4_frame)

    def _create_section1_window(self):
        """Create Section 1 as a separate Toplevel window"""
        # Create Toplevel window
        self.section1_window = tk.Toplevel(self.root)
        self.section1_window.title("Pre-Mission Configuration")
        self.section1_window.geometry("900x900")
        self.section1_window.configure(bg='#4a6fa5')

        # Make modal (blocks main window interaction)
        self.section1_window.transient(self.root)
        self.section1_window.grab_set()

        # Prevent closing via X button
        self.section1_window.protocol("WM_DELETE_WINDOW", self._on_section1_close_attempt)

        # Create Section 1 content
        self._create_section1(self.section1_window)

        # Load default values
        self._load_default_values()

        # Center window
        self.section1_window.update_idletasks()
        x = (self.section1_window.winfo_screenwidth() // 2) - 300
        y = (self.section1_window.winfo_screenheight() // 2) - 250
        self.section1_window.geometry(f"900x700+{x}+{y}")

    # ========== SECTION 1: PRE-MISSION CONFIG ==========

    def _create_section1(self, parent):
        """Create pre-mission configuration section"""
        # Title
        title_label = tk.Label(parent, text="PRE-MISSION CONFIGURATION",
                              bg='#4a6fa5', fg='white',
                              font=('Arial', 14, 'bold'))
        title_label.pack(pady=5)

        # Main container
        container = tk.Frame(parent, bg='#4a6fa5')
        container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Left half: Map canvas
        left_frame = tk.Frame(container, bg='#4a6fa5')
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        tk.Label(left_frame, text="Click to Place Aircraft",
                bg='#4a6fa5', fg='white', font=('Arial', 10, 'bold')).pack()
        tk.Label(left_frame, text="Left-click: Human | Right-click: Wingman",
                bg='#4a6fa5', fg='white', font=('Arial', 8)).pack()

        self.section1_canvas = tk.Canvas(left_frame, width=440, height=440,
                                         bg='#e0e0e0', highlightthickness=2,
                                         highlightbackground='white')
        self.section1_canvas.pack(pady=5)
        self.section1_canvas.bind('<Button-1>', self._on_map_click_human)
        self.section1_canvas.bind('<Button-3>', self._on_map_click_wingman)

        # Right half: Manual entry
        right_frame = tk.Frame(container, bg='#4a6fa5')
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=10)

        # Human position entries
        tk.Label(right_frame, text="Human Position:", bg='#4a6fa5', fg='white',
                font=('Arial', 10, 'bold')).grid(row=0, column=0, columnspan=2, pady=5)

        self.human_entries = {}
        for i, field in enumerate(['Lat', 'Long', 'Alt (m)', 'Spd (kts)']):
            tk.Label(right_frame, text=f"{field}:", bg='#4a6fa5', fg='white').grid(row=i+1, column=0, sticky='e', padx=2)
            entry = tk.Entry(right_frame, width=15)
            entry.grid(row=i+1, column=1, padx=2, pady=2)
            self.human_entries[field.split()[0].lower()] = entry

        # Wingman position entries
        tk.Label(right_frame, text="Wingman Position:", bg='#4a6fa5', fg='white',
                font=('Arial', 10, 'bold')).grid(row=5, column=0, columnspan=2, pady=5)

        self.wingman_entries = {}
        for i, field in enumerate(['Lat', 'Long', 'Alt (m)', 'Spd (kts)']):
            tk.Label(right_frame, text=f"{field}:", bg='#4a6fa5', fg='white').grid(row=i+6, column=0, sticky='e', padx=2)
            entry = tk.Entry(right_frame, width=15)
            entry.grid(row=i+6, column=1, padx=2, pady=2)
            self.wingman_entries[field.split()[0].lower()] = entry

        # Mission time
        tk.Label(right_frame, text="Mission Time (s):", bg='#4a6fa5', fg='white',
                font=('Arial', 10, 'bold')).grid(row=10, column=0, sticky='e', padx=2)
        self.mission_time_entry = tk.Entry(right_frame, width=15)
        self.mission_time_entry.grid(row=10, column=1, padx=2, pady=2)
        self.mission_time_entry.insert(0, "1800")

        # Target configuration grid
        tk.Label(right_frame, text="Target Configuration:", bg='#4a6fa5', fg='white',
                font=('Arial', 10, 'bold')).grid(row=11, column=0, columnspan=2, pady=5)

        target_frame = tk.Frame(right_frame, bg='#4a6fa5')
        target_frame.grid(row=12, column=0, columnspan=2)

        # Headers
        tk.Label(target_frame, text="ID", bg='#4a6fa5', fg='white', width=5).grid(row=0, column=0)
        tk.Label(target_frame, text="Status", bg='#4a6fa5', fg='white', width=8).grid(row=0, column=1)
        tk.Label(target_frame, text="WhoFlew", bg='#4a6fa5', fg='white', width=8).grid(row=0, column=2)

        self.target_status_vars = {}
        self.target_whoflew_vars = {}
        self.target_classification_vars = {}

        for i in range(self.mm.num_targets):
            tk.Label(target_frame, text=str(i), bg='#4a6fa5', fg='white').grid(row=i+1, column=0)

            # Status dropdown
            status_var = tk.DoubleVar(value=0.0)
            status_menu = ttk.Combobox(target_frame, textvariable=status_var,
                                      values=[0.0, 1.0, 2.0, 3.0, 4.0],
                                      width=6, state='readonly')
            status_menu.grid(row=i+1, column=1, padx=2)
            self.target_status_vars[i] = status_var

            # WhoFlew dropdown
            whoflew_var = tk.DoubleVar(value=0.0)
            whoflew_menu = ttk.Combobox(target_frame, textvariable=whoflew_var,
                                       values=[0.0, 1.0, 2.0],
                                       width=6, state='readonly')
            whoflew_menu.grid(row=i+1, column=2, padx=2)
            self.target_whoflew_vars[i] = whoflew_var

            if float(status_var.get()) > 0.0:
                classification = 1.0 if self.mm.targets[i].type == 'moderate' else 2.0 if self.mm.targets[i].type == 'severe' else 0.0
            else:
                classification = 0.0
            self.target_classification_vars[i] = tk.DoubleVar(value=classification)


        # LOAD CRASHED STATE button
        load_crash_btn = tk.Button(right_frame, text="LOAD CRASHED STATE",
                                  bg='#ff9800', fg='white',
                                  font=('Arial', 12, 'bold'),
                                  height=2, command=self._load_crashed_state_clicked)
        load_crash_btn.grid(row=13, column=0, columnspan=2, pady=5, sticky='ew')

        # START MISSION button
        start_btn = tk.Button(right_frame, text="START MISSION",
                             bg='#4caf50', fg='white',
                             font=('Arial', 14, 'bold'),
                             height=2, command=self._start_mission_clicked)
        start_btn.grid(row=14, column=0, columnspan=2, pady=10, sticky='ew')

    def _load_default_values(self):
        """Load default values into Section 1 fields"""
        # Load human defaults
        human_spawn = self.mm.human_spawn_lla
        self.human_entries['lat'].insert(0, f"{human_spawn[0]:.6f}")
        self.human_entries['long'].insert(0, f"{human_spawn[1]:.6f}")
        self.human_entries['alt'].insert(0, f"{human_spawn[2]:.1f}")
        self.human_entries['spd'].insert(0, f"{self.mm.human_spawn_spd:.1f}")

        # Load wingman defaults
        wingman_spawn = self.mm.ai_spawn_lla
        self.wingman_entries['lat'].insert(0, f"{wingman_spawn[0]:.6f}")
        self.wingman_entries['long'].insert(0, f"{wingman_spawn[1]:.6f}")
        self.wingman_entries['alt'].insert(0, f"{wingman_spawn[2]:.1f}")
        self.wingman_entries['spd'].insert(0, f"{self.mm.ai_default_spd:.1f}")

        # Draw initial map
        self._draw_section1_map()

    def _draw_section1_map(self):
        """Draw AOR and aircraft positions on Section 1 map"""
        self.section1_canvas.delete('all')

        # Draw AOR boundary
        margin = 20
        canvas_width = 440
        canvas_height = 440
        usable_width = canvas_width - 2 * margin
        usable_height = canvas_height - 2 * margin

        # AOR rectangle
        self.section1_canvas.create_rectangle(margin, margin,
                                              margin + usable_width,
                                              margin + usable_height,
                                              outline='black', width=2)

        # Draw grid lines
        for i in range(1, 4):
            x = margin + i * usable_width / 4
            self.section1_canvas.create_line(x, margin, x, margin + usable_height,
                                            fill='gray', dash=(2, 2))
            y = margin + i * usable_height / 4
            self.section1_canvas.create_line(margin, y, margin + usable_width, y,
                                            fill='gray', dash=(2, 2))

        # Draw fire/target positions
        for target in self.mm.targets:
            tx, ty = self._lat_lon_to_canvas_section1(target.lat, target.long)
            # Draw fire as small orange circle
            self.section1_canvas.create_oval(tx-6, ty-6, tx+6, ty+6,
                                            fill='#ff6600', outline='black', width=1)
            # Draw target ID
            self.section1_canvas.create_text(tx, ty, text=str(target.id),
                                            fill='white', font=('Arial', 8, 'bold'))

        # Draw aircraft if positions set
        try:
            human_lat = float(self.mm.human_lla[0])
            human_lon = float(self.mm.human_lla[1])
            hx, hy = self._lat_lon_to_canvas_section1(human_lat, human_lon)
            self.section1_canvas.create_oval(hx-8, hy-8, hx+8, hy+8,
                                            fill='blue', outline='white', width=2)
            self.section1_canvas.create_text(hx, hy-15, text='H', fill='white',
                                            font=('Arial', 10, 'bold'))
        except Exception:
            pass

        try:
            wingman_lat = float(self.mm.wingman.lat)
            wingman_lon = float(self.mm.wingman.long)
            wx, wy = self._lat_lon_to_canvas_section1(wingman_lat, wingman_lon)
            self.section1_canvas.create_oval(wx-8, wy-8, wx+8, wy+8,
                                            fill='cyan', outline='white', width=2)
            self.section1_canvas.create_text(wx, wy-15, text='W', fill='white',
                                            font=('Arial', 10, 'bold'))
        except Exception:
            pass

    def _on_map_click_human(self, event):
        """Handle left-click to place human"""
        lat, lon = self._canvas_to_lat_lon_section1(event.x, event.y)
        self.human_entries['lat'].delete(0, tk.END)
        self.human_entries['lat'].insert(0, f"{lat:.6f}")
        self.human_entries['long'].delete(0, tk.END)
        self.human_entries['long'].insert(0, f"{lon:.6f}")
        self._draw_section1_map()

    def _on_map_click_wingman(self, event):
        """Handle right-click to place wingman"""
        lat, lon = self._canvas_to_lat_lon_section1(event.x, event.y)
        self.wingman_entries['lat'].delete(0, tk.END)
        self.wingman_entries['lat'].insert(0, f"{lat:.6f}")
        self.wingman_entries['long'].delete(0, tk.END)
        self.wingman_entries['long'].insert(0, f"{lon:.6f}")
        self._draw_section1_map()

    def _start_mission_clicked(self):
        """Handle START MISSION button click"""
        # Validate inputs
        if not self._validate_coordinates():
            return

        # Build start_conditions dictionary
        try:
            self.start_conditions = {
                'human_lat': float(self.human_entries['lat'].get()),
                'human_long': float(self.human_entries['long'].get()),
                'human_alt': float(self.human_entries['alt'].get()),
                'human_spd': float(self.human_entries['spd'].get()),
                'wingman_lat': float(self.wingman_entries['lat'].get()),
                'wingman_long': float(self.wingman_entries['long'].get()),
                'wingman_alt': float(self.wingman_entries['alt'].get()),
                'wingman_spd': float(self.wingman_entries['spd'].get()),
                'mission_time_remaining': float(self.mission_time_entry.get()),
                'target_status': {i: self.target_status_vars[i].get() for i in range(self.mm.num_targets)},
                'target_classification': {i: self.target_classification_vars[i].get() for i in range(self.mm.num_targets)},
                'target_whoflew': {i: self.target_whoflew_vars[i].get()
                                  for i in range(self.mm.num_targets)}
            }
        except ValueError as e:
            messagebox.showerror("Input Error", f"Invalid numeric value: {e}")
            return

        # Destroy Section 1 window instead of hiding frame
        if hasattr(self, 'section1_window') and self.section1_window:
            self.section1_window.destroy()
            self.section1_window = None

        # Set completion flags
        self.pre_mission_complete = True
        self.mission_start_var.set(1)  # Unblock run_pre_mission_config()

        # Enable mission sections (remove overlay)
        self._enable_mission_sections()

        # Draw initial fire map
        self._draw_section2_map()

        # Signal threading event if provided
        if self.start_ready_event:
            self.start_ready_event.set()

        print("Pre-mission config complete, starting mission...")

    def _load_crashed_state_clicked(self):
        """Handle LOAD CRASHED STATE button click"""
        # Step 1: Find latest crash file

        crash_file = crash_recovery.find_latest_crash_file(self.crash_dir)

        if crash_file is None:
            messagebox.showerror(
                "No Crash Files Found",
                f"No crashed mission files found in {self.crash_dir}\n\n"
                "Start a mission first to generate crash recovery data."
            )
            return

        # Step 2: Load and validate crash state
        try:
            with open(crash_file, 'r') as f:
                crash_state = json.load(f)

            if not crash_recovery.validate_crash_state(crash_state):
                raise ValueError("Crash state validation failed")

        except Exception as e:
            messagebox.showerror(
                "Load Failed",
                f"Failed to load crash file:\n{crash_file}\n\nError: {str(e)}"
            )
            return

        # Step 3: Extract data from crash state
        # Extract human position
        human_pos = crash_state.get('human', {})
        human_lat = human_pos.get('sim/flightmodel/position/latitude', 0.0)
        human_lon = human_pos.get('sim/flightmodel/position/longitude', 0.0)
        human_alt_m = human_pos.get('sim/flightmodel/position/elevation', 0.0)

        # Extract wingman position
        wingman_data = crash_state.get('wingman', {})
        wingman_lat = wingman_data.get('lat', 0.0)
        wingman_lon = wingman_data.get('long', 0.0)
        wingman_alt_m = wingman_data.get('alt', 0.0)
        wingman_spd = wingman_data.get('spd', 0.0)

        # Extract mission time (now stored in UDP state, fall back to old dref location for old crash files)
        mission_time = (
            crash_state.get('planning', {}).get('udp_state', {}).get('mission_time_left')
            or crash_state.get('mission_state', {}).get('custom/haato/mission_time_left', 1800.0)
        )

        # Extract target arrays
        target_arrays = crash_state.get('target_arrays', {})
        target_status_array = target_arrays.get('target_status', [0.0] * 8)
        target_classification_array = target_arrays.get('target_classification', [0.0] * 8)
        target_whoflew_array = target_arrays.get('target_whoflew_initial', [0.0] * 8)

        # Step 4: Clear existing values
        for entry in self.human_entries.values():
            entry.delete(0, tk.END)

        for entry in self.wingman_entries.values():
            entry.delete(0, tk.END)

        self.mission_time_entry.delete(0, tk.END)

        # Step 5: Populate GUI fields
        # Populate human position (note: no speed in crash state for human)
        self.human_entries['lat'].insert(0, f"{human_lat:.6f}")
        self.human_entries['long'].insert(0, f"{human_lon:.6f}")
        self.human_entries['alt'].insert(0, f"{human_alt_m:.1f}")
        self.human_entries['spd'].insert(0, f"{self.mm.human_spawn_spd:.1f}")  # Use default

        # Populate wingman position
        self.wingman_entries['lat'].insert(0, f"{wingman_lat:.6f}")
        self.wingman_entries['long'].insert(0, f"{wingman_lon:.6f}")
        self.wingman_entries['alt'].insert(0, f"{wingman_alt_m:.1f}")
        self.wingman_entries['spd'].insert(0, f"{wingman_spd:.1f}")

        # Populate mission time
        self.mission_time_entry.insert(0, f"{mission_time:.0f}")

        # Populate target configuration
        for i in range(min(self.mm.num_targets, len(target_status_array))):
            self.target_status_vars[i].set(target_status_array[i])
            self.target_classification_vars[i].set(target_classification_array[i])
            self.target_whoflew_vars[i].set(target_whoflew_array[i])
            print(f'Target status: {target_status_array[i]}')

        # Step 6: Update map visualization
        self._draw_section1_map()

        # Step 7: Show success message
        metadata = crash_state.get('metadata', {})
        crash_time = metadata.get('timestamp', 'unknown')
        subject_id = metadata.get('subject_id', 'unknown')

        messagebox.showinfo(
            "Crashed State Loaded",
            f"Successfully loaded crashed mission state:\n\n"
            f"Subject ID: {subject_id}\n"
            f"Crash Time: {crash_time}\n"
            f"Mission Time Remaining: {mission_time:.0f}s\n\n"
            f"Review the values and click START MISSION to resume."
        )

    def _validate_coordinates(self) -> bool:
        """Validate all coordinate inputs"""
        errors = []

        try:
            human_lat = float(self.human_entries['lat'].get())
            if not (-90 <= human_lat <= 90):
                errors.append("Human latitude must be between -90 and 90")
        except ValueError:
            errors.append("Human latitude must be a number")

        try:
            human_lon = float(self.human_entries['long'].get())
            if not (-180 <= human_lon <= 180):
                errors.append("Human longitude must be between -180 and 180")
        except ValueError:
            errors.append("Human longitude must be a number")

        try:
            human_alt = float(self.human_entries['alt'].get())
            if not (0 <= human_alt <= 15000):
                errors.append("Human altitude must be between 0 and 15000m")
        except ValueError:
            errors.append("Human altitude must be a number")

        try:
            human_spd = float(self.human_entries['spd'].get())
            if not (0 <= human_spd <= 500):
                errors.append("Human speed must be between 0 and 500 knots")
        except ValueError:
            errors.append("Human speed must be a number")

        # Validate wingman (similar checks)
        try:
            wingman_lat = float(self.wingman_entries['lat'].get())
            if not (-90 <= wingman_lat <= 90):
                errors.append("Wingman latitude must be between -90 and 90")
        except ValueError:
            errors.append("Wingman latitude must be a number")

        try:
            wingman_lon = float(self.wingman_entries['long'].get())
            if not (-180 <= wingman_lon <= 180):
                errors.append("Wingman longitude must be between -180 and 180")
        except ValueError:
            errors.append("Wingman longitude must be a number")

        try:
            wingman_alt = float(self.wingman_entries['alt'].get())
            if not (0 <= wingman_alt <= 15000):
                errors.append("Wingman altitude must be between 0 and 15000m")
        except ValueError:
            errors.append("Wingman altitude must be a number")

        try:
            wingman_spd = float(self.wingman_entries['spd'].get())
            if not (0 <= wingman_spd <= 500):
                errors.append("Wingman speed must be between 0 and 500 knots")
        except ValueError:
            errors.append("Wingman speed must be a number")

        # Validate mission time
        try:
            mission_time = float(self.mission_time_entry.get())
            if not (0 <= mission_time <= 7200):
                errors.append("Mission time must be between 0 and 7200 seconds")
        except ValueError:
            errors.append("Mission time must be a number")

        if errors:
            messagebox.showerror("Validation Error", "\n".join(errors))
            return False

        return True

    # ========== SECTION 2: TARGET STATUS CONTROL ==========

    def _create_section2(self, parent):
        """Create target status control section"""
        # Map canvas
        self.section2_canvas = tk.Canvas(parent, width=440, height=440,
                                        bg='#e0e0e0', highlightthickness=2,
                                        highlightbackground='white')
        self.section2_canvas.pack(pady=5)

        # Status text
        self.queue_status_label = tk.Label(parent, text="No changes queued",
                                          bg='#d97230', fg='white',
                                          font=('Arial', 9))
        self.queue_status_label.pack(pady=2)

        # Buttons
        btn_frame = tk.Frame(parent, bg='#d97230')
        btn_frame.pack(pady=5)

        send_btn = tk.Button(btn_frame, text="SEND CHANGES",
                            bg='#c62828', fg='white',
                            font=('Arial', 11, 'bold'),
                            width=15, height=2,
                            command=self._send_queued_changes)
        send_btn.pack(side=tk.LEFT, padx=5)

        reset_btn = tk.Button(btn_frame, text="RESET QUEUE",
                             bg='#757575', fg='white',
                             font=('Arial', 9),
                             width=15, height=2,
                             command=self._reset_queue)
        reset_btn.pack(side=tk.LEFT, padx=5)

        save_state_btn = tk.Button(parent, text="SAVE STATE",
                                   bg='#c30010', fg='black',
                                   font=('Arial', 11, 'bold'),
                                   width=15, height=2,
                                   command=self.save_state)
        save_state_btn.pack(pady=20)

        # Add EMERGENCY KILL button
        kill_btn = tk.Button(parent, text="EMERGENCY KILL",
                             width=15, height=2,
                             bg='#c30010',  # Red to indicate danger
                             fg='white',
                             font=('Arial', 10, 'bold'),
                             command=self._emergency_kill)
        kill_btn.pack(pady=5)

        # Button to save state for debugging wingman
        save_debug_btn = tk.Button(parent, text="DEBUG STATE",
                                   width=15, height=2,
                                   bg='green',  # Red to indicate danger
                                   fg='white',
                                   font=('Arial', 10, 'bold'),
                                   command=self._save_wingman_state)
        save_debug_btn.pack(pady=5)

        verbose_btn = tk.Button(parent, text="Verbose",
                                width=15, height=2,
                                bg="#008000" if self.verbose else "#FF0000",  # Green if true, red if false
                                fg='black',
                                font=('Arial', 9, 'bold'),
                                command=self._toggle_verbose)
        verbose_btn.pack(pady=2)

    def _draw_section2_map(self):
        """Draw fire map with status indicators"""
        # Check if number of targets has changed
        current_target_count = len(self.mm.targets)
        target_count_changed = (current_target_count != self.last_target_count)

        # Only destroy and recreate buttons if target count changed
        if target_count_changed and self.buttons_created:
            # Destroy all button widgets BEFORE clearing canvas
            for target_buttons in self.target_status_buttons.values():
                for btn in target_buttons.values():
                    btn.destroy()
            for target_buttons in self.target_whoflew_buttons.values():
                for btn in target_buttons.values():
                    btn.destroy()

            # Clear button references
            self.target_status_buttons.clear()
            self.target_whoflew_buttons.clear()
            self.target_status_window_ids.clear()
            self.target_whoflew_window_ids.clear()
            self.buttons_created = False

        self.last_target_count = current_target_count

        # Delete only non-button canvas items (use tags to identify them)
        self.section2_canvas.delete('map_item')

        margin = 20
        canvas_width = 440
        canvas_height = 440
        usable_width = canvas_width - 2 * margin
        usable_height = canvas_height - 2 * margin

        # Draw AOR boundary (tagged so it can be deleted without affecting buttons)
        self.section2_canvas.create_rectangle(margin, margin,
                                              margin + usable_width,
                                              margin + usable_height,
                                              outline='black', width=2, tags='map_item')

        # Draw fires
        for i, target in enumerate(self.mm.targets):
            x, y = self._lat_lon_to_canvas_section2(target.lat, target.long)

            # Check if status change is queued
            if i in self.queued_target_changes and 'status' in self.queued_target_changes[i]:
                status = self.queued_target_changes[i]['status']
                is_queued = True
            else:
                status = self._safe_get_dref(f"custom/haato/target_status[{i}]", 0.0, f"target_status[{i}]")
                is_queued = False

            # Also check if whoflew is queued (for yellow ring)
            if i in self.queued_target_changes and 'whoflew' in self.queued_target_changes[i]:
                is_queued = True

            whoflew = self._safe_get_dref(f"custom/haato/target_whoflew_initial[{i}]", 0.0, f"whoflew[{i}]")

            self._draw_fire_status_circle(self.section2_canvas, x, y, status, whoflew, is_queued)

            # Draw target ID (tagged)
            self.section2_canvas.create_text(x, y, text=str(i),
                                            fill='white' if status < 4.0 else 'black',
                                            font=('Arial', 8, 'bold'), tags='map_item')

            # Create or reattach button grid for this target
            if not self.buttons_created:
                # First time: create buttons and canvas windows
                self._create_target_button_grid(i, x, y)
            else:
                # Subsequent times: reattach existing buttons to new canvas windows
                self._reattach_target_buttons(i, x, y)

        # Mark buttons as created after first pass
        if not self.buttons_created:
            self.buttons_created = True

        # Update all button highlights
        self._update_all_button_highlights()

    def _create_target_button_grid(self, target_id, x, y):
        """Create button grid for a single target at position (x, y)"""
        # Initialize storage for buttons and window IDs
        self.target_status_buttons[target_id] = {}
        self.target_whoflew_buttons[target_id] = {}
        self.target_status_window_ids[target_id] = {}
        self.target_whoflew_window_ids[target_id] = {}

        # Top row: status buttons 0-4
        status_values = [0.0, 1.0, 2.0, 3.0, 4.0]
        status_labels = ["0", "1", "2", "3", "4"]

        for i, (val, label) in enumerate(zip(status_values, status_labels)):
            btn_x = x - 49 + i * 20  # 18px button + 2px gap
            btn_y = y - 46

            btn = tk.Button(
                self.section2_canvas,
                text=label, font=('Arial', 6),
                bg='#cccccc', fg='black',
                width=2, height=1,
                command=lambda tid=target_id, v=val: self._on_status_button_click(tid, v)
            )

            window_id = self.section2_canvas.create_window(btn_x, btn_y, window=btn, anchor='nw')
            self.target_status_buttons[target_id][val] = btn  # Store button widget for styling
            self.target_status_window_ids[target_id][val] = window_id  # Store window ID for positioning

        # Bottom row: whoflew buttons -, H, W
        whoflew_values = [0.0, 1.0, 2.0]
        whoflew_labels = ["-", "H", "W"]

        for i, (val, label) in enumerate(zip(whoflew_values, whoflew_labels)):
            btn_x = x - 29 + i * 20
            btn_y = y - 28

            btn = tk.Button(
                self.section2_canvas,
                text=label, font=('Arial', 6),
                bg='#cccccc', fg='black',
                width=2, height=1,
                command=lambda tid=target_id, v=val: self._on_whoflew_button_click(tid, v)
            )

            window_id = self.section2_canvas.create_window(btn_x, btn_y, window=btn, anchor='nw')
            self.target_whoflew_buttons[target_id][val] = btn  # Store button widget for styling
            self.target_whoflew_window_ids[target_id][val] = window_id  # Store window ID for positioning

    def _reattach_target_buttons(self, target_id, x, y):
        """Reattach existing button widgets to new canvas windows at updated positions"""
        # Skip if buttons don't exist for this target
        if target_id not in self.target_status_buttons:
            return

        # Reattach status buttons by creating new canvas windows
        status_values = [0.0, 1.0, 2.0, 3.0, 4.0]
        for i, val in enumerate(status_values):
            if val in self.target_status_buttons[target_id]:
                btn_x = x - 49 + i * 20
                btn_y = y - 46
                btn = self.target_status_buttons[target_id][val]
                # Create new canvas window for the existing button widget
                window_id = self.section2_canvas.create_window(btn_x, btn_y, window=btn, anchor='nw')
                self.target_status_window_ids[target_id][val] = window_id

        # Reattach whoflew buttons by creating new canvas windows
        whoflew_values = [0.0, 1.0, 2.0]
        for i, val in enumerate(whoflew_values):
            if val in self.target_whoflew_buttons[target_id]:
                btn_x = x - 29 + i * 20
                btn_y = y - 28
                btn = self.target_whoflew_buttons[target_id][val]
                # Create new canvas window for the existing button widget
                window_id = self.section2_canvas.create_window(btn_x, btn_y, window=btn, anchor='nw')
                self.target_whoflew_window_ids[target_id][val] = window_id

    def _draw_fire_status_circle(self, canvas, x, y, status, whoflew, is_queued=False):
        """Draw fire circle based on status"""
        radius = 12

        # Draw outer yellow ring if queued
        if is_queued:
            canvas.create_oval(x-radius-3, y-radius-3, x+radius+3, y+radius+3,
                              outline='#ffeb3b', width=4, tags='map_item')

        if status == 0.0:
            # Red circle (unclassified)
            canvas.create_oval(x-radius, y-radius, x+radius, y+radius,
                              fill='#ff0000', outline='black', width=2, tags='map_item')

        elif status == 1.0:
            # Red circle with black filled center (classified)
            canvas.create_oval(x-radius, y-radius, x+radius, y+radius,
                              fill='#ff0000', outline='black', width=2, tags='map_item')
            canvas.create_oval(x-6, y-6, x+6, y+6,
                              fill='black', outline='black', tags='map_item')

        elif status == 2.0:
            # Orange circle with black line (position marked)
            canvas.create_oval(x-radius, y-radius, x+radius, y+radius,
                              fill='#ff6600', outline='black', width=2, tags='map_item')
            canvas.create_line(x-radius, y, x+radius, y,
                              fill='black', width=3, tags='map_item')

        elif status == 3.0:
            # Circle with line - color based on whoflew
            color = '#00ff00' if whoflew == 1.0 else '#00ffff'
            canvas.create_oval(x-radius, y-radius, x+radius, y+radius,
                              fill=color, outline='black', width=2, tags='map_item')
            canvas.create_line(x-radius, y, x+radius, y,
                              fill='black', width=3, tags='map_item')

        elif status == 4.0:
            # Gray circle with green checkmark (complete)
            canvas.create_oval(x-radius, y-radius, x+radius, y+radius,
                              fill='#888888', outline='black', width=2, tags='map_item')
            # Draw checkmark
            canvas.create_line(x-6, y, x-2, y+6,
                              fill='#00ff00', width=3, tags='map_item')
            canvas.create_line(x-2, y+6, x+8, y-6,
                              fill='#00ff00', width=3, tags='map_item')

    def _on_status_button_click(self, target_id, new_status):
        """Handle status button click - queues status change"""
        if target_id not in self.queued_target_changes:
            self.queued_target_changes[target_id] = {}

        self.queued_target_changes[target_id]['status'] = new_status
        self._update_queue_status_label()
        self._update_button_highlights(target_id)

    def _on_whoflew_button_click(self, target_id, new_whoflew):
        """Handle whoflew button click - queues whoflew change"""
        if target_id not in self.queued_target_changes:
            self.queued_target_changes[target_id] = {}

        self.queued_target_changes[target_id]['whoflew'] = new_whoflew
        self._update_queue_status_label()
        self._update_button_highlights(target_id)

    def _update_button_highlights(self, target_id):
        """Update button colors for a specific target"""
        # Get current status (queued or from dataref)
        if target_id in self.queued_target_changes and 'status' in self.queued_target_changes[target_id]:
            current_status = self.queued_target_changes[target_id]['status']
        else:
            current_status = self._safe_get_dref(f"custom/haato/target_status[{target_id}]", 0.0, "")

        # Get current whoflew (queued or from dataref)
        if target_id in self.queued_target_changes and 'whoflew' in self.queued_target_changes[target_id]:
            current_whoflew = self.queued_target_changes[target_id]['whoflew']
        else:
            current_whoflew = self._safe_get_dref(f"custom/haato/target_whoflew_initial[{target_id}]", 0.0, "")

        # Update status button colors
        if target_id in self.target_status_buttons:
            for status_val, btn in self.target_status_buttons[target_id].items():
                if status_val == current_status:
                    btn.config(bg='#4caf50')  # Green for selected
                else:
                    btn.config(bg='#cccccc')  # Gray for unselected

        # Update whoflew button colors
        if target_id in self.target_whoflew_buttons:
            for whoflew_val, btn in self.target_whoflew_buttons[target_id].items():
                if whoflew_val == current_whoflew:
                    btn.config(bg='#4caf50')  # Green for selected
                else:
                    btn.config(bg='#cccccc')  # Gray for unselected

    def _update_all_button_highlights(self):
        """Update button highlights for all targets"""
        for target_id in self.target_status_buttons.keys():
            self._update_button_highlights(target_id)

    def _update_queue_status_label(self):
        """Update the queue status label with change count"""
        total_changes = sum(len(changes) for changes in self.queued_target_changes.values())
        if total_changes == 0:
            self.queue_status_label.config(text="No changes queued")
        else:
            self.queue_status_label.config(text=f"{total_changes} change(s) queued")

    def _send_queued_changes(self):
        """Send all queued target status and whoflew changes"""
        if not self.queued_target_changes:
            messagebox.showinfo("No Changes", "No queued changes to send")
            return

        # Send all changes
        for target_id, changes in self.queued_target_changes.items():
            # Send status change if queued
            if 'status' in changes:
                new_status = changes['status']
                if self.output_queue:
                    try:
                        self.output_queue.put_nowait({
                            'type': 'target_status',
                            'target_id': target_id,
                            'status': new_status
                        })
                    except queue.Full:
                        print(f"Warning: Queue full, dropping target {target_id} status")
                else:
                    self._safe_send_dref(f"custom/haato/target_status[{target_id}]",
                                        new_status, f"target_status[{target_id}]")

            # Send whoflew change if queued
            if 'whoflew' in changes:
                new_whoflew = changes['whoflew']
                if self.output_queue:
                    try:
                        self.output_queue.put_nowait({
                            'type': 'target_whoflew',
                            'target_id': target_id,
                            'whoflew': new_whoflew
                        })
                    except queue.Full:
                        print(f"Warning: Queue full, dropping target {target_id} whoflew")
                else:
                    self._safe_send_dref(f"custom/haato/target_whoflew_initial[{target_id}]", new_whoflew, f"whoflew[{target_id}]")

        total_changes = sum(len(changes) for changes in self.queued_target_changes.values())
        print(f"Sent {total_changes} target changes")

        # Clear queue
        self.queued_target_changes.clear()
        self.queue_status_label.config(text="No changes queued")
        self._draw_section2_map()

        #messagebox.showinfo("Success", "Target changes sent successfully")

    def _reset_queue(self):
        """Clear all queued changes"""
        self.queued_target_changes.clear()
        self.queue_status_label.config(text="No changes queued")
        self._draw_section2_map()

    # ========== SECTION 3: TEAM PLAN CONTROL ==========

    def _create_section3(self, parent):
        """Create team plan control section"""
        # Human plan
        tk.Label(parent, text="Human Plan:", bg='#2e7d32', fg='white',
                font=('Arial', 10, 'bold')).pack(pady=2)

        human_frame = tk.Frame(parent, bg='#2e7d32')
        human_frame.pack(pady=2)

        self.human_plan_buttons = {}
        for i, val in enumerate([0, 1, 2, 3, 4, 5, 6, 7, 99]):
            row = i // 3
            col = i % 3
            btn = tk.Button(human_frame, text=str(val), width=5, height=1,
                           bg='#cccccc',
                           command=lambda v=val: self._select_human_plan(v))
            btn.grid(row=row, column=col, padx=2, pady=2)
            self.human_plan_buttons[val] = btn

        # Wingman plan
        tk.Label(parent, text="Wingman Plan:", bg='#2e7d32', fg='white',
                font=('Arial', 10, 'bold')).pack(pady=2)

        wingman_frame = tk.Frame(parent, bg='#2e7d32')
        wingman_frame.pack(pady=2)

        self.wingman_plan_buttons = {}
        for i, val in enumerate([0, 1, 2, 3, 4, 5, 6, 7, 99]):
            row = i // 3
            col = i % 3
            btn = tk.Button(wingman_frame, text=str(val), width=5, height=1,
                           bg='#cccccc',
                           command=lambda v=val: self._select_wingman_plan(v))
            btn.grid(row=row, column=col, padx=2, pady=2)
            self.wingman_plan_buttons[val] = btn

        # Current selection display
        self.plan_selection_label = tk.Label(parent, text="No plan selected",
                                            bg='#2e7d32', fg='white',
                                            font=('Arial', 9))
        self.plan_selection_label.pack(pady=5)

        # SEND button
        send_btn = tk.Button(parent, text="SEND TEAM PLAN",
                            bg='#66bb6a', fg='black',
                            font=('Arial', 11, 'bold'),
                            width=18, height=2,
                            command=self._send_team_plan)
        send_btn.pack(pady=3)

        request_plan_btn = tk.Button(parent, text="REQUEST PLAN",
                             bg='#66bb6a', fg='black',
                             font=('Arial', 11, 'bold'),
                             width=18, height=2,
                             command=self._request_plan)
        request_plan_btn.pack(pady=3)


    def save_state(self):
        print(f'Saved state to {self.crash_dir}')
        crash_file = save_crash_state(self.xpc, self.mm, self.crash_dir, {})
        print(f'CRASH STATE SAVED TO: {crash_file}')

    def _select_human_plan(self, value):
        """Select human plan value"""
        # Reset all button colors
        for btn in self.human_plan_buttons.values():
            btn.config(bg='#cccccc')

        # Highlight selected
        self.human_plan_buttons[value].config(bg='#4caf50')
        self.selected_human_plan = value
        self._update_plan_selection_label()

    def _select_wingman_plan(self, value):
        """Select wingman plan value"""
        # Reset all button colors
        for btn in self.wingman_plan_buttons.values():
            btn.config(bg='#cccccc')

        # Highlight selected
        self.wingman_plan_buttons[value].config(bg='#4caf50')
        self.selected_wingman_plan = value
        self._update_plan_selection_label()

    def _update_plan_selection_label(self):
        """Update plan selection display"""
        if self.selected_human_plan is not None and self.selected_wingman_plan is not None:
            self.plan_selection_label.config(
                text=f"H:{self.selected_human_plan} | W:{self.selected_wingman_plan}"
            )
        elif self.selected_human_plan is not None:
            self.plan_selection_label.config(text=f"H:{self.selected_human_plan} | W:?")
        elif self.selected_wingman_plan is not None:
            self.plan_selection_label.config(text=f"H:? | W:{self.selected_wingman_plan}")
        else:
            self.plan_selection_label.config(text="No plan selected")

    def _request_plan(self):
        self.mm.wingman.is_planning = False
        self.mm.wingman.force_send_plan = True
        self._safe_send_dref("custom/haato/human_requests_plan_suggestion", 1.0, "human_requests_plan_suggestion")
        print(f"\nWoz GUI: Requested team plan")

    def _send_team_plan(self):
        """Send team plan to system"""
        # if self.selected_human_plan is None:
        #     messagebox.showwarning("Incomplete", "Please select human plan first")
        #     return
        # if self.selected_wingman_plan is None:
        #     messagebox.showwarning("Incomplete", "Please select wingman plan first")
        #     return

        if self.output_queue:
            # Threaded mode: send via queue
            try:
                self.output_queue.put_nowait({
                    'type': 'team_plan',
                    'human_plan': float(self.selected_human_plan),
                    'wingman_plan': float(self.selected_wingman_plan)
                })
            except queue.Full:
                messagebox.showerror("Error", "Command queue full, try again")
                return
        else:
            # Direct mode: update mm directly and send datarefs
            self.mm.woz_team_plan = {
                'show_plan': 1.0,
                'human_plan': float(self.selected_human_plan),
                'wingman_plan': float(self.selected_wingman_plan),
                'second_best_human_plan': 99.0,
                'second_best_wingman_plan': 99.0,
                'best_followon_human': 99.0,
                'best_followon_wingman': 99.0,
                'second_best_followon_human': 99.0,
                'second_best_followon_wingman': 99.0,
                'rationale': None,
                'planning_mode': None
            }

            # Set wingman's internal plan
            self.mm.wingman.current_plan_for_self = float(self.selected_wingman_plan)
            if hasattr(self.mm, 'udp_bridge'):
                self.mm.current_team_plan = {
                    'show_plan': True,
                    'human_plan': float(self.selected_human_plan),
                    'wingman_plan': float(self.selected_wingman_plan),
                    'second_best_human_plan': 99.0,
                    'second_best_wingman_plan': 99.0,
                    'best_followon_human': 99.0,
                    'best_followon_wingman': 99.0,
                    'second_best_followon_human': 99.0,
                    'second_best_followon_wingman': 99.0,
                    'rationale_code': 99.0,
                    'planning_mode_code': 99.0,
                    'mission_time': float(getattr(self.mm, 'mission_timer', 0.0)),
                }
                self.mm.udp_bridge.send_team_plan_suggestion(self.mm.current_team_plan)

        print(f"\nWoz GUI: Team plan sent: H={self.selected_human_plan}, W={self.selected_wingman_plan}")
        #messagebox.showinfo("Success", "Team plan sent successfully")

    # ========== SECTION 4: MANUAL COMMAND CONTROL ==========

    def _create_section4(self, parent):
        """Create manual command control section"""
        # Create two-column layout
        left_frame = tk.Frame(parent, bg='#5e35b1')
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)

        right_frame = tk.Frame(parent, bg='#5e35b1')
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5)

        # Left column: command_from_human
        tk.Label(left_frame, text="Command From Human", bg='#5e35b1', fg='white',
                font=('Arial', 9, 'bold')).pack(pady=2)

        left_values = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 12.0]
        for val in left_values:
            label = f"T{int(val)}" if val < 8 else "NEUTRAL"
            btn = tk.Button(left_frame, text=label, width=12, height=1,
                           bg='#cccccc',
                           command=lambda v=val: self._send_command_from_human(v))
            btn.pack(pady=2)

        # Add spacing separator
        tk.Frame(left_frame, height=10, bg='#5e35b1').pack()

        # Add RESET WINGMAN button
        reset_btn = tk.Button(left_frame, text="RESET WINGMAN",
                              width=12, height=1,
                              bg='#ff9800',  # Orange to distinguish
                              fg='black',
                              font=('Arial', 9, 'bold'),
                              command=self._reset_wingman)
        reset_btn.pack(pady=2)





        # Right column: wingman_status
        tk.Label(right_frame, text="Wingman Status", bg='#5e35b1', fg='white',
                font=('Arial', 9, 'bold')).pack(pady=2)

        right_values = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 9.0]
        for val in right_values:
            btn = tk.Button(right_frame, text=f"S{int(val)}", width=12, height=1,
                           bg='#cccccc',
                           command=lambda v=val: self._send_wingman_status(v))
            btn.pack(pady=2)



    def _save_wingman_state(self):
        # Prepare the target list data
        targets_data = []
        for target in self.mm.targets:
            targets_data.append({
                "id": target.id,
                "status": target.status,
                "classification": target.classification,
                "route1_recorder": target.route1_recorder,
                "route2_recorder": target.route2_recorder,
                "initial_drop_route_complete": target.initial_drop_route_complete,
                "refined_drop_route_complete": target.refined_drop_route_complete
            })

        # Construct the debug state dictionary
        safe_last_action = self.mm.wingman.last_action.copy() if self.mm.wingman.last_action else {}
        if isinstance(safe_last_action, dict):
            safe_last_action.pop("outgoing_messages", None)

        if self.mm.latest_observation is not None:
            latest_obs = self.mm.latest_observation.tolist()
        else:
            latest_obs = None

        wingman_debug_state = {
            # Mission Manager / Target related
            "latest_observation": latest_obs,
            "targets": targets_data,

            # XPC Data Refs
            "xpc_target_status": self.xpc.getDREF("custom/haato/target_status"),
            "xpc_target_whoflew": self.xpc.getDREF("custom/haato/target_whoflew_initial"),
            "xpc_target_classification": self.xpc.getDREF("custom/haato/target_classification"),

            # General Wingman Attributes
            "status": self.mm.wingman.status,
            "last_status": self.mm.wingman.last_status,
            "action": self.mm.wingman.action,
            "last_action": safe_last_action,
            "current_target": self.mm.wingman.current_target,
            "request_response": self.mm.wingman.request_response,
            "requesting_help": self.mm.wingman.requesting_help,
            "latest_human_command": self.mm.wingman.latest_human_command,
            "auto_spot": self.mm.wingman.auto_spot,

            # Route marking state
            "current_route_target": self.mm.wingman.current_route_target,
            "route_marking_stage": self.mm.wingman.route_marking_stage,
            "route_type": self.mm.wingman.route_type,
            "route_start_time": self.mm.wingman.route_start_time,

            # Position marking state
            "marking_position_target": self.mm.wingman.marking_position_target,
            "position_marking_stage": self.mm.wingman.position_marking_stage,

            # Planning & Lookahead optimization
            "sent_first_plan": self.mm.wingman.sent_first_plan,
            "current_plan_for_self": self.mm.wingman.current_plan_for_self,
            "latest_human_plan_sent": self.mm.wingman.latest_human_plan_sent,
            "latest_plan": self.mm.wingman.latest_plan,
            "lookahead_count": self.mm.wingman.lookahead_count,
            "started_planning_step": self.mm.wingman.started_planning_step,
            "ended_planning_step": self.mm.wingman.ended_planning_step,
            "is_planning": self.mm.wingman.is_planning,
            "planning_queue_empty": self.mm.wingman.planning_queue.empty(),
            "cached_plans": self.mm.wingman.cached_plans,
            "lookahead_cache": self.mm.wingman._lookahead_cache,
            "cache_stats": self.mm.wingman._cache_stats
        }

        def convert_tuples_to_lists(obj):
            """Recursively convert all tuples to lists in a nested structure."""
            if isinstance(obj, tuple):
                return list(convert_tuples_to_lists(item) for item in obj)
            elif isinstance(obj, list):
                return [convert_tuples_to_lists(item) for item in obj]
            elif isinstance(obj, dict):
                return {key: convert_tuples_to_lists(value) for key, value in obj.items()}
            else:
                return obj

        wingman_debug_state = convert_tuples_to_lists(wingman_debug_state)
        self.check_serializable(wingman_debug_state)

        # Write to JSON file
        # TODO causes error. Need to create file
        try:
            with open(self.wingman_debug_state_json_path, "w") as f:
                json.dump(wingman_debug_state, f, indent=4)
                print(f'Dumped wingman debug state to {self.wingman_debug_state_json_path}')
        except Exception as e:
            print(f"Error saving wingman state: {e}")
            traceback.print_exc()


    def _toggle_verbose(self):
        self.mm.wingman.verbose = not self.mm.wingman.verbose
        self.mm.verbose = not self.mm.verbose
        self.verbose = self.mm.wingman.verbose
        if self.mm.wingman.verbose != self.mm.wingman.verbose:
            raise ValueError(f'Wingman and mm verbosity mismatch')
        print(f'\n[Woz GUI] Set verbose to {self.verbose}')


    def _send_command_from_human(self, value):
        """Send command_from_human dataref immediately"""
        if self.output_queue:
            # Threaded mode: send via queue
            try:
                self.output_queue.put_nowait({
                    'type': 'command_from_human',
                    'value': value
                })
            except queue.Full:
                print(f"Warning: Command queue full, dropping command_from_human = {value}")
        else:
            # Direct mode: send dataref immediately
            self._safe_send_dref("custom/haato/command_from_human", value, "command_from_human")

        self.last_command_from_human = value
        print(f"\nWoz GUI: Sent command_from_human = {value}")

    def _send_wingman_status(self, value):
        """Send wingman_status dataref immediately"""
        if self.output_queue:
            # Threaded mode: send via queue
            try:
                self.output_queue.put_nowait({
                    'type': 'wingman_status',
                    'value': value
                })
            except queue.Full:
                print(f"Warning: Command queue full, dropping wingman_status = {value}")
        else:
            if hasattr(self.mm, 'udp_bridge'):
                self.mm.udp_bridge.current_state["wingman"]["status"] = float(value)
                self.mm._send_shared_state("status_change")

        self.last_wingman_status = value
        print(f"\nWoz GUI: Sent wingman_status = {value}")

    def _reset_wingman(self):
        """Reset wingman agent to initial state"""
        try:
            self.mm.wingman.reset()
            self._safe_send_dref("custom/haato/command_from_human", 12.0)
            self._safe_send_dref("custom/haato/human_requests_plan_suggestion", 1.0)
            if hasattr(self.mm, 'udp_bridge'):
                self.mm.udp_bridge.current_state["wingman"]["status"] = 99.0
                self.mm.udp_bridge.current_state["wingman"]["recently_finished_task"] = -1.0
                self.mm.udp_bridge.current_state["human"]["indicated_plan"] = -1.0
                self.mm.udp_bridge.current_state["human"]["recently_finished_task"] = -1.0
                self.mm.current_team_plan = None
                self.mm._send_shared_state("reset")

            self.mm.cached_wingman_action = None
            self.mm.last_plan_send_time = -999.0
            self.mm.wingman.latest_plan = None
            self.mm.wingman.current_target = None

            self.mm.wingman.status = 99.0
            self.mm.wingman.last_status = 'none'
            self.mm.wingman.action = None
            self.mm.wingman.last_action = {'type': 'none', 'goal': (0.0, 0.0, 0.0), 'request': 'none'}
            self.mm.wingman.request_response = 0.0
            self.mm.wingman.requesting_help = False  # Whether agent is requesting help with its current target.
            self.mm.wingman.latest_human_command = None
            self.mm.wingman.sent_first_plan = False
            self.mm.wingman.current_plan_for_self = 99.0
            self.mm.wingman.latest_human_plan_sent = None

            # Route marking state
            self.mm.wingman.current_route_target = None
            self.mm.wingman.route_marking_stage = None  # 'flying_to_start', 'at_start', 'flying_route', 'at_end', 'complete'
            self.mm.wingman.route_type = None  # 'initial' or 'refined'
            self.mm.wingman.route_start_time = None
            self.mm.wingman.route_waypoint_tolerance = 0.5  # NM tolerance for being "at" a waypoint

            # Position marking state
            self.mm.wingman.marking_position_target = None
            self.mm.wingman.position_marking_stage = None  # 'flying_to_overfly', 'complete'
            self.mm.wingman.overfly_tolerance = 0.3  # NM tolerance for position marking

            print("\nWoZ GUI: Wingman reset successfully")
            #messagebox.showinfo("Success", "Wingman agent has been reset")
        except Exception as e:
            print(f"\nWoZ GUI: Error resetting wingman: {e}")
            #messagebox.showerror("Error", f"Failed to reset wingman: {e}")

    def _emergency_kill(self):
        """Emergency kill - immediately terminate the mission"""
        if self.output_queue:
            # Threaded mode: send via queue
            try:
                self.output_queue.put_nowait({
                    'type': 'emergency_kill',
                    'timestamp': self.mm.mission_timer
                })
                print("nWoZ GUI: EMERGENCY KILL command sent")
            except queue.Full:
                print("Warning: Command queue full, could not send emergency kill")
        else:
            # Direct mode: print warning (shouldn't happen in normal operation)
            print("\nWoZ GUI: EMERGENCY KILL pressed (direct mode - no action taken)")

    # ========== WINDOW MANAGEMENT METHODS ==========

    def check_serializable(self, d, path=""):
        for k, v in d.items():
            current_path = f"{path}/{k}"
            try:
                json.dumps(v)
            except TypeError:
                if isinstance(v, dict):
                    self.check_serializable(v, current_path)
                else:
                    print(f"FAILED: Key '{current_path}' is type {type(v)}")

    def _on_section1_close_attempt(self):
        """Handle X button click on Section 1 window"""
        messagebox.showwarning(
            "Action Required",
            "Please complete the pre-mission configuration and click 'START MISSION'.\n\n"
            "You cannot close this window without starting the mission."
        )

    def _on_main_window_close(self):
        """Handle main window close request"""
        if not self.pre_mission_complete:
            messagebox.showwarning(
                "Pre-Mission Config Active",
                "Please complete the pre-mission configuration window first."
            )
            return
        self.close()

    def _disable_mission_sections(self):
        """Overlay Sections 2-4 during pre-mission config"""
        self.overlay_frame = tk.Frame(self.root, bg='#000000')
        self.overlay_frame.place(x=0, y=0, relwidth=1, relheight=1)
        self.overlay_frame.lift()

        tk.Label(self.overlay_frame,
                 text="Complete Pre-Mission Configuration to Continue",
                 bg='#000000', fg='white',
                 font=('Arial', 16, 'bold')).place(relx=0.5, rely=0.5, anchor='center')

    def _enable_mission_sections(self):
        """Remove overlay to enable Sections 2-4"""
        if hasattr(self, 'overlay_frame') and self.overlay_frame:
            self.overlay_frame.destroy()
            self.overlay_frame = None

    # ========== UTILITY METHODS ==========

    def _lat_lon_to_canvas_section1(self, lat, lon):
        """Convert lat/lon to canvas coordinates for Section 1"""
        margin = 20
        usable_width = 440 - 2*margin
        usable_height = 440 - 2*margin

        x = margin + (lon - self.aor_lon_min) / (self.aor_lon_max - self.aor_lon_min) * usable_width
        y = margin + (1 - (lat - self.aor_lat_min) / (self.aor_lat_max - self.aor_lat_min)) * usable_height

        return int(x), int(y)

    def _canvas_to_lat_lon_section1(self, x, y):
        """Convert canvas coordinates to lat/lon for Section 1"""
        margin = 20
        usable_width = 440 - 2*margin
        usable_height = 440 - 2*margin

        lon = self.aor_lon_min + (x - margin) / usable_width * (self.aor_lon_max - self.aor_lon_min)
        lat = self.aor_lat_min + (1 - (y - margin) / usable_height) * (self.aor_lat_max - self.aor_lat_min)

        return lat, lon

    def _lat_lon_to_canvas_section2(self, lat, lon):
        """Convert lat/lon to canvas coordinates for Section 2"""
        margin = 50
        usable_width = 440 - 2*margin
        usable_height = 440 - 2*margin

        x = margin + (lon - self.aor_lon_min) / (self.aor_lon_max - self.aor_lon_min) * usable_width
        y = margin + (1 - (lat - self.aor_lat_min) / (self.aor_lat_max - self.aor_lat_min)) * usable_height

        return int(x), int(y)

    def _safe_send_dref(self, dref_path, value, description=""):
        """Safely send dataref with error handling"""
        try:
            self.xpc.sendDREF(dref_path, value)
        except Exception as e:
            print(f"WoZ GUI Error writing {description}: {e}")
            messagebox.showerror("Error", f"Failed to send {description}")

    def _safe_get_dref(self, dref_path, default, description=""):
        """Safely get dataref with 1-second caching"""
        current_time = time.time()

        # Check if we have a cached value that's less than 1 second old
        if dref_path in self._dref_cache:
            cache_entry = self._dref_cache[dref_path]
            age = current_time - cache_entry['timestamp']

            if age < self._dref_cache_ttl:
                # Return cached value
                return cache_entry['value']

        # Cache miss or expired - fetch new value
        try:
            value = self.xpc.getDREF(dref_path)

            # Update cache
            self._dref_cache[dref_path] = {
                'value': value,
                'timestamp': current_time
            }

            return value

        except Exception as e:
            print(f"WoZ GUI Error reading {description}: {e}")

            # If we have a stale cached value, return it as fallback
            if dref_path in self._dref_cache:
                return self._dref_cache[dref_path]['value']

            return default

    # ========== MAIN CONTROL METHODS ==========

    def run_pre_mission_config(self):
        """
        Display pre-mission config screen and BLOCK until START MISSION clicked

        Returns:
            dict: start_conditions dictionary
        """
        # Guard against multiple calls
        if self.pre_mission_complete:
            return self.start_conditions

        # Disable main window sections with overlay
        self._disable_mission_sections()

        # Create Section 1 as separate window
        self._create_section1_window()

        # BLOCK until window destroyed via START MISSION
        self.section1_window.wait_window()

        # Enable main window sections
        self._enable_mission_sections()

        # Draw initial fire map
        self._draw_section2_map()

        return self.start_conditions

    def run_during_mission(self):
        """
        Update GUI without blocking (called from main mission loop)

        Returns:
            bool: True if GUI is still running, False if closed
        """
        try:
            self.root.update()
            # Periodically redraw Section 2 to show current status
            if self.pre_mission_complete:
                self._draw_section2_map()
        except tk.TclError:
            return False
        return True

    def close(self):
        """Close the GUI"""
        try:
            self.root.destroy()
        except Exception:
            pass

    # ========== THREADED GUI METHODS ==========

    def start_gui_loop(self):
        """
        Start GUI main loop with scheduled polling (for threaded mode)

        Schedules periodic polling of input queue and display updates,
        then enters blocking mainloop on this thread.
        """
        # Create pre-mission config window if not already done
        if not self.pre_mission_complete:
            self._disable_mission_sections()
            self._create_section1_window()

        if self.input_queue is not None:
            # Schedule queue polling at 10 Hz
            self.root.after(self.refresh_ms, self._poll_input_queue)

            # Schedule display updates at 10 Hz
            self.root.after(self.refresh_ms, self._update_display)

        # Start main event loop (blocks until window closed)
        self.root.mainloop()

    def _poll_input_queue(self):
        """
        Poll input queue for state updates from mission thread

        Called periodically via root.after() at 10 Hz.
        Processes all pending messages in queue without blocking.
        """
        try:
            # Process all pending messages
            while not self.input_queue.empty():
                try:
                    msg = self.input_queue.get_nowait()
                    self._process_input_message(msg)
                except queue.Empty:
                    break
        except Exception as e:
            print(f"Error polling input queue: {e}")

        # Schedule next poll
        self.root.after(self.refresh_ms, self._poll_input_queue)

    def _process_input_message(self, msg):
        """
        Process a message from the input queue

        Args:
            msg: Dictionary with 'type', 'data', 'timestamp' keys
        """
        msg_type = msg.get('type')

        if msg_type == 'state_update':
            # Cache state for rendering
            self._cached_state = msg.get('data')

        elif msg_type == 'stop':
            # Stop signal from main thread
            self.close()

    def _update_display(self):
        """
        Update display if state has changed

        Called periodically via root.after() at 10 Hz.
        Only redraws if cached state differs from last drawn state.
        """
        if self.pre_mission_complete and self._state_has_changed():
            try:
                self._draw_section2_map()
                self._update_last_drawn_state()
            except Exception as e:
                print(f"Error updating display: {e}")

        # Schedule next update
        self.root.after(self.refresh_ms, self._update_display)

    def _state_has_changed(self):
        """
        Check if cached state differs from last drawn state

        Returns:
            bool: True if state has changed and redraw is needed
        """
        if self._cached_state is None:
            # No cached state from mission thread, check datarefs instead
            # This handles both non-threaded mode and initial state
            return True

        # Compare target statuses to detect changes
        targets = self._cached_state.get('targets', [])

        for target_id, status, lat, lon in targets:
            # Check if status changed
            if target_id not in self._last_drawn_state:
                return True  # New target

            if self._last_drawn_state[target_id] != status:
                return True  # Status changed

        # No changes detected
        return False

    def _update_last_drawn_state(self):
        """
        Update last drawn state cache after rendering

        Should be called after _draw_section2_map() completes
        """
        if self._cached_state:
            targets = self._cached_state.get('targets', [])
            self._last_drawn_state = {tid: status for tid, status, _, _ in targets}


class WoZGUIThread(threading.Thread):
    """
    Thread wrapper for WizardOfOzGUI that provides non-blocking interface

    The GUI runs on its own thread with independent event loop, communicating
    with the main mission thread via queues (same pattern as team planning).
    """

    def __init__(self, xpc, mm):
        """
        Initialize threaded WoZ GUI

        Args:
            xpc: XPlaneConnectX instance
            mm: MissionManager (FireWatchMM) instance
        """
        super().__init__(daemon=True, name="WoZGUIThread")

        self.xpc = xpc
        self.mm = mm

        # Queues for bidirectional communication
        self.gui_input_queue = queue.Queue(maxsize=20)   # Mission → GUI
        self.gui_output_queue = queue.Queue(maxsize=20)  # GUI → Mission

        # Threading control
        self.start_ready_event = threading.Event()
        self.stop_event = threading.Event()

        # GUI instance (created on GUI thread)
        self.woz_gui = None
        self.start_conditions = None
        self.gui_error = None

    def run(self):
        """
        Thread entry point - creates and runs GUI on this thread

        This method runs on the GUI thread, not the main thread.
        """
        try:
            # Import here so WizardOfOzGUI is created on GUI thread

            # Create GUI on this thread with queue parameters
            self.woz_gui = WizardOfOzGUI(
                xpc=self.xpc,
                mm=self.mm,
                input_queue=self.gui_input_queue,
                output_queue=self.gui_output_queue,
                start_ready_event=self.start_ready_event
            )

            # Start GUI main loop (blocks until window closed)
            self.woz_gui.start_gui_loop()

        except Exception as e:
            self.gui_error = e
            print(f"WoZ GUI Thread Error: {e}")
            import traceback
            traceback.print_exc()
            self.start_ready_event.set()  # Unblock waiting thread

    def wait_for_start_conditions(self, timeout=3000):
        """
        Block main thread until pre-mission config complete

        Args:
            timeout: Maximum seconds to wait (default 5 minutes)

        Returns:
            dict: start_conditions from pre-mission config

        Raises:
            TimeoutError: If user doesn't click START MISSION within timeout
            RuntimeError: If GUI thread encountered an error
        """
        # Wait for START MISSION button to be clicked
        if not self.start_ready_event.wait(timeout=timeout):
            raise TimeoutError("Timeout waiting for pre-mission configuration")

        # Check for GUI errors
        if self.gui_error:
            raise RuntimeError(f"GUI thread error: {self.gui_error}")

        # Get start conditions from GUI
        if self.woz_gui:
            return self.woz_gui.start_conditions
        else:
            raise RuntimeError("GUI not initialized")

    def send_state_update(self, state_dict):
        """
        Send state update to GUI (non-blocking)

        Args:
            state_dict: Dictionary with mission state to display
                Expected keys: 'targets', 'mission_timer', 'step_count'

        Drops update if queue is full (graceful degradation)
        """
        try:
            self.gui_input_queue.put_nowait({
                'type': 'state_update',
                'data': state_dict,
                'timestamp': time.time()
            })
        except queue.Full:
            # Queue full, GUI processing slower - drop this frame
            pass

    def get_pending_commands(self):
        """
        Get all pending commands from GUI (non-blocking)

        Returns:
            list: List of command dictionaries from GUI
                Each command has 'type', 'data', 'timestamp' keys
        """
        commands = []

        try:
            while not self.gui_output_queue.empty():
                cmd = self.gui_output_queue.get_nowait()
                commands.append(cmd)
        except queue.Empty:
            pass

        return commands

    def stop(self):
        """
        Signal GUI thread to stop

        This sends a stop message to the GUI and sets the stop event.
        Call join() after this to wait for thread to finish.
        """
        self.stop_event.set()

        # Send stop message to GUI
        try:
            self.gui_input_queue.put_nowait({
                'type': 'stop',
                'data': None,
                'timestamp': time.time()
            })
        except queue.Full:
            pass

        # Try to close GUI window from this thread
        if self.woz_gui:
            try:
                self.woz_gui.close()
            except Exception:
                pass

    def is_alive_and_healthy(self):
        """
        Check if GUI thread is running without errors

        Returns:
            bool: True if thread is alive and no errors encountered
        """
        return self.is_alive() and self.gui_error is None


def process_woz_command(mm, xpc, cmd):
    """
    Process commands sent from WoZ GUI thread

    Args:
        mm: Mission manager instance
        xpc: X-Plane connection instance
        cmd: Command dictionary with 'type' and command-specific data

    Returns:
        bool: True if mission should be killed, False otherwise
    """
    cmd_type = cmd.get('type')

    try:
        if cmd_type == 'target_status':
            # Update target status
            target_id = cmd['target_id']
            status = cmd['status']
            xpc.sendDREF(f"custom/haato/target_status[{target_id}]", status)
            print(f"WoZ: Set target {target_id} status to {status}")

        elif cmd_type == 'target_whoflew':
            target_id = cmd['target_id']
            whoflew = cmd['whoflew']
            xpc.sendDREF(f"custom/haato/target_whoflew_initial[{target_id}]", whoflew)
            print(f"WoZ: Set target {target_id} whoflew to {whoflew}")

        elif cmd_type == 'team_plan':
            # Update team plan
            human_plan = cmd['human_plan']
            wingman_plan = cmd['wingman_plan']

            # Set mm.woz_team_plan attribute
            mm.woz_team_plan = {
                'show_plan': 1.0,
                'human_plan': float(human_plan),
                'wingman_plan': float(wingman_plan),
                'second_best_human_plan': 99.0,
                'second_best_wingman_plan': 99.0,
                'best_followon_human': 99.0,
                'best_followon_wingman': 99.0,
                'second_best_followon_human': 99.0,
                'second_best_followon_wingman': 99.0,
                'rationale': None,
                'planning_mode': None
            }

            # Set wingman's internal plan
            mm.wingman.current_plan_for_self = float(wingman_plan)

            if hasattr(mm, 'udp_bridge'):
                mm.current_team_plan = {
                    'show_plan': True,
                    'human_plan': float(human_plan),
                    'wingman_plan': float(wingman_plan),
                    'second_best_human_plan': 99.0,
                    'second_best_wingman_plan': 99.0,
                    'best_followon_human': 99.0,
                    'best_followon_wingman': 99.0,
                    'second_best_followon_human': 99.0,
                    'second_best_followon_wingman': 99.0,
                    'rationale_code': 99.0,
                    'planning_mode_code': 99.0,
                    'mission_time': float(getattr(mm, 'mission_timer', 0.0)),
                }
                mm.udp_bridge.send_team_plan_suggestion(mm.current_team_plan)

            print(f"WoZ: Set team plan H={human_plan}, W={wingman_plan}")

        elif cmd_type == 'command_from_human':
            # Send manual command from human
            value = cmd['value']
            xpc.sendDREF("custom/haato/command_from_human", value)
            print(f"WoZ: Set command_from_human = {value}")

        elif cmd_type == 'wingman_status':
            # Send wingman status
            value = cmd['value']
            if hasattr(mm, 'udp_bridge'):
                mm.udp_bridge.current_state["wingman"]["status"] = float(value)
                mm._send_shared_state("status_change")
            print(f"WoZ: Set wingman_status = {value}")

        elif cmd_type == 'emergency_kill':
            # Emergency kill - terminate mission immediately
            timestamp = cmd.get('timestamp', 'unknown')
            print(f"WoZ: EMERGENCY KILL received at mission time {timestamp}")
            print("WoZ: Terminating mission immediately...")
            return True

        else:
            print(f"WoZ: Unknown command type: {cmd_type}")

    except Exception as e:
        print(f"Error processing WoZ command {cmd_type}: {e}")
        traceback.print_exc()

    return False
