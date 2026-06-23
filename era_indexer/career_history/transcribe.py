"""Audio transcription via MLX Whisper (Apple Silicon).

Transcription only — there is no speaker diarization in this pipeline. MLX
Whisper runs on the Mac GPU via Metal and is far faster than CPU faster-whisper.
Every segment is attributed to a single placeholder speaker so the downstream
chunking/attribution contract (``speaker_segments`` + chunk prefixes) keeps
working unchanged.

Decode options are tuned to minimize hallucination/repetition loops:
``condition_on_previous_text=False`` stops the decoder from feeding a bad window
forward, and a lower ``compression_ratio_threshold`` (1.8 vs the 2.4 default)
detects and re-rolls repetitive ("stuck") segments more aggressively.
"""
from __future__ import annotations

import os
import time
from typing import Any

from rich.console import Console

from career_history import config


console = Console()

# Single placeholder speaker: diarization was removed with the MLX switch.
SINGLE_SPEAKER = "SPEAKER_00"

_DEFAULT_MLX_REPO = "mlx-community/whisper-large-v3-mlx"

# Common Whisper names -> MLX Community repos, used only when an explicit
# ``whisper_mlx_repo`` is not configured.
_KNOWN_REPOS = {
    "large-v3": "mlx-community/whisper-large-v3-mlx",
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
    "turbo": "mlx-community/whisper-turbo",
    "medium": "mlx-community/whisper-medium-mlx",
    "small": "mlx-community/whisper-small-mlx",
    "base": "mlx-community/whisper-base-mlx",
    "tiny": "mlx-community/whisper-tiny-mlx",
}


def _model_repo() -> str:
    cfg = config.get()["models"]
    repo = cfg.get("whisper_mlx_repo")
    if repo:
        return repo
    name = cfg.get("whisper_model", "large-v3")
    return _KNOWN_REPOS.get(name, f"mlx-community/whisper-{name}-mlx")


def _decode_options() -> dict[str, Any]:
    """Build the mlx_whisper.transcribe keyword options from config.

    Anti-hallucination defaults are applied here and can be overridden per
    deployment via config.yaml.
    """
    cfg = config.get()["models"]
    options: dict[str, Any] = {
        "condition_on_previous_text": cfg.get(
            "whisper_condition_on_previous_text", False
        ),
        "compression_ratio_threshold": cfg.get(
            "whisper_compression_ratio_threshold", 1.8
        ),
        "word_timestamps": False,
        "verbose": False,
    }
    if cfg.get("whisper_language"):
        options["language"] = cfg["whisper_language"]
    # Optional extra decode knobs, only forwarded when explicitly configured.
    optional = {
        "whisper_no_speech_threshold": "no_speech_threshold",
        "whisper_logprob_threshold": "logprob_threshold",
        "whisper_initial_prompt": "initial_prompt",
    }
    for cfg_key, opt_key in optional.items():
        if cfg.get(cfg_key) is not None:
            options[opt_key] = cfg[cfg_key]
    return options


def transcribe(audio_path: str) -> dict:
    """Run MLX Whisper transcription on an audio file.

    Returns:
        {"language": str, "segments": [{start, end, text, speaker}, ...]}
    """
    import mlx_whisper

    repo = _model_repo()
    options = _decode_options()

    t0 = time.time()
    console.log(f"[dim]Transcribing with MLX Whisper ({repo})…[/dim]")
    result = mlx_whisper.transcribe(audio_path, path_or_hf_repo=repo, **options)

    language = result.get("language", "en")
    _validate_language(language)

    out_segments: list[dict] = []
    for s in result.get("segments", []):
        text = (s.get("text") or "").strip()
        if not text:
            continue
        out_segments.append({
            "start": float(s.get("start") or 0.0),
            "end": float(s.get("end") or 0.0),
            "text": text,
            "speaker": SINGLE_SPEAKER,
        })

    elapsed = time.time() - t0
    console.log(
        f"[green]Transcribed[/green] {os.path.basename(audio_path)} "
        f"({len(out_segments)} segs, {elapsed:.1f}s, lang={language})"
    )
    return {"language": language, "segments": out_segments, "elapsed": elapsed}


def _validate_language(language: str) -> None:
    allowed = config.get()["models"].get("allowed_languages")
    if not allowed:
        return

    allowed_set = {str(code).lower() for code in allowed}
    detected = language.lower()
    if detected not in allowed_set:
        raise RuntimeError(
            f"Detected language '{language}' is not allowed. "
            f"Allowed languages: {sorted(allowed_set)}"
        )


def segments_to_transcript(segments: list[dict]) -> str:
    """Render segments as a human-readable transcript."""
    lines = []
    for s in segments:
        ts = f"[{_fmt_time(s['start'])} → {_fmt_time(s['end'])}]"
        lines.append(f"{ts} {s['speaker']}: {s['text']}")
    return "\n".join(lines)


def _fmt_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"
