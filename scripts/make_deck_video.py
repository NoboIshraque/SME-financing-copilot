"""Narrated video of the submission deck (WP-19): one 1080p MP4, a voice-over per slide.

    uv run --no-project --with edge-tts python scripts/make_deck_video.py

Reads the slides from docs/submission/pdf/deck.pdf (re-export it first with
scripts/export_submission_pdfs.py if the deck changed) and the narration from
docs/submission/video/narration.json (one text per slide, in deck order). Writes
docs/submission/video/DecisionGuard_TopicE_deck_narrated.mp4 and a matching .srt.

The voice is Microsoft's neural text-to-speech (the `edge-tts` package; needs the network
once). Needs ffmpeg and pdftoppm (poppler) on the PATH. Each slide stays on screen for its
narration plus a short pause; subtitles are timed per sentence, in proportion to its length.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DECK_PDF = ROOT / "docs" / "submission" / "pdf" / "deck.pdf"
DECK_JSON = ROOT / "docs" / "submission" / "deck" / "deck.json"
OUT_DIR = ROOT / "docs" / "submission" / "video"
NARRATION = OUT_DIR / "narration.json"
VIDEO = OUT_DIR / "DecisionGuard_TopicE_deck_narrated.mp4"
SUBTITLES = OUT_DIR / "DecisionGuard_TopicE_deck_narrated.srt"
LEAD_IN = 0.6  # seconds of silence before each slide's narration
TAIL = 0.9  # and after it
MAX_MINUTES = 10


def _use_system_ca() -> None:
    """edge-tts pins certifi's CA list; behind a TLS-inspecting proxy, use the one given in
    SSL_CERT_FILE instead (verification stays on)."""
    bundle = os.environ.get("SSL_CERT_FILE")
    if bundle:
        import certifi
        certifi.where = lambda: bundle


async def _speak(text: str, voice: str, rate: str, target: Path) -> None:
    import edge_tts
    await edge_tts.Communicate(text, voice, rate=rate).save(str(target))


def _duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], check=True, capture_output=True,
                         text=True).stdout
    return float(out.strip())


def _clock(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true", help="keep the working folder")
    args = parser.parse_args()
    _use_system_ca()
    narration = json.loads(NARRATION.read_text(encoding="utf-8"))
    order = json.loads(DECK_JSON.read_text(encoding="utf-8"))["order"]
    slides = {s["id"]: s["text"] for s in narration["slides"]}
    missing = [o for o in order if o not in slides]
    if missing:
        raise SystemExit(f"no narration for slides: {', '.join(missing)}")

    work = Path(tempfile.mkdtemp(prefix="deckvideo-"))
    subprocess.run(["pdftoppm", "-png", "-scale-to-x", "1920", "-scale-to-y", "1080",
                    str(DECK_PDF), str(work / "slide")], check=True)
    pages = sorted(work.glob("slide-*.png"))
    if len(pages) != len(order):
        raise SystemExit(f"deck.pdf has {len(pages)} pages, deck.json lists {len(order)}")

    clips, captions, start = [], [], 0.0
    for index, (slide_id, page) in enumerate(zip(order, pages, strict=True), start=1):
        text = slides[slide_id]
        audio = work / f"voice-{index:02d}.mp3"
        asyncio.run(_speak(text, narration["voice"], narration.get("rate", "+0%"), audio))
        spoken = _duration(audio)
        length = LEAD_IN + spoken + TAIL
        clip = work / f"clip-{index:02d}.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-v", "error", "-loop", "1", "-framerate", "25", "-i", str(page),
            "-i", str(audio), "-filter_complex",
            f"[1:a]adelay={int(LEAD_IN * 1000)}:all=1,apad[a]", "-map", "0:v", "-map", "[a]",
            "-t", f"{length:.3f}", "-c:v", "libx264", "-tune", "stillimage", "-preset",
            "medium", "-pix_fmt", "yuv420p", "-r", "25", "-c:a", "aac", "-b:a", "160k",
            "-ar", "48000", "-ac", "2", str(clip)], check=True)
        clips.append(clip)
        parts = _sentences(text)
        total = sum(len(p) for p in parts)
        at = start + LEAD_IN
        for part in parts:
            span = spoken * len(part) / total
            captions.append((at, at + span, part))
            at += span
        start += length
        print(f"{index:2d} {slide_id:10s} {length:6.1f}s")

    listing = work / "clips.txt"
    listing.write_text("".join(f"file '{c}'\n" for c in clips), encoding="utf-8")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i",
                    str(listing), "-c", "copy", "-movflags", "+faststart", str(VIDEO)],
                   check=True)
    SUBTITLES.write_text("".join(
        f"{n}\n{_clock(a)} --> {_clock(b)}\n{line}\n\n"
        for n, (a, b, line) in enumerate(captions, start=1)), encoding="utf-8")
    total = _duration(VIDEO)
    print(f"{VIDEO.relative_to(ROOT)}: {total / 60:.1f} min")
    if total > MAX_MINUTES * 60:
        raise SystemExit(f"the video is longer than {MAX_MINUTES} minutes: shorten narration.json")
    if not args.keep:
        shutil.rmtree(work)


if __name__ == "__main__":
    main()
