#!/usr/bin/env bash
# Reproducible setup for the Trading Shorts Video Factory.
# Clones MoneyPrinterTurbo, installs deps, applies the two environment fixes we
# found, and overlays the factory/ layer. Idempotent-ish; safe to re-run.
set -euo pipefail

MPT_DIR="${MPT_DIR:-$HOME/MoneyPrinterTurbo}"
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "== 1/6 system deps (ffmpeg, imagemagick) =="
if ! command -v ffmpeg >/dev/null; then
  sudo apt-get update -qq && sudo apt-get install -y -qq ffmpeg imagemagick
fi

echo "== 2/6 clone MoneyPrinterTurbo -> $MPT_DIR =="
[ -d "$MPT_DIR/.git" ] || git clone --depth 1 https://github.com/harry0703/MoneyPrinterTurbo.git "$MPT_DIR"

echo "== 3/6 python venv + deps (uv) =="
cd "$MPT_DIR"
command -v uv >/dev/null || pip install -q uv
[ -d .venv ] || uv venv .venv --python 3.11
uv pip install --python .venv -r requirements.txt

echo "== 4/6 config (free Pollinations LLM) =="
[ -f config.toml ] || cp config.example.toml config.toml
python - <<'PY'
p="config.toml"; s=open(p).read()
s=s.replace('llm_provider = "openai"','llm_provider = "pollinations"')
s=s.replace('pollinations_base_url = "https://pollinations.ai/api/v1"','pollinations_base_url = ""')
open(p,"w").write(s)
print("  llm_provider=pollinations, pollinations_base_url cleared")
PY

echo "== 5/6 TLS fix: trust system CA in certifi (edge-tts behind proxy) =="
.venv/bin/python - <<'PY'
import certifi, shutil, os
sys_ca = "/etc/ssl/certs/ca-certificates.crt"
if os.path.exists(sys_ca):
    shutil.copy(certifi.where(), certifi.where()+".bak")
    shutil.copy(sys_ca, certifi.where())
    print("  certifi synced to system CA store")
else:
    print("  system CA not found; skip (only needed behind a TLS-intercepting proxy)")
PY

echo "== 6/6 overlay factory layer =="
cp -r "$HERE/factory" "$MPT_DIR/factory"
mkdir -p "$MPT_DIR/storage/research"
cp "$HERE/research/trend_research.md" "$MPT_DIR/storage/research/" 2>/dev/null || true

cat <<EOF

✅ Setup complete.

Run a batch:
  cd "$MPT_DIR"
  PYTHONPATH=. .venv/bin/python -m factory.factory factory/plan.json storage/factory_out

Continuous loop:
  ./factory/run_loop.sh factory/plan.json storage/factory_out 1800 0

Outputs land in storage/factory_out/<id>/ (final.mp4 + caption.txt + metadata.json).
EOF
