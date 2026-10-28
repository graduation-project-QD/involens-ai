#!/usr/bin/env bash
# B7: create the VietOCR training environment on a rented Ubuntu GPU VM.
# Usage: bash setup_ubuntu.sh   (run from the extracted bundle folder)
set -euo pipefail

TORCH_INDEX_URL="${TORCH_INDEX_URL:-https://download.pytorch.org/whl/cu129}"  # RTX 50xx needs CUDA >= 12.8
TORCH_VERSION="${TORCH_VERSION:-2.8.0}"            # same pair as the T05 smoke test that passed
TORCHVISION_VERSION="${TORCHVISION_VERSION:-0.23.0}"
VENV="${VENV:-$HOME/b7-venv}"
HERE="$(cd "$(dirname "$0")" && pwd)"

nvidia-smi || { echo "nvidia-smi failed: ask the provider to fix the driver, do not reinstall it on billed time"; exit 1; }
if [ "${B7_SKIP_APT:-0}" != "1" ]; then
  sudo apt-get update -y && sudo apt-get install -y python3-venv python3-pip unzip libgl1 libglib2.0-0
fi

python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/python" -m pip install "torch==${TORCH_VERSION}" "torchvision==${TORCHVISION_VERSION}" --index-url "$TORCH_INDEX_URL"
"$VENV/bin/python" -m pip install -r "$HERE/requirements-vietocr.txt"
"$VENV/bin/python" -m pip install --no-deps vietocr==0.3.13
# imgaug pulls the GUI build of OpenCV, which needs libGL (often missing, and apt may need sudo);
# keep only the headless build, which provides the same cv2 module.
"$VENV/bin/python" -m pip uninstall -y opencv-python || true
"$VENV/bin/python" -m pip install --force-reinstall --no-deps opencv-python-headless==4.10.0.84

"$VENV/bin/python" - <<'PY'
import torch, numpy
from vietocr.tool.config import Cfg
print("torch", torch.__version__, "cuda", torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else "-")
print("numpy", numpy.__version__)
x = torch.randn(256, 256, device="cuda"); print("cuda matmul ok", float((x @ x).sum()) != 0.0)
Cfg.load_config_from_name("vgg_transformer"); print("vietocr ok")
PY
echo "Environment ready: source $VENV/bin/activate"
