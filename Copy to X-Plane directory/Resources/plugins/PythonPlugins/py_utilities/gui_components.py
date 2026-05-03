import xp
from XPPython3 import xpgl
from XPPython3.xpgl import Colors
from OpenGL import GL

# ======================================================================================================================
# UI COMPONENTS - Button System
# ======================================================================================================================

class Button:
    """Represents a single interactive button with rendering and state management"""

    def __init__(self, x, y, width, height, label, text_font, button_colors, plugin, grid_column = None, grid_row = None, id=None, function=None):
        """
        Initialize a button

        Args:
            x, y: Bottom-left position
            width, height: Button dimensions
            label: Display text
            id: Optional identifier for the button
            callback: Optional function to call when button is activated
        """
        self.id = id
        self.function = function
        self.plugin = plugin  # PythonInterface class that uses this button

        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.label = label
        self.text_font = text_font
        self.text_color_idle = button_colors['text_color_idle']
        self.text_color_hover = button_colors['text_color_hover']
        self.text_color_active = button_colors['text_color_active']

        self.color_idle = button_colors['color_idle']
        self.color_highlighted = button_colors['color_hover']
        self.color_active = button_colors['color_active']

        # Define where the button is in the grid. Used to determine if the button is highlighted
        self.grid_column = grid_column # Which grid position this button corresponds to. Used in the plugin to detrermine
        self.grid_row = grid_row
        self.enabled = True
        self.state = 'idle'  # idle when not highlighted or activated, "hover" when the cursor is over the button, or "active" when toggled
        self.custom_data = {}  # For storing button-specific data

    def render(self, is_selected=False, is_active=False, custom_colors=None):
        """
        Render the button

        Args:
            font: Font object for text rendering
            is_selected: Whether button is currently selected (highlighted)
            is_active: Whether button is in active/pressed state
            custom_colors: Optional dict with 'selected_bg', 'selected_text', 'normal_bg', 'normal_text', 'active_bg'
        """

        if is_selected:
            self.state = 'hover'
        elif not self.state == 'active':
            self.state = 'idle'

        # Determine colors based on state
        if custom_colors:
            if is_active and 'active_bg' in custom_colors:
                btn_color = custom_colors['active_bg']
                text_color = custom_colors.get('active_text', Colors['white'])
            elif is_selected:
                btn_color = custom_colors.get('selected_bg', Colors['white'])
                text_color = custom_colors.get('selected_text', Colors['black'])
            else:
                btn_color = custom_colors.get('normal_bg', (0.4, 0.4, 0.4))
                text_color = custom_colors.get('normal_text', Colors['white'])
        else:
            # Default color scheme
            if self.state == 'idle':
                btn_color = self.color_idle
                text_color = self.text_color_idle
            elif self.state == 'hover':
                btn_color = self.color_highlighted
                text_color = self.text_color_hover
            elif self.state == 'active':
                btn_color = self.color_active
                text_color = self.text_color_active

        # Draw button background
        xpgl.drawRectangle(self.x, self.y, self.width, self.height, color=btn_color)

        # Draw button text centered
        text_x = self.x + self.width / 2
        text_y = self.y + self.height / 2 - 14  # Adjust for font height
        xpgl.drawText(self.text_font, text_x, text_y, self.label, alignment="C", color=text_color)

    def contains_point(self, x, y):
        """Check if a point is inside this button"""
        return (self.x <= x <= self.x + self.width and
                self.y <= y <= self.y + self.height)

    def activate(self):
        """Call the button's callback if it exists"""
        self.state = 'active'
        if self.function and self.enabled:
            self.function(self)


class ButtonGrid:
    """Manages a collection of buttons in a grid layout with navigation"""

    def __init__(self, rows=1, cols=1):
        """
        Initialize button grid

        Args:
            rows: Number of rows in grid
            cols: Number of columns per row (can be list for variable columns per row)
        """
        self.rows = rows
        self.cols = cols if isinstance(cols, int) else cols
        self.buttons = []  # List of lists: buttons[row][col]
        self.selected_row = 0
        self.selected_col = 0

        # Initialize button grid structure
        if isinstance(self.cols, int):
            self.buttons = [[None for _ in range(self.cols)] for _ in range(self.rows)]
        else:
            self.buttons = [[None for _ in range(c)] for c in self.cols]

    def add_button(self, row, col, button):
        """Add a button at the specified grid position"""
        if 0 <= row < len(self.buttons) and 0 <= col < len(self.buttons[row]):
            self.buttons[row][col] = button
        else:
            raise IndexError(f"Invalid button position: ({row}, {col})")

    def create_button(self, row, col, x, y, width, height, label, id=None, callback=None):
        """Helper method to create and add a button in one step"""
        button = Button(x, y, width, height, label, id, callback)
        self.add_button(row, col, button)
        return button

    def get_button(self, row, col):
        """Get button at specified position"""
        if 0 <= row < len(self.buttons) and 0 <= col < len(self.buttons[row]):
            return self.buttons[row][col]
        return None

    def get_selected_button(self):
        """Get the currently selected button"""
        return self.get_button(self.selected_row, self.selected_col)

    def navigate(self, direction):
        """
        Navigate in the specified direction

        Args:
            direction: 'up', 'down', 'left', or 'right'

        Returns:
            True if navigation was successful, False if at boundary
        """
        if direction == 'up':
            if self.selected_row > 0:
                self.selected_row -= 1
                # Clamp column to valid range for new row
                self.selected_col = min(self.selected_col, len(self.buttons[self.selected_row]) - 1)
                return True
        elif direction == 'down':
            if self.selected_row < len(self.buttons) - 1:
                self.selected_row += 1
                # Clamp column to valid range for new row
                self.selected_col = min(self.selected_col, len(self.buttons[self.selected_row]) - 1)
                return True
        elif direction == 'left':
            if self.selected_col > 0:
                self.selected_col -= 1
                return True
        elif direction == 'right':
            if self.selected_col < len(self.buttons[self.selected_row]) - 1:
                self.selected_col += 1
                return True
        return False

    def render(self, font, active_button_id=None, custom_colors=None):
        """
        Render all buttons in the grid

        Args:
            font: Font object for text rendering
            active_button_id: ID of button in active state (e.g., latched command)
            custom_colors: Optional color scheme for buttons
        """
        for row_idx, row in enumerate(self.buttons):
            for col_idx, button in enumerate(row):
                if button:
                    is_selected = (row_idx == self.selected_row and col_idx == self.selected_col)
                    is_active = (active_button_id is not None and button.id == active_button_id)
                    button.render(is_selected, is_active, custom_colors)

    def activate_selected(self):
        """Activate the currently selected button"""
        button = self.get_selected_button()
        if button:
            button.activate()
            return button
        return None


class Screen:
    """
    Manages a custom screen with buttons, rendering, and input handling.
    """

    def __init__(self, name, layout_type='button_grid'):
        """
        Args:
            name: Screen identifier (e.g., 'classify', 'commands')
            layout_type: 'button_grid', 'custom', 'info_only'
        """
        self.name = name
        self.layout_type = layout_type
        self.button_grid = None  # ButtonGrid instance
        self.custom_render_callback = None  # Custom rendering function
        self.on_enter_callback = None  # Called when screen becomes active
        self.on_exit_callback = None  # Called when leaving screen
        self.data = {}  # Screen-specific data storage

    def enter(self, gui_instance):
        """Called when this screen becomes active"""
        if self.button_grid:
            self.button_grid.selected_row = 0
            self.button_grid.selected_col = 0
        if self.on_enter_callback:
            self.on_enter_callback(gui_instance, self)

    def exit(self, gui_instance):
        """Called when leaving this screen"""
        if self.on_exit_callback:
            self.on_exit_callback(gui_instance, self)

    def handle_input(self, action, gui_instance):
        """
        Handle input action for this screen.

        Args:
            action: Direction string ('up', 'down', 'left', 'right') or 'select'
            gui_instance: PythonInterface instance

        Returns:
            True if action was handled
        """
        if not self.button_grid:
            return False

        if action in ['up', 'down', 'left', 'right']:
            return self.button_grid.navigate(action)
        elif action == 'select':
            button = self.button_grid.activate_selected()
            return button is not None
        return False

    def render(self, gui_instance, font):
        """Render the screen"""
        # Clear screen
        xpgl.drawRectangle(0, 0, 1024, 768, color=Colors['black'])

        # Custom rendering
        if self.custom_render_callback:
            self.custom_render_callback(gui_instance, self, font)

        # Render buttons
        if self.button_grid:
            active_button_id = self._get_active_button_id(gui_instance)
            custom_colors = self.data.get('custom_colors')
            self.button_grid.render(font, active_button_id, custom_colors)

    def _get_active_button_id(self, gui_instance):
        """Override in custom_render_callback if needed"""
        return self.data.get('active_button_id')
