import wave

import xp
import time
import os

# ============================================================================
# SOUNDS - Play custom sounds at will
# ============================================================================

class SoundManager:
    """
    Manages sound playback with queueing, delays, and automatic duration calculation.

    Integrates with X-Plane's playPCMOnBus API to play WAV files without overlap.
    Sounds are queued and played sequentially. Supports delayed playback scheduling.
    """

    # TODO edit so that sounds are played on a loop

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
        self._process_queue()

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