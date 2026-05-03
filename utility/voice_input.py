"""
Voice Input Manager for X-Plane Copilot

Manages voice input with multiple modes:
1. Push-to-Talk (PTT) mode - X-Plane dataref polling (custom/haato/mic_keyed)
2. Open Voice mode - Always listening with wake word detection
3. Enter key fallback - When X-Plane unavailable

Integrates with X-Plane dataref for PTT detection and UDP protocol for text display.
"""

import threading
import time
import os
import traceback
from datetime import datetime
from typing import Optional, Callable, Any
from enum import Enum

try:
    import speech_recognition as sr
except ImportError:
    sr = None

_WHISPER_AVIATION_PROMPT = (
    "Aviation radio communication. "
    "ICAO airport codes: KSAV, KORL, KMCO, KSVN, KLHW, KLAX, KSFO, KORD, KJFK, KEWR, KLGA, KPAO, KSQL, KNUQ. "
    "Navigation: VOR, ILS, DME, NDB, GPS, FMS, ATIS, SIGMET, PIREP, NOTAM, METAR, TAF. "
    "Runway two eight left, one zero right. Squawk code. "
    "Altitudes in feet, airspeed in knots, headings in degrees. "
    "Mixture, throttle, alternator, avionics, fuel, approach, departure."
)


class VoiceInputMode(str, Enum):
    """Voice input mode types"""
    PTT = "ptt"  # Push-to-talk: button press to activate
    OPEN_VOICE = "open_voice"  # Always listening
    ENTER_KEY = "enter_key"  # Fallback mode


class VoiceInputManager:
    """
    Manages voice input with X-Plane push-to-talk integration via dataref polling.

    Polls X-Plane dataref 'custom/haato/mic_keyed' for PTT state and handles
    speech recognition lifecycle synchronized with mic key state.
    Falls back to Enter key if X-Plane unavailable.

    Modes:
    - PTT (push-to-talk): Poll dataref for mic key state, record while keyed
    - Open Voice: Always listening, no button needed
    - Enter Key: Manual trigger (fallback when X-Plane unavailable)
    """
    MIC_KEYED_DREF = "custom/haato/mic_keyed"

    def __init__(
        self,
        xpc: Optional[Any] = None,
        udp_protocol: Optional[Any] = None,
        mode: VoiceInputMode = VoiceInputMode.PTT,
        timeout_sec: float = 15.0,
        phrase_time_limit_sec: float = 12.0,
        dataref_poll_interval: float = 0.05,
        verbose: bool = True,
        porcupine_access_key: Optional[str] = None,
        wake_word: str = "jarvis",
        porcupine_sensitivity: float = 0.5,
        use_porcupine: bool = True,
        whisper_model: str = "base",
        whisper_aviation_prompt: str = "",
    ):
        """
        Initialize voice input manager.

        Audio backends (speech_recognition, pvporcupine) are initialised internally;
        callers do not need to set them up beforehand.

        Args:
            xpc: X-Plane connection for dataref polling (required for PTT mode)
            udp_protocol: UDP protocol instance (used for text display)
            mode: Voice input mode (ptt, open_voice, or enter_key)
            timeout_sec: Maximum time to wait for speech to start (seconds)
            phrase_time_limit_sec: Maximum duration of a single phrase (seconds)
            dataref_poll_interval: Polling interval for mic_keyed dataref (seconds)
            verbose: Whether to print status messages
            porcupine_access_key: Picovoice access key for pvporcupine wake word detection
            wake_word: Wake word to listen for (e.g. 'jarvis', 'hey siri')
            porcupine_sensitivity: pvporcupine detection sensitivity (0.0-1.0)
            use_porcupine: Whether to prefer pvporcupine over speech_recognition fallback
        """
        # Validate PTT mode requirements
        if mode == VoiceInputMode.PTT and xpc is None:
            if verbose:
                print("    ⚠️ PTT mode requires xpc connection - falling back to Enter key mode")
            mode = VoiceInputMode.ENTER_KEY

        self.xpc = xpc
        self.udp_protocol = udp_protocol
        self.recognizer = None
        self.microphone = None
        self.mode = mode
        self.timeout_sec = timeout_sec
        self.phrase_time_limit_sec = phrase_time_limit_sec
        self.dataref_poll_interval = dataref_poll_interval
        self.verbose = verbose
        self.porcupine_access_key = porcupine_access_key
        self.wake_word = wake_word
        self.porcupine_sensitivity = porcupine_sensitivity
        self.use_porcupine = use_porcupine
        self.whisper_model = whisper_model
        self.whisper_aviation_prompt = whisper_aviation_prompt

        # State management
        self.listening_active = False
        self._cleanup_done = False
        self._wake_word_detector = None
        self._mic_poll_source_logged = False
        self.debug_audio_dir = os.path.join("logs", "voice_debug")

        # Initialise speech_recognition for voice modes
        if self.mode in (VoiceInputMode.PTT, VoiceInputMode.OPEN_VOICE):
            sr_ok = self._init_sr()
            if not sr_ok:
                if self.verbose:
                    print("    ⚠️ Voice recognition unavailable - falling back to Enter key mode")
                self.mode = VoiceInputMode.ENTER_KEY

        # Mode initialization messages
        if self.verbose:
            print(f'\n[VoiceInputManager] Starting...')
            print(f"    mode={self.mode.value}")
            print(f"    recognizer={'set' if self.recognizer else 'None'}, microphone={'set' if self.microphone else 'None'}")
            print(f"    xpc={'set' if self.xpc else 'None'}, udp_protocol={'set' if self.udp_protocol else 'None'}")
            print(f"    timeout_sec={self.timeout_sec}, phrase_time_limit_sec={self.phrase_time_limit_sec}")
            print(f"    use_porcupine={self.use_porcupine}, porcupine_access_key={'set' if self.porcupine_access_key else 'None'}, wake_word='{self.wake_word}', sensitivity={self.porcupine_sensitivity}")

        if self.mode == VoiceInputMode.PTT:
            if self.verbose:
                print(f"    ✓ Voice input: PTT mode (dataref polling)")
        elif self.mode == VoiceInputMode.OPEN_VOICE:
            if self.verbose:
                print(f"    ✓ Voice input: Open voice mode (always listening)")
            self._init_wake_word_detector()
            if self.verbose:
                detector_type = type(self._wake_word_detector).__name__ if self._wake_word_detector else 'None'
                print(f"    [VoiceInputManager] wake_word_detector={detector_type}")
        else:
            if self.verbose:
                print(f"    ℹ️ Voice input: Enter key fallback mode")

    def _init_sr(self) -> bool:
        """Try to initialise speech_recognition. Returns True on success."""
        if sr is None:
            if self.verbose:
                print("    ⚠️ speech_recognition not available")
            return False
        try:
            self.recognizer = sr.Recognizer()
        except Exception as e:
            if self.verbose:
                print(f"    ⚠️ Failed to create recognizer: {e}")
            return False
        try:
            self.microphone = sr.Microphone()
        except Exception as e:
            if self.verbose:
                print(f"    ⚠️ Microphone initialization failed: {e}")
            return False
        try:
            if self.verbose:
                print("    🎙️ Calibrating microphone for ambient noise...")
            with self.microphone as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=1)
            if self.verbose:
                print("    ✓ Microphone calibrated")
        except Exception as e:
            if self.verbose:
                print(f"    ⚠️ Microphone calibration failed (non-fatal): {e}")
            # Calibration failure is non-fatal
        return True

    def _init_wake_word_detector(self) -> None:
        """Initialize wake word detector: pvporcupine preferred, speech_recognition fallback."""

        if self.use_porcupine and self.porcupine_access_key:
            try:
                self._wake_word_detector = PorcupineWakeWordDetector(
                    access_key=self.porcupine_access_key,
                    wake_word=self.wake_word,
                    sensitivity=self.porcupine_sensitivity
                )
                print(f"    ✓ Wake word detector: pvporcupine (offline) - listening for '{self.wake_word}'")
                return
            except Exception as e:
                print(f"    ⚠️ pvporcupine unavailable ({e}) - falling back to speech_recognition")

        # Fallback: Google speech_recognition for wake word
        if self.recognizer and self.microphone:
            self._wake_word_detector = GoogleWakeWordDetector(
                recognizer=self.recognizer,
                microphone=self.microphone,
                wake_word=self.wake_word
            )
            print(f"    ✓ Wake word detector: speech_recognition (online fallback) - listening for '{self.wake_word}'")
        else:
            print(f"    ⚠️ No wake word detector available - OPEN_VOICE will listen immediately")

    def _poll_mic_keyed(self) -> bool:
        """
        Poll X-Plane dataref for mic keyed state.

        Returns:
            True if mic is keyed (1.0), False otherwise (0.0 or unavailable)
        """
        if self.xpc is None:
            print(f'[poll mic keyed] xpc is none, return')
            return False

        try:
            value = None
            poll_source = "getDREF"

            dref_cache = getattr(self.xpc, "current_dref_values", None)
            if isinstance(dref_cache, dict):
                cached_entry = dref_cache.get(self.MIC_KEYED_DREF)
                if isinstance(cached_entry, dict):
                    cached_value = cached_entry.get("value")
                    if cached_value is not None:
                        value = cached_value
                        poll_source = "subscribed"

            if value is None:
                value = self.xpc.getDREF(self.MIC_KEYED_DREF)

            if self.verbose and not self._mic_poll_source_logged:
                print(f"    [PTT Poll] mic_keyed source={poll_source}")
                self._mic_poll_source_logged = True

            return value >= 0.5  # Treat >= 0.5 as keyed (allows for float imprecision)
        except Exception as e:
            print(f"    [PTT Poll] WARNING error polling mic_keyed dataref: {e}")
            traceback.print_exc()
            return False

    def wait_for_pilot(self, timeout: Optional[float] = None) -> bool:
        """
        Block until pilot initiates communication.

        Behavior depends on mode:
        - PTT: Poll dataref for mic key state (or Enter key fallback)
        - Open Voice: Return immediately (always ready)
        - Enter Key: Wait for Enter key

        Args:
            timeout: Optional timeout in seconds (None = wait forever)

        Returns:
            True if pilot ready, False on timeout
        """

        # Open voice mode - use wake word detector if available
        if self.mode == VoiceInputMode.OPEN_VOICE:
            if self._wake_word_detector is None:
                return True  # No detector available, proceed immediately

            if self.verbose:
                print(f"\n👤 Waiting for wake word '{self.wake_word}'...")

            detected = threading.Event()

            def _detect():
                try:
                    if isinstance(self._wake_word_detector, PorcupineWakeWordDetector):
                        self._wake_word_detector.start()
                    self._wake_word_detector.listen_for_wake_word()
                    detected.set()
                except Exception:
                    detected.set()  # Unblock on error

            t = threading.Thread(target=_detect, daemon=True)
            t.start()
            result = detected.wait(timeout=timeout)

            try:
                if isinstance(self._wake_word_detector, PorcupineWakeWordDetector):
                    self._wake_word_detector.stop()
            except Exception:
                pass

            if result and self.verbose:
                print(f"    ✓ Wake word detected")
            return result

        # PTT mode with xpc available
        if self.mode == VoiceInputMode.PTT and self.xpc is not None:
            print(f"\n👤 Waiting for push-to-talk (mic key)...")

            # Poll dataref for mic keyed state
            start_time = time.time()
            last_mic_state = False

            while True:
                # Poll mic keyed dataref
                current_mic_state = self._poll_mic_keyed()

                # Detect transition from False → True (mic keyed)
                if current_mic_state and not last_mic_state:
                    if self.verbose:
                        print("    ✓ Mic keyed (dataref)")
                    return True

                last_mic_state = current_mic_state

                # Check for Enter key fallback (non-blocking)
                import sys
                if sys.platform == 'win32':
                    import msvcrt
                    if msvcrt.kbhit():
                        key = msvcrt.getch()
                        if key in [b'\r', b'\n']:
                            if self.verbose:
                                print("    ✓ Enter key pressed")
                            return True
                else:
                    import select
                    if select.select([sys.stdin], [], [], 0)[0]:
                        line = sys.stdin.readline()
                        if line:
                            if self.verbose:
                                print("    ✓ Enter key pressed")
                            return True

                # Check timeout
                if timeout and (time.time() - start_time) > timeout:
                    return False

                # Sleep before next poll
                time.sleep(self.dataref_poll_interval)

        # Enter key fallback mode
        else:
            print("\n👤 Press ENTER to speak to Otto (Ctrl+C to exit)...")
            try:
                input()
                return True
            except EOFError:
                return False

    def listen_until_release(self) -> str:
        """
        Capture voice and return transcription.

        Behavior depends on mode:
        - PTT: Record while button held, stop on release
        - Open Voice: Record with automatic silence detection
        - Enter Key: Record with automatic silence detection

        Returns:
            Transcribed text or empty string on error
        """
        if not self.recognizer or not self.microphone:
            print("    ✗ Voice recognition not available")
            return ""

        if self.verbose:
            if self.mode == VoiceInputMode.PTT:
                print("\n🎤 Listening... (release button when done)")
            else:
                print("\n🎤 Listening... (speak now)")

        self.listening_active = True
        transcribed_text = ""

        try:
            # Start recording
            with self.microphone as source:
                # For PTT mode with xpc, we need to handle mic key release
                if self.mode == VoiceInputMode.PTT and self.xpc is not None:
                    # Grace window: avoid a race where key-up happens between wait_for_pilot and capture start.
                    if not self._confirm_mic_still_keyed():
                        if self.verbose:
                            print("    [PTT Capture] Mic released before capture started")
                        return ""
                    # Use a custom listening strategy that checks for mic key release
                    audio = self._listen_with_button_release(source)
                else:
                    # Standard listening with timeout and phrase limit
                    audio = self.recognizer.listen(
                        source,
                        timeout=self.timeout_sec,
                        phrase_time_limit=self.phrase_time_limit_sec
                    )

                if audio is None:
                    if self.verbose:
                        print("    ℹ️ No audio captured")
                    return ""
                if self.mode == VoiceInputMode.PTT:
                    self._save_debug_audio(audio)

            # Transcribe
            if self.verbose:
                print("    🔄 Transcribing...")

            transcribed_text = self._transcribe_with_retry(audio)

            if transcribed_text:
                if self.verbose:
                    print(f"    ✓ Transcribed: \"{transcribed_text}\"")
            else:
                if self.verbose:
                    print("    ⚠️ Could not understand audio")

        except sr.WaitTimeoutError:
            if self.verbose:
                print("    ⚠️ No speech detected (timeout)")
        except sr.UnknownValueError:
            if self.verbose:
                print("    ⚠️ Could not understand audio")
        except sr.RequestError as e:
            if self.verbose:
                print(f"    ✗ Recognition service error: {e}")
        except Exception as e:
            if self.verbose:
                traceback.print_exc()
                print(f"    ✗ Unexpected error: {e}")
        finally:
            self.listening_active = False

        return transcribed_text

    def _save_debug_audio(self, audio: "sr.AudioData") -> None:
        """Save captured PTT audio to disk for debugging."""
        try:
            os.makedirs(self.debug_audio_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            out_path = os.path.join(self.debug_audio_dir, f"ptt_capture_{ts}.wav")
            with open(out_path, "wb") as f:
                f.write(audio.get_wav_data())
            if self.verbose:
                print(f"    [PTT Capture] Saved audio: {out_path}")
        except Exception as e:
            if self.verbose:
                print(f"    [PTT Capture] WARNING failed to save audio: {e}")

    def _listen_with_button_release(self, source) -> Optional['sr.AudioData']:
        """
        Custom listening that stops when mic key is released (dataref polling).

        Args:
            source: Microphone audio source

        Returns:
            AudioData or None if mic released before speech
        """
        # Record continuously while keyed; avoid artificial sleeps that create audio gaps.
        frames = []
        start_time = time.time()
        unkeyed_streak = 0
        unkeyed_threshold = 2  # Require consecutive unkeyed polls to treat as release.
        tail_chunks_after_release = 3  # Capture a short trailing tail after button release.

        if self.verbose:
            print(
                f"    [PTT Capture] stream={type(getattr(source, 'stream', None)).__name__}, "
                f"chunk={getattr(source, 'CHUNK', 'n/a')}, "
                f"sample_rate={getattr(source, 'SAMPLE_RATE', 'n/a')}, "
                f"sample_width={getattr(source, 'SAMPLE_WIDTH', 'n/a')}"
            )

        while True:
            if (time.time() - start_time) > self.phrase_time_limit_sec:
                break

            try:
                buffer = self._read_stream_chunk(source)
                frames.append(buffer)
            except Exception:
                break

            if self._poll_mic_keyed():
                unkeyed_streak = 0
                continue

            unkeyed_streak += 1
            if unkeyed_streak >= unkeyed_threshold:
                for _ in range(tail_chunks_after_release):
                    try:
                        frames.append(self._read_stream_chunk(source))
                    except Exception:
                        break
                break

        if not frames:
            if self.verbose:
                print("    [PTT Capture] No frames captured")
            return None

        # Convert frames to AudioData
        frame_data = b''.join(frames)
        min_bytes = int(getattr(source, "CHUNK", 0) * max(getattr(source, "SAMPLE_WIDTH", 0), 1))
        if len(frame_data) < max(min_bytes, 1):
            if self.verbose:
                print(
                    f"    [PTT Capture] Insufficient audio length: {len(frame_data)} bytes "
                    f"(min expected {max(min_bytes, 1)} bytes)"
                )
            return None
        audio_data = sr.AudioData(
            frame_data,
            source.SAMPLE_RATE,
            source.SAMPLE_WIDTH
        )

        return audio_data

    def _confirm_mic_still_keyed(self) -> bool:
        """Small grace window to verify mic key remains active at capture start."""
        attempts = 4
        for _ in range(attempts):
            if self._poll_mic_keyed():
                return True
            time.sleep(0.05)
        return False

    def _read_stream_chunk(self, source) -> bytes:
        """Read one chunk from stream with compatibility across stream backends."""
        stream = source.stream
        chunk_size = source.CHUNK
        try:
            return stream.read(chunk_size, exception_on_overflow=False)
        except TypeError:
            # Some stream implementations do not accept the overflow kwarg.
            return stream.read(chunk_size)
        except Exception as e:
            if self.verbose:
                print(f"    [PTT Capture] Stream read failed: {type(e).__name__}: {e}")
            raise

    def _transcribe_with_retry(self, audio: 'sr.AudioData', max_attempts: int = 2) -> str:
        """
        Transcribe audio with retry logic.

        Args:
            audio: AudioData to transcribe
            max_attempts: Maximum number of attempts

        Returns:
            Transcribed text or empty string on failure
        """
        for attempt in range(max_attempts):
            try:
                prompt = self.whisper_aviation_prompt or _WHISPER_AVIATION_PROMPT
                return self.recognizer.recognize_whisper(
                    audio,
                    model=self.whisper_model,
                    language="english",
                    initial_prompt=prompt,
                ).strip()
            except sr.UnknownValueError:
                if attempt < max_attempts - 1:
                    time.sleep(0.5)
                    continue
                return ""
            except sr.RequestError as e:
                if attempt < max_attempts - 1:
                    time.sleep(1.0)
                    continue
                raise
        return ""

    def cleanup(self) -> None:
        """Cleanup resources"""
        if self._cleanup_done:
            return

        if hasattr(self, '_wake_word_detector') and self._wake_word_detector is not None:
            if hasattr(self._wake_word_detector, 'cleanup'):
                try:
                    self._wake_word_detector.cleanup()
                except Exception:
                    pass

        self._cleanup_done = True


class PorcupineWakeWordDetector:
    """Wake word detector using Picovoice Porcupine (offline, accurate)"""

    def __init__(self, access_key, wake_word='jarvis', sensitivity=0.5):
        try:
            import pvporcupine
            from pvrecorder import PvRecorder
        except ImportError:
            raise ImportError(
                "Porcupine libraries not installed. Install with:\n"
                "  pip install pvporcupine pvrecorder"
            )

        self.wake_word = wake_word
        self.porcupine = pvporcupine.create(
            access_key=access_key,
            keywords=[wake_word],
            sensitivities=[sensitivity]
        )
        self.recorder = PvRecorder(
            device_index=-1,  # Use default microphone
            frame_length=self.porcupine.frame_length
        )

    def start(self):
        """Start the audio recorder"""
        self.recorder.start()

    def stop(self):
        """Stop the audio recorder"""
        self.recorder.stop()

    def listen_for_wake_word(self):
        """Blocking call that returns True when wake word detected"""
        while True:
            pcm = self.recorder.read()
            keyword_index = self.porcupine.process(pcm)
            if keyword_index >= 0:
                return True

    def cleanup(self):
        """Clean up resources"""
        if hasattr(self, 'recorder'):
            self.recorder.stop()
            self.recorder.delete()
        if hasattr(self, 'porcupine'):
            self.porcupine.delete()


class GoogleWakeWordDetector:
    """Wake word detector using Google Speech Recognition (online, fallback)"""

    def __init__(self, recognizer, microphone, wake_word='jarvis'):
        self.recognizer = recognizer
        self.microphone = microphone
        self.wake_word = wake_word.lower()

    def listen_for_wake_word(self):
        """Blocking call that returns True when wake word detected"""
        while True:
            try:
                with self.microphone as source:
                    # Short timeout for wake word detection
                    audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=2)

                text = self.recognizer.recognize_google(audio).lower()
                if self.wake_word in text:
                    return True
            except (sr.WaitTimeoutError, sr.UnknownValueError):
                # Keep listening
                continue
            except sr.RequestError as e:
                print(f"Wake word detection error: {e}")
                # Brief pause before retrying
                time.sleep(1)

