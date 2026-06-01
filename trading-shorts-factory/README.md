# Trading Shorts Video Factory

A **keyless, validated, multi-agent pipeline** that mass-produces vertical
(9:16) short-form trading/finance videos for Instagram Reels & YouTube Shorts —
built on top of [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo).

"Keyless" = it needs **no paid API keys**. Scripts come from Pollinations (free),
voice from Microsoft edge-tts (free), and background footage from Pollinations'
free AI image API animated with Ken Burns motion (instead of Pexels/Pixabay,
which require keys). Add a Pexels key later to swap in real stock footage.

> ⚠️ **Compliance:** All content is framed as **education only — not financial
> advice**, with no buy/sell calls, signals, or guaranteed-return claims. Every
> output ships with a disclaimer + an AI-content disclosure note. **Nothing is
> auto-posted** — you review every video before publishing.

## The swarm

```
[Research agent]  -> storage/research/trend_research.md   (trending niches, hooks, monetization, compliance)
[Scriptwriter ]  -> factory/plan.json                    (12 specs: hook + script + footage prompts + hashtags)
[Factory      ]  -> storage/factory_out/<id>/final.mp4    (script->tts->subtitle->footage->combine->render->package)
[QA agent     ]  -> reviews qa_contact_sheet.png          (hook strength, caption readability, compliance pass/fail)
```

The factory itself loops over specs (`run_batch`) with a validation gate after
every stage; `run_loop.sh` wraps it for continuous operation.

## Pipeline stages (per video)

`script → tts → subtitle → footage → combine → render → package`

Each stage has a **validation gate** (script length, audio duration window,
render resolution/streams/duration). Transient steps **retry** with backoff.
Completed audio is reused on re-run (**idempotent resume**). A per-video
`manifest.json` + a `batch_manifest.json` record exactly what happened.

## Files

| File | Purpose |
|---|---|
| `factory/factory.py` | Orchestrator: `produce_video`, `run_batch`, gates, packaging |
| `factory/footage.py` | Keyless footage: Pollinations AI images + Ken Burns (parallel; reuses a good image instead of a flat gradient on failure) |
| `factory/topics.py` | Autonomous topic generator (keyless): invents fresh validated specs |
| `factory/autoloop.py` | **Perpetual engine**: invent → render → dedupe-registry → cumulative posting pack → sleep → repeat |
| `factory/qa.py` | Builds a QA review packet (frame contact-sheet + summary) per video |
| `factory/posting_pack.py` | Consolidates a batch into one ready-to-post `POSTING_PACK.md` |
| `factory/plan.json` | 12 ready-to-render seed specs |
| `factory/run_loop.sh` | Launches the perpetual engine |
| `storage/research/trend_research.md` | The trend/monetization research report |
| `storage/factory_out/<id>/` | Per-video output: `final.mp4`, `caption.txt`, `metadata.json`, `manifest.json` |
| `storage/factory_out/produced_registry.json` | Dedupe registry of everything produced |
| `storage/factory_out/POSTING_PACK.md` | Cumulative, ready-to-post doc for the whole library |

## Setup (fresh machine)

```bash
# 1. system deps
sudo apt-get update && sudo apt-get install -y ffmpeg imagemagick

# 2. python env (uv recommended)
pip install uv && uv venv .venv --python 3.11
uv pip install --python .venv -r requirements.txt

# 3. config
cp config.example.toml config.toml
#   set llm_provider = "pollinations"  and  pollinations_base_url = ""   (the shipped default URL 404s)

# 4. TLS fix for edge-tts behind a proxy (only if edge-tts hangs):
#   sync certifi to the system CA store so the proxy CA is trusted
python -c "import certifi,shutil,ssl; shutil.copy('/etc/ssl/certs/ca-certificates.crt', certifi.where())"
```

## Run

```bash
# PERPETUAL LOOP — invent + render fresh videos forever into a review queue
# args: n_per_cycle  out_dir  sleep_seconds  max_cycles(0=forever)
./factory/run_loop.sh 3 storage/factory_out 1800 0

# one fixed batch from a plan
PYTHONPATH=. .venv/bin/python -m factory.factory factory/plan.json storage/factory_out

# just invent topics (prints JSON specs, renders nothing)
PYTHONPATH=. .venv/bin/python -m factory.topics 5
```

### How the perpetual loop stays fresh & safe
- **Dedupe:** every produced title is recorded in `produced_registry.json`; each cycle's topic prompt is told to avoid them.
- **Validation:** specs are schema/word-count checked before rendering; each render passes resolution/stream/duration gates.
- **Compliance:** the topic prompt forbids buy/sell calls, signals, and guaranteed-return claims; packaging always appends the *not financial advice* disclaimer.
- **Crash-safe:** the registry is saved after every video, so Ctrl-C or a restart resumes cleanly.
- **Review queue:** nothing posts automatically — `POSTING_PACK.md` grows into your to-review list.

## Publishing (you stay in control)

For each `storage/factory_out/<id>/`:
1. Watch `final.mp4`.
2. Use `caption.txt` (Instagram) or `metadata.json → youtube_title/description` (YouTube).
3. Keep the `⚠️ Not financial advice` disclaimer; add `#ad` if you include affiliate/sponsor links (FTC).
4. Per the research, treat Shorts as **top-of-funnel** — the revenue is affiliates (prop firms/brokers/apps), sponsorships, courses, and email lead-gen, not the Shorts ad pool.

## Upgrade to real stock footage (optional)

Add a free Pexels key to `config.toml` (`pexels_api_keys = ["..."]`) and switch
the footage source — or keep the AI-image look, which is fully topical and
unique. The keyless path needs zero accounts.
