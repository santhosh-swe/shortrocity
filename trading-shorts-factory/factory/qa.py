"""QA harness: turn a rendered video into a review packet for a validator agent.

Produces a horizontal contact sheet of N frames (so subtitles + footage can be
eyeballed) and a JSON summary (script, duration, streams, caption). A Claude QA
agent reads the contact sheet image + summary and returns pass/fail + notes.
"""
import os
import json
import subprocess


def _ffprobe(path: str) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
        capture_output=True, text=True)
    return json.loads(out.stdout or "{}")


def contact_sheet(video_path: str, out_path: str, n: int = 6, cols: int = 6) -> str:
    """Extract n evenly-spaced frames and tile them into one image."""
    info = _ffprobe(video_path)
    dur = float(info.get("format", {}).get("duration", 0)) or 1.0
    tmpdir = os.path.join(os.path.dirname(out_path), "_qa_frames")
    os.makedirs(tmpdir, exist_ok=True)
    frames = []
    for i in range(n):
        t = max(0.1, dur * (i + 0.5) / n)
        fp = os.path.join(tmpdir, f"f{i}.png")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", video_path,
                        "-frames:v", "1", "-vf", "scale=270:480", fp], check=True)
        frames.append(fp)
    # Combine the N separate frame images side by side. `tile` only works on
    # consecutive frames of ONE input, so use hstack across the N inputs.
    labels = "".join(f"[{i}:v]" for i in range(len(frames)))
    subprocess.run(["ffmpeg", "-y", "-v", "error", *sum([["-i", f] for f in frames], []),
                    "-filter_complex", f"{labels}hstack=inputs={len(frames)}", out_path], check=True)
    for f in frames:
        os.remove(f)
    os.rmdir(tmpdir)
    return out_path


def review_packet(video_dir: str) -> dict:
    """Build a QA packet for one produced video directory."""
    final = os.path.join(video_dir, "final.mp4")
    manifest = json.load(open(os.path.join(video_dir, "manifest.json")))
    meta_path = os.path.join(video_dir, "metadata.json")
    meta = json.load(open(meta_path)) if os.path.exists(meta_path) else {}
    sheet = os.path.join(video_dir, "qa_contact_sheet.png")
    contact_sheet(final, sheet, n=6)
    packet = {
        "id": manifest.get("id"),
        "niche": manifest.get("niche"),
        "duration": manifest.get("duration"),
        "script": manifest.get("script"),
        "hook": meta.get("hook"),
        "hashtags": meta.get("hashtags"),
        "render": manifest.get("stages", {}).get("render"),
        "contact_sheet": sheet,
    }
    with open(os.path.join(video_dir, "qa_packet.json"), "w") as f:
        json.dump(packet, f, indent=2)
    return packet


if __name__ == "__main__":
    import sys
    print(json.dumps(review_packet(sys.argv[1]), indent=2))
