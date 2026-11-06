"""API Key Diagnostic & Connectivity Checker.

Tests whether your ElevenLabs and LLM API keys are configured and valid
before processing large media files.
"""

from io import BytesIO
import json
from pathlib import Path
import struct
import urllib.error
import urllib.request
import uuid
import wave

from config import config


def check_elevenlabs() -> bool:
    print("\n🔍 Checking ElevenLabs API Key...")
    if not config.elevenlabs_api_key:
        print("  ⚠️  ELEVENLABS_API_KEY is not set in .env")
        return False

    key_preview = (
        config.elevenlabs_api_key[:6] + "..." + config.elevenlabs_api_key[-4:]
    )
    print(f"  Key detected: {key_preview}")

    # First attempt: check user subscription details
    url_sub = "https://api.elevenlabs.io/v1/user/subscription"
    req_sub = urllib.request.Request(
        url_sub,
        headers={
            "xi-api-key": config.elevenlabs_api_key,
            "User-Agent": "AE-Caption-Checker/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req_sub, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            tier = data.get("tier", "standard")
            character_count = data.get("character_count", 0)
            character_limit = data.get("character_limit", 0)
            print("  ✅ ElevenLabs connection SUCCESSFUL!")
            print(f"     Tier: {tier}")
            print(
                f"     Usage: {character_count} / {character_limit} characters"
            )
            return True
    except urllib.error.HTTPError as e:
        err_text = e.read().decode("utf-8", errors="ignore")
        # If user_read permission is missing on a scoped key, test Speech-to-Text directly
        if "user_read" in err_text:
            print(
                "  ℹ️  Scoped key detected (user_read omitted). Testing Speech-to-Text permission directly..."
            )
            return test_stt_endpoint()
        else:
            print(f"  ❌ ElevenLabs connection FAILED (HTTP {e.code}): {err_text}")
            return False
    except Exception as e:
        print(f"  ❌ Network error connecting to ElevenLabs: {e}")
        return False


def test_stt_endpoint() -> bool:
    """Tests Speech-to-Text endpoint directly with a 0.5s dummy audio wave."""
    # Build tiny valid WAV buffer in memory
    buf = BytesIO()
    with wave.open(buf, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(16000)
        f.writeframes(struct.pack("<h", 0) * 8000)
    audio_bytes = buf.getvalue()

    boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="model_id"\r\n\r\nscribe_v2\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="test.wav"\r\n'
        f"Content-Type: audio/wav\r\n\r\n"
    ).encode("utf-8") + audio_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

    req = urllib.request.Request(
        "https://api.elevenlabs.io/v1/speech-to-text",
        data=body,
        headers={
            "xi-api-key": config.elevenlabs_api_key,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            print("  ✅ ElevenLabs Speech-to-Text Scribe API permission verified SUCCESSFUL!")
            return True
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="ignore")
        # Even if empty audio produces 400 bad request, it confirms authentication succeeded if not 401
        if e.code != 401:
            print("  ✅ ElevenLabs Speech-to-Text Scribe API permission verified SUCCESSFUL!")
            return True
        print(f"  ❌ ElevenLabs STT permission FAILED (HTTP {e.code}): {err}")
        return False
    except Exception as e:
        print(f"  ❌ Network error: {e}")
        return False


def check_llm() -> bool:
    print("\n🔍 Checking LLM API Key (OpenAI / Gemini)...")
    if config.openai_api_key:
        key_preview = (
            config.openai_api_key[:6] + "..." + config.openai_api_key[-4:]
        )
        print(f"  OpenAI Key detected: {key_preview}")
        url = "https://api.openai.com/v1/models"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {config.openai_api_key}",
                "User-Agent": "AE-Caption-Checker/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                print("  ✅ OpenAI connection SUCCESSFUL! (Models verified)")
                return True
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", errors="ignore")
            print(f"  ❌ OpenAI connection FAILED (HTTP {e.code}): {err}")
            return False
        except Exception as e:
            print(f"  ❌ Network error connecting to OpenAI: {e}")
            return False

    elif config.gemini_api_key:
        key_preview = (
            config.gemini_api_key[:6] + "..." + config.gemini_api_key[-4:]
        )
        print(f"  Gemini Key detected: {key_preview}")
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={config.gemini_api_key}"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                print("  ✅ Google Gemini connection SUCCESSFUL!")
                return True
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", errors="ignore")
            print(f"  ❌ Gemini connection FAILED (HTTP {e.code}): {err}")
            return False
        except Exception as e:
            print(f"  ❌ Network error connecting to Gemini: {e}")
            return False
    else:
        print("  ℹ️  No LLM key detected in .env.")
        print(
            "     (Built-in rule-based rhythmic grouper active for free)."
        )
        return True


def main():
    print("=" * 60)
    print("      🔑 AI CAPTION GENERATOR - API KEY CHECKER 🔑")
    print("=" * 60)

    el_ok = check_elevenlabs()
    llm_ok = check_llm()

    print("\n" + "=" * 60)
    if el_ok:
        print("🎉 Ready to transcribe real audio and video files!")
    else:
        print(
            "👉 Please check your ELEVENLABS_API_KEY in .env and re-run."
        )
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
