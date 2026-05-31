"""Consolidate a batch's per-video packages into one posting pack (markdown).

For the review-then-publish workflow: one document with every video's title,
hook, ready-to-paste caption, hashtags, and YouTube metadata.
"""
import os
import json
import sys


def build(out_dir: str, plan_path: str, dest: str) -> str:
    order = [s["id"] for s in json.load(open(plan_path))]
    lines = [
        "# Posting Pack — Trading Shorts",
        "",
        "Review each video, then post. Keep the **Not financial advice** disclaimer. "
        "Add `#ad` if you include affiliate/sponsor links (FTC). Per platform policy, "
        "faceless AI voiceover + stock/AI B-roll generally needs no AIGC label, but "
        "disclose if asked.",
        "",
        "> **Monetization:** these are top-of-funnel. Revenue = prop-firm/broker "
        "affiliates, sponsorships, course/email funnel — not the Shorts ad pool.",
        "",
        "---",
        "",
    ]
    n = 0
    for vid in order:
        vdir = os.path.join(out_dir, vid)
        meta_p = os.path.join(vdir, "metadata.json")
        cap_p = os.path.join(vdir, "caption.txt")
        if not (os.path.exists(meta_p) and os.path.exists(cap_p)):
            continue
        n += 1
        meta = json.load(open(meta_p))
        caption = open(cap_p).read().strip()
        has_video = os.path.exists(os.path.join(vdir, "final.mp4"))
        lines += [
            f"## {n}. {meta.get('youtube_title', vid)}",
            f"*niche: {meta.get('niche','')}* · file: `{vid}/final.mp4` {'✅' if has_video else '⚠️ missing'}",
            "",
            f"**Hook:** {meta.get('hook','')}",
            "",
            "**Instagram / TikTok caption:**",
            "```",
            caption,
            "```",
            "",
            f"**YouTube title:** {meta.get('youtube_title','')}",
            "",
            f"**Hashtags:** {' '.join(meta.get('hashtags', []))}",
            "",
            "---",
            "",
        ]
    lines.insert(6, f"**{n} videos in this pack.**\n")
    with open(dest, "w") as f:
        f.write("\n".join(lines))
    return dest


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "storage/factory_out"
    plan = sys.argv[2] if len(sys.argv) > 2 else "factory/plan.json"
    dest = sys.argv[3] if len(sys.argv) > 3 else os.path.join(out, "POSTING_PACK.md")
    print("wrote", build(out, plan, dest))
