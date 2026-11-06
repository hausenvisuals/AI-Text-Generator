"""Modular Speech-to-Text (STT) service with word-level timestamps.

Supports:
1. ElevenLabs Scribe API (model: scribe_v2)
2. MockSTTProvider (for offline testing & cost-free development)
3. Audio extraction from common video files using macOS built-in afconvert.
"""

from abc import ABC, abstractmethod
import aifc
from dataclasses import asdict, dataclass
import json
import math
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile
from typing import Any, Dict, List, Optional, Tuple
import urllib.error
import urllib.parse
import urllib.request
import uuid
import wave

from config import config, safe_urlopen

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".aif", ".aiff"}


@dataclass
class WordToken:
    """Represents a single transcribed word with start and end timestamps in seconds."""

    text: str
    start: float
    end: float
    index: int = 0
    rms_db: float = 0.0
    emphasis_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def extract_waveform_samples(audio_path: Path) -> Tuple[List[float], int]:
    """Reads audio samples from WAV or AIFF (converting via afconvert if necessary)
    and returns normalized mono float samples (-1.0 to 1.0) along with the sample rate.
    """
    if not audio_path.exists():
        return [], 44100

    suffix = audio_path.suffix.lower()
    temp_wav = None
    target_path = audio_path

    # If compressed or video format, convert to uncompressed 16-bit PCM WAV first
    if suffix not in {".wav", ".aif", ".aiff"}:
        temp_wav = Path(tempfile.gettempdir()) / f"acoustic_{uuid.uuid4().hex[:8]}.wav"
        cmd = [
            "/usr/bin/afconvert",
            "-f",
            "WAVE",
            "-d",
            "LEI16@44100",
            "-c",
            "1",
            str(audio_path),
            str(temp_wav),
        ]
        try:
            subprocess.run(cmd, capture_output=True, check=True)
            target_path = temp_wav
        except Exception:
            return [], 44100

    try:
        if target_path.suffix.lower() in {".aif", ".aiff"}:
            reader = aifc.open(str(target_path), "r")
            endian = ">"
        else:
            reader = wave.open(str(target_path), "r")
            endian = "<"

        with reader as af:
            n_channels = af.getnchannels()
            sampwidth = af.getsampwidth()
            framerate = af.getframerate()
            n_frames = af.getnframes()
            raw_data = af.readframes(n_frames)

        if sampwidth == 2:
            fmt = f"{endian}{n_frames * n_channels}h"
            samples = struct.unpack(fmt, raw_data)
            max_val = 32768.0
        elif sampwidth == 1:
            fmt = f"{n_frames * n_channels}B"
            samples = [s - 128 for s in struct.unpack(fmt, raw_data)]
            max_val = 128.0
        else:
            return [], framerate

        if n_channels == 2:
            mono = [(samples[i] + samples[i + 1]) / (2.0 * max_val) for i in range(0, len(samples), 2)]
        else:
            mono = [s / max_val for s in samples]

        return mono, framerate
    except Exception:
        return [], 44100
    finally:
        if temp_wav and temp_wav.exists():
            try:
                temp_wav.unlink()
            except Exception:
                pass


def enrich_tokens_with_audio_acoustics(
    tokens: List[WordToken], audio_path: Path
) -> List[WordToken]:
    """Analyzes audio waveform to compute RMS dB volume, duration elongation,
    and a composite acoustic emphasis score for each word token.
    """
    if not tokens or not audio_path or not audio_path.exists():
        return tokens

    samples, framerate = extract_waveform_samples(audio_path)
    if not samples or framerate <= 0:
        return tokens

    total_samples = len(samples)
    word_dbs: List[float] = []

    for t in tokens:
        s_idx = max(0, min(total_samples, int(t.start * framerate)))
        e_idx = max(0, min(total_samples, int(t.end * framerate)))
        w_s = samples[s_idx:e_idx]
        dur = max(0.01, t.end - t.start)
        if w_s:
            rms = math.sqrt(sum(s**2 for s in w_s) / max(1, len(w_s)))
            db = 20 * math.log10(rms + 1e-6)
        else:
            db = -60.0
        word_dbs.append(db)

    # Compute mean and standard deviation for Z-score normalization
    mean_db = sum(word_dbs) / max(1, len(word_dbs))
    variance = sum((d - mean_db) ** 2 for d in word_dbs) / max(1, len(word_dbs))
    std_db = math.sqrt(variance) or 1.0

    for i, t in enumerate(tokens):
        dur = max(0.01, t.end - t.start)
        clean_len = max(2, len(re.sub(r"[^\w]", "", t.text)))
        elongation = dur / (clean_len * 0.045 + 0.08)

        pause_before = max(0.0, t.start - tokens[i - 1].end) if i > 0 else 0.0
        pause_after = (
            max(0.0, tokens[i + 1].start - t.end) if i < len(tokens) - 1 else 0.0
        )

        db_z = (word_dbs[i] - mean_db) / std_db

        # Composite score: 45% volume/loudness, 35% elongation/stress, 20% cadence pause
        composite = (
            db_z * 0.45
            + min(2.5, elongation) * 0.35
            + min(2.0, (pause_before + pause_after) / 0.15) * 0.20
        )

        t.rms_db = round(word_dbs[i], 1)
        t.emphasis_score = round(composite, 2)

    return tokens


class STTError(Exception):
    """Custom exception for Speech-to-Text failures."""

    pass


def extract_audio_from_video(video_path: Path) -> Path:
    """Extracts audio from a video file using macOS built-in afconvert.

    Converts to 16-bit uncompressed WAV in a temporary directory.
    """
    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    temp_wav = Path(tempfile.gettempdir()) / f"extracted_{uuid.uuid4().hex[:8]}.wav"
    cmd = [
        "/usr/bin/afconvert",
        "-f",
        "WAVE",
        "-d",
        "LEI16@44100",
        "-c",
        "1",
        str(video_path),
        str(temp_wav),
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        if temp_wav.exists() and temp_wav.stat().st_size > 0:
            return temp_wav
        raise STTError(
            f"afconvert finished without creating valid audio: {result.stderr}"
        )
    except subprocess.CalledProcessError as e:
        # Fall back to passing the original file if afconvert cannot parse it
        print(
            f"[Notice] Built-in audio extraction warning: {e.stderr.strip()}. Attempting direct file upload."
        )
        return video_path
    except Exception as e:
        print(
            f"[Notice] Could not run afconvert ({e}). Proceeding with original file."
        )
        return video_path


class BaseSTTProvider(ABC):
    """Abstract interface for STT providers."""

    @abstractmethod
    def transcribe(self, file_path: Path) -> List[WordToken]:
        """Transcribe an audio or video file into a list of timestamped WordTokens."""
        pass


class MockSTTProvider(BaseSTTProvider):
    """Offline STT provider for testing without an API key or internet access.

    Returns realistic sentence words with accurate timestamps and natural pauses.
    """

    def __init__(self, custom_words: Optional[List[Dict[str, Any]]] = None):
        self.custom_words = custom_words

    def transcribe(self, file_path: Optional[Path] = None) -> List[WordToken]:
        if self.custom_words:
            raw_list = self.custom_words
        else:
            # Default realistic speech transcript with natural pauses and varying phrase lengths
            raw_list = [
                # Sentence 1: "Welcome back to our channel." (0.2s - 1.55s)
                {"text": "Welcome", "start": 0.20, "end": 0.55},
                {"text": "back", "start": 0.56, "end": 0.82},
                {"text": "to", "start": 0.83, "end": 0.95},
                {"text": "our", "start": 0.96, "end": 1.15},
                {"text": "channel.", "start": 1.16, "end": 1.55},
                # Pause: 1.55s to 2.10s (0.55s pause)
                # Sentence 2: "Today we are building an automated caption tool." (2.10s - 4.60s)
                {"text": "Today", "start": 2.10, "end": 2.45},
                {"text": "we", "start": 2.46, "end": 2.60},
                {"text": "are", "start": 2.61, "end": 2.75},
                {"text": "building", "start": 2.76, "end": 3.20},
                {"text": "an", "start": 3.21, "end": 3.32},
                {"text": "automated", "start": 3.33, "end": 3.85},
                {"text": "caption", "start": 3.86, "end": 4.25},
                {"text": "tool.", "start": 4.26, "end": 4.60},
                # Pause: 4.60s to 5.20s (0.60s pause)
                # Sentence 3: "It syncs text layers directly inside After Effects." (5.20s - 8.10s)
                {"text": "It", "start": 5.20, "end": 5.35},
                {"text": "syncs", "start": 5.36, "end": 5.75},
                {"text": "text", "start": 5.76, "end": 6.05},
                {"text": "layers", "start": 6.06, "end": 6.45},
                {"text": "directly", "start": 6.48, "end": 6.95},
                {"text": "inside", "start": 6.96, "end": 7.35},
                {"text": "After", "start": 7.36, "end": 7.65},
                {"text": "Effects.", "start": 7.66, "end": 8.10},
            ]

        tokens: List[WordToken] = []
        for i, item in enumerate(raw_list):
            tokens.append(
                WordToken(
                    text=str(item["text"]).strip(),
                    start=float(item["start"]),
                    end=float(item["end"]),
                    index=i,
                )
            )
        return tokens


class ElevenLabsSTTProvider(BaseSTTProvider):
    """Speech-to-Text provider utilizing the ElevenLabs Scribe API.

    API Endpoint: https://api.elevenlabs.io/v1/speech-to-text
    Model: scribe_v2
    """

    ENDPOINT = "https://api.elevenlabs.io/v1/speech-to-text"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_id: Optional[str] = None,
    ):
        self.api_key = api_key or config.elevenlabs_api_key
        self.model_id = model_id or config.elevenlabs_model_id

    def _build_multipart_payload(
        self,
        file_path: Path,
        fields: Dict[str, str],
        boundary: str,
    ) -> bytes:
        """Builds standard RFC 2046 multipart/form-data body using standard Python."""
        lines: List[bytes] = []

        # Add regular text fields
        for key, value in fields.items():
            lines.append(f"--{boundary}".encode("utf-8"))
            lines.append(
                f'Content-Disposition: form-data; name="{key}"'.encode("utf-8")
            )
            lines.append(b"")
            lines.append(value.encode("utf-8"))

        # Add binary file
        with open(file_path, "rb") as f:
            file_data = f.read()

        filename = file_path.name
        content_type = "audio/mpeg"
        if file_path.suffix.lower() == ".wav":
            content_type = "audio/wav"
        elif file_path.suffix.lower() == ".mp4":
            content_type = "video/mp4"

        lines.append(f"--{boundary}".encode("utf-8"))
        lines.append(
            f'Content-Disposition: form-data; name="file"; filename="{filename}"'.encode(
                "utf-8"
            )
        )
        lines.append(f"Content-Type: {content_type}".encode("utf-8"))
        lines.append(b"")
        lines.append(file_data)
        lines.append(f"--{boundary}--".encode("utf-8"))
        lines.append(b"")

        return b"\r\n".join(lines)

    def transcribe(self, file_path: Path) -> List[WordToken]:
        """Transcribe audio using ElevenLabs Scribe API."""
        if not self.api_key:
            raise STTError(
                "ElevenLabs API Key is missing. "
                "Please add ELEVENLABS_API_KEY to your .env file or environment."
            )

        target_file = Path(file_path)
        if not target_file.exists():
            raise FileNotFoundError(f"Input file not found: {target_file}")

        # Check if video extraction is warranted
        cleanup_temp = False
        if target_file.suffix.lower() in VIDEO_EXTENSIONS:
            extracted = extract_audio_from_video(target_file)
            if extracted != target_file:
                target_file = extracted
                cleanup_temp = True

        try:
            boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
            fields = {
                "model_id": self.model_id,
                "timestamps_granularity": "word",
                "diarize": "false",
            }

            payload = self._build_multipart_payload(
                target_file, fields, boundary
            )

            req = urllib.request.Request(
                self.ENDPOINT,
                data=payload,
                headers={
                    "xi-api-key": self.api_key,
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                    "User-Agent": "AE-AI-Caption-Generator/1.0",
                },
                method="POST",
            )

            with safe_urlopen(req, timeout=120) as resp:
                status_code = resp.getcode()
                response_text = resp.read().decode("utf-8")

            if status_code != 200:
                raise STTError(
                    f"ElevenLabs API responded with status {status_code}: {response_text}"
                )

            data = json.loads(response_text)
            return self._parse_elevenlabs_response(data)

        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            raise STTError(
                f"ElevenLabs HTTP {e.code} Error: {e.reason} - {err_body}"
            )
        except urllib.error.URLError as e:
            raise STTError(f"Network connection failed: {e.reason}")
        except json.JSONDecodeError as e:
            raise STTError(f"Invalid JSON returned from ElevenLabs API: {e}")
        finally:
            if cleanup_temp and target_file.exists():
                try:
                    target_file.unlink()
                except Exception:
                    pass

    def _parse_elevenlabs_response(
        self, data: Dict[str, Any]
    ) -> List[WordToken]:
        """Parses the 'words' array from ElevenLabs Scribe JSON response.

        Attaches trailing punctuation to preceding words so caption phrases remain natural.
        """
        raw_words = data.get("words", [])
        if not raw_words:
            raise STTError(
                "ElevenLabs transcription returned no words or empty transcript."
            )

        tokens: List[WordToken] = []
        token_index = 0

        for item in raw_words:
            item_type = item.get("type", "word")
            raw_text = item.get("text", "")

            # Filter out pure whitespace / spacing tokens
            if item_type == "spacing" or not raw_text.strip():
                continue

            # Skip audio events like (applause) if present
            if item_type == "audio_event":
                continue

            # If token is punctuation attached or standalone punctuation (e.g., "." or ",")
            # attach it to the previous word token if timestamps align
            stripped = raw_text.strip()
            if stripped in {".", ",", "!", "?", ";", ":", "-", "—"} and tokens:
                tokens[-1].text += stripped
                if "end" in item and item["end"] is not None:
                    tokens[-1].end = max(tokens[-1].end, float(item["end"]))
                continue

            start = float(item.get("start", 0.0))
            end = float(item.get("end", start + 0.1))

            tokens.append(
                WordToken(
                    text=stripped,
                    start=round(start, 3),
                    end=round(end, 3),
                    index=token_index,
                )
            )
            token_index += 1

        return tokens


def get_stt_provider(use_mock: bool = False) -> BaseSTTProvider:
    """Factory helper to obtain the configured STT provider."""
    if use_mock or not config.has_elevenlabs_key():
        return MockSTTProvider()
    return ElevenLabsSTTProvider()
