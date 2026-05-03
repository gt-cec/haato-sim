import time
import xp
from XPPython3.utils.datarefs import find_dataref

# ============================================================================
# INPUT HANDLING - Handle joystick and keyboard inputs
# ============================================================================

class InputHandler:
    """Unified input handler that translates physical inputs to logical actions"""

    def __init__(self, parent):
        """
        Initialize input handler

        Args:
            parent: Parent PythonInterface instance (for accessing config and state)
        """
        self.parent = parent
        self.last_key_press_time = {}
        self.last_joystick_button_press_time = {}


    def should_process_key(self, key):
        """Check if enough time has passed since last key press (debouncing)"""
        current_time = time.time()
        last_time = self.last_key_press_time.get(key, 0)

        if current_time - last_time >= self.parent.key_debounce_delay:
            self.last_key_press_time[key] = current_time
            return True
        return False

    def should_process_joystick_button(self, button_index):
        """Check if enough time has passed since last joystick button press (debouncing)"""
        current_time = time.time()
        last_time = self.last_joystick_button_press_time.get(button_index, 0)

        if current_time - last_time >= self.parent.key_debounce_delay:
            self.last_joystick_button_press_time[button_index] = current_time
            return True
        return False

    def process_keyboard(self, vKey):
        """
        Process keyboard input and return logical action

        Args:
            vKey: Virtual key code

        Returns:
            InputAction constant or None if no action
        """
        if not self.should_process_key(vKey):
            return None

        # Dev functions
        elif vKey == xp.VK_NUMPAD1:
            self.parent.saved_recordings = []
        elif vKey == xp.VK_NUMPAD3:
            self.parent.handle_recording()
        elif vKey == xp.VK_MULTIPLY:
            find_dataref("custom/haato/reset_wingman").value = 1.0

        elif vKey == xp.VK_EQUAL:
            self.parent.current_range_level = min(len(self.parent.g1000_range_steps) - 1, self.parent.current_range_level + 1)
        elif vKey == xp.VK_MINUS:
            self.parent.current_range_level = max(0, self.parent.current_range_level - 1)
        elif vKey == self.parent.map_zoom_in_key:
            xp.commandOnce(self.parent.range_up_cmd)
        if vKey == self.parent.map_zoom_out_key:
            xp.commandOnce(self.parent.range_down_cmd)


        # TODO not sure if any of the below fns work
        # Navigation
        if vKey == self.parent.up_key:
            return InputAction.UP
        if vKey == self.parent.down_key:
            return InputAction.DOWN
        if vKey == self.parent.left_key:
            return InputAction.LEFT
        if vKey == self.parent.right_key:
            return InputAction.RIGHT
        if vKey in self.parent.select_keys:
            return InputAction.SELECT
        if vKey == xp.VK_ESCAPE:
            return InputAction.BACK

        # Screen shortcuts
        if vKey == self.parent.primary_screen_key:
            self.parent.set_screen('primary')
        if vKey == self.parent.command_screen_key: # TODO Not working
            self.parent.set_screen('commands')
        if vKey == self.parent.show_human_plan_key: # TODO Not working
            self.parent.set_screen('human_plan')

        # Actions
        if vKey == self.parent.record_key:
            self.parent.handle_recording()

        if vKey == self.parent.relay_recording_key:
            return InputAction.RELAY_RECORDING
        if vKey == self.parent.delete_key:
            return InputAction.DELETE
        if vKey == self.parent.auto_spot_switch_key:
            return InputAction.AUTO_SPOT_TOGGLE
        if vKey == self.parent.reject_key:
            return InputAction.REJECT
        if vKey == self.parent.map_zoom_in_key:
            return InputAction.MAP_ZOOM_IN
        if vKey == self.parent.map_zoom_out_key:
            return InputAction.MAP_ZOOM_OUT

        return None

    def process_joystick(self, button_values):
        """
        Process joystick button states and return logical action

        Args:
            button_values: List of button states (0 or 1)

        Returns:
            List of InputAction constants (can be multiple simultaneous actions)
        """
        actions = []

        # Handle mic button separately (edge detection, not debouncing)
        if len(button_values) > self.parent.mic_key:
            if button_values[self.parent.mic_key] == 1:
                if self.parent.mic_press_time is None:
                    actions.append(InputAction.MIC_PRESS)
                    self.parent.mic_press_time = time.time()
            else:
                if self.parent.mic_press_time is not None:
                    actions.append(InputAction.MIC_RELEASE)
                    self.parent.mic_release_time = time.time()
                    self.parent.mic_press_time = None

        # Process other buttons with debouncing
        button_map = {
            self.parent.up_joystick_button: InputAction.UP,
            self.parent.down_joystick_button: InputAction.DOWN,
            self.parent.left_joystick_button: InputAction.LEFT,
            self.parent.right_joystick_button: InputAction.RIGHT,
            self.parent.select_joystick_button: InputAction.SELECT,
            self.parent.escape_joystick_button: InputAction.BACK,
            self.parent.primary_screen_joystick_button: InputAction.GOTO_PRIMARY,
            self.parent.commands_screen_joystick_button: InputAction.GOTO_COMMANDS,
            self.parent.human_plan_screen_joystick_button: InputAction.GOTO_HUMAN_PLAN,
            self.parent.developer_screen_joystick_button: InputAction.GOTO_DEVELOPER,
            self.parent.record_joystick_button: InputAction.RECORD,
         #   self.parent.toggle_recording_mode_joystick_button: InputAction.TOGGLE_RECORDING_MODE,
            self.parent.auto_spot_toggle_joystick_button: InputAction.AUTO_SPOT_TOGGLE,
            self.parent.map_zoom_in_joystick_button: InputAction.MAP_ZOOM_IN,
            self.parent.map_zoom_out_joystick_button: InputAction.MAP_ZOOM_OUT,
            self.parent.delete_joystick_button: InputAction.DELETE,
        }

        for button_idx, action in button_map.items():
            if button_idx < len(button_values) and button_values[button_idx] == 1:
                if self.should_process_joystick_button(button_idx):
                    actions.append(action)

        return actions


class InputAction:
    """Enum-like class for logical input actions"""
    # Navigation
    UP = 'up'
    DOWN = 'down'
    LEFT = 'left'
    RIGHT = 'right'
    SELECT = 'select'
    BACK = 'back'

    # Screen shortcuts
    GOTO_PRIMARY = 'goto_primary'
    GOTO_COMMANDS = 'goto_commands'
    GOTO_CLASSIFY = 'goto_classify'
    GOTO_HUMAN_PLAN = 'goto_human_plan'
    GOTO_DEVELOPER = 'goto_developer'

    # Actions
    RECORD = 'record'
    RELAY_RECORDING = 'relay_recording'
    TOGGLE_RECORDING_MODE = 'toggle_recording_mode'
    DELETE = 'delete'
    AUTO_SPOT_TOGGLE = 'auto_spot_toggle'
    REJECT = 'reject'
    MAP_ZOOM_IN = 'map_zoom_in'
    MAP_ZOOM_OUT = 'map_zoom_out'

    # Mic (special handling)
    MIC_PRESS = 'mic_press'
    MIC_RELEASE = 'mic_release'

