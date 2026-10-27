#!/usr/bin/env bash
# B10: LayoutXLM training environment on a rented Ubuntu GPU VM (run from the extracted bundle folder).
#   bash ai-service/runtime/b10/setup_ubuntu.sh
# LayoutXLM's visual branch needs detectron2, built here from source. Only its ResNeXt-FPN backbone is
# used (standard convolutions), so detectron2's custom CUDA ops are not needed: they are built CPU-only,
# which avoids requiring nvcc to match the driver.
set -euo pipefail

TORCH_INDEX_URL="${TORCH_INDEX_URL:-https://download.pytorch.org/whl/cu129}"  # RTX 50xx needs CUDA >= 12.8
TORCH_VERSION="${TORCH_VERSION:-2.8.0}"
TORCHVISION_VERSION="${TORCHVISION_VERSION:-0.23.0}"
DETECTRON2_COMMIT="${DETECTRON2_COMMIT:-1e3e13bbf607b54f62205c4c33922521822fb298}"  # main, 2026-09-30
VENV="${VENV:-$HOME/b10-venv}"
HERE="$(cd "$(dirname "$0")" && pwd)"

nvidia-smi || { echo "nvidia-smi failed: ask the provider to fix the driver"; exit 1; }

# detectron2 compiles a C++ extension: needs g++ and the Python headers.
PY_INCLUDE="$(python3 -c 'import sysconfig; print(sysconfig.get_paths()["include"])')"
if ! command -v g++ >/dev/null || [ ! -f "$PY_INCLUDE/Python.h" ] || ! command -v git >/dev/null; then
  if sudo -n true 2>/dev/null; then
    sudo apt-get update -y && sudo apt-get install -y build-essential python3-dev python3-venv git
  else
    echo "Missing build tools (g++, Python.h or git). Run once, typing the VM password yourself:"
    echo "  sudo apt-get update && sudo apt-get install -y build-essential python3-dev python3-venv git"
    exit 2
  fi
fi

python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install --upgrade pip wheel setuptools
"$VENV/bin/python" -m pip install "torch==${TORCH_VERSION}" "torchvision==${TORCHVISION_VERSION}" --index-url "$TORCH_INDEX_URL"
"$VENV/bin/python" -m pip install -r "$HERE/requirements-b10.txt"
# Hide the GPU during the build so setup.py compiles the CPU-only extension.
CUDA_VISIBLE_DEVICES="" MAX_JOBS="${MAX_JOBS:-8}" "$VENV/bin/python" -m pip install --no-build-isolation \
  "git+https://github.com/facebookresearch/detectron2.git@${DETECTRON2_COMMIT}"

"$VENV/bin/python" - <<'PY'
import torch, detectron2, transformers
from transformers import LayoutLMv2Config, LayoutLMv2ForTokenClassification
print("torch", torch.__version__, "cuda", torch.cuda.is_available(), torch.cuda.get_device_name(0))
print("detectron2", detectron2.__version__, "transformers", transformers.__version__)
# Random-weight LayoutXLM-sized model, one forward/backward on the GPU: checks the visual backbone.
model = LayoutLMv2ForTokenClassification(LayoutLMv2Config(vocab_size=250002, num_labels=17)).cuda()
batch = {
    "input_ids": torch.randint(5, 1000, (2, 64)).cuda(),
    "bbox": torch.tensor([[[10, 10, 50, 30]] * 64] * 2).cuda(),
    "attention_mask": torch.ones(2, 64, dtype=torch.long).cuda(),
    "image": torch.rand(2, 3, 224, 224).cuda() * 255,
    "labels": torch.randint(0, 17, (2, 64)).cuda(),
}
with torch.autocast("cuda", dtype=torch.bfloat16):
    loss = model(**batch).loss
loss.backward()
print("layoutlmv2 forward/backward ok, loss", round(loss.item(), 3))
PY
echo "Environment ready: source $VENV/bin/activate"
