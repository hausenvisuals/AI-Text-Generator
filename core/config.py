"""Configuration module for AE AI Caption Generator.

Safely loads API keys and settings from environment variables or a local .env file.
Secrets are never logged or exposed.
"""

from dataclasses import dataclass
import os
from pathlib import Path
import ssl
from typing import Optional, Union
import urllib.error
import urllib.request


def get_ssl_context() -> ssl.SSLContext:
    """Returns an SSL context suitable for HTTPS requests, with fallback for macOS certificate issues."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass

    try:
        return ssl.create_default_context()
    except Exception:
        return ssl._create_unverified_context()


def safe_urlopen(req: Union[urllib.request.Request, str], timeout: int = 30):
    """Executes urllib.request.urlopen with auto-fallback to unverified SSL if macOS certificate verification fails."""
    ctx = get_ssl_context()
    try:
        return urllib.request.urlopen(req, context=ctx, timeout=timeout)
    except urllib.error.URLError as e:
        err_msg = str(e)
        if "CERTIFICATE_VERIFY_FAILED" in err_msg or "certificate verify failed" in err_msg:
            # Automatic fallback for macOS installations where Python certificates were not installed
            unverified_ctx = ssl._create_unverified_context()
            return urllib.request.urlopen(req, context=unverified_ctx, timeout=timeout)
        raise


def load_dotenv_file(filepath: Path) -> None:
    """Simple, zero-dependency .env loader."""
    if not filepath.exists():
        return
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                # Do not override existing environment variables
                if key not in os.environ and val:
                    os.environ[key] = val
    except Exception as e:
        print(f"[Warning] Could not parse .env file: {e}")


# Load .env from current directory or parent directory
_base_dir = Path(__file__).resolve().parent
load_dotenv_file(_base_dir / ".env")


@dataclass
class Config:
    # STT Keys & Settings
    elevenlabs_api_key: str = os.getenv("ELEVENLABS_API_KEY", "").strip()
    elevenlabs_model_id: str = os.getenv("ELEVENLABS_MODEL_ID", "scribe_v2").strip()

    # LLM Keys & Settings
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "").strip()
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "").strip()
    llm_model: str = os.getenv("LLM_MODEL", "gpt-4o-mini").strip()

    # Caption Grouping Constraints
    target_words_min: int = int(os.getenv("TARGET_WORDS_MIN", "3"))
    target_words_max: int = int(os.getenv("TARGET_WORDS_MAX", "5"))
    max_words_tolerance: int = int(os.getenv("MAX_WORDS_TOLERANCE", "7"))
    min_words_tolerance: int = int(os.getenv("MIN_WORDS_TOLERANCE", "1"))
    max_pause_seconds: float = float(os.getenv("MAX_PAUSE_SECONDS", "0.35"))

    # File Paths
    output_dir: Path = _base_dir / "output"
    test_data_dir: Path = _base_dir / "test_data"

    def has_elevenlabs_key(self) -> bool:
        return bool(self.elevenlabs_api_key)

    def has_llm_key(self) -> bool:
        return bool(self.openai_api_key or self.gemini_api_key)


# Global default configuration instance
config = Config()
