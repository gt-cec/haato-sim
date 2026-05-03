import sys
import types
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_PATH = REPO_ROOT / "Copy to X-Plane directory" / "Resources" / "plugins" / "PythonPlugins" / "PI_firemission.py"
INPUT_MANAGER_PATH = (
    REPO_ROOT
    / "Copy to X-Plane directory"
    / "Resources"
    / "plugins"
    / "PythonPlugins"
    / "py_utilities"
    / "revamped_input_handling.py"
)


class _DummyDataRef:
    def __init__(self, value=0.0):
        self.value = value


class _ArrayDataRef:
    def __init__(self, values):
        self.values = list(values)

    def __getitem__(self, index):
        return self.values[index]

    def __setitem__(self, index, value):
        self.values[index] = value


def _load_input_manager_module():
    xp_module = types.ModuleType("xp")
    xp_module.log = lambda *args, **kwargs: None

    previous_xp = sys.modules.get("xp")
    sys.modules["xp"] = xp_module
    try:
        module = types.ModuleType("test_revamped_input_handling")
        module.__file__ = str(INPUT_MANAGER_PATH)
        source = INPUT_MANAGER_PATH.read_text(encoding="utf-8")
        exec(compile(source, str(INPUT_MANAGER_PATH), "exec"), module.__dict__)
        return module
    finally:
        if previous_xp is None:
            sys.modules.pop("xp", None)
        else:
            sys.modules["xp"] = previous_xp


def _load_pi_firemission_module():
    xp_module = types.ModuleType("xp")
    xp_module.log = lambda *args, **kwargs: None
    xp_module.speakString = lambda *args, **kwargs: None

    xpgl_module = types.ModuleType("XPPython3.xpgl")
    xpgl_module.loadImage = lambda *args, **kwargs: {"path": args[0] if args else ""}
    xpgl_module.loadFont = lambda *args, **kwargs: {"font": args[0] if args else ""}
    xpgl_module.Colors = {}

    xppython_module = types.ModuleType("XPPython3")
    xppython_module.xpgl = xpgl_module

    dataref_store = {}

    def _find_dataref(name, *args, **kwargs):
        return dataref_store.setdefault(name, _DummyDataRef())

    datarefs_module = types.ModuleType("XPPython3.utils.datarefs")
    datarefs_module.find_dataref = _find_dataref

    commands_module = types.ModuleType("XPPython3.utils.commands")
    utils_module = types.ModuleType("XPPython3.utils")
    utils_module.datarefs = datarefs_module
    utils_module.commands = commands_module

    class DummyTarget:
        def __init__(self, *args, **kwargs):
            self.id = kwargs.get("id", 0)
            self.status = 0.0

    class DummyRadioHandler:
        def __init__(self, *args, **kwargs):
            pass

    class DummySoundManager:
        def __init__(self, *args, **kwargs):
            pass

    fire_classes_module = types.ModuleType("fire_classes")
    fire_classes_module.RadioHandler = DummyRadioHandler
    fire_classes_module.Target = DummyTarget
    fire_classes_module.PositionRecording = object
    fire_classes_module.RouteRecording = object
    fire_classes_module.SoundManager = DummySoundManager

    grid_module = types.ModuleType("py_utilities.grid_system")
    grid_module.GridSystem = object

    input_module = types.ModuleType("py_utilities.revamped_input_handling")
    input_module.InputManager = object
    input_module.InputAction = object

    rendering_module = types.ModuleType("py_utilities.rendering")

    gui_components_module = types.ModuleType("py_utilities.gui_components")
    gui_components_module.Button = object
    gui_components_module.ButtonGrid = object
    gui_components_module.Screen = object

    py_utilities_module = types.ModuleType("py_utilities")
    py_utilities_module.grid_system = grid_module
    py_utilities_module.revamped_input_handling = input_module
    py_utilities_module.rendering = rendering_module
    py_utilities_module.gui_components = gui_components_module

    haato_udp_module = types.ModuleType("haato_udp")
    haato_udp_module.CockpitHaatoUDPBridge = object

    fire_gui_module = types.ModuleType("fire_mission.fire_gui")
    fire_recordings_module = types.ModuleType("fire_mission.fire_recordings")
    fire_recordings_module.handle_recording = lambda plugin: None
    fire_mission_module = types.ModuleType("fire_mission")
    fire_mission_module.fire_gui = fire_gui_module
    fire_mission_module.fire_recordings = fire_recordings_module

    numpy_module = types.ModuleType("numpy")
    numpy_module.mean = lambda values: sum(values) / len(values) if values else 0.0

    stubbed_modules = {
        "xp": xp_module,
        "XPPython3": xppython_module,
        "XPPython3.xpgl": xpgl_module,
        "XPPython3.utils": utils_module,
        "XPPython3.utils.datarefs": datarefs_module,
        "XPPython3.utils.commands": commands_module,
        "fire_classes": fire_classes_module,
        "py_utilities": py_utilities_module,
        "py_utilities.grid_system": grid_module,
        "py_utilities.revamped_input_handling": input_module,
        "py_utilities.rendering": rendering_module,
        "py_utilities.gui_components": gui_components_module,
        "haato_udp": haato_udp_module,
        "fire_mission": fire_mission_module,
        "fire_mission.fire_gui": fire_gui_module,
        "fire_mission.fire_recordings": fire_recordings_module,
        "numpy": numpy_module,
    }

    previous_modules = {name: sys.modules.get(name) for name in stubbed_modules}
    sys.modules.update(stubbed_modules)
    try:
        module = types.ModuleType("test_pi_firemission_modal_module")
        module.__file__ = str(PLUGIN_PATH)
        source = PLUGIN_PATH.read_text(encoding="utf-8")
        source = source.replace("\n# Required for XPPython3\nPI = PythonInterface()\n", "\n")
        exec(compile(source, str(PLUGIN_PATH), "exec"), module.__dict__)
        return module
    finally:
        for name, previous in previous_modules.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


def test_input_manager_json_trigger_is_not_double_dispatched():
    module = _load_input_manager_module()

    manager = module.InputManager()
    manager.joystick_dref = object()
    manager.config.select = 7

    triggered = {"action": 0, "button": 0}
    manager.register_action_callback(module.InputAction.SELECT, lambda: triggered.__setitem__("action", triggered["action"] + 1))
    assert manager.register_button("TRIGGER", fn=lambda: triggered.__setitem__("button", triggered["button"] + 1))

    def _fake_read():
        manager.joystick_values = [0] * 16
        manager.joystick_values[7] = 1
        return True

    manager.read_joystick_values = _fake_read
    actions = manager.process_joystick_buttons()

    assert actions == []
    assert triggered["action"] == 0
    assert triggered["button"] == 1


def test_plan_modal_captures_select_before_primary_review():
    module = _load_pi_firemission_module()

    plugin = module.PythonInterface.__new__(module.PythonInterface)
    plugin.current_screen = "primary"
    plugin.initiative_level = 2.0
    plugin.team_plan_dataref = _ArrayDataRef([1.0, 99.0, 99.0, 99.0])
    plugin.team_plan_cache = [1.0] + [99.0] * 10
    plugin.saved_recordings = [object()]
    plugin.plan_grid = types.SimpleNamespace(selected_row=0, selected_col=0)
    plugin.review_grid = types.SimpleNamespace(selected_col=0)
    plugin.show_best_plan = True
    plugin.human_request_plan_suggestion_dataref = _DummyDataRef(1.0)
    plugin.udp_bridge = types.SimpleNamespace(
        current_team_plan={
            "show_plan": True,
            "human_plan": 99.0,
            "wingman_plan": 99.0,
            "second_best_human_plan": 99.0,
            "second_best_wingman_plan": 99.0,
            "best_followon_human": 99.0,
            "best_followon_wingman": 99.0,
            "second_best_followon_human": 99.0,
            "second_best_followon_wingman": 99.0,
            "rationale_code": 99.0,
            "planning_mode_code": 99.0,
        }
    )
    plugin.log = lambda *args, **kwargs: None
    plugin.log_experiment_data = lambda *args, **kwargs: None
    plugin._send_plan_response = lambda *args, **kwargs: None
    plugin.set_human_indicated_plan = lambda *args, **kwargs: None

    transitions = []
    cleanup_calls = []
    plugin.set_screen = lambda screen: transitions.append(screen)
    plugin.cleanup_recordings = lambda: cleanup_calls.append("called")

    plugin._on_select()

    assert cleanup_calls == []
    assert transitions == ["primary"]
    assert plugin.team_plan_cache == [0.0] + [99.0] * 10
    assert plugin.udp_bridge.current_team_plan is None
    assert plugin.human_request_plan_suggestion_dataref.value == 0.0


def test_plan_modal_blocks_recording_handler():
    module = _load_pi_firemission_module()

    plugin = module.PythonInterface.__new__(module.PythonInterface)
    plugin.current_screen = "primary"
    plugin.initiative_level = 2.0
    plugin.team_plan_dataref = _ArrayDataRef([1.0, 99.0, 99.0, 99.0])
    plugin.log = lambda *args, **kwargs: None

    called = []
    module.fire_recordings.handle_recording = lambda _plugin: called.append("recorded")

    plugin.handle_recording()

    assert called == []


def test_sync_team_plan_cache_ignores_last_answered_plan():
    module = _load_pi_firemission_module()

    plugin = module.PythonInterface.__new__(module.PythonInterface)
    plugin.team_plan_cache = [0.0] + [99.0] * 10
    stale_plan = {
        "show_plan": True,
        "human_plan": 1.0,
        "wingman_plan": 2.0,
        "second_best_human_plan": 3.0,
        "second_best_wingman_plan": 4.0,
        "best_followon_human": 5.0,
        "best_followon_wingman": 6.0,
        "second_best_followon_human": 7.0,
        "second_best_followon_wingman": 0.0,
        "rationale_code": 2.0,
        "planning_mode_code": 1.0,
    }
    plugin.udp_bridge = types.SimpleNamespace(current_team_plan=stale_plan)
    plugin.last_answered_plan_signature = module.PythonInterface._get_team_plan_signature(plugin, stale_plan)

    plugin._sync_team_plan_cache_from_udp()

    assert plugin.team_plan_cache == [0.0] + [99.0] * 10
