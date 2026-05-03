"""Local Piper TTS wrapper for copilot voice output."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import threading
import unicodedata
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, Match, Optional, Union


# ----------------------------
# Core pronunciation resources
# ----------------------------

NATO = {
    "A": "Alpha",
    "B": "Bravo",
    "C": "Charlie",
    "D": "Delta",
    "E": "Echo",
    "F": "Foxtrot",
    "G": "Golf",
    "H": "Hotel",
    "I": "India",
    "J": "Juliett",
    "K": "Kilo",
    "L": "Lima",
    "M": "Mike",
    "N": "November",
    "O": "Oscar",
    "P": "Papa",
    "Q": "Quebec",
    "R": "Romeo",
    "S": "Sierra",
    "T": "Tango",
    "U": "Uniform",
    "V": "Victor",
    "W": "Whiskey",
    "X": "X-ray",
    "Y": "Yankee",
    "Z": "Zulu",
}

DIGIT_WORD = {
    "0": "zero",
    "1": "one",
    "2": "two",
    "3": "three",
    "4": "four",
    "5": "five",
    "6": "six",
    "7": "seven",
    "8": "eight",
    "9": "nine",
}

DIGIT_WORD_RADIO = {
    **DIGIT_WORD,
    "9": "niner",
}

RUNWAY_SIDE = {
    "L": "left",
    "R": "right",
    "C": "center",
}

CARDINAL = {
    "N": "north",
    "S": "south",
    "E": "east",
    "W": "west",
    "NE": "northeast",
    "NW": "northwest",
    "SE": "southeast",
    "SW": "southwest",
}


# ----------------------------
# Number helpers
# ----------------------------

ONES = [
    "zero", "one", "two", "three", "four",
    "five", "six", "seven", "eight", "nine"
]
TEENS = [
    "ten", "eleven", "twelve", "thirteen", "fourteen",
    "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"
]
TENS = [
    "", "", "twenty", "thirty", "forty",
    "fifty", "sixty", "seventy", "eighty", "ninety"
]


def int_to_words(n: int) -> str:
    """Convert 0..999999 to plain English words."""
    if n < 0:
        return f"minus {int_to_words(-n)}"
    if n < 10:
        return ONES[n]
    if n < 20:
        return TEENS[n - 10]
    if n < 100:
        tens = TENS[n // 10]
        rem = n % 10
        return tens if rem == 0 else f"{tens} {ONES[rem]}"
    if n < 1000:
        hundreds = f"{ONES[n // 100]} hundred"
        rem = n % 100
        return hundreds if rem == 0 else f"{hundreds} {int_to_words(rem)}"
    if n < 1_000_000:
        thousands = f"{int_to_words(n // 1000)} thousand"
        rem = n % 1000
        return thousands if rem == 0 else f"{thousands} {int_to_words(rem)}"
    return str(n)


def digits_to_words(text: str, radio: bool = False) -> str:
    """Speak each digit individually."""
    mapping = DIGIT_WORD_RADIO if radio else DIGIT_WORD
    out = []
    for ch in text:
        if ch.isdigit():
            out.append(mapping[ch])
        elif ch == ".":
            out.append("point")
        elif ch == "/":
            out.append("slash")
        else:
            out.append(ch)
    return " ".join(token for token in out if token.strip())


def number_string_to_words(num_str: str) -> str:
    """Convert integer string like '4500' or '10,000' to plain English."""
    n = int(num_str.replace(",", ""))
    return int_to_words(n)


def heading_to_words(num_str: str) -> str:
    """
    Headings are typically read digit-by-digit.
    090 -> zero niner zero
    270 -> two seven zero
    """
    s = num_str.zfill(3)
    return " ".join(DIGIT_WORD_RADIO[d] for d in s)


def runway_number_to_words(num_str: str) -> str:
    """
    Runway numbers are spoken digit-by-digit.
    9  -> zero nine
    27 -> two seven
    36 -> three six
    """
    n = int(num_str)
    s = f"{n:02d}"
    return " ".join(DIGIT_WORD_RADIO[d] for d in s)


def altitude_to_words(num_str: str) -> str:
    """
    Altitudes are better as regular number words than digit-by-digit.
    4500 -> four thousand five hundred
    9500 -> nine thousand five hundred
    """
    return number_string_to_words(num_str)


def squawk_to_words(num_str: str) -> str:
    """Squawk codes are digit-by-digit."""
    s = re.sub(r"\D", "", num_str)
    return " ".join(DIGIT_WORD[d] for d in s)


def frequency_to_words(freq: str) -> str:
    """
    Frequencies are digit-by-digit with point, typically using niner.
    121.9 -> one two one point niner
    118.70 -> one one eight point seven zero
    """
    parts = []
    for ch in freq:
        if ch.isdigit():
            parts.append(DIGIT_WORD_RADIO[ch])
        elif ch == ".":
            parts.append("point")
    return " ".join(parts)


def ident_to_nato(ident: str) -> str:
    """
    Convert uppercase alphanumeric ident to NATO words + digits.
    KSAV  -> Kilo Sierra Alpha Victor
    HBU5  -> Hotel Bravo Uniform five
    """
    words = []
    for ch in ident:
        if ch.isalpha():
            words.append(NATO.get(ch.upper(), ch))
        elif ch.isdigit():
            words.append(DIGIT_WORD[ch])
        else:
            words.append(ch)
    return " ".join(words)


# ----------------------------
# Config
# ----------------------------

@dataclass
class NormalizerConfig:
    # Exact phrase overrides applied early, case-insensitive.
    exact_phrase_overrides: Dict[str, str] = field(default_factory=lambda: {
        "EMERGENCY": "emergency",
        "LAND NOW": "land now",
        "LAND IMMEDIATELY": "land immediately",
        "GO AROUND": "go around",
        "PULL UP": "pull up",
        "LOW FUEL": "low fuel",
        "ENGINE FAILURE": "engine failure",
        "MAYDAY": "mayday",
        "PAN-PAN": "pan pan",
        "PAN PAN": "pan pan",
        "TERRAIN": "terrain",
        "TRAFFIC": "traffic",
    })

    # Acronyms that are safer letter-by-letter.
    acronym_expansions: Dict[str, str] = field(default_factory=lambda: {
        "ATIS": "A T I S",
        "ATC": "A T C",
        "AWOS": "A W O S",
        "ASOS": "A S O S",
        "VFR": "V F R",
        "IFR": "I F R",
        "ILS": "I L S",
        "VOR": "V O R",
        "GPS": "G P S",
        "FMS": "F M S",
        "MFD": "M F D",
        "PFD": "P F D",
        "HSI": "H S I",
        "CDI": "C D I",
        "ADF": "A D F",
        "DME": "D M E",
        "TFR": "T F R",
        "CTAF": "C T A F",
        "FBO": "F B O",
        "RPM": "R P M",
        "EGT": "E G T",
        "CHT": "C H T",
        "OAT": "O A T",
        "MSL": "M S L",
        "AGL": "A G L",
        "ETA": "E T A",
        "ETE": "E T E",
        "PIC": "P I C",
        "SIC": "S I C",
    })

    # Spoken as words instead of letters.
    word_expansions: Dict[str, str] = field(default_factory=lambda: {
        "RNAV": "R NAV",
        "UNICOM": "UNICOM",
        "METAR": "METAR",
        "TAF": "TAF",
        "PIREP": "PIREP",
        "SIGMET": "SIGMET",
        "AIRMET": "AIRMET",
        "NOTAM": "NOTAM",
    })

    # Unit replacements.
    unit_replacements: Dict[str, str] = field(default_factory=lambda: {
        "kts": "knots",
        "kt": "knots",
        "nm": "nautical miles",
        "sm": "statute miles",
        "fpm": "feet per minute",
        "ft": "feet",
        "lbs": "pounds",
        "lb": "pound",
        "gal": "gallons",
        "mph": "miles per hour",
        "inhg": "inches of mercury",
        "mb": "millibars",
    })

    # Token-specific overrides for stubborn mispronunciations.
    custom_token_overrides: Dict[str, str] = field(default_factory=dict)

    # Words that look like all-caps idents but should not be NATO-ized.
    ident_exclusion_set: set[str] = field(default_factory=lambda: {
        "ATIS", "AWOS", "ASOS", "VFR", "IFR", "ILS", "VOR", "GPS", "FMS",
        "MFD", "PFD", "HSI", "CDI", "ADF", "DME", "TFR", "CTAF", "FBO",
        "RPM", "EGT", "CHT", "OAT", "MSL", "AGL", "ETA", "ETE", "PIC",
        "SIC", "RNAV", "METAR", "TAF", "PIREP", "SIGMET", "AIRMET",
        "NOTAM", "UNICOM", "RWY", "FL", "RICH", "ATC"
    })


# ----------------------------
# Main normalizer
# ----------------------------

class AviationTTSNormalizer:
    def __init__(self, config: Optional[NormalizerConfig] = None) -> None:
        self.config = config or NormalizerConfig()

        # Precompile patterns.
        self._re_whitespace = re.compile(r"\s+")
        self._re_exact_boundary = lambda term: re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)

        # Frequencies: 118.7, 121.90, 122.8 MHz
        self._re_frequency = re.compile(
            r"\b(?P<freq>(?:1[1-3]\d)\.\d{1,3})(?:\s*MHz)?\b",
            re.IGNORECASE
        )

        # Flight levels: FL180
        self._re_flight_level = re.compile(r"\bFL\s*(?P<level>\d{2,3})\b", re.IGNORECASE)

        # Squawk 7700 / squawk code 1200
        self._re_squawk = re.compile(
            r"\b(squawk(?:\s+code)?)\s+(?P<code>\d{4})\b",
            re.IGNORECASE
        )

        # Headings / course / bearing
        self._re_heading = re.compile(
            r"\b(?P<label>heading|hdg|course|bearing)\s+(?P<deg>\d{1,3})\b",
            re.IGNORECASE
        )

        # Runways:
        # RWY 27, RWY 09L, runway 4R, expect 27L
        self._re_runway_keyword = re.compile(
            r"\b(?:RWY|runway)\s+(?P<num>\d{1,2})(?P<side>[LRC])?\b",
            re.IGNORECASE
        )

        # Standalone runway-like references after verbs/prepositions:
        # expect 27L, for 09, to 22R approach
        self._re_runway_contextual = re.compile(
            r"\b(?P<prefix>runway|rwy|expect|using|depart(?:ing)?|arrival|approach)\s+"
            r"(?P<num>\d{1,2})(?P<side>[LRC])?\b",
            re.IGNORECASE
        )

        # Altitudes with units
        self._re_altitude_ft = re.compile(
            r"\b(?P<alt>\d{1,5})\s*(?:ft|feet)\b",
            re.IGNORECASE
        )

        # Plain "at 4500" or "climb to 3000" patterns
        self._re_altitude_context = re.compile(
            r"\b(?P<label>at|to|climb to|descend to|maintain|leaving|cross at|crossing at)\s+"
            r"(?P<alt>\d{3,5})\b",
            re.IGNORECASE
        )

        # Wind groups like 270/15G25
        self._re_wind_compact = re.compile(
            r"\b(?P<dir>\d{3})/(?P<spd>\d{2,3})(?:G(?P<gust>\d{2,3}))?\b"
        )

        # ICAO-style airport codes: 4 uppercase letters
        self._re_icao = re.compile(r"\b([A-Z]{4})\b")

        # 3-5 uppercase alphanumeric idents containing at least one digit.
        self._re_alnum_ident = re.compile(r"\b(?=[A-Z0-9]{3,5}\b)(?=.*\d)[A-Z0-9]{3,5}\b")

        # Units
        self._re_unit = re.compile(
            r"\b(" + "|".join(sorted(map(re.escape, self.config.unit_replacements.keys()), key=len, reverse=True)) + r")\b",
            re.IGNORECASE
        )

        # Word-level expansions
        all_terms = list(self.config.acronym_expansions.keys()) + list(self.config.word_expansions.keys())
        self._re_known_terms = re.compile(
            r"\b(" + "|".join(sorted(map(re.escape, all_terms), key=len, reverse=True)) + r")\b",
            re.IGNORECASE
        )

        # Token override pattern
        if self.config.custom_token_overrides:
            self._re_custom_tokens = re.compile(
                r"\b(" + "|".join(sorted(map(re.escape, self.config.custom_token_overrides.keys()), key=len, reverse=True)) + r")\b",
                re.IGNORECASE
            )
        else:
            self._re_custom_tokens = None

    def normalize(self, text: str) -> str:
        """
        Main entry point.
        Order matters.
        """
        if not text:
            return text

        text = self._normalize_punctuation(text)
        text = self._apply_exact_phrase_overrides(text)
        text = self._apply_custom_token_overrides(text)

        # Structured numeric/token rules first.
        text = self._replace_frequencies(text)
        text = self._replace_flight_levels(text)
        text = self._replace_squawks(text)
        text = self._replace_headings(text)
        text = self._replace_runways(text)
        text = self._replace_wind_groups(text)
        text = self._replace_altitudes(text)

        # Acronyms/words/units.
        text = self._replace_known_terms(text)
        text = self._replace_units(text)

        # Identifier handling late, so ATIS/ILS/etc. have already been protected.
        text = self._replace_icao_idents(text)
        text = self._replace_alnum_idents(text)

        # Direction cleanup if isolated.
        text = self._replace_cardinals(text)

        # Final cleanup.
        text = self._cleanup(text)
        return text

    # ----------------------------
    # Normalization steps
    # ----------------------------

    def _normalize_punctuation(self, text: str) -> str:
        text = text.replace("\u2013", "-").replace("\u2014", "-")
        return text

    def _apply_exact_phrase_overrides(self, text: str) -> str:
        for src, dst in self.config.exact_phrase_overrides.items():
            text = self._re_exact_boundary(src).sub(dst, text)
        return text

    def _apply_custom_token_overrides(self, text: str) -> str:
        if not self._re_custom_tokens:
            return text

        def repl(match: Match[str]) -> str:
            token = match.group(0)
            return self.config.custom_token_overrides.get(token, self.config.custom_token_overrides.get(token.upper(), token))

        return self._re_custom_tokens.sub(repl, text)

    def _replace_frequencies(self, text: str) -> str:
        def repl(match: Match[str]) -> str:
            freq = match.group("freq")
            return frequency_to_words(freq)
        return self._re_frequency.sub(repl, text)

    def _replace_flight_levels(self, text: str) -> str:
        def repl(match: Match[str]) -> str:
            level = match.group("level")
            spoken = " ".join(DIGIT_WORD[d] for d in level)
            return f"flight level {spoken}"
        return self._re_flight_level.sub(repl, text)

    def _replace_squawks(self, text: str) -> str:
        def repl(match: Match[str]) -> str:
            label = match.group(1)
            code = match.group("code")
            return f"{label} {squawk_to_words(code)}"
        return self._re_squawk.sub(repl, text)

    def _replace_headings(self, text: str) -> str:
        def repl(match: Match[str]) -> str:
            label = match.group("label")
            deg = match.group("deg")
            return f"{label} {heading_to_words(deg)}"
        return self._re_heading.sub(repl, text)

    def _replace_runways(self, text: str) -> str:
        def runway_phrase(num: str, side: Optional[str]) -> str:
            spoken = runway_number_to_words(num)
            if side:
                spoken += f" {RUNWAY_SIDE[side.upper()]}"
            return f"runway {spoken}"

        def repl_keyword(match: Match[str]) -> str:
            return runway_phrase(match.group("num"), match.group("side"))

        text = self._re_runway_keyword.sub(repl_keyword, text)

        def repl_context(match: Match[str]) -> str:
            prefix = match.group("prefix")
            num = match.group("num")
            side = match.group("side")
            return f"{prefix} {runway_phrase(num, side)}"

        text = self._re_runway_contextual.sub(repl_context, text)
        return text

    def _replace_wind_groups(self, text: str) -> str:
        def repl(match: Match[str]) -> str:
            direction = heading_to_words(match.group("dir"))
            speed = " ".join(DIGIT_WORD[d] for d in match.group("spd"))
            gust = match.group("gust")
            if gust:
                gust_words = " ".join(DIGIT_WORD[d] for d in gust)
                return f"wind {direction} at {speed} gust {gust_words}"
            return f"wind {direction} at {speed}"
        return self._re_wind_compact.sub(repl, text)

    def _replace_altitudes(self, text: str) -> str:
        def repl_ft(match: Match[str]) -> str:
            alt = match.group("alt")
            return f"{altitude_to_words(alt)} feet"

        text = self._re_altitude_ft.sub(repl_ft, text)

        def repl_context(match: Match[str]) -> str:
            label = match.group("label")
            alt = match.group("alt")
            value = int(alt)
            if 300 <= value <= 60000:
                return f"{label} {altitude_to_words(alt)}"
            return match.group(0)

        text = self._re_altitude_context.sub(repl_context, text)
        return text

    def _replace_known_terms(self, text: str) -> str:
        def repl(match: Match[str]) -> str:
            token = match.group(0)
            upper = token.upper()
            if upper in self.config.acronym_expansions:
                return self.config.acronym_expansions[upper]
            if upper in self.config.word_expansions:
                return self.config.word_expansions[upper]
            return token
        return self._re_known_terms.sub(repl, text)

    def _replace_units(self, text: str) -> str:
        def repl(match: Match[str]) -> str:
            token = match.group(0)
            return self.config.unit_replacements[token.lower()]
        return self._re_unit.sub(repl, text)

    def _replace_icao_idents(self, text: str) -> str:
        def repl(match: Match[str]) -> str:
            token = match.group(1)
            if token in self.config.ident_exclusion_set:
                return token
            return ident_to_nato(token)
        return self._re_icao.sub(repl, text)

    def _replace_alnum_idents(self, text: str) -> str:
        def repl(match: Match[str]) -> str:
            token = match.group(0)
            if token in self.config.ident_exclusion_set:
                return token
            return ident_to_nato(token)
        return self._re_alnum_ident.sub(repl, text)

    def _replace_cardinals(self, text: str) -> str:
        # Restrict to multi-letter cardinals so acronym expansions like "A T I S" stay intact.
        for src, dst in sorted(
            ((src, dst) for src, dst in CARDINAL.items() if len(src) > 1),
            key=lambda x: len(x[0]),
            reverse=True,
        ):
            text = re.sub(rf"\b{re.escape(src)}\b", dst, text)
        return text

    def _cleanup(self, text: str) -> str:
        # Remove duplicate "runway runway" in odd overlaps.
        text = re.sub(r"\brunway\s+runway\b", "runway", text, flags=re.IGNORECASE)

        # Collapse whitespace.
        text = self._re_whitespace.sub(" ", text).strip()

        # Clean spaces before punctuation.
        text = re.sub(r"\s+([,.;:!?])", r"\1", text)
        return text

try:
    import pyaudio
except ImportError:  # pragma: no cover - optional dependency in tests
    pyaudio = None

try:
    import winsound
except ImportError:  # pragma: no cover - non-Windows fallback
    winsound = None


_PIPER_NORMALIZER = AviationTTSNormalizer(NormalizerConfig())
_DEFAULT_SAMPLE_RATE = 22050
_PCM_WIDTH_BYTES = 2
_PCM_CHANNELS = 1
_STREAM_CHUNK_SIZE = 4096


def sanitize_tts_text(text: str) -> str:
    """Normalize cockpit text into speech-friendly aviation phrasing for Piper."""
    sanitized = str(text or "").strip()
    if not sanitized:
        return ""

    sanitized = re.sub(r"(?<=\d)\s*%", " percent", sanitized)
    sanitized = re.sub(r"(?<=\d)\s*[Â°Âº]", " degrees", sanitized)
    sanitized = re.sub(r"(?i)\b(\d+(?:\.\d+)?)\s*m\b", r"\1 meters", sanitized)

    normalized = unicodedata.normalize("NFKD", sanitized)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    if not ascii_text:
        return ""

    return _PIPER_NORMALIZER.normalize(ascii_text)


class PiperTTSVoice:
    """Serialize Piper synthesis + local playback for copilot speech."""

    def __init__(
        self,
        model_path: Optional[Union[Path, str]] = None,
        voice_dir: Optional[Union[Path, str]] = None,
        model_name: str = "en_US-hfc_male-medium.onnx",
        length_scale: float = 0.8,
        noise_scale: float = 0.6,
        noise_w: float = 0.8,
        logger: Optional[Any] = None,
    ) -> None:
        base_dir = Path(voice_dir) if voice_dir is not None else Path("./piper_voices")
        resolved_model_path = Path(model_path) if model_path is not None else (base_dir / model_name)

        self.voice_dir = base_dir
        self.model_path = resolved_model_path
        self.model_name = model_name
        self.length_scale = length_scale
        self.noise_scale = noise_scale
        self.noise_w = noise_w
        self.logger = logger
        self._speak_lock = threading.Lock()
        self._playback_lock = threading.Lock()
        self._closed = False
        self._stop_requested = False
        self._active_process: Optional[subprocess.Popen] = None
        self._active_audio: Optional[Any] = None
        self._active_stream: Optional[Any] = None

    def is_available(self) -> bool:
        """Return True when Piper binary, model, and streaming playback support exist."""
        return not self._closed and self._can_synthesize() and self._has_stream_playback_support()

    def speak(self, text: str) -> bool:
        """Synthesize text via Piper and stream it locally."""
        raw_text = str(text or "").strip()
        if not raw_text or self._closed:
            return False
        tts_text = sanitize_tts_text(raw_text)

        if not self.is_available():
            self._log_event(
                "agent_voice_unavailable",
                {
                    "has_piper": shutil.which("piper") is not None,
                    "resolved_piper": str(self._resolve_piper_executable()),
                    "model_path": str(self.model_path),
                    "model_exists": self.model_path.exists(),
                    "has_pyaudio": pyaudio is not None,
                },
            )
            return False

        with self._speak_lock:
            self._stop_requested = False
            try:
                self._log_event(
                    "agent_voice_speak",
                    {
                        "text_length": len(tts_text),
                        "model_path": str(self.model_path),
                    },
                )
                return self._stream_speech_unlocked(tts_text)
            except Exception as exc:
                self._log_error("agent_voice_error", f"Piper playback failed: {exc}")
                return False
            finally:
                self._stop_requested = False

    def stop(self) -> None:
        """Stop any in-progress local playback when supported."""
        self._stop_requested = True

        with self._playback_lock:
            process = self._active_process
            stream = self._active_stream
            audio = self._active_audio
            self._active_process = None
            self._active_stream = None
            self._active_audio = None

        if process is not None:
            try:
                process.terminate()
            except Exception:
                pass

        if stream is not None:
            try:
                stream.stop_stream()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass

        if audio is not None:
            try:
                audio.terminate()
            except Exception:
                pass

        if winsound is not None:
            try:
                winsound.PlaySound(None, 0)
            except Exception:
                pass

    def close(self) -> None:
        """Release the voice service."""
        self._closed = True
        self.stop()

    def generate_wav(self, text: str, output_path: Optional[Union[Path, str]]) -> bool:
        """Generate a WAV file for later reuse without playing it immediately."""
        raw_text = str(text or "").strip()
        if not raw_text or self._closed or output_path is None:
            return False

        tts_text = sanitize_tts_text(raw_text)
        if not self._can_synthesize():
            self._log_event(
                "agent_voice_unavailable",
                {
                    "has_piper": shutil.which("piper") is not None,
                    "resolved_piper": str(self._resolve_piper_executable()),
                    "model_path": str(self.model_path),
                    "model_exists": self.model_path.exists(),
                    "has_pyaudio": pyaudio is not None,
                },
            )
            return False

        target_path = Path(output_path)
        with self._speak_lock:
            try:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                if not self._synthesize_to_file(tts_text, target_path):
                    return False

                self._log_event(
                    "agent_voice_asset_generated",
                    {
                        "text_length": len(tts_text),
                        "model_path": str(self.model_path),
                        "output_path": str(target_path),
                    },
                )
                return True
            except Exception as exc:
                self._log_error("agent_voice_error", f"Piper asset generation failed: {exc}")
                return False

    def play_wav(self, wav_path: Optional[Union[Path, str]]) -> bool:
        """Play an existing WAV file via the local audio device."""
        if self._closed or wav_path is None:
            return False

        target_path = Path(wav_path)
        if winsound is None or not target_path.exists():
            self._log_error(
                "agent_voice_error",
                "Pre-generated WAV unavailable for playback",
                {
                    "wav_path": str(target_path),
                    "exists": target_path.exists(),
                    "has_winsound": winsound is not None,
                },
            )
            return False

        with self._speak_lock:
            return self._play_wav_unlocked(target_path)

    def _can_synthesize(self) -> bool:
        return self._resolve_piper_executable() is not None and self.model_path.exists()

    @staticmethod
    def _has_stream_playback_support() -> bool:
        return pyaudio is not None

    def _synthesize_to_file(self, text: str, output_path: Path) -> bool:
        piper_executable = self._resolve_piper_executable()
        if piper_executable is None:
            self._log_error("agent_voice_error", "Piper executable could not be resolved")
            return False

        cmd = self._build_piper_command("--output_file", str(output_path))

        try:
            subprocess.run(
                cmd,
                input=text,
                text=True,
                capture_output=True,
                check=True,
            )
            return True
        except subprocess.CalledProcessError as exc:
            stderr_msg = exc.stderr.strip() if exc.stderr else "(no stderr)"
            print(f"[agent_voice] Piper synthesis failed (exit {exc.returncode}): {stderr_msg}", flush=True)
            self._log_error(
                "agent_voice_error",
                f"Piper synthesis failed: {exc}",
                {"stderr": exc.stderr.strip() if exc.stderr else ""},
            )
            return False

    def _stream_speech_unlocked(self, text: str) -> bool:
        piper_executable = self._resolve_piper_executable()
        if piper_executable is None or pyaudio is None:
            self._log_error("agent_voice_error", "Streaming playback is unavailable")
            return False

        cmd = self._build_piper_command("--output_raw")
        process = None
        audio = None
        stream = None
        stderr_output = ""
        wrote_audio = False

        try:
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
            if process.stdin is None or process.stdout is None or process.stderr is None:
                raise RuntimeError("Piper process streams were not available")

            audio = pyaudio.PyAudio()
            stream = audio.open(
                format=audio.get_format_from_width(_PCM_WIDTH_BYTES),
                channels=_PCM_CHANNELS,
                rate=self._resolve_sample_rate(),
                output=True,
                frames_per_buffer=_STREAM_CHUNK_SIZE,
            )
            self._set_active_playback(process=process, audio=audio, stream=stream)

            process.stdin.write((text + "\n").encode("utf-8"))
            process.stdin.close()

            while not self._stop_requested:
                chunk = process.stdout.read(_STREAM_CHUNK_SIZE)
                if not chunk:
                    break
                wrote_audio = True
                stream.write(chunk)

            stderr_output = process.stderr.read().decode("utf-8", errors="replace").strip()
            return_code = process.wait()
            if self._stop_requested:
                return False
            if return_code != 0:
                print(f"[agent_voice] Piper synthesis failed (exit {return_code}): {stderr_output or '(no stderr)'}", flush=True)
                self._log_error(
                    "agent_voice_error",
                    f"Piper synthesis failed with exit {return_code}",
                    {"stderr": stderr_output},
                )
                return False
            if not wrote_audio:
                print("[agent_voice] speak() aborted: Piper produced no audio stream", flush=True)
                return False
            return True
        finally:
            self._clear_active_playback(process=process, audio=audio, stream=stream)
            if stream is not None:
                try:
                    stream.stop_stream()
                except Exception:
                    pass
                try:
                    stream.close()
                except Exception:
                    pass
            if audio is not None:
                try:
                    audio.terminate()
                except Exception:
                    pass
            if process is not None:
                if process.stdin is not None and not process.stdin.closed:
                    try:
                        process.stdin.close()
                    except Exception:
                        pass
                if process.stdout is not None:
                    try:
                        process.stdout.close()
                    except Exception:
                        pass
                if process.stderr is not None:
                    try:
                        process.stderr.close()
                    except Exception:
                        pass
                if process.poll() is None:
                    try:
                        process.terminate()
                    except Exception:
                        pass

    def _build_piper_command(self, output_flag: str, output_value: Optional[str] = None) -> list[str]:
        piper_executable = self._resolve_piper_executable()
        if piper_executable is None:
            raise RuntimeError("Piper executable is unavailable")

        cmd = [
            str(piper_executable),
            "--model",
            str(self.model_path),
            "--length_scale",
            str(self.length_scale),
            "--noise_scale",
            str(self.noise_scale),
            "--noise_w",
            str(self.noise_w),
            output_flag,
        ]
        if output_value is not None:
            cmd.append(output_value)
        return cmd

    def _resolve_sample_rate(self) -> int:
        config_path = Path(str(self.model_path) + ".json")
        try:
            config_bytes = config_path.read_bytes()
            config = json.loads(config_bytes.decode("utf-8", errors="ignore"))
            sample_rate = int(config.get("audio", {}).get("sample_rate", _DEFAULT_SAMPLE_RATE))
            return sample_rate if sample_rate > 0 else _DEFAULT_SAMPLE_RATE
        except Exception:
            return _DEFAULT_SAMPLE_RATE

    def _set_active_playback(self, process: Any, audio: Any, stream: Any) -> None:
        with self._playback_lock:
            self._active_process = process
            self._active_audio = audio
            self._active_stream = stream

    def _clear_active_playback(self, process: Any, audio: Any, stream: Any) -> None:
        with self._playback_lock:
            if self._active_process is process:
                self._active_process = None
            if self._active_audio is audio:
                self._active_audio = None
            if self._active_stream is stream:
                self._active_stream = None

    @staticmethod
    def _resolve_piper_executable() -> Optional[Path]:
        direct_path = shutil.which("piper")
        if direct_path:
            return Path(direct_path)

        executable_dir = Path(sys.executable).resolve().parent
        candidates = ("piper.exe", "piper")
        for candidate in candidates:
            candidate_path = executable_dir / candidate
            if candidate_path.exists():
                return candidate_path
        return None

    def _play_wav_unlocked(self, wav_path: Path) -> bool:
        try:
            winsound.PlaySound(str(wav_path), winsound.SND_FILENAME)
            return True
        except Exception as exc:
            self._log_error(
                "agent_voice_error",
                f"Piper playback failed: {exc}",
                {"wav_path": str(wav_path)},
            )
            return False

    def _log_event(self, event_type: str, data: dict) -> None:
        if self.logger is not None:
            try:
                self.logger.log_event(event_type, data)
            except Exception:
                pass

    def _log_error(self, error_type: str, error_message: str, context: Optional[dict] = None) -> None:
        if self.logger is not None:
            try:
                self.logger.log_error(error_type, error_message, context)
            except Exception:
                pass
