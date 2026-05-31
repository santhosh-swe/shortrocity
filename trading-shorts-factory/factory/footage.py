"""Keyless footage engine for the video factory.

Instead of Pexels/Pixabay (which need API keys), generate topical background
clips from Pollinations' keyless AI image API, then add Ken Burns motion with
ffmpeg. Falls back to an ffmpeg gradient if image generation fails.
"""
import os
import subprocess
import urllib.parse
import random
import time
import requests
from loguru import logger

POLLINATIONS_IMG = "https://image.pollinations.ai/prompt/{prompt}"

# Cinematic style suffix so every image looks like premium finance B-roll.
STYLE = (
    "cinematic, dramatic moody lighting, dark teal and orange, depth of field, "
    "ultra detailed, 8k, no text, no words, no watermark, vertical composition"
)


def _ffmpeg() -> str:
    return os.environ.get("FACTORY_FFMPEG", "ffmpeg")


def generate_image(prompt: str, out_path: str, width: int = 1080, height: int = 1920,
                   seed: int | None = None, retries: int = 3, timeout: int = 90) -> bool:
    """Download one keyless AI image. Returns True on success."""
    full = f"{prompt}, {STYLE}"
    enc = urllib.parse.quote(full, safe="")
    if seed is None:
        seed = random.randint(1, 10_000_000)
    params = {"width": width, "height": height, "nologo": "true", "model": "flux", "seed": seed}
    url = POLLINATIONS_IMG.format(prompt=enc)
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            if r.status_code == 200 and len(r.content) > 5000 and r.content[:3] in (b"\xff\xd8\xff", b"\x89PN"):
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                with open(out_path, "wb") as f:
                    f.write(r.content)
                logger.info(f"image ok: {os.path.basename(out_path)} ({len(r.content)} bytes, seed={seed})")
                return True
            logger.warning(f"image attempt {attempt} bad response: {r.status_code}, {len(r.content)} bytes")
        except Exception as e:
            logger.warning(f"image attempt {attempt} failed: {str(e)[:120]}")
        time.sleep(2 * attempt)
    return False


def _gradient_fallback(out_path: str, duration: float, width: int, height: int) -> str:
    """Abstract animated gradient when image gen is unavailable."""
    c1 = random.choice(["0x0d1b2a", "0x1b263b", "0x0b132b", "0x12263a"])
    vf = (f"gradients=s={width}x{height}:rate=30:duration={duration}:speed=0.04:"
          f"c0={c1}:c1=0x1f6feb,format=yuv420p")
    cmd = [_ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", vf, "-t", str(duration),
           "-c:v", "libx264", "-pix_fmt", "yuv420p", out_path]
    subprocess.run(cmd, check=True)
    return out_path


def ken_burns_clip(image_path: str, out_path: str, duration: float = 5.0,
                   width: int = 1080, height: int = 1920, direction: str = "in") -> str:
    """Animate a still image with a slow zoom/pan (Ken Burns) at 30fps."""
    frames = max(1, int(round(duration * 30)))
    # Upscale ~1.35x before zoompan: enough headroom for smooth zoom/pan while
    # keeping zoompan ~2x faster than a full 2x upscale (benchmarked).
    bigw, bigh = int(width * 1.35), int(height * 1.35)
    if direction == "in":
        z = "min(zoom+0.0009,1.5)"
        x, y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif direction == "out":
        z = "if(eq(on,0),1.5,max(zoom-0.0009,1.0))"
        x, y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif direction == "left":
        z = "1.25"
        x, y = "max(0,(iw-iw/zoom)-(iw-iw/zoom)*on/%d)" % frames, "ih/2-(ih/zoom/2)"
    else:  # right
        z = "1.25"
        x, y = "min((iw-iw/zoom),(iw-iw/zoom)*on/%d)" % frames, "ih/2-(ih/zoom/2)"
    vf = (f"scale={bigw}:{bigh}:force_original_aspect_ratio=increase,"
          f"crop={bigw}:{bigh},"
          f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={width}x{height}:fps=30,"
          f"format=yuv420p")
    cmd = [_ffmpeg(), "-y", "-v", "error", "-loop", "1", "-i", image_path, "-t", str(duration),
           "-vf", vf, "-r", "30", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", out_path]
    subprocess.run(cmd, check=True)
    return out_path


def make_background_clips(prompts: list[str], outdir: str, clip_duration: float = 5.0,
                          width: int = 1080, height: int = 1920) -> list[str]:
    """For each prompt: generate a keyless image and animate it. Returns clip paths.

    Image generation (network-bound) runs concurrently; Ken Burns rendering
    (CPU-bound ffmpeg) runs sequentially to avoid core contention.
    """
    from concurrent.futures import ThreadPoolExecutor
    os.makedirs(outdir, exist_ok=True)
    directions = ["in", "left", "out", "right"]
    imgs = [os.path.join(outdir, f"img_{i:02d}.jpg") for i in range(len(prompts))]

    def _gen(i):
        return i, generate_image(prompts[i], imgs[i], width, height)

    got = {}
    with ThreadPoolExecutor(max_workers=min(4, len(prompts) or 1)) as ex:
        for i, ok in ex.map(_gen, range(len(prompts))):
            got[i] = ok

    good_idx = [i for i in range(len(prompts)) if got.get(i)]
    clips = []
    for i in range(len(prompts)):
        clip = os.path.join(outdir, f"bg_{i:02d}.mp4")
        # Prefer this clip's own image; if it failed, reuse another successful
        # cinematic image from the same video (with different motion) rather than
        # dropping to a flat gradient. Gradient only if every image failed.
        if got.get(i):
            src = imgs[i]
        elif good_idx:
            src = imgs[good_idx[i % len(good_idx)]]
            logger.info(f"clip {i}: image failed, reusing cinematic image {os.path.basename(src)}")
        else:
            src = None
        if src:
            try:
                ken_burns_clip(src, clip, clip_duration, width, height, directions[i % 4])
            except subprocess.CalledProcessError as e:
                logger.warning(f"ken burns failed for clip {i}, using gradient: {e}")
                _gradient_fallback(clip, clip_duration, width, height)
        else:
            logger.warning(f"all images failed for this video, clip {i} -> gradient fallback")
            _gradient_fallback(clip, clip_duration, width, height)
        clips.append(clip)
    return clips


if __name__ == "__main__":
    # quick self-test
    out = "storage/research/kenburns_test.mp4"
    ken_burns_clip("storage/research/img_test.jpg", out, duration=5.0, direction="in")
    print("ken burns clip:", out, os.path.getsize(out), "bytes")
