import sys
import types
from copy import deepcopy
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_PATH = REPO_ROOT / "Copy to X-Plane directory" / "Resources" / "plugins" / "PythonPlugins" / "PI_firemission.py"
CONFIG_PATH = REPO_ROOT / "Copy to X-Plane directory" / "Resources" / "plugins" / "HAATO_assets" / "config.yaml"


def _load_pi_firemission_module():
    xp_module = types.ModuleType("xp")
    xp_module.log = lambda *args, **kwargs: None

    xpgl_module = types.ModuleType("XPPython3.xpgl")
    xpgl_module.loadImage = lambda *args, **kwargs: {"path": args[0] if args else ""}
    xpgl_module.loadFont = lambda *args, **kwargs: {"font": args[0] if args else ""}
    xpgl_module.Colors = types.SimpleNamespace()

    xppython_module = types.ModuleType("XPPython3")
    xppython_module.xpgl = xpgl_module

    class DummyDataRef:
        def __init__(self, value=0.0):
            self.value = value

    dataref_store = {}

    def _find_dataref(name, *args, **kwargs):
        return dataref_store.setdefault(name, DummyDataRef())

    datarefs_module = types.ModuleType("XPPython3.utils.datarefs")
    datarefs_module.find_dataref = _find_dataref

    commands_module = types.ModuleType("XPPython3.utils.commands")
    utils_module = types.ModuleType("XPPython3.utils")
    utils_module.datarefs = datarefs_module
    utils_module.commands = commands_module

    class DummyTarget:
        def __init__(self, lat, long, alt, type, id, is_dynamic=False, trigger_time_s=0.0):
            self.lat = lat
            self.long = long
            self.alt = alt
            self.type = type
            self.id = id
            self.is_dynamic = is_dynamic
            self.trigger_time_s = trigger_time_s
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

    class DummyGridSystem:
        @staticmethod
        def latlon_to_grid_position(lat, lon):
            return (lat, lon)

    grid_module = types.ModuleType("py_utilities.grid_system")
    grid_module.GridSystem = DummyGridSystem

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
    fire_mission_module = types.ModuleType("fire_mission")
    fire_mission_module.fire_gui = fire_gui_module
    fire_mission_module.fire_recordings = fire_recordings_module

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
    }

    previous_modules = {name: sys.modules.get(name) for name in stubbed_modules}
    sys.modules.update(stubbed_modules)
    try:
        module = types.ModuleType("test_pi_firemission_module")
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


def test_fallback_parser_reads_current_mission_shapes():
    module = _load_pi_firemission_module()

    parsed = module._parse_haato_config_fallback(str(CONFIG_PATH))

    assert len(parsed["missions"][1]["fires"]) == 8
    assert len(parsed["missions"][1]["fires_reported"]) == 8
    assert parsed["missions"][1]["dynamic_events"] == []
    assert len(parsed["missions"][4]["data_points"]) == 2
    assert parsed["missions"][1]["fires"][0]["id"] == 0
    assert parsed["missions"][4]["data_points"][0]["type"] == "severe"
    assert parsed["experiment"]["practice_configs"][0]["fire_layout"] == 4
    assert parsed["experiment"]["configs"][99][0]["initiative_level"] == "high"


def test_load_targets_from_yaml_supports_new_and_legacy_missions():
    module = _load_pi_firemission_module()
    parsed = module._parse_haato_config_fallback(str(CONFIG_PATH))

    plugin = module.PythonInterface.__new__(module.PythonInterface)
    plugin.fire_images = {}
    plugin.log = lambda *_args, **_kwargs: None

    plugin.load_targets_from_yaml(parsed["missions"][1])
    assert plugin.num_targets == 8
    assert plugin.targets[0].id == 0
    assert plugin.targets[0].is_known_to_cockpit is True
    assert plugin.targets[0].reported_lat == parsed["missions"][1]["fires_reported"][0]["latitude"]

    plugin.load_targets_from_yaml(parsed["missions"][4])
    assert plugin.num_targets == 2
    assert plugin.targets[0].id == 0
    assert plugin.targets[0].is_known_to_cockpit is True
    assert plugin.targets[1].type == "severe"


def test_load_targets_from_yaml_hides_new_schema_fires_without_reported_positions():
    module = _load_pi_firemission_module()
    parsed = module._parse_haato_config_fallback(str(CONFIG_PATH))

    plugin = module.PythonInterface.__new__(module.PythonInterface)
    plugin.fire_images = {}
    plugin.log = lambda *_args, **_kwargs: None

    mission_data = deepcopy(parsed["missions"][1])
    mission_data["fires"] = [
        {"id": 10, "latitude": 47.5, "longitude": -121.2, "altitude": 1000.0, "type": "moderate"},
        {"id": 11, "latitude": 47.6, "longitude": -121.1, "altitude": 1100.0, "type": "severe"},
    ]
    mission_data["fires_reported"] = [
        {"id": 10, "latitude": 47.55, "longitude": -121.25, "altitude": 1010.0},
    ]

    plugin.load_targets_from_yaml(mission_data)

    target_known = plugin._get_target_by_id(10)
    target_unknown = plugin._get_target_by_id(11)

    assert target_known.is_known_to_cockpit is True
    assert target_known.reported_lat == 47.55
    assert target_known.reported_long == -121.25
    assert target_known.reported_alt == 1010.0
    assert target_unknown.is_known_to_cockpit is False
    assert target_unknown.reported_lat == target_unknown.lat


def test_get_target_screen_position_uses_reported_coordinates_by_target_id():
    module = _load_pi_firemission_module()

    plugin = module.PythonInterface.__new__(module.PythonInterface)
    plugin.aor_center_lat = 47.0
    plugin.aor_center_long = -121.0
    plugin.lon_scale_nm = 10.0
    plugin.lat_scale_nm = 20.0
    plugin.pixels_per_nm = 4.0
    plugin.mfd_center_x = 100.0
    plugin.mfd_center_y = 200.0

    target = types.SimpleNamespace(
        id=7,
        lat=48.0,
        long=-120.0,
        reported_lat=47.25,
        reported_long=-120.5,
    )
    plugin.targets = [target]
    plugin._get_target_by_id = lambda target_id: target if target_id == 7 else None

    screen_x, screen_y = plugin.get_target_screen_position(7, 3.0, -2.0)

    assert screen_x == 123.0
    assert screen_y == 218.0
    assert plugin.get_target_screen_position(99, 0.0, 0.0) is None
