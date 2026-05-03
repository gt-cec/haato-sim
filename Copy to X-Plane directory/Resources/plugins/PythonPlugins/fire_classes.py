import xp
from XPPython3 import xpgl
from XPPython3.xpgl import Colors
from XPPython3.utils.datarefs import find_dataref
from XPPython3.utils import commands
from OpenGL import GL
import time
import random
import wave
import os


class RadioHandler:
    def __init__(self, gui, sound_manager):

        self.gui = gui
        self.sound_manager = sound_manager

        self.radio_call_frequency = 1.5 * 42 * 45 # Trigger a radio call every this many steps. About 42 steps per second
        self.steps_since_last_call = 0
        self.last_call_time = 0 # Timestamp of last call
        self.steps_since_last_repeat = 0
        self.minimum_response_time = 0.3 # Human needs to key mic at least this long to be considered a valid response
        self.repeat_frequency = 1.5 * 42 * 15 # How often to repeat a radio call already sent

        self.waiting_for_response = False
        self.last_call_type = None

        self.radio_call_names = [
            #'say_altitude',
            'say_fires_remaining',
            'say_status'
        ]
        self.radio_call_options = {
            #'say_altitude': 'Resources/plugins/HAATO_assets/lead1_airattack_sayaltitude.wav',
            'say_fires_remaining': 'Resources/plugins/HAATO_assets/lead1_airattack_sayremainingfires.wav',
            'say_status': 'Resources/plugins/HAATO_assets/lead1_airattack_saystatus.wav',
            'comm_check': 'Resources/plugins/HAATO_assets/comm_check.wav',
        }

        self.acknowledged_sound = 'Resources/plugins/HAATO_assets/acknowledged.wav'
        self.please_repeat_sound = 'Resources/plugins/HAATO_assets/please_repeat.wav'

        self.sim_paused_dataref = find_dataref("sim/time/paused")


    def act(self):
        if self.sim_paused_dataref.value == 0:
            if self.steps_since_last_call >= self.radio_call_frequency:
                self.trigger_radio_call()

                self.waiting_for_response = True
                self.steps_since_last_call = 0
                self.steps_since_last_repeat = 0

                self.gui.log_experiment_data({
                    'event_type': 'radio_call_triggered',
                    'radio_call_type': self.last_call_type,
                })

                return

            elif self.waiting_for_response:
                self.steps_since_last_repeat += 1

                if self.steps_since_last_repeat >= self.repeat_frequency:
                    self.repeat_radio_call()
                    self.steps_since_last_repeat = 0

            self.steps_since_last_call += 1
        return


    def trigger_radio_call(self):
        if random.random() <= 0.5:
            selected_radio_call = 'comm_check'
        else:
            selected_radio_call = random.choice(list(self.radio_call_names))
        self.sound_manager.play_sound(self.radio_call_options[selected_radio_call])
        self.last_call_time = time.time()
        self.last_call_type = selected_radio_call
        return f'[RadioHandler] Played radio call: {selected_radio_call}'


    def repeat_radio_call(self):
        selected_radio_call = self.last_call_type
        self.sound_manager.play_sound(self.radio_call_options[selected_radio_call])
        return f'[RadioHandler] Repeated radio call: {selected_radio_call}'


    def handle_response(self, length_of_transmission):
        """Called when main plugin detects response"""
        radio_call_type = self.last_call_type

        if length_of_transmission >= self.minimum_response_time:
            self.sound_manager.play_sound(self.acknowledged_sound)
            valid_response = True
            response_delay = time.time() - self.last_call_time
            self.waiting_for_response = False
        else:
            self.sound_manager.play_sound(self.please_repeat_sound)
            valid_response = False
            response_delay = 0

        return radio_call_type, valid_response, response_delay


class Target:
    """Target class"""
    def __init__(self, type, lat, long, alt, id):
        self.lat = lat  # Latitude
        self.long = long  # Longitude
        self.alt = alt
        self.id = id
        self.type = type  # moderate or severe

        self.status = 0.0 # 0.0 = not classified yet, 1.0 = classified, 2.0 = position marked, 3.0 = first drop route flown, 4.0 = second drop route flown

        #self.spotted = 0  # 0 or 1
        self.classification = None
        #self.handled = False
        #self.human_in_range_time = 0.0
        #self.progress = 0.0
        #self.wingman_in_range_time = 0.0
        #self.wingman_observation_time = 0.0  # Time wingman has observed a misclassified fire
        #self.handling_start_time = None
        #self.is_being_handled = False
        self.grid_position = None # (str) which grid the fire is inside

        self.initial_drop_route_complete = False
        self.refined_drop_route_complete = False

        self.route1_start = None
        self.route1_end = None
        self.route1_recorder = None  # 'human' or 'wingman'

        self.route2_start = None
        self.route2_end = None
        self.route2_recorder = None  # 'human' or 'agent'

        self.marked_position = None

class PositionRecording:
    def __init__(self, type, fire_id, position, timestamp, wingman_pos_at_time):
        self.unique_id = None
        self.fire_id = fire_id
        self.type = type # 'position', 'initial_route', or 'refined_route'
        self.sent_to_ground = False
        self.position = position
        self.timestamp = timestamp
        self.wingman_pos_at_time = wingman_pos_at_time

class RouteRecording:
    def __init__(self, type, fire_id, start_pos, timestamp):
        self.unique_id = None
        self.fire_id = fire_id
        self.type = type # 'initial', or 'refined'
        self.sent_to_ground = False
        self.start_pos = start_pos
        self.end_pos = None
        self.timestamp = timestamp
        self.trajectory_points = [start_pos]  # NEW: List of (lat, lon) tuples along the route


# ============================================================================
# SOUND MANAGER - Centralized Sound Playback with Queueing
# ============================================================================

# TODO consolidate with the souind manage in sounds.py
class SoundManager:
    """
    Manages sound playback with queueing, delays, and automatic duration calculation.

    Integrates with X-Plane's playPCMOnBus API to play WAV files without overlap.
    Sounds are queued and played sequentially. Supports delayed playback scheduling.
    """

    def __init__(self):
        """Initialize the SoundManager with empty queue and cache."""
        self.sound_queue = []  # List of (sound_path, scheduled_time) tuples
        self.duration_cache = {}  # {sound_path: duration_seconds}
        self.current_sound = None  # Currently playing sound path
        self.current_sound_started_at = None  # Start timestamp
        self.current_channel = None  # X-Plane audio channel reference

        xp.log("[SoundManager] Initialized")

    def play_sound(self, sound_path, delay=0):
        """
        Queue a sound for playback with optional delay.
        Args:
            sound_path (str): Path to WAV file
            delay (float): Delay in seconds before playing (default: 0)
        Returns:
            bool: True if sound was queued successfully
        """
        try:
            # Validate file exists
            if not os.path.exists(sound_path):
                xp.log(f"[SoundManager] ERROR: Sound file not found: {sound_path}")
                return False

            # Calculate scheduled time
            scheduled_time = time.time() + delay

            # Add to queue
            self.sound_queue.append((sound_path, scheduled_time))

            if delay > 0:
                xp.log(f"[SoundManager] Queued: {sound_path} (delay={delay:.2f}s, queue_length={len(self.sound_queue)})")
            else:
                xp.log(f"[SoundManager] Queued: {sound_path} (queue_length={len(self.sound_queue)})")

            # Try to process queue immediately
            self._process_queue()

            return True

        except Exception as e:
            xp.log(f"[SoundManager] ERROR queueing sound {sound_path}: {e}")
            import traceback
            xp.log(traceback.format_exc())
            return False

    def _process_queue(self):
        """
        Process the sound queue - play next sound if ready.
        Called after queueing a sound and after a sound finishes.
        """
        # Don't process if something is already playing
        if self.current_sound is not None:
            return

        # Don't process if queue is empty
        if not self.sound_queue:
            return

        # Check if first queued sound is ready to play
        sound_path, scheduled_time = self.sound_queue[0]

        if time.time() >= scheduled_time:
            # Remove from queue and play
            self.sound_queue.pop(0)
            self._play_sound_now(sound_path)
        # else: Not ready yet, wait for next process call

    def _play_sound_now(self, sound_path):
        """
        Play a sound immediately using X-Plane's PCM API.

        Args:
            sound_path (str): Path to WAV file
        """
        try:
            # Open and read WAV file
            w = wave.open(sound_path, 'rb')

            # Play via X-Plane API
            channel = xp.playPCMOnBus(
                w.readframes(w.getnframes()),
                bufferSize=w.getnframes() * w.getsampwidth() * w.getnchannels(),
                soundFormat=w.getsampwidth(),
                freqHz=w.getframerate(),
                numChannels=w.getnchannels(),
                loop=0,
                audioType=7,  # Sound effect audio bus
                callback=self._sound_callback,
                refCon=sound_path
            )

            w.close()

            # Track current sound
            self.current_sound = sound_path
            self.current_sound_started_at = time.time()
            self.current_channel = channel

            xp.log(f"[SoundManager] Now playing: {sound_path}")

        except Exception as e:
            xp.log(f"[SoundManager] ERROR playing sound {sound_path}: {e}")
            import traceback
            xp.log(traceback.format_exc())

            # Clear tracking so next sound can play
            self.current_sound = None
            self.current_sound_started_at = None
            self.current_channel = None

    def _sound_callback(self, refCon, status):
        """
        Called by X-Plane when a sound finishes playing.

        Args:
            refCon: Sound path (passed through from playPCMOnBus)
            status: Playback status code
        """
        xp.log(f"[SoundManager] Sound ended: '{refCon}' (status={status})")

        # Clear current sound tracking
        self.current_sound = None
        self.current_sound_started_at = None
        self.current_channel = None

        # Process next sound in queue
        #self._process_queue()

    def _get_wav_duration(self, sound_path):
        """
        Calculate WAV file duration in seconds.
        Results are cached to avoid repeated file I/O.

        Args:
            sound_path (str): Path to WAV file

        Returns:
            float: Duration in seconds, or 0.0 on error
        """
        # Check cache first
        if sound_path in self.duration_cache:
            return self.duration_cache[sound_path]

        try:
            # Calculate duration from WAV file
            with wave.open(sound_path, 'rb') as w:
                frames = w.getnframes()
                rate = w.getframerate()
                duration = frames / float(rate)

            # Cache result
            self.duration_cache[sound_path] = duration

            xp.log(f"[SoundManager] Cached duration for {sound_path}: {duration:.2f}s")

            return duration

        except Exception as e:
            xp.log(f"[SoundManager] ERROR calculating duration for {sound_path}: {e}")
            return 0.0

    def clear_queue(self):
        """
        Clear all pending sounds from the queue.
        Does not stop currently playing sound.
        """
        count = len(self.sound_queue)
        self.sound_queue.clear()
        xp.log(f"[SoundManager] Queue cleared ({count} sounds removed)")

    def get_queue_length(self):
        """
        Get number of sounds waiting in queue.

        Returns:
            int: Number of queued sounds (not including currently playing)
        """
        return len(self.sound_queue)

    def is_playing(self):
        """
        Check if a sound is currently playing.

        Returns:
            bool: True if sound is playing
        """
        return self.current_sound is not None

