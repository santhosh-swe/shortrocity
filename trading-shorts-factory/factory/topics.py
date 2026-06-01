"""Autonomous topic generator for the perpetual loop.

Invents fresh, non-duplicate video specs (idea + hook + full script + footage
prompts + hashtags) using the same keyless Pollinations LLM the factory uses.
Bakes in the research's format + compliance rules. Validates every spec and
de-dupes against a registry of already-produced titles.

One spec per LLM call: Pollinations truncates long responses (~1.4k chars), so
batching many full specs into one call cuts off mid-JSON. Calls run in parallel.
"""
import json
import re
import time
import uuid
import random
from concurrent.futures import ThreadPoolExecutor
from loguru import logger

from app.services import llm

NICHES = [
    "trading psychology", "risk management", "personal finance",
    "candlestick basics", "trading mistakes", "investing basics",
]

REQUIRED = ["subject", "niche", "title", "hook", "script", "footage_prompts", "hashtags"]

ANGLES = [
    "a costly beginner mistake", "a counterintuitive truth", "a simple rule or formula",
    "a psychology trap", "a 'what I wish I knew' lesson", "a myth debunked",
    "a before/after mindset shift", "a quick framework", "a hidden cost", "a discipline habit",
]


def _slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return (s[:40] or "video") + "-" + uuid.uuid4().hex[:4]


def _extract_json_object(text: str):
    text = text.strip().replace("```json", "").replace("```", "")
    # prefer an array's first element, else a bare object
    a, b = text.find("{"), text.rfind("}")
    if a == -1 or b == -1 or b < a:
        return None
    try:
        return json.loads(text[a:b + 1])
    except json.JSONDecodeError:
        return None


def _valid(spec: dict) -> bool:
    if not isinstance(spec, dict) or not all(k in spec for k in REQUIRED):
        return False
    if not isinstance(spec.get("footage_prompts"), list) or len(spec["footage_prompts"]) < 3:
        return False
    if not isinstance(spec.get("hashtags"), list) or len(spec["hashtags"]) < 6:
        return False
    return 45 <= len(str(spec.get("script", "")).split()) <= 115


def _write_script(hook: str, subject: str) -> str | None:
    """Dedicated script call. Producing the script separately (not inside the
    metadata JSON) yields markedly cleaner copy — the model isn't splitting
    attention across 7 JSON fields."""
    prompt = (
        f"Write a voiceover script for a 25-35 second vertical short video about: {subject}.\n"
        f"Start with this EXACT first line: \"{hook}\"\n"
        "Then 70-95 words total. Short punchy sentences. One concrete number or example. "
        "End with \"Follow for more\" or \"Save this\". Plain spoken English, no markdown, no emojis, "
        "no stage directions. Education only: NO buy/sell calls, signals, guaranteed returns, or "
        "get-rich-quick claims. Output only the script text."
    )
    try:
        txt = llm._generate_response(prompt)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"script LLM error: {str(e)[:120]}")
        return None
    if not isinstance(txt, str) or txt.startswith("Error"):
        return None
    txt = txt.strip().strip('"')
    return txt if 45 <= len(txt.split()) <= 130 else None


def _generate_one(avoid_list, niches) -> dict | None:
    niche = random.choice(niches)
    angle = random.choice(ANGLES)
    # Stage 1: metadata only (no script) -> small, reliable JSON.
    meta_prompt = f"""Create ONE short-form video idea for Instagram Reels / YouTube Shorts in the niche "{niche}", built around {angle}.

Return ONLY a single JSON object (no prose, no array, no script field) with these exact keys:
- "subject": one-line topic
- "niche": "{niche}"
- "title": YouTube title <=80 chars, punchy
- "hook": spoken first line <=14 words; lead with a SPECIFIC number or dollar amount; education only (no buy/sell/guarantees)
- "footage_prompts": array of 5 cinematic AI-image prompts (scene/lighting/mood, vertical 9:16, NO readable text/words/labels in the image)
- "hashtags": array of 8-12 strings each starting with "#"

Make it DISTINCT from these existing titles: {avoid_list}
Output the JSON object only."""
    try:
        raw = llm._generate_response(meta_prompt)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"topic LLM error: {str(e)[:120]}")
        return None
    if not isinstance(raw, str) or raw.startswith("Error"):
        return None
    spec = _extract_json_object(raw)
    if not spec:
        return None
    # Stage 2: dedicated, higher-quality script.
    script = _write_script(str(spec.get("hook", "")), str(spec.get("subject", spec.get("title", ""))))
    if not script:
        return None
    spec["script"] = script
    if _valid(spec):
        spec["id"] = _slug(str(spec["title"]))
        return spec
    return None


def generate_specs(n: int, avoid_titles=None, niches=None, tries: int = 3) -> list[dict]:
    """Return up to n fresh, valid, de-duplicated specs (one LLM call per spec)."""
    avoid = {t.strip().lower() for t in (avoid_titles or [])}
    niches = niches or NICHES
    collected, seen = [], set(avoid)
    avoid_list = list(avoid)[-30:]

    for attempt in range(1, tries + 1):
        need = n - len(collected)
        if need <= 0:
            break
        # over-request a little to absorb dupes/failures
        workers = min(6, need + 2)
        with ThreadPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(lambda _: _generate_one(avoid_list, niches), range(workers)))
        for spec in results:
            if not spec:
                continue
            t = str(spec.get("title", "")).strip().lower()
            if t in seen:
                continue
            seen.add(t)
            collected.append(spec)
            if len(collected) >= n:
                break
        logger.info(f"topic gen attempt {attempt}: {len(collected)}/{n} valid specs")
        if len(collected) < n:
            time.sleep(2)
    return collected[:n]


if __name__ == "__main__":
    import sys
    k = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    specs = generate_specs(k)
    print(json.dumps(specs, indent=2))
    print(f"\n=> {len(specs)} valid specs")
