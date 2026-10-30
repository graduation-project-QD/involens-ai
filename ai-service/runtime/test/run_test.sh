#!/usr/bin/env bash
# Final test run on the GPU VM (one pass, E2 + E1). bash run_test.sh <step>
#   recognize   – VietOCR reads the test detector crops: pretrained weights (E1) and fine-tuned weights (E2)
#   prepare     – hallucination filter + OCR cache, BIO records (OCR and oracle), LayoutXLM inputs
#   predict     – E2 model on the fine-tuned OCR (E2) and on the pretrained OCR (E1)
#   all         – recognize, prepare, predict, pack, one after another (no parallel GPU jobs)
#   pack        – tar everything except weights for download
# Inputs come from test_bundle.zip (see README.md). Every parameter is the one chosen on train/val.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"   # ai-service/
BASE="$(cd "$ROOT/.." && pwd)"
B7_PY="${B7_VENV:-$HOME/b7-venv}/bin/python"
B10_PY="${B10_VENV:-$HOME/b10-venv}/bin/python"
DATASET="$BASE/data/dataset_upright_test_auto"
CROPS="$BASE/data/det_crops_test"
FT_WEIGHTS="$BASE/weights/ft_vgg_transformer_20000.pth"
E2_MODEL="$BASE/weights/layoutxlm_e2"
WORK="$BASE/work"
RUNS="$BASE/runs_test"
export PYTHONPATH="$ROOT/src" PYTHONUTF8=1 HF_HOME="${HF_HOME:-$HOME/.cache/huggingface}"
mkdir -p "$WORK/vietocr_config" "$RUNS"

case "${1:-}" in
  recognize)
    # --data only fills VietOCR's dataset config; recognition reads the crops listed in det_crops.csv.
    "$B7_PY" -m invoice_ai.ocr.vietocr_finetune recognize --data "$WORK/vietocr_config" --model vgg_transformer \
      --crops "$CROPS" --split test --weights pretrained --out "$RUNS/ocr_pretrained"
    "$B7_PY" -m invoice_ai.ocr.vietocr_finetune recognize --data "$WORK/vietocr_config" --model vgg_transformer \
      --crops "$CROPS" --split test --weights "$FT_WEIGHTS" --out "$RUNS/ocr_ft" ;;
  prepare)
    "$B10_PY" -c "import cv2" 2>/dev/null || "$B10_PY" -m pip install opencv-python-headless==4.10.0.84
    "$B10_PY" -m invoice_ai.ocr.det_crops export-cache --dataset "$DATASET" --crops "$CROPS" --split test \
      --predictions "$RUNS/ocr_ft/predictions_det_test.csv" --out "$WORK/ocr_v2_cache/test" \
      --ocr-version paddle_det_c1920__vietocr_ft_v1
    "$B10_PY" -m invoice_ai.ocr.det_crops export-cache --dataset "$DATASET" --crops "$CROPS" --split test \
      --predictions "$RUNS/ocr_pretrained/predictions_det_test.csv" --out "$WORK/ocr_v2_pretrained_cache/test" \
      --ocr-version paddle_det_c1920__vietocr_pretrained
    "$B10_PY" -m invoice_ai.kie.build_bio --dataset "$DATASET" --ocr-cache "$WORK/ocr_v2_cache/test" --ocr-frame upright \
      --out "$RUNS/kie_bio_v3"
    "$B10_PY" -m invoice_ai.kie.build_bio --dataset "$DATASET" --ocr-cache "$WORK/ocr_v2_pretrained_cache/test" --ocr-frame upright \
      --out "$RUNS/kie_bio_v3_pretrained"
    "$B10_PY" -m invoice_ai.kie.tokenize_layoutxlm --bio "$RUNS/kie_bio_v3" --dataset "$DATASET" --out "$WORK/layoutxlm_test" \
      --splits test --sources ocr oracle
    "$B10_PY" -m invoice_ai.kie.tokenize_layoutxlm --bio "$RUNS/kie_bio_v3_pretrained" --dataset "$DATASET" --out "$WORK/layoutxlm_test" \
      --splits test --sources ocr --suffix _pretrained
    cp "$WORK/layoutxlm_test/summary.json" "$RUNS/layoutxlm_test_summary.json" ;;
  predict)
    "$B10_PY" -m invoice_ai.kie.train_layoutxlm predict --model "$E2_MODEL" --data "$WORK/layoutxlm_test" \
      --split test.ocr.jsonl --out "$RUNS/e2/predict_test"
    "$B10_PY" -m invoice_ai.kie.train_layoutxlm predict --model "$E2_MODEL" --data "$WORK/layoutxlm_test" \
      --split test.ocr_pretrained.jsonl --out "$RUNS/e2/predict_test_e1" ;;
  all)
    bash "$0" recognize > "$RUNS/recognize.log" 2>&1
    bash "$0" prepare > "$RUNS/prepare.log" 2>&1
    bash "$0" predict > "$RUNS/predict.log" 2>&1
    bash "$0" pack
    echo TEST_DONE ;;
  pack)    tar -czf "$BASE/test_results_$(date +%Y%m%dT%H%M%S).tar.gz" -C "$RUNS" . ;;
  *) echo "usage: bash run_test.sh recognize|prepare|predict|all|pack"; exit 1 ;;
esac
