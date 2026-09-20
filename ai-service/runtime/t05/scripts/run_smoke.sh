#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
source candidate.env
source .venv/bin/activate

export T05_ROOT="$ROOT_DIR"
export T05_OUTPUT_DIR="$ROOT_DIR/outputs"
export T05_FIXTURE_IMAGE="$ROOT_DIR/fixtures/sample_invoice.jpg"
mkdir -p "$T05_OUTPUT_DIR"

python scripts/hardware_inventory.py > "$T05_OUTPUT_DIR/hardware_inventory.log"

layout_status=0
paddle_status=0
python scripts/smoke_layoutxlm.py 2>&1 | tee "$T05_OUTPUT_DIR/layoutxlm_smoke.log" || layout_status=$?
python scripts/smoke_paddleocr.py 2>&1 | tee "$T05_OUTPUT_DIR/paddleocr_smoke.log" || paddle_status=$?

python -m pip check > "$T05_OUTPUT_DIR/pip_check_final.txt" || true
python -m pip freeze --all | sort > "$T05_OUTPUT_DIR/dependency-lock-final.txt"
python -m pip inspect > "$T05_OUTPUT_DIR/pip-inspect-final.json"

final_status=0
python scripts/finalize_runtime.py 2>&1 | tee "$T05_OUTPUT_DIR/finalize_runtime.log" || final_status=$?
if [[ -f "$T05_OUTPUT_DIR/runtime_manifest.json" ]]; then
  python scripts/render_smoke_report.py
fi
bash scripts/package_results.sh

if [[ $layout_status -ne 0 || $paddle_status -ne 0 || $final_status -ne 0 ]]; then
  echo "T05 smoke did not pass. Download the result archive before changing or deleting the instance." >&2
  exit 1
fi

echo "T05 smoke PASS. Download the result archive before deleting the instance."
