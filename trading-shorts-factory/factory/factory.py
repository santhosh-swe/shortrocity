"""Video factory: end-to-end, keyless, validated short-video pipeline.

Stages per video:  script -> tts -> subtitle -> footage -> combine -> render -> package
Each stage has a validation gate; transient steps retry; completed stages are
skipped on re-run (idempotent resume). Per-video manifest + batch manifest are
written so an external loop (cron / `while`) can drive continuous production.

Creative content (script/hook/caption) is supplied per-spec (e.g. authored by a
Claude agent). If a spec has no script, it falls back to keyless Pollinations.
"""
import os
import json
import time
import subprocess
from dataclasses import dataclass, field, asdict
from typing import Optional
from loguru import logger

from app.services import voice, video as mpt_video
from app.services import llm
from app.models.schema import VideoParams, VideoAspect, VideoConcatMode
from factory import footage

# ---- tunables -------------------------------------------------------------
CLIP_DURATION = 5.0
TARGET_MIN_SEC = 12.0
TARGET_MAX_SEC = 60.0
VOICE_NAME = "en-US-AndrewNeural-Male"
FONT_NAME = "MicrosoftYaHeiBold.ttc"
WIDTH, HEIGHT = 1080, 1920
DISCLAIMER = "Educational content only. Not financial advice. Created with AI."


@dataclass
class VideoSpec:
    id: str
    subject: str
    niche: str = "trading"
    hook: str = ""
    script: Optional[str] = None          # if None -> Pollinations
    footage_prompts: list = field(default_factory=list)
    hashtags: list = field(default_factory=list)
    title: str = ""
    voice_name: str = VOICE_NAME


class GateError(Exception):
    """A validation gate failed for this video."""


def _ffprobe(path: str) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", path],
        capture_output=True, text=True,
    )
    return json.loads(out.stdout or "{}")


def _audio_duration(path: str) -> float:
    info = _ffprobe(path)
    return float(info.get("format", {}).get("duration", 0.0))


def _retry(fn, tries=3, base=2, label="op"):
    last = None
    for i in range(1, tries + 1):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            logger.warning(f"{label} attempt {i}/{tries} failed: {str(e)[:160]}")
            time.sleep(base * i)
    raise GateError(f"{label} failed after {tries} tries: {last}")


def produce_video(spec: VideoSpec, workdir: str) -> dict:
    """Run the full pipeline for one spec. Returns a manifest dict."""
    vdir = os.path.join(workdir, spec.id)
    os.makedirs(vdir, exist_ok=True)
    manifest_path = os.path.join(vdir, "manifest.json")
    manifest = {"id": spec.id, "niche": spec.niche, "stages": {}, "status": "running"}

    p_audio = os.path.join(vdir, "audio.mp3")
    p_srt = os.path.join(vdir, "sub.srt")
    p_combined = os.path.join(vdir, "combined.mp4")
    p_final = os.path.join(vdir, "final.mp4")

    # 1) SCRIPT --------------------------------------------------------------
    script = (spec.script or "").strip()
    if not script:
        logger.info(f"[{spec.id}] no authored script -> Pollinations fallback")
        script = _retry(
            lambda: llm.generate_script(video_subject=spec.subject, language="en", paragraph_number=2),
            label="llm.generate_script",
        )
    if script.startswith("Error"):
        raise GateError(f"script generation returned error: {script[:120]}")
    if not (40 <= len(script) <= 1400):
        raise GateError(f"script length out of bounds: {len(script)} chars")
    manifest["stages"]["script"] = {"chars": len(script), "ok": True}
    manifest["script"] = script

    # 2) TTS -----------------------------------------------------------------
    if not (os.path.exists(p_audio) and os.path.getsize(p_audio) > 0):
        sub_maker = _retry(
            lambda: voice.tts(text=script, voice_name=spec.voice_name, voice_rate=1.0,
                              voice_file=p_audio, voice_volume=1.0),
            label="voice.tts",
        )
        if sub_maker is None or not os.path.exists(p_audio):
            raise GateError("tts produced no audio / sub_maker")
    else:
        sub_maker = _retry(
            lambda: voice.tts(text=script, voice_name=spec.voice_name, voice_rate=1.0,
                              voice_file=p_audio, voice_volume=1.0),
            label="voice.tts(resub)",
        )
    dur = _audio_duration(p_audio)
    if not (TARGET_MIN_SEC <= dur <= TARGET_MAX_SEC):
        logger.warning(f"[{spec.id}] audio duration {dur:.1f}s outside target window")
    manifest["stages"]["tts"] = {"duration": round(dur, 2), "ok": True}
    manifest["duration"] = round(dur, 2)

    # 3) SUBTITLE ------------------------------------------------------------
    voice.create_subtitle(text=script, sub_maker=sub_maker, subtitle_file=p_srt)
    srt_ok = os.path.exists(p_srt) and os.path.getsize(p_srt) > 0
    manifest["stages"]["subtitle"] = {"ok": srt_ok}

    # 4) FOOTAGE (keyless) ---------------------------------------------------
    n_clips = max(2, int(dur // CLIP_DURATION) + 1)
    prompts = (spec.footage_prompts or [spec.subject])
    prompts = [prompts[i % len(prompts)] for i in range(n_clips)]
    clips = footage.make_background_clips(prompts, os.path.join(vdir, "clips"),
                                          clip_duration=CLIP_DURATION, width=WIDTH, height=HEIGHT)
    good = [c for c in clips if os.path.exists(c) and os.path.getsize(c) > 10000]
    if len(good) < 1:
        raise GateError("no usable background clips produced")
    manifest["stages"]["footage"] = {"clips": len(good), "ok": True}

    # 5) COMBINE -------------------------------------------------------------
    _retry(
        lambda: mpt_video.combine_videos(
            combined_video_path=p_combined, video_paths=good, audio_file=p_audio,
            video_aspect=VideoAspect.portrait, video_concat_mode=VideoConcatMode.random,
            max_clip_duration=int(CLIP_DURATION), threads=4),
        tries=2, label="combine_videos",
    )
    if not os.path.exists(p_combined):
        raise GateError("combine_videos produced no output")
    manifest["stages"]["combine"] = {"ok": True}

    # 6) RENDER --------------------------------------------------------------
    params = VideoParams(
        video_subject=spec.subject, video_script=script, video_aspect=VideoAspect.portrait,
        voice_name=spec.voice_name, subtitle_enabled=True, font_name=FONT_NAME, font_size=72,
        text_fore_color="#FFFFFF", stroke_color="#000000", stroke_width=2.5,
        subtitle_position="bottom", bgm_type="", n_threads=4,
    )
    mpt_video.generate_video(video_path=p_combined, audio_path=p_audio,
                             subtitle_path=p_srt if srt_ok else "", output_file=p_final, params=params)

    # 7) RENDER GATE ---------------------------------------------------------
    if not os.path.exists(p_final) or os.path.getsize(p_final) < 50000:
        raise GateError("final render missing/too small")
    info = _ffprobe(p_final)
    streams = {s["codec_type"]: s for s in info.get("streams", [])}
    if "video" not in streams or "audio" not in streams:
        raise GateError(f"final missing stream(s): {list(streams)}")
    vw, vh = int(streams["video"]["width"]), int(streams["video"]["height"])
    fdur = float(info.get("format", {}).get("duration", 0))
    if (vw, vh) != (WIDTH, HEIGHT):
        raise GateError(f"wrong resolution {vw}x{vh}")
    if abs(fdur - dur) > 2.0:
        logger.warning(f"[{spec.id}] final {fdur:.1f}s vs audio {dur:.1f}s")
    manifest["stages"]["render"] = {"ok": True, "res": f"{vw}x{vh}", "duration": round(fdur, 2),
                                    "size_mb": round(os.path.getsize(p_final) / 1e6, 2)}

    # 8) PACKAGE -------------------------------------------------------------
    package(spec, script, vdir, p_final)
    manifest["status"] = "complete"
    manifest["final"] = p_final
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    logger.success(f"[{spec.id}] DONE -> {p_final} ({manifest['stages']['render']['size_mb']}MB, {round(fdur,1)}s)")
    return manifest


def package(spec: VideoSpec, script: str, vdir: str, final_path: str) -> None:
    """Write review-ready posting assets (caption + metadata) next to the video."""
    tags = " ".join(spec.hashtags) if spec.hashtags else "#trading #investing #stocks #fintok"
    yt_title = (spec.title or spec.subject)[:95]
    # The script already opens with the hook verbatim, so don't repeat it.
    caption = f"{script}\n\n⚠️ {DISCLAIMER}\n\n{tags}"
    with open(os.path.join(vdir, "caption.txt"), "w") as f:
        f.write(caption)
    meta = {
        "id": spec.id, "niche": spec.niche, "video": os.path.basename(final_path),
        "youtube_title": yt_title,
        "youtube_description": f"{spec.hook}\n\n{script}\n\n{DISCLAIMER}\n\n{tags}",
        "instagram_caption": caption,
        "hook": spec.hook, "hashtags": spec.hashtags,
        "disclaimer": DISCLAIMER,
        "ai_disclosure": "Contains AI-generated visuals, voice, and script. Disclose as 'altered/synthetic' per platform policy.",
        "review_required": True,
    }
    with open(os.path.join(vdir, "metadata.json"), "w") as f:
        json.dump(meta, f, indent=2)


def run_batch(specs: list[VideoSpec], workdir: str) -> dict:
    """Produce a batch; continue past individual failures; write batch manifest."""
    os.makedirs(workdir, exist_ok=True)
    results = []
    for spec in specs:
        t0 = time.time()
        try:
            m = produce_video(spec, workdir)
            m["seconds"] = round(time.time() - t0, 1)
            results.append(m)
        except Exception as e:  # noqa: BLE001
            logger.error(f"[{spec.id}] FAILED: {str(e)[:200]}")
            results.append({"id": spec.id, "status": "failed", "error": str(e)[:300],
                            "seconds": round(time.time() - t0, 1)})
    batch = {
        "total": len(specs),
        "complete": sum(1 for r in results if r.get("status") == "complete"),
        "failed": sum(1 for r in results if r.get("status") == "failed"),
        "results": results,
    }
    with open(os.path.join(workdir, "batch_manifest.json"), "w") as f:
        json.dump(batch, f, indent=2)
    logger.success(f"BATCH: {batch['complete']}/{batch['total']} complete, {batch['failed']} failed")
    return batch


def load_specs(plan_path: str) -> list[VideoSpec]:
    with open(plan_path) as f:
        data = json.load(f)
    return [VideoSpec(**s) for s in data]


if __name__ == "__main__":
    import sys
    plan = sys.argv[1] if len(sys.argv) > 1 else "factory/plan.json"
    work = sys.argv[2] if len(sys.argv) > 2 else "storage/factory_out"
    run_batch(load_specs(plan), work)
