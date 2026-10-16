"""Shared content-only processing, with no performance or provider requests."""

from pathlib import Path

from app import video_processing


def analyze_file(source, directory, *, allow_silent=False, operations=None, on_stage=None):
    ops = operations if operations is not None else vars(video_processing)
    def stage(value):
        if on_stage:
            on_stage(value)
    stage('inspecting')
    metadata = (
        ops["inspect_video"](source, allow_silent=True)
        if allow_silent
        else ops["inspect_video"](source)
    )
    normalized = Path(directory, "normalised.mp4")
    stage('normalizing')
    ops["normalise_video"](source, normalized)
    stage('detecting_scenes')
    scenes = ops["detect_scenes"](normalized)
    stage('reading_text')
    text = ops["detect_on_screen_text"](normalized)
    stage('detecting_motion')
    motion = ops["detect_motion_events"](normalized)
    # The detector emits start/end, whereas the persisted/public analysis contract
    # uses start_seconds/end_seconds. Normalize at the common pipeline boundary.
    motion = [
        {
            **{
                key: value
                for key, value in event.items()
                if key not in ("start", "end")
            },
            "start_seconds": event.get("start_seconds", event.get("start")),
            "end_seconds": event.get("end_seconds", event.get("end")),
        }
        for event in motion
    ]
    audio = {"text": "", "segments": []}
    if metadata.audio["codec"] is not None:
        wav = Path(directory, "audio.wav")
        stage('extracting_audio')
        ops["extract_wav_audio"](normalized, wav)
        stage('transcribing')
        audio = ops["transcribe_audio"](wav)
    return {
        "metadata": metadata.as_dict(),
        "audio": audio,
        "scenes": scenes,
        "on_screen_text": text,
        "motion_events": motion,
    }
