# Joystick Setup

HAATO cockpit input is configured with joystick YAML files loaded by the XPPython3 plugin.

## Where Profiles Live

Current profiles live in:

```text
Copy to X-Plane directory/Resources/plugins/PythonPlugins/
```

Included profiles:

- `joystick_logitech.yaml`
- `joystick_thrustmaster.yaml`
- `joystick_microsoft.yaml`

Legacy JSON profiles in `HAATO_assets/` are retained as reference material only. The current plugin loads `joystick_<control_prefix>.yaml`.

## Create a Profile for a New Joystick

1. Copy the closest existing YAML profile.
2. Rename it to `joystick_<short-name>.yaml`.
3. In X-Plane, inspect button indices with `Plugins -> FlyWithLua -> FlyWithLua macros -> Show joystick button numbers`.
4. Press each physical control you want to use and record the displayed button index.
5. Update the YAML values for the HAATO button names.
6. Copy the updated profile into `X-Plane 12/Resources/plugins/PythonPlugins/`.
7. Run HAATO with the matching control prefix:

```bash
python run_mission.py -s 99 -t 1 -c <short-name>
```

`run_mission.py` currently restricts `--control_prefix` to `logitech`, `thrustmaster`, and `microsoft`. To use a new profile, add the new short name to that argument's choices and add a matching value to the cockpit plugin's `custom/haato/control_prefix` mapping.

## Required Button Names

The Fire Scouting cockpit UI expects these names where available:

```yaml
TRIGGER: 160
THUMB: 1
RECORD: 161
QUERY_STATUS: 14
MAP_ZOOM_OUT: 166
MAP_ZOOM_IN: 168
DPAD_UP: 174
DPAD_RIGHT: 175
DPAD_DOWN: 176
DPAD_LEFT: 177
PRIMARY_ESC: 163
CONTROL_REF: 164
AUTO_SPOT: 11
```

Some profiles also include correction and development controls:

```yaml
MAP_ZOOM_IN_CORRECTION: 170
MAP_ZOOM_OUT_CORRECTION: 172
DELETE: 6
CHANGE_CONFIG: 20
ENABLE_AUTOPILOT: 25
```

If a named button is absent from the YAML file, the input manager skips that binding.
