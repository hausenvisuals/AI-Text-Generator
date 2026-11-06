#!/usr/bin/env python3
"""Main Entry Point for AI Caption Generator for Adobe After Effects.

Workflow:
1. Load audio/video input (or auto-render Work Area from After Effects).
2. Select Caption Grouping Mode: Single Word | Short (Default) | Long.
3. Transcribe words with word-level timestamps (ElevenLabs Scribe API or Mock).
4. Group words into natural caption phrases based on selected mode (OpenAI or Heuristic).
5. Apply timeline offset (e.g. comp.workAreaStart) to align with timeline.
6. Validate caption integrity (word order, timing, mode constraints).
7. Export structured JSON and optionally auto-import to After Effects.
"""

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, Optional

from config import config
from grouping_rules import GroupingMode
from grouping_service import (
    CaptionGroup,
    LLMGroupingService,
    bridge_caption_gaps,
    generate_srt,
    validate_caption_groups,
)
from stt_service import (
    BaseSTTProvider,
    ElevenLabsSTTProvider,
    MockSTTProvider,
    WordToken,
    enrich_tokens_with_audio_acoustics,
    get_stt_provider,
)


def print_banner():
    print("=" * 68)
    print("       🎬 AI CAPTION GENERATOR FOR ADOBE AFTER EFFECTS 🎬")
    print("=" * 68)


def format_timestamp(seconds: float) -> str:
    """Format seconds into MM:SS.mmm for readable terminal logs."""
    mins = int(seconds // 60)
    secs = seconds % 60
    return f"{mins:02d}:{secs:06.3f}"


def render_ae_workarea() -> Dict[str, Any]:
    """Instructs After Effects to render the active comp's Work Area audio."""
    jsx_script = (Path(__file__).parent / "render_workarea_audio.jsx").resolve()
    meta_json = Path("/tmp/ae_workarea_meta.json")
    if meta_json.exists():
        try:
            meta_json.unlink()
        except Exception:
            pass

    cmd = [
        "osascript",
        "-e",
        f'tell application id "com.adobe.AfterEffects.application" to DoScriptFile "{jsx_script}"',
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if not meta_json.exists():
        err_msg = res.stderr.strip() or res.stdout.strip()
        raise RuntimeError(
            f"Could not render Work Area audio from After Effects.\n"
            f"Please verify After Effects is open and has an active composition timeline.\nDetail: {err_msg}"
        )

    with open(meta_json, "r", encoding="utf-8") as f:
        meta = json.load(f)
    return meta


def trigger_ae_import() -> bool:
    """Triggers After Effects to run import_captions_to_ae.jsx to create text layers."""
    jsx_script = (Path(__file__).parent / "import_captions_to_ae.jsx").resolve()
    cmd = [
        "osascript",
        "-e",
        f'tell application id "com.adobe.AfterEffects.application" to DoScriptFile "{jsx_script}"',
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    return res.returncode == 0


def export_captions(
    input_file: Optional[Path] = None,
    mode: GroupingMode = GroupingMode.SHORT,
    use_mock: bool = False,
    time_offset: float = 0.0,
    output_path: Optional[Path] = None,
    force_heuristic: bool = False,
) -> Dict[str, Any]:
    """Stage 1: Render Work Area, transcribe audio, group words according to mode,

    and export to structured captions.json and captions.srt.
    """
    print_banner()
    print(f"🎯 Selected Caption Grouping Mode: [{mode.value}]")
    if time_offset != 0.0:
        print(f"⏱️  Applying Timeline Offset: +{time_offset:.3f}s (Work Area Start)")

    # Step 1: Initialize STT Provider
    tokens = None
    if use_mock or (input_file is None and not config.has_elevenlabs_key()):
        print("\n[Step 1/3] Speech-to-Text: Using Mock Speech Provider (Offline Mode)")
        stt_provider = MockSTTProvider()
        tokens = stt_provider.transcribe()
    else:
        print(f"\n[Step 1/3] Speech-to-Text: Processing file: {input_file}")
        if not input_file.exists():
            print(f"[Error] File not found: {input_file}")
            sys.exit(1)

        # Check local cache for identical file to avoid redundant API calls
        # Use content hash instead of just file size to avoid cache collisions
        import hashlib
        def _get_audio_content_hash(path: Path) -> str:
            h = hashlib.md5()
            with open(path, "rb") as f:
                h.update(f.read(65536))
                size = path.stat().st_size
                if size > 65536:
                    f.seek(max(0, size - 65536))
                    h.update(f.read(65536))
            return f"{size}_{h.hexdigest()[:8]}"

        try:
            content_sig = _get_audio_content_hash(input_file)
        except Exception:
            content_sig = str(input_file.stat().st_size)

        cache_file = config.output_dir / f".stt_{input_file.stem}_{content_sig}.json"
        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as cf:
                    cached_data = json.load(cf)
                tokens = [
                    WordToken(
                        text=t["text"],
                        start=t["start"],
                        end=t["end"],
                        index=i,
                    )
                    for i, t in enumerate(cached_data)
                ]
                print(f"✓ Reused cached transcription: {len(tokens)} words loaded.")
            except Exception:
                tokens = None

        if tokens is None:
            if not config.has_elevenlabs_key():
                print(
                    "[Notice] ELEVENLABS_API_KEY is not set in .env. Falling back to Mock Speech Data."
                )
                stt_provider = MockSTTProvider()
            else:
                print("[Notice] Connecting to ElevenLabs Scribe API...")
                stt_provider = ElevenLabsSTTProvider()

            tokens = stt_provider.transcribe(input_file)
            # Save cache
            try:
                config.output_dir.mkdir(parents=True, exist_ok=True)
                with open(cache_file, "w", encoding="utf-8") as cf:
                    json.dump([t.to_dict() for t in tokens], cf, indent=2)
            except Exception:
                pass

    print(f"✓ Transcribed {len(tokens)} words with timestamps.")

    # Step 1b: Enrich tokens with acoustic stress & volume energy from raw audio
    if input_file and input_file.exists():
        tokens = enrich_tokens_with_audio_acoustics(tokens, input_file)
        anchors = [t for t in tokens if getattr(t, "emphasis_score", 0.0) >= 1.2]
        if anchors:
            print(f"✓ Acoustic stress analysis: {len(anchors)} primary anchor words identified.")

    # Apply timeline offset so grouping and validation are synchronized to comp time
    if time_offset != 0.0:
        for t in tokens:
            t.start = round(t.start + time_offset, 3)
            t.end = round(t.end + time_offset, 3)

    if tokens:
        print(
            f"  First word: '{tokens[0].text}' at {tokens[0].start:.3f}s timeline"
        )
        print(
            f"  Last word:  '{tokens[-1].text}' at {tokens[-1].end:.3f}s timeline"
        )

    # Step 2: Intelligent Caption Grouping according to Mode
    print(f"\n[Step 2/3] Caption Grouping (Mode: {mode.value})...")
    grouper = LLMGroupingService()
    groups = grouper.group_words(
        tokens, mode=mode, force_fallback=force_heuristic
    )

    # Step 3: Validate Grouping Integrity
    print("\n[Step 3/3] Validating Caption Integrity & Constraints...")
    is_valid, reason = validate_caption_groups(groups, tokens, mode=mode)
    if not is_valid:
        print(f"[Validation Failed] {reason}")
        sys.exit(1)
    print(
        f"✓ Validation passed! {len(groups)} synchronized caption groups created."
    )

    # Step 4: Intelligent Gap Bridging / Snap-to-Next (Eliminates micro-gaps <= 0.35s)
    groups = bridge_caption_gaps(groups, max_bridge_gap=0.35)
    print("✓ Intelligent Gap Bridging applied: micro-gaps (<= 0.35s) snapped seamlessly.")

    # Print summary table
    print("\n" + "-" * 72)
    print(f"{'#':<4} {'TIMING (COMP TIME)':<22} {'WORDS':<6} {'CAPTION PHRASE'}")
    print("-" * 72)
    for g in groups:
        timing_str = f"{format_timestamp(g.start)} -> {format_timestamp(g.end)}"
        print(f"{g.index:<4} {timing_str:<22} {g.word_count:<6} {g.text}")
    print("-" * 72)

    # Export to JSON & SRT
    if output_path is None:
        config.output_dir.mkdir(parents=True, exist_ok=True)
        output_path = config.output_dir / "captions.json"
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Generate & Save SRT
    srt_path = output_path.with_suffix(".srt")
    srt_content = generate_srt(groups)
    with open(srt_path, "w", encoding="utf-8") as sf:
        sf.write(srt_content)
    print(f"✓ SubRip (.srt) subtitles saved to:\n  {srt_path.resolve()}")

    # 2. Save JSON for After Effects
    export_payload = {
        "mode": mode.value,
        "time_offset": time_offset,
        "total_captions": len(groups),
        "generated_at": datetime.now().isoformat(),
        "srt": srt_content,
        "captions": [g.to_dict() for g in groups],
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(export_payload, f, indent=2, ensure_ascii=False)

    # Master copies for multi-language translation and manual edit persistence
    master_path = output_path.with_name("captions_master.json")
    with open(master_path, "w", encoding="utf-8") as f:
        json.dump(export_payload, f, indent=2, ensure_ascii=False)

    orig_output_path = output_path.with_name("captions_original.json")
    with open(orig_output_path, "w", encoding="utf-8") as f:
        json.dump(export_payload, f, indent=2, ensure_ascii=False)

    print(f"✓ After Effects JSON saved to:\n  {output_path.resolve()}")
    return export_payload


def translate_captions(
    target_language: str = "id",
    captions_file: Optional[Path] = None,
) -> Dict[str, Any]:
    """Translates existing captions chunk-by-chunk and saves to a separate language file.

    Always uses captions_master.json (or captions_original.json) as source, preserving the clean
    original transcript when switching between languages or generating multiple language tracks.
    Crucially, does NOT trigger After Effects AppleScript import, preventing deadlocks
    when invoked from within an active After Effects ScriptUI panel via system.callSystem().
    """
    if captions_file is None:
        master_file = config.output_dir / "captions_master.json"
        orig_file = config.output_dir / "captions_original.json"
        if master_file.exists():
            captions_file = master_file
        elif orig_file.exists():
            captions_file = orig_file
        else:
            captions_file = config.output_dir / "captions.json"

    if not captions_file.exists():
        raise FileNotFoundError(
            f"Captions file not found: {captions_file}. Please run Export first."
        )

    with open(captions_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    mode_str = data.get("mode", "Long")
    mode_enum = GroupingMode.from_string(mode_str)
    raw_captions = data.get("captions", [])

    groups = [
        CaptionGroup(
            index=c["index"],
            text=c["text"],
            start=float(c["start"]),
            end=float(c["end"]),
            word_indices=c.get("word_indices", []),
            word_count=int(c.get("word_count", len(c["text"].split()))),
        )
        for c in raw_captions
    ]

    lang_clean = target_language.lower().strip()
    if lang_clean in {"id", "indonesia", "indonesian", "en", "english"}:
        print(
            f"\n🌐 Translating {len(groups)} caption chunks to {lang_clean.upper()}..."
        )
        from translation_service import TranslationService

        translator = TranslationService()
        try:
            groups = translator.translate_groups(
                groups, target_language=lang_clean, mode=mode_enum
            )
        except Exception as e:
            print(f"\n[Error] Translation failed: {e}", file=sys.stderr)
            lang_json_path = config.output_dir / f"captions_{lang_clean}.json"
            if lang_json_path.exists():
                try:
                    lang_json_path.unlink()
                except Exception:
                    pass
            sys.exit(1)

        translated_payload = {
            "mode": mode_str,
            "language": lang_clean,
            "time_offset": data.get("time_offset", 0.0),
            "total_captions": len(groups),
            "generated_at": datetime.now().isoformat(),
            "srt": generate_srt(groups),
            "captions": [g.to_dict() for g in groups],
        }

        # Save language-specific json
        lang_json_path = config.output_dir / f"captions_{lang_clean}.json"
        with open(lang_json_path, "w", encoding="utf-8") as f:
            json.dump(translated_payload, f, indent=2, ensure_ascii=False)

        trans_srt_path = config.output_dir / f"captions_{lang_clean}.srt"
        with open(trans_srt_path, "w", encoding="utf-8") as sf:
            sf.write(translated_payload["srt"])

        # Also update active captions.json for generic consumers
        target_json_path = config.output_dir / "captions.json"
        with open(target_json_path, "w", encoding="utf-8") as f:
            json.dump(translated_payload, f, indent=2, ensure_ascii=False)

        print(f"✓ Translated subtitles saved to: {trans_srt_path.name}")
        return translated_payload
    else:
        return data

    return {
        "success": True,
        "language": lang_clean,
        "total_layers": len(groups),
        "captions": [g.to_dict() for g in groups],
    }


def import_captions_to_timeline(
    target_language: str = "original",
    captions_file: Optional[Path] = None,
    trigger_ae: bool = True,
) -> Dict[str, Any]:
    """Stage 2: Translates captions chunk-by-chunk if requested and imports directly

    as text layers in the active After Effects timeline.
    """
    res = translate_captions(target_language=target_language, captions_file=captions_file)

    if trigger_ae:
        print("\n🎬 Importing text layers directly into After Effects timeline...")
        ok = trigger_ae_import()
        if not ok:
            raise RuntimeError(
                "Could not send command to After Effects. Please verify AE is open."
            )

        print(
            f"✓ {res['total_layers']} text layers successfully created in After Effects active timeline!"
        )

    return res


def run_pipeline(
    input_file: Optional[Path] = None,
    mode: GroupingMode = GroupingMode.SHORT,
    use_mock: bool = False,
    time_offset: float = 0.0,
    output_path: Optional[Path] = None,
    force_heuristic: bool = False,
    auto_import: bool = False,
    target_language: str = "original",
) -> Dict[str, Any]:
    """Convenience runner executing Export and optional Import."""
    export_res = export_captions(
        input_file=input_file,
        mode=mode,
        use_mock=use_mock,
        time_offset=time_offset,
        output_path=output_path,
        force_heuristic=force_heuristic,
    )

    if auto_import:
        import_captions_to_timeline(
            target_language=target_language, captions_file=output_path
        )

    print("\n" + "=" * 68)
    print(f"🎉 PIPELINE COMPLETED SUCCESSFULLY! Mode: [{mode.value}]")
    print("=" * 68 + "\n")
    return export_res


def main():
    parser = argparse.ArgumentParser(
        description="AI Caption Generator for Adobe After Effects"
    )
    parser.add_argument(
        "--input",
        "-i",
        type=Path,
        default=None,
        help="Path to input audio or video file (.mp3, .wav, .m4a, .mp4, .mov, .aif)",
    )
    parser.add_argument(
        "--workarea",
        action="store_true",
        help="Automatically render audio from active After Effects Work Area and generate captions",
    )
    parser.add_argument(
        "--time-offset",
        type=float,
        default=0.0,
        help="Time offset in seconds to add to caption timestamps (e.g. comp.workAreaStart)",
    )
    parser.add_argument(
        "--mode",
        "-m",
        type=str,
        default="short",
        choices=[
            "single",
            "short",
            "long",
            "Single Word",
            "Short",
            "Long",
            "single word",
        ],
        help="Caption Grouping Mode: 'single' (Single Word), 'short' (Short, 2-3 words), 'long' (Long, 4-5 words). Default: short",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Run offline mock test with sample speech data (no API key required)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Path to output JSON file (default: output/captions.json)",
    )
    parser.add_argument(
        "--heuristic-only",
        action="store_true",
        help="Force rule-based heuristic grouping without calling LLM API",
    )
    parser.add_argument(
        "--auto-import",
        action="store_true",
        help="Automatically trigger After Effects import after generating captions",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch the desktop graphical user interface with dropdown selector",
    )
    parser.add_argument(
        "--import-only",
        action="store_true",
        help="Only import existing captions.json into After Effects (skips STT & grouping)",
    )
    parser.add_argument(
        "--translate-only",
        action="store_true",
        help="Only translate existing captions.json chunk-by-chunk without AE AppleScript trigger (safe for ScriptUI panel)",
    )
    parser.add_argument(
        "--lang",
        type=str,
        default="original",
        choices=["original", "id", "en"],
        help="Target language for After Effects text layers: 'original' (default), 'id' (Indonesian), or 'en' (English)",
    )

    args = parser.parse_args()

    if args.gui:
        import web_ui

        web_ui.main()
        return

    if args.translate_only:
        translate_captions(
            target_language=args.lang, captions_file=args.output
        )
        return

    if args.import_only:
        import_captions_to_timeline(
            target_language=args.lang, captions_file=args.output
        )
        return

    # Silent background update of grouping rules from GitHub if online
    try:
        from updater import check_and_update_rules
        check_and_update_rules(timeout_sec=2.0)
    except Exception:
        pass

    selected_mode = GroupingMode.from_string(args.mode)
    time_offset = args.time_offset
    input_file = args.input
    auto_import = args.auto_import

    if args.workarea:
        print("[Work Area] Instructing After Effects to render Work Area audio...")
        meta = render_ae_workarea()
        input_file = Path(meta["audio_file"])
        time_offset = float(meta["work_area_start"])
        auto_import = True
        print(
            f"✓ Rendered Work Area audio: {meta['work_area_duration']:.2f}s starting at {time_offset:.2f}s"
        )

    use_mock = args.mock or (input_file is None and not args.workarea)

    run_pipeline(
        input_file=input_file,
        mode=selected_mode,
        use_mock=use_mock,
        time_offset=time_offset,
        output_path=args.output,
        force_heuristic=args.heuristic_only,
        auto_import=auto_import,
        target_language=args.lang,
    )


if __name__ == "__main__":
    main()
