"""
Revamped Input Handling Module

A standalone, reusable module for handling joystick and keyboard inputs in XPPython3 plugins.
Provides JSON-based configuration, debouncing, edge detection, and action mapping.

Usage Example:
    from py_utilities.revamped_input_handling import InputManager, InputAction

    class MyPlugin:
        def XPluginStart(self):
            self.input_manager = InputManager(
                parent_plugin=self,
                config_path='Resources/plugins/my_plugin/joystick_config.json',
                debounce_delay=0.25
            )
            return "My Plugin", "com.example.myplugin", "Description"

        def XPluginEnable(self):
            self.input_manager.initialize_joystick()
            return 1

        def flight_loop_callback(self, elapsedMe, elapsedSim, counter, refcon):
            actions = self.input_manager.process_joystick_buttons()
            for action in actions:
                if action == InputAction.MIC_PRESS:
                    self.start_recording()
                elif action == InputAction.SELECT:
                    self.handle_select()
            return -1
"""

import json
import os
import time
import xp
from typing import List, Dict, Optional, Callable, Any


# ============================================================================
# INPUT ACTION CONSTANTS
# ============================================================================

class InputAction:
    """Enum-like class for logical input actions"""

    # Navigation
    UP = 'up'
    DOWN = 'down'
    LEFT = 'left'
    RIGHT = 'right'
    SELECT = 'select'
    BACK = 'back'
    COPILOT_TOGGLE = 'copilot_toggle'
    COPILOT_ACCEPT_OR_NEWER = 'copilot_accept_or_newer'
    COPILOT_REJECT_OR_OLDER = 'copilot_reject_or_older'

    # Screen shortcuts
    GOTO_PRIMARY = 'escape'
    GOTO_COMMANDS = 'commands'
    GOTO_CLASSIFY = 'goto_classify'
    GOTO_HUMAN_PLAN = 'goto_human_plan'
    GOTO_DEVELOPER = 'goto_developer'
    GOTO_CONTROL_REFERENCE = 'goto_control_reference'

    # Actions
    RECORD = 'record'
    RELAY_RECORDING = 'relay_recording'
    TOGGLE_RECORDING_MODE = 'toggle_recording_mode'
    DELETE = 'delete'
    AUTO_SPOT_TOGGLE = 'auto_spot_toggle'
    REJECT = 'reject'
    MAP_ZOOM_IN = 'map_zoom_in'
    MAP_ZOOM_OUT = 'map_zoom_out'
    MAP_ZOOM_IN_CORRECTION = 'map_zoom_in_correction'
    MAP_ZOOM_OUT_CORRECTION = 'map_zoom_out_correction'
    QUERY_STATUS = 'query_status'
    CHANGE_CONTROL_CONFIG = 'change_control_config'
    ENABLE_AUTOPILOT = 'enable_autopilot'

    # Mic (special edge-detection handling)
    MIC_PRESS = 'mic_press'
    MIC_RELEASE = 'mic_release'


# ============================================================================
# JOYSTICK CONFIGURATION
# ============================================================================

class JoystickConfig:
    """
    Manages joystick button mappings loaded from JSON configuration files.

    Config structure:
        {
            "mic_key": 0,
            "navigation": {
                "up": 1,
                "down": 2,
                "left": 3,
                "right": 4,
                "select": 5,
                "select_button_name": "TRIGGER",
                "dpad_name": "HAT SWITCH"
            },
            "screen_shortcuts": {
                "primary": 6,
                "commands": 7,
                "human_plan": 8,
                "developer": 9,
                "control_reference": 10
            },
            "global_actions": {
                "record": 11,
                "auto_spot_toggle": 12,
                "map_zoom_in": 13,
                "map_zoom_out": 14,
                "map_zoom_in_correction": 15,
                "map_zoom_out_correction": 16,
                "delete": 17,
                "escape": 18,
                "change_control_config": 19,
                "query_wingman_status": 20,
                "enable_autopilot": 21
            }
        }
    """

    def __init__(self):
        """Initialize with default values"""
        # Mic button
        self.mic_key = None

        # Navigation
        self.up = 0
        self.down = 0
        self.left = 0
        self.right = 0
        self.select = 0
        self.select_button_name = 'SELECT'
        self.dpad_name = 'D-PAD'

        # Screen shortcuts
        self.primary = 0
        self.commands = 0
        self.human_plan = 0
        self.developer = 0
        self.control_reference = 0

        # Global actions
        self.record = 0
        self.auto_spot_toggle = 0
        self.map_zoom_in = 0
        self.map_zoom_out = 0
        self.map_zoom_in_correction = 0
        self.map_zoom_out_correction = 0
        self.delete = 0
        self.escape = 0
        self.change_control_config = 0
        self.query_wingman_status = 0
        self.enable_autopilot = 0

    def load_from_file(self, path: str, logger: Optional[Callable] = None) -> bool:
        """
        Load joystick configuration from JSON file.

        Args:
            path: Path to JSON config file
            logger: Optional logging function (defaults to xp.log)

        Returns:
            True if config loaded successfully, False otherwise
        """
        log = logger or xp.log

        try:
            with open(path, 'r') as f:
                config = json.load(f)

            # Load mic button
            self.mic_key = config.get('mic_key')
            if self.mic_key is None:
                log("WARNING: mic_key not found in config, using default")
                self.mic_key = None

            # Load navigation buttons
            nav = config.get('navigation', {})
            self.up = nav.get('up', 0)
            self.down = nav.get('down', 0)
            self.left = nav.get('left', 0)
            self.right = nav.get('right', 0)
            self.select = nav.get('select', 0)
            self.select_button_name = nav.get('select_button_name', 'SELECT')
            self.dpad_name = nav.get('dpad_name', 'D-PAD')

            if not nav:
                log("WARNING: navigation config not found, using defaults")

            # Load screen shortcut buttons
            shortcuts = config.get('screen_shortcuts', {})
            self.primary = shortcuts.get('primary', 0)
            self.commands = shortcuts.get('commands', 0)
            self.human_plan = shortcuts.get('human_plan', 0)
            self.developer = shortcuts.get('developer', 0)
            self.control_reference = shortcuts.get('control_reference', 0)

            if not shortcuts:
                log("WARNING: screen_shortcuts config not found, using defaults")

            # Load global action buttons
            actions = config.get('global_actions', {})
            self.record = actions.get('record', 0)
            self.auto_spot_toggle = actions.get('auto_spot_toggle', 0)
            self.map_zoom_in = actions.get('map_zoom_in', 0)
            self.map_zoom_out = actions.get('map_zoom_out', 0)
            self.map_zoom_in_correction = actions.get('map_zoom_in_correction', 0)
            self.map_zoom_out_correction = actions.get('map_zoom_out_correction', 0)
            self.delete = actions.get('delete', 0)
            self.escape = actions.get('escape', 0)
            self.change_control_config = actions.get('change_control_config', 0)
            self.query_wingman_status = actions.get('query_wingman_status', 0)
            self.enable_autopilot = actions.get('enable_autopilot', 0)

            if not actions:
                log("WARNING: global_actions config not found, using defaults")

            log(f"Successfully loaded joystick config from {path}")
            return True

        except FileNotFoundError:
            log(f"Joystick config file not found at {path}, using defaults")
            return False
        except json.JSONDecodeError as e:
            log(f"Error parsing joystick config file: {e}, using defaults")
            return False
        except Exception as e:
            log(f"Unexpected error loading joystick config: {e}, using defaults")
            return False

    def get_button_mapping(self, action_name: str) -> Optional[int]:
        """
        Get button index for a given action name.

        Args:
            action_name: Action name (e.g., 'select', 'record', 'up')

        Returns:
            Button index or None if action not found
        """
        return getattr(self, action_name, None)

    def set_button_mapping(self, action_name: str, button_index: int) -> bool:
        """
        Set button mapping for a given action.

        Args:
            action_name: Action name (e.g., 'select', 'record', 'up')
            button_index: Button index to assign

        Returns:
            True if mapping was set, False if action doesn't exist
        """
        if hasattr(self, action_name):
            setattr(self, action_name, button_index)
            return True
        return False


# ============================================================================
# INPUT MANAGER
# ============================================================================

class InputManager:
    """
    Main input handling class that processes joystick and keyboard inputs.

    Features:
    - JSON-based joystick configuration
    - Variable debouncing delays per button type
    - Edge detection for mic button (press/release events)
    - Safe array access with bounds checking
    - Optional callback system for action handling
    - Standalone operation (no required parent plugin)
    """

    def __init__(
        self,
        parent_plugin: Optional[Any] = None,
        config_path: Optional[str] = None,
        debounce_delay: float = 0.25,
        num_joystick_values: int = 2000,
        logger: Optional[Callable] = None
    ):
        """
        Initialize InputManager.

        Args:
            parent_plugin: Optional parent plugin instance (for callbacks)
            config_path: Optional path to joystick config JSON
            debounce_delay: Default debounce delay in seconds (default: 0.25)
            num_joystick_values: Number of joystick values to read (default: 2000)
            logger: Optional logging function (defaults to xp.log)
        """
        self.parent_plugin = parent_plugin
        self.debounce_delay = debounce_delay
        self.num_joystick_values = num_joystick_values
        self.log = logger or xp.log

        # Joystick state
        self.joystick_dref = None
        self.joystick_values = []
        self.config = JoystickConfig()

        # Debouncing state
        self.last_joystick_button_press_time = {}
        self.last_key_press_time = {}

        # Custom debounce delays (multipliers)
        self.custom_debounce_multipliers = {}

        # Mic button state (edge detection)
        self.mic_press_time = None
        self.mic_release_time = None

        # Callback system
        self.action_callbacks = {}
        self.named_button_callbacks: Dict[str, Dict[str, List[dict]]] = {}
        self.named_button_map: Dict[str, int] = {}
        self.previous_button_states: Dict[int, int] = {}

        # Load config if provided
        if config_path:
            self.load_config(config_path)

    # ========================================================================
    # CONFIGURATION
    # ========================================================================

    def load_config(self, path: str) -> bool:
        """
        Load joystick configuration from JSON file.

        Args:
            path: Path to JSON config file

        Returns:
            True if config loaded successfully, False otherwise
        """
        ext = os.path.splitext(path)[1].lower()
        if ext in (".yaml", ".yml"):
            return self._load_named_yaml_config(path)
        return self.config.load_from_file(path, self.log)

    def _load_named_yaml_config(self, path: str) -> bool:
        """
        Load simple button-name to button-id mappings from YAML.

        Supported shape:
            BUTTON_NAME: 123
        """
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read()
        except FileNotFoundError:
            self.log(f"Joystick config file not found at {path}")
            return False
        except Exception as e:
            self.log(f"Error reading joystick config {path}: {e}")
            return False

        parsed = None
        try:
            import yaml  # type: ignore
            parsed = yaml.safe_load(raw)
        except Exception:
            parsed = self._parse_simple_yaml_mapping(raw)

        if not isinstance(parsed, dict):
            self.log(f"Invalid YAML config structure in {path}: expected top-level mapping")
            return False

        result = {}
        for key, value in parsed.items():
            if key is None:
                continue
            try:
                result[str(key).strip().upper()] = int(value)
            except (TypeError, ValueError):
                self.log(f"WARNING: invalid button id for '{key}' in {path}: {value}")

        self.named_button_map = result
        self.log(f"Successfully loaded joystick YAML config from {path} ({len(result)} button mappings)")
        return True

    def _parse_simple_yaml_mapping(self, raw: str) -> Dict[str, int]:
        """
        Strict fallback parser for simple KEY: value YAML mappings.
        """
        result = {}
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if ":" not in stripped:
                continue
            key, value = stripped.split(":", 1)
            key = key.strip().strip("'\"")
            value = value.strip().strip("'\"")
            if not key:
                continue
            result[key] = value
        return result

    def set_custom_debounce(self, action_name: str, multiplier: float):
        """
        Set custom debounce delay multiplier for a specific action.

        Args:
            action_name: Action name (e.g., 'select', 'query_wingman_status')
            multiplier: Multiplier for base debounce delay (e.g., 2.0 for 2x)
        """
        button_index = self.config.get_button_mapping(action_name)
        if button_index is not None:
            self.custom_debounce_multipliers[button_index] = multiplier

    # ========================================================================
    # JOYSTICK INITIALIZATION
    # ========================================================================

    def initialize_joystick(self) -> bool:
        """
        Initialize joystick by finding the button values dataref.
        Should be called during XPluginEnable.

        Returns:
            True if joystick dataref found, False otherwise
        """
        try:
            self.joystick_dref = xp.findDataRef("sim/joystick/joystick_button_values")
            if self.joystick_dref:
                self.log("Joystick dataref initialized successfully")
                return True
            else:
                self.log("WARNING: Joystick dataref not found")
                return False
        except Exception as e:
            self.log(f"Error initializing joystick: {e}")
            return False

    # ========================================================================
    # JOYSTICK BUTTON PROCESSING
    # ========================================================================

    def read_joystick_values(self) -> bool:
        """
        Read current joystick button values from X-Plane.

        Returns:
            True if values read successfully, False otherwise
        """
        if not self.joystick_dref:
            return False

        try:
            self.joystick_values = []
            xp.getDatavi(self.joystick_dref, self.joystick_values, count=self.num_joystick_values)
            return True
        except Exception as e:
            self.log(f"Error reading joystick values: {e}")
            return False

    def safe_joystick_button_state(self, button_index: int) -> int:
        """
        Safely get joystick button state with bounds checking.

        Args:
            button_index: Button index to check

        Returns:
            Button state (0 or 1), or 0 if index out of bounds
        """
        try:
            button_index = int(button_index)
            if 0 <= button_index < len(self.joystick_values):
                return self.joystick_values[button_index]
            return 0
        except (IndexError, TypeError, ValueError):
            return 0

    def should_process_joystick_button(self, button_index: int) -> bool:
        """
        Check if enough time has passed since last button press (debouncing).
        Supports variable debounce delays via custom_debounce_multipliers.

        Args:
            button_index: Button index to check

        Returns:
            True if button should be processed, False if still in debounce period
        """
        current_time = time.time()
        last_press = self.last_joystick_button_press_time.get(button_index, 0)

        # Get custom debounce multiplier if set
        multiplier = self.custom_debounce_multipliers.get(button_index, 1.0)
        debounce_delay = self.debounce_delay * multiplier

        if current_time - last_press >= debounce_delay:
            self.last_joystick_button_press_time[button_index] = current_time
            return True
        return False

    def process_joystick_buttons(self) -> List[str]:
        """
        Process all joystick buttons and return list of triggered actions.

        This is the main method to call in your flight loop callback.

        Returns:
            List of InputAction constants for triggered actions
        """
        actions = []

        # Early return if joystick not initialized
        if not self.joystick_dref:
            xp.log('[InputManager] Joystick not initialized')
            return actions

        # Read current button values
        if not self.read_joystick_values():
            return actions

        # Handle mic button with edge detection (press/release events)
        if isinstance(self.config.mic_key, int):
            xp.log(f'[Input handler] Mic key')

            mic_state = self.safe_joystick_button_state(self.config.mic_key)
            if mic_state == 1 and self.mic_press_time is None:
                xp.log(f'[Input handler] Mic key 1')
                actions.append(InputAction.MIC_PRESS)
                self.mic_press_time = time.time()
            elif mic_state == 0 and self.mic_press_time is not None:
                xp.log(f'[Input handler] Mic key 0')
                actions.append(InputAction.MIC_RELEASE)
                self.mic_release_time = time.time()
                self.mic_press_time = None

        # Build button-to-action mapping
        button_map = {}
        self._add_button_mapping(button_map, self.config.up, InputAction.UP)
        self._add_button_mapping(button_map, self.config.down, InputAction.DOWN)
        self._add_button_mapping(button_map, self.config.left, InputAction.LEFT)
        self._add_button_mapping(button_map, self.config.right, InputAction.RIGHT)
        self._add_button_mapping(button_map, self.config.select, InputAction.SELECT)
        self._add_button_mapping(button_map, self.config.escape, InputAction.BACK)

        self._add_button_mapping(button_map, self.config.primary, InputAction.GOTO_PRIMARY)
        self._add_button_mapping(button_map, self.config.commands, InputAction.GOTO_COMMANDS)
        self._add_button_mapping(button_map, self.config.human_plan, InputAction.GOTO_HUMAN_PLAN)
        self._add_button_mapping(button_map, self.config.developer, InputAction.GOTO_DEVELOPER)
        self._add_button_mapping(button_map, self.config.control_reference, InputAction.GOTO_CONTROL_REFERENCE)

        self._add_button_mapping(button_map, self.config.record, InputAction.RECORD)
        self._add_button_mapping(button_map, self.config.auto_spot_toggle, InputAction.AUTO_SPOT_TOGGLE)
        self._add_button_mapping(button_map, self.config.map_zoom_in, InputAction.MAP_ZOOM_IN)
        self._add_button_mapping(button_map, self.config.map_zoom_out, InputAction.MAP_ZOOM_OUT)
        self._add_button_mapping(button_map, self.config.map_zoom_in_correction, InputAction.MAP_ZOOM_IN_CORRECTION)
        self._add_button_mapping(button_map, self.config.map_zoom_out_correction, InputAction.MAP_ZOOM_OUT_CORRECTION)
        self._add_button_mapping(button_map, self.config.delete, InputAction.DELETE)
        self._add_button_mapping(button_map, self.config.query_wingman_status, InputAction.QUERY_STATUS)
        self._add_button_mapping(button_map, self.config.change_control_config, InputAction.CHANGE_CONTROL_CONFIG)
        self._add_button_mapping(button_map, self.config.enable_autopilot, InputAction.ENABLE_AUTOPILOT)

        # Process all buttons with debouncing
        for button_idx, action in button_map.items():
            if self.safe_joystick_button_state(button_idx) == 1:
                if self.should_process_joystick_button(button_idx):
                    actions.append(action)
                    xp.log(f'Detected joystick button {button_idx} - triggering action {action}')

        # Trigger callbacks if registered
        if actions:
            self.trigger_action_callbacks(actions)

        # Trigger named button callbacks (YAML-config mode)
        self._trigger_named_button_callbacks()

        return actions

    def _add_button_mapping(self, button_map: Dict[int, str], button_idx: Any, action: str):
        """
        Add a button mapping if the index is valid and currently unused.
        """
        if not isinstance(button_idx, int):
            return
        if button_idx < 0:
            return
        # In named YAML mode, skip legacy mappings that collide with named buttons.
        if button_idx in self.named_button_map.values():
            return
        if button_idx in button_map:
            return
        button_map[button_idx] = action

    def _resolve_button_index(self, name: str) -> Optional[int]:
        """
        Resolve a named button against YAML mappings first, then JSON config aliases.
        """
        norm_name = str(name).strip().upper()

        button_idx = self.named_button_map.get(norm_name)
        if isinstance(button_idx, int):
            return button_idx

        alias_map = {
            "DPAD_UP": self.config.up,
            "DPAD_DOWN": self.config.down,
            "DPAD_LEFT": self.config.left,
            "DPAD_RIGHT": self.config.right,
            "TRIGGER": self.config.select,
            "PRIMARY_ESC": self.config.primary,
            "COMMANDS_SCREEN": self.config.commands,
            "HUMAN_PLAN": self.config.human_plan,
            "CONTROL_REF": self.config.control_reference,
            "RECORD": self.config.record,
            "AUTO_SPOT": self.config.auto_spot_toggle,
            "MAP_ZOOM_IN": self.config.map_zoom_in,
            "MAP_ZOOM_OUT": self.config.map_zoom_out,
            "MAP_ZOOM_IN_CORRECTION": self.config.map_zoom_in_correction,
            "MAP_ZOOM_OUT_CORRECTION": self.config.map_zoom_out_correction,
            "DELETE": self.config.delete,
            "QUERY_STATUS": self.config.query_wingman_status,
        }
        button_idx = alias_map.get(norm_name)
        if isinstance(button_idx, int) and button_idx >= 0:
            self.named_button_map[norm_name] = button_idx
            return button_idx
        return None

    # ========================================================================
    # KEYBOARD PROCESSING
    # ========================================================================

    def should_process_key(self, vKey: int) -> bool:
        """
        Check if enough time has passed since last key press (debouncing).

        Args:
            vKey: Virtual key code

        Returns:
            True if key should be processed, False if still in debounce period
        """
        current_time = time.time()
        last_time = self.last_key_press_time.get(vKey, 0)

        if current_time - last_time >= self.debounce_delay:
            self.last_key_press_time[vKey] = current_time
            return True
        return False

    def process_keyboard(self, vKey: int) -> Optional[str]:
        """
        Process keyboard input with debouncing.

        Args:
            vKey: Virtual key code

        Returns:
            InputAction constant or None if no action triggered
        """
        if not self.should_process_key(vKey):
            return None

        # Basic navigation keys (can be extended)
        key_map = {
            xp.VK_UP: InputAction.UP,
            xp.VK_DOWN: InputAction.DOWN,
            xp.VK_LEFT: InputAction.LEFT,
            xp.VK_RIGHT: InputAction.RIGHT,
            xp.VK_RETURN: InputAction.SELECT,
            xp.VK_ESCAPE: InputAction.BACK,
        }
        numpad5_key = getattr(xp, "VK_NUMPAD5", None)
        if numpad5_key is not None:
            key_map[numpad5_key] = InputAction.COPILOT_TOGGLE
        numpad4_key = getattr(xp, "VK_NUMPAD4", None)
        if numpad4_key is not None:
            key_map[numpad4_key] = InputAction.COPILOT_ACCEPT_OR_NEWER
        numpad6_key = getattr(xp, "VK_NUMPAD6", None)
        if numpad6_key is not None:
            key_map[numpad6_key] = InputAction.COPILOT_REJECT_OR_OLDER
        backspace_key = getattr(xp, "VK_BACK", None)
        if backspace_key is not None:
            key_map[backspace_key] = InputAction.BACK

        action = key_map.get(vKey)
        if action:
            self.trigger_action_callbacks([action])

        return action

    # ========================================================================
    # CALLBACK SYSTEM
    # ========================================================================

    def register_action_callback(self, action: str, callback: Callable):
        """
        Register a callback function for a specific action.

        Args:
            action: InputAction constant (e.g., InputAction.SELECT)
            callback: Callback function to call when action is triggered
        """
        if action not in self.action_callbacks:
            self.action_callbacks[action] = []
        self.action_callbacks[action].append(callback)

    def register_button(
        self,
        name: str,
        fn: Optional[Callable] = None,
        action: Optional[str] = None,
        event: str = "press",
        args: Optional[List[Any]] = None,
        kwargs: Optional[Dict[str, Any]] = None,
        debounce_multiplier: float = 1.0,
        enabled: bool = True,
    ) -> bool:
        """
        Register a callback or named action for a button name from YAML config.
        """
        if fn is None and action is None:
            self.log(f"WARNING: register_button('{name}') requires fn or action")
            return False

        norm_name = str(name).strip().upper()
        event = str(event).strip().lower()
        if event not in ("press", "release"):
            self.log(f"WARNING: unsupported event '{event}' for button '{name}'")
            return False

        button_idx = self._resolve_button_index(norm_name)
        if button_idx is None:
            self.log(f"WARNING: button '{name}' not found in joystick config")
            return False

        self.custom_debounce_multipliers[button_idx] = float(debounce_multiplier)
        if norm_name not in self.named_button_callbacks:
            self.named_button_callbacks[norm_name] = {"press": [], "release": []}

        self.named_button_callbacks[norm_name][event].append(
            {
                "fn": fn,
                "action": action,
                "args": args or [],
                "kwargs": kwargs or {},
                "enabled": bool(enabled),
            }
        )
        return True

    def _trigger_named_button_callbacks(self):
        for button_name, callbacks_by_event in self.named_button_callbacks.items():
            button_idx = self.named_button_map.get(button_name)
            if button_idx is None:
                continue

            current = 1 if self.safe_joystick_button_state(button_idx) == 1 else 0
            prev = self.previous_button_states.get(button_idx, 0)

            event = None
            if prev == 0 and current == 1:
                event = "press"
            elif prev == 1 and current == 0:
                event = "release"

            if event and self.should_process_joystick_button(button_idx):
                for binding in callbacks_by_event.get(event, []):
                    if not binding.get("enabled", True):
                        continue
                    self._invoke_button_binding(binding)

            self.previous_button_states[button_idx] = current

    def _invoke_button_binding(self, binding: Dict[str, Any]):
        fn = binding.get("fn")
        action = binding.get("action")
        args = binding.get("args", [])
        kwargs = binding.get("kwargs", {})
        try:
            if callable(fn):
                fn(*args, **kwargs)
            elif action:
                self.trigger_action_callbacks([action])
        except Exception as e:
            self.log(f"Error in button callback: {e}")

    def trigger_action_callbacks(self, actions: List[str]):
        """
        Trigger all registered callbacks for the given actions.

        Args:
            actions: List of InputAction constants
        """
        for action in actions:
            if action in self.action_callbacks:
                for callback in self.action_callbacks[action]:
                    try:
                        callback()
                    except Exception as e:
                        self.log(f"Error in action callback for {action}: {e}")

    # ========================================================================
    # UTILITY METHODS
    # ========================================================================

    def get_mic_press_duration(self) -> Optional[float]:
        """
        Get duration of current mic press (if mic is pressed).

        Returns:
            Duration in seconds, or None if mic not pressed
        """
        if self.mic_press_time is None:
            return None
        return time.time() - self.mic_press_time

    def get_last_mic_press_duration(self) -> Optional[float]:
        """
        Get duration of last mic press (after release).

        Returns:
            Duration in seconds, or None if no previous press
        """
        if self.mic_press_time is None and self.mic_release_time is not None:
            # Mic was pressed and released - calculate from last known times
            # Note: This assumes mic_press_time was set to 0 after release
            # For more accurate tracking, store the original press time separately
            return None
        return None

    def reset_debounce_state(self):
        """Reset all debounce timers (useful for testing or state reset)"""
        self.last_joystick_button_press_time = {}
        self.last_key_press_time = {}

    def is_button_pressed(self, action_name: str) -> bool:
        """
        Check if a button is currently pressed (without debouncing).

        Args:
            action_name: Action name (e.g., 'select', 'record')

        Returns:
            True if button is pressed, False otherwise
        """
        button_index = self.config.get_button_mapping(action_name)
        if button_index is None:
            return False
        return self.safe_joystick_button_state(button_index) == 1
