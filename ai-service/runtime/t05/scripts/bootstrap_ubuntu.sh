#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
source candidate.env

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "T05 bootstrap must run on the rented Linux GPU instance." >&2
  exit 1
fi

if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "nvidia-smi is missing. Ask the provider to fix the GPU driver before continuing." >&2
  exit 1
fi
nvidia-smi

if [[ "${T05_SKIP_APT:-0}" != "1" ]]; then
  sudo apt-get update
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
    build-essential git libgl1 libglib2.0-0 python3 python3-dev python3-venv
fi

python3 - <<'PY'
import sys
if not ((3, 11) <= sys.version_info[:2] <= (3, 12)):
    raise SystemExit(f"Expected Python 3.11 or 3.12, got {sys.version}")
print(sys.version)
PY

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel

python -m pip install \
  "torch==${TORCH_VERSION}" \
  "torchvision==${TORCHVISION_VERSION}" \
  --index-url "$TORCH_INDEX_URL"

python -m pip install \
  "${PADDLE_PACKAGE:-paddlepaddle-gpu}==${PADDLE_VERSION}" \
  --index-url "$PADDLE_INDEX_URL" \
  --extra-index-url https://pypi.org/simple

python -m pip install -r requirements-candidate.txt

# LayoutXLM's visual backbone needs Detectron2. The candidate ref is recorded;
# the exact resolved commit is captured by pip freeze after the smoke passes.
python -m pip install --no-build-isolation \
  "git+https://github.com/facebookresearch/detectron2.git@${DETECTRON2_REF}"

# Detectron2's optional plotting stack may otherwise select NumPy 2.x, which is
# outside PaddleX 3.7's supported range.
python -m pip install "numpy==1.26.4" "contourpy==1.3.3"

mkdir -p outputs
python -m pip check | tee outputs/pip_check_after_install.txt
python -m pip freeze --all | sort > outputs/dependency-lock-candidate.txt
python -m pip inspect > outputs/pip-inspect.json
python scripts/hardware_inventory.py > outputs/hardware_inventory.log

echo "Bootstrap complete. Run: bash scripts/run_smoke.sh"
