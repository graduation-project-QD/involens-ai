#!/usr/bin/env bash
# B7 run sequence on the GPU VM. Each step can be run on its own: bash run_b7.sh <step>
#   bench        – 200 iterations to measure seconds/iteration
#   baseline     – E1 recognizer: pretrained VietOCR (no fine-tuning) on the val GT crops
#   train        – fine-tune vgg_transformer (ITERS iterations, augmentation on)
#   evaluate     – CER per label of the fine-tuned weights on the val GT crops
#   noaug-train  – same fine-tuning with augmentation off (ablation)
#   noaug-eval   – CER per label of the no-augmentation weights on the val GT crops
#   recognize    – read detector-box crops: val with the pretrained weights, train+val with the
#                  fine-tuned weights (OCR input for LayoutXLM, B8)
#   recognize-pretrained / recognize-ft – the two halves of recognize
#   recognize-noaug – read the val detector-box crops with the no-augmentation weights
#   benchmark2   – the whole second round in turn: recognize-pretrained, noaug-train, noaug-eval, recognize-noaug, recognize-ft, pack
#   pack         – tar the results to download (weights, configs, metrics, predictions, logs)
set -euo pipefail

VENV="${VENV:-$HOME/b7-venv}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"   # ai-service/
DATA="${DATA:-$ROOT/../data/vietocr_v1}"
DET_CROPS="${DET_CROPS:-$ROOT/../data/det_crops_v1}"
RUNS="${RUNS:-$ROOT/../runs_b7}"
MODEL="${MODEL:-vgg_transformer}"
ITERS="${ITERS:-20000}"
BATCH="${BATCH:-32}"
# Fine-tuned weights from the first B7 run (bundled), or the ones trained on this VM.
FT_WEIGHTS="${FT_WEIGHTS:-$ROOT/../weights/ft_vgg_transformer_20000.pth}"
NOAUG_DIR="$RUNS/ft_${MODEL}_${ITERS}_noaug"
export PYTHONPATH="$ROOT/src" PYTHONUTF8=1
PY="$VENV/bin/python -m invoice_ai.ocr.vietocr_finetune"
mkdir -p "$RUNS"

case "${1:-}" in
  bench)       $PY train --data "$DATA" --model "$MODEL" --iters 200 --print-every 50 --valid-every 1000000 --batch-size "$BATCH" --out "$RUNS/bench_$MODEL" ;;
  baseline)    $PY evaluate --data "$DATA" --model "$MODEL" --weights pretrained --out "$RUNS/pretrained_$MODEL" ;;
  train)       $PY train --data "$DATA" --model "$MODEL" --iters "$ITERS" --batch-size "$BATCH" --out "$RUNS/ft_${MODEL}_${ITERS}" 2>&1 | tee "$RUNS/ft_${MODEL}_${ITERS}.console.log" ;;
  evaluate)    $PY evaluate --data "$DATA" --model "$MODEL" --weights "$RUNS/ft_${MODEL}_${ITERS}/weights.pth" --out "$RUNS/ft_${MODEL}_${ITERS}" ;;
  noaug-train) $PY train --data "$DATA" --model "$MODEL" --iters "$ITERS" --batch-size "$BATCH" --no-aug --out "$NOAUG_DIR" 2>&1 | tee "$NOAUG_DIR.console.log" ;;
  noaug-eval)  $PY evaluate --data "$DATA" --model "$MODEL" --weights "$NOAUG_DIR/weights.pth" --out "$NOAUG_DIR" ;;
  recognize) bash "$0" recognize-pretrained; bash "$0" recognize-ft ;;
  recognize-pretrained) $PY recognize --data "$DATA" --model "$MODEL" --crops "$DET_CROPS" --split val --weights pretrained --out "$RUNS/pretrained_$MODEL" ;;
  recognize-ft) $PY recognize --data "$DATA" --model "$MODEL" --crops "$DET_CROPS" --split all --weights "$FT_WEIGHTS" --out "$RUNS/ft_${MODEL}_${ITERS}_bundled" ;;
  recognize-noaug) $PY recognize --data "$DATA" --model "$MODEL" --crops "$DET_CROPS" --split val --weights "$NOAUG_DIR/weights.pth" --out "$NOAUG_DIR" ;;
  benchmark2)
    # Whole second round, one job at a time: training and reading crops on the same GPU in parallel
    # was slower than running them in turn (crop reading 0.03 -> 0.1 s/crop), and two processes
    # downloading the pretrained weights to /tmp at once left a truncated file.
    bash "$0" recognize-pretrained > "$RUNS/recognize_pretrained.log" 2>&1
    bash "$0" noaug-train > "$RUNS/noaug_train.log" 2>&1
    bash "$0" noaug-eval > "$RUNS/noaug_eval.log" 2>&1
    bash "$0" recognize-noaug > "$RUNS/recognize_noaug.log" 2>&1
    bash "$0" recognize-ft > "$RUNS/recognize_ft.log" 2>&1
    bash "$0" pack
    echo BENCHMARK2_DONE ;;
  pack)        tar -czf "$RUNS/../b7_results_$(date +%Y%m%dT%H%M%S).tar.gz" -C "$RUNS" --exclude='*/lmdb' --exclude='train_lmdb' --exclude='valid_lmdb' --exclude='checkpoint.pth' . ;;
  *) echo "usage: bash run_b7.sh bench|baseline|train|evaluate|noaug-train|noaug-eval|recognize|recognize-pretrained|recognize-ft|recognize-noaug|benchmark2|pack"; exit 1 ;;
esac
