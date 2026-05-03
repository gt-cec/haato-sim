"""Main mission runner for the firefighting mission."""

from __future__ import annotations

import argparse
import os
import random
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from typing import Any

try:
    import speech_recognition as sr
except Exception:
    print("Speech recognition module not found")

from missions.fire.mission_manager import FireWatchMM
from utility.XPlaneConnectX import XPlaneConnectX
from utility.config_loader import get_config
from utility.crash_recovery import CrashStateSaverThread, restore_mission_from_crash, save_crash_state
from utility.data_logger import DataLogger
from utility.helper_functions import print_debug_header
from utility.utility_classes import MissionTimer, SimMode
from utility.voice_input import VoiceInputManager, VoiceInputMode
from utility.woz_gui import WoZGUIThread, process_woz_command


def _load_experiment_configs():
    exp = get_config()["experiment"]
    practice = exp["practice_configs"]
    configs = {int(k): v for k, v in exp["configs"].items()}
    return practice, configs


PRACTICE_CONFIGS, CONFIGS = _load_experiment_configs()

CRASHED_MISSION_FILES_DIR = os.path.join(os.path.dirname(__file__), "logs/crashed_mission_files")


@dataclass
class MissionSelection:
    config: dict[str, Any]
    initiative_level_name: str
    initiative_level_float: float
    fire_layout: int


@dataclass
class MissionRuntime:
    args: argparse.Namespace
    selection: MissionSelection
    log_file_identifier: float
    xpc: XPlaneConnectX
    voice_thread: threading.Thread | None = None
    timer: MissionTimer | None = None
    mm: FireWatchMM | None = None
    logger: DataLogger | None = None
    sim: SimMode | None = None
    combinedgui: Any = None
    msg_visualizer: Any = None
    dev_gui: Any = None
    woz_gui_thread: WoZGUIThread | None = None
    crash_saver_thread: CrashStateSaverThread | None = None
    fm: Any = None
    pause_time: float = 0.0
    met: float = 0.0
    done: bool = False
    step_count: int = 0
    steps_since_statesave: int = 99
    cleaned_up: bool = False
    voice_stop_event: threading.Event | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run X-Plane mission experiments")
    parser.add_argument("--subject_id", "-s", type=int, required=True, help="Participant ID")
    parser.add_argument("--trial", "-t", type=int, required=True, choices=[1, 2, 3, 4, 5], help="Trial number")
    parser.add_argument("--practice", type=int, default=None, choices=[1, 2, None], help="Practice round number")
    parser.add_argument("--control_prefix", "-c", type=str, required=True, choices=["logitech", "thrustmaster", "microsoft"])
    parser.add_argument("--verbose", action="store_true", default=False, help="Enable verbose output")
    parser.add_argument("--dev_mode", action="store_true", default=False, help="Enable development mode")
    parser.add_argument("--configure", action="store_true", default=False, help="Open WoZ GUI for pre-mission configuration")
    parser.add_argument("--simulate_xplane", action="store_true", default=False, help="Enable X-Plane simulation")
    parser.add_argument("--sim_human", action="store_true", default=False, help="Enable simulated human")
    parser.add_argument("--log_hz", type=float, default=1.0, help="Logging frequency in Hz")
    parser.add_argument("--noreset", action="store_true", default=False, help="Skip simulator reset")
    parser.add_argument("--resume", action="store_true", default=False, help="Resume from most recent crashed mission state")
    parser.add_argument("--testing_wingman", action="store_true", default=False, help="Run wingman testing mode")
    return parser.parse_args()


def initiative_level_to_float(name: str) -> float:
    return 0.0 if name == "low" else 1.0 if name == "medium" else 2.0


def select_trial_config(subject_id: int, trial: int, practice: int | None) -> MissionSelection:
    if practice in [1, 2]:
        config = PRACTICE_CONFIGS[practice - 1]
    elif subject_id in [99, 97]:
        config = CONFIGS[subject_id][trial - 1]
    else:
        config = CONFIGS[((subject_id - 1) % 9) + 1][trial - 1]

    initiative_level_name = config["initiative_level"]
    return MissionSelection(
        config=config,
        initiative_level_name=initiative_level_name,
        initiative_level_float=initiative_level_to_float(initiative_level_name),
        fire_layout=config["fire_layout"],
    )



def voice_input_loop(runtime: MissionRuntime) -> None:
    assert runtime.mm is not None

    voice_manager = VoiceInputManager(
        xpc=runtime.xpc,
        mode=VoiceInputMode.PTT,
        verbose=runtime.args.verbose,
    )
    stop_event = runtime.voice_stop_event

    try:
        while stop_event is None or not stop_event.is_set():
            try:
                pilot_ready = voice_manager.wait_for_pilot(timeout=0.25)
                if not pilot_ready:
                    continue

                transcript = (voice_manager.listen_until_release() or "").strip()
                if not transcript:
                    time.sleep(0.05)
                    continue

                runtime.mm.receive_human_message(transcript, source="voice_input")
            except Exception as exc:
                print(f"[Voice Input] Error in voice loop: {exc}")
                traceback.print_exc()
                time.sleep(0.25)
    finally:
        voice_manager.cleanup()


def start_voice_thread(runtime: MissionRuntime) -> threading.Thread:
    voice_thread = threading.Thread(target=voice_input_loop, args=(runtime,), daemon=True)
    voice_thread.start()
    return voice_thread


def print_selection_debug(selection: MissionSelection, practice: int | None) -> None:
    if practice in [1, 2]:
        print_debug_header(
            f"[RUN_MISSION] - PRACTICE ROUND {practice} - "
            f"INITIATIVE LEVEL {selection.initiative_level_float} ({selection.initiative_level_name}) - "
            f"FIRE LAYOUT {selection.fire_layout}"
        )
    else:
        print_debug_header(
            f"[RUN_MISSION] STARTING - INITIATIVE LEVEL "
            f"{selection.initiative_level_float} ({selection.initiative_level_name}) - FIRE LAYOUT {selection.fire_layout}"
        )


def initialize_runtime(args: argparse.Namespace) -> MissionRuntime:
    selection = select_trial_config(args.subject_id, args.trial, args.practice)
    print(f"Config = {selection.config}")
    print(f"Control prefix = {args.control_prefix}")
    print_selection_debug(selection, args.practice)

    log_file_identifier = float(random.randint(1, 100000))
    print(f"Generated log file identifier {log_file_identifier}")

    _net = get_config()["network"]
    xpc = XPlaneConnectX(ip=_net["xplane_ip"], port=_net["xplane_port"])
    print("XPCX Connection established successfully")

    runtime = MissionRuntime(
        args=args,
        selection=selection,
        log_file_identifier=log_file_identifier,
        xpc=xpc,
        voice_stop_event=threading.Event(),
    )
    runtime.timer = MissionTimer()
    runtime.mm = FireWatchMM(
        xpc=xpc,
        user_id=args.subject_id,
        fire_layout=selection.fire_layout,
        initiative_level=selection.initiative_level_float,
        dev_mode=args.dev_mode,
        log_file_identifier=log_file_identifier,
        control_prefix=args.control_prefix,
        sim_human=args.sim_human,
        noreset=args.noreset,
        resume=args.resume,
        testing_wingman=args.testing_wingman,
        verbose=args.verbose,
    )
    runtime.logger = DataLogger(
        xpc,
        runtime.mm,
        config=selection.config,
        trial=args.trial,
        user_id=args.subject_id,
        verbose=args.verbose,
        wingman_initiative_level=selection.initiative_level_float,
        fire_layout=selection.fire_layout,
        log_freq=args.log_hz,
        log_file_identifier=log_file_identifier,
        notes=f"initiativelevel{selection.initiative_level_name}_firelayout{selection.fire_layout}",
    )
    runtime.voice_thread = None #start_voice_thread(runtime)
    print(f"MM initialized for fire layout {selection.fire_layout}, initiative level {selection.initiative_level_float}")

    runtime.sim = SimMode(runtime.mm) if args.simulate_xplane else None
    runtime.xpc.sim_mode = runtime.sim

    initialize_mission_state(runtime)
    initialize_crash_saver(runtime)
    return runtime


def initialize_mission_state(runtime: MissionRuntime) -> None:
    assert runtime.mm is not None
    if runtime.args.resume:
        try:
            print_debug_header("RESUMING FROM CRASHED MISSION")
            runtime.mm.reset()
            crash_state = restore_mission_from_crash(runtime.xpc, runtime.mm, CRASHED_MISSION_FILES_DIR)
            print(
                f"Resumed: timer={crash_state['metadata']['mission_timer']:.1f}s, "
                f"step={crash_state['metadata']['step_count']}"
            )
            return
        except Exception as exc:
            print(f"ERROR RESUMING FROM CRASH: {exc}")
            traceback.print_exc()
            print("Proceeding with normal reset...")

    runtime.mm.reset()
    runtime.woz_gui_thread = WoZGUIThread(xpc=runtime.xpc, mm=runtime.mm)
    runtime.woz_gui_thread.start()
    if runtime.args.configure:
        print_debug_header("WAITING FOR WOZ PRE-MISSION CONFIG")
        start_conditions = runtime.woz_gui_thread.wait_for_start_conditions()
        runtime.mm.resume_start_conditions(start_conditions)
    else:
        runtime.mm.resume_start_conditions(None)


def initialize_crash_saver(runtime: MissionRuntime) -> None:
    runtime.crash_saver_thread = CrashStateSaverThread(
        xpc=runtime.xpc,
        mm=runtime.mm,
        crash_dir=CRASHED_MISSION_FILES_DIR,
        save_interval_steps=get_config()["system"]["crash_save_interval_steps"],
    )
    runtime.crash_saver_thread.start()
    print("[CrashStateSaver] Background saver initialized")


def cleanup_runtime(runtime: MissionRuntime) -> None:
    if runtime.cleaned_up:
        return

    runtime.cleaned_up = True
    print(f"\n[Cleanup] Cleaning up mission resources for fire layout {runtime.selection.fire_layout}...")

    if runtime.fm:
        runtime.fm.plot()

    if runtime.voice_stop_event:
        runtime.voice_stop_event.set()

    if runtime.crash_saver_thread:
        print("[Cleanup] Stopping crash state saver thread...")
        runtime.crash_saver_thread.stop()

    if runtime.woz_gui_thread:
        print("[Cleanup] Stopping WoZ GUI thread...")
        runtime.woz_gui_thread.stop()

    if runtime.combinedgui:
        print("[Cleanup] Closing combined GUI...")
        runtime.combinedgui.close()

    if runtime.msg_visualizer:
        print("[Cleanup] Closing message visualizer...")
        runtime.msg_visualizer.close()

    if runtime.dev_gui:
        print("[Cleanup] Closing dev GUI...")
        runtime.dev_gui.close()

    if runtime.logger:
        print("[Cleanup] Closing data logger...")
        runtime.logger.close()

    if runtime.timer:
        print("[Cleanup] Stopping timer...")
        runtime.timer.stop()

    if runtime.mm and hasattr(runtime.mm, "cleanup"):
        print("[Cleanup] Cleaning up mission manager...")
        runtime.mm.cleanup()

    print(f"[Cleanup] Cleanup complete for fire layout {runtime.selection.fire_layout}")


def process_runtime_step(runtime: MissionRuntime, dt: float) -> None:
    assert runtime.timer is not None
    assert runtime.mm is not None

    runtime.met = runtime.timer.get_mission_elapsed_time() - runtime.pause_time

    try:
        pause_state = runtime.xpc.getDREF("sim/time/paused")
    except Exception:
        print("Failed to get pause state, assuming false")
        pause_state = False

    if pause_state != 0:
        runtime.pause_time += dt
        return

    try:
        if runtime.args.verbose:
            print(f"\n========== STEP {runtime.step_count} (met = {runtime.met:.1f}s) ==========")
        runtime.done = runtime.mm.step(dt, runtime.met)
        runtime.step_count += 1
        if runtime.fm:
            runtime.fm.log_fps(runtime.step_count)
    except Exception as exc:
        print(f"ERROR IN MM.STEP: {exc}")
        traceback.print_exc()
        exception_info = {
            "error_message": str(exc),
            "error_type": type(exc).__name__,
            "traceback": traceback.format_exc(),
            "mission_timer": runtime.met,
            "step_count": runtime.mm.step_count if hasattr(runtime.mm, "step_count") else 0,
        }
        if runtime.crash_saver_thread:
            runtime.crash_saver_thread.request_save(runtime.met, runtime.step_count, exception_info)
        runtime.done = True

    update_woz_state(runtime)
    perform_state_saves(runtime)

    if runtime.crash_saver_thread:
        runtime.crash_saver_thread.request_save(runtime.met, runtime.step_count)

    if int(runtime.met) % (1 / runtime.args.log_hz) == 0 and runtime.logger:
        runtime.logger.log_step_data(runtime.mm.step_count)


def update_woz_state(runtime: MissionRuntime) -> None:
    if not runtime.woz_gui_thread or not runtime.mm:
        return

    try:
        runtime.woz_gui_thread.send_state_update(
            {
                "targets": [(t.id, t.status, t.lat, t.long) for t in runtime.mm.targets],
                "mission_timer": runtime.met,
                "step_count": runtime.mm.step_count,
            }
        )
    except Exception:
        pass

    try:
        for cmd in runtime.woz_gui_thread.get_pending_commands():
            should_kill = process_woz_command(runtime.mm, runtime.xpc, cmd)
            if should_kill:
                runtime.done = True
                break
    except Exception as exc:
        print(f"ERROR when running woz gui: {exc}")
        traceback.print_exc()


def perform_state_saves(runtime: MissionRuntime) -> None:
    runtime.steps_since_statesave += 1
    if runtime.steps_since_statesave <= 10 or runtime.mm is None:
        return

    try:
        save_crash_state(runtime.xpc, runtime.mm, CRASHED_MISSION_FILES_DIR, {})
        runtime.steps_since_statesave = 0
    except Exception as save_error:
        print(f"FAILED TO SAVE CRASH STATE: {save_error}")
        traceback.print_exc()


def run_mission_loop(runtime: MissionRuntime) -> None:
    assert runtime.timer is not None
    assert runtime.mm is not None

    print_debug_header("MISSION READY, UNPAUSE X-PLANE TO BEGIN")
    while (not runtime.done) and runtime.met <= runtime.mm.max_mission_time:
        dt = runtime.timer.get_dt_and_wait()
        process_runtime_step(runtime, dt)


def main() -> int:
    args = parse_args()
    runtime = initialize_runtime(args)

    try:
        run_mission_loop(runtime)
    except KeyboardInterrupt:
        print("\n[Run Mission] Keyboard interrupt received. Cleaning up...")
        return 0
    except Exception as exc:
        print(f"\n[Run Mission] Error occurred in mission {runtime.selection.fire_layout}: {exc}")
        traceback.print_exc()
        return 1
    finally:
        cleanup_runtime(runtime)

    return 0


if __name__ == "__main__":
    sys.exit(main())
