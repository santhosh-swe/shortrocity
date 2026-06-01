"""Perpetual content engine.

Each cycle: invent N fresh topics (de-duped against everything produced so far)
-> render them through the factory -> append to a registry -> rebuild a
cumulative POSTING_PACK.md -> sleep -> repeat. Produces an ever-growing review
queue. Ctrl-C safe (registry is saved after every video).

Usage: python -m factory.autoloop [n_per_cycle] [out_dir] [sleep_sec] [max_cycles]
       max_cycles 0 = run forever.
"""
import os
import sys
import json
import time
import datetime
from loguru import logger

from factory.factory import produce_video, VideoSpec
from factory import topics, posting_pack

REGISTRY = "produced_registry.json"


def _registry_path(out_dir):
    return os.path.join(out_dir, REGISTRY)


def _load_registry(out_dir):
    p = _registry_path(out_dir)
    return json.load(open(p)) if os.path.exists(p) else []


def _save_registry(out_dir, reg):
    with open(_registry_path(out_dir), "w") as f:
        json.dump(reg, f, indent=2)


def run_perpetual(n_per_cycle=3, out_dir="storage/factory_out", sleep_sec=1800, max_cycles=0):
    os.makedirs(out_dir, exist_ok=True)
    cyc_dir = os.path.join(out_dir, "_cycles")
    os.makedirs(cyc_dir, exist_ok=True)
    cycle = 0
    while True:
        cycle += 1
        reg = _load_registry(out_dir)
        avoid = [r["title"] for r in reg]
        logger.info(f"=== CYCLE {cycle}: inventing {n_per_cycle} topics (avoiding {len(avoid)} existing) ===")

        specs_raw = topics.generate_specs(n_per_cycle, avoid_titles=avoid)
        if not specs_raw:
            logger.warning("no valid topics this cycle; backing off")
            if max_cycles and cycle >= max_cycles:
                break
            time.sleep(min(sleep_sec, 120))
            continue

        ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        with open(os.path.join(cyc_dir, f"cycle_{ts}.json"), "w") as f:
            json.dump(specs_raw, f, indent=2)

        made = 0
        for sr in specs_raw:
            spec = VideoSpec(**sr)
            try:
                m = produce_video(spec, out_dir)
                reg.append({"id": spec.id, "title": sr["title"], "niche": sr.get("niche", ""),
                            "ts": ts, "final": m.get("final"), "duration": m.get("duration")})
                _save_registry(out_dir, reg)  # incremental: Ctrl-C safe
                made += 1
            except Exception as e:  # noqa: BLE001
                logger.error(f"[{spec.id}] failed: {str(e)[:180]}")

        # cumulative posting pack (registry entries carry "id", which is all
        # posting_pack needs to locate each video's metadata/caption)
        try:
            posting_pack.build(out_dir, _registry_path(out_dir),
                               os.path.join(out_dir, "POSTING_PACK.md"))
        except Exception as e:  # noqa: BLE001
            logger.warning(f"posting pack rebuild failed: {str(e)[:120]}")

        logger.success(f"CYCLE {cycle} complete: +{made} videos, registry now {len(reg)} total")
        if max_cycles and cycle >= max_cycles:
            break
        logger.info(f"sleeping {sleep_sec}s before next cycle...")
        time.sleep(sleep_sec)

    logger.success(f"autoloop finished after {cycle} cycle(s)")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    out = sys.argv[2] if len(sys.argv) > 2 else "storage/factory_out"
    slp = int(sys.argv[3]) if len(sys.argv) > 3 else 1800
    mx = int(sys.argv[4]) if len(sys.argv) > 4 else 0
    run_perpetual(n, out, slp, mx)
