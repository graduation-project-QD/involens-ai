#!/usr/bin/env bash
# B10 run sequence on the GPU VM. bash run_b10.sh <step>
#   smoke  – 20 training steps on E2 data + evaluation (checks download, memory, speed)
#   e2     – train on OCR text (PaddleOCR det + fine-tuned VietOCR), select on val
#   e3     – train on the oracle (GT text in labelled regions), select on val
#   predict – word predictions of the best E2/E3 models on their val sets, and E1 (E2 model on OCR from
#            the pretrained VietOCR)
#   all    – e2, e3, predict, pack, one after another (no parallel GPU jobs)
#   pack   – tar runs to download (best weights, configs, history, scores, predictions)
set -euo pipefail

VENV="${VENV:-$HOME/b10-venv}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"   # ai-service/
DATA="${DATA:-$ROOT/../data/layoutxlm_v1}"
RUNS="${RUNS:-$ROOT/../runs_b10}"
EPOCHS="${EPOCHS:-30}"
LR="${LR:-5e-5}"
export PYTHONPATH="$ROOT/src" PYTHONUTF8=1 HF_HOME="${HF_HOME:-$HOME/.cache/huggingface}"
PY="$VENV/bin/python -m invoice_ai.kie.train_layoutxlm"
mkdir -p "$RUNS"

case "${1:-}" in
  smoke)   $PY train --data "$DATA" --train train.ocr.jsonl --val val.ocr.jsonl --max-steps 20 --patience 0 --out "$RUNS/smoke" ;;
  e2)      $PY train --data "$DATA" --train train.ocr.jsonl --val val.ocr.jsonl --epochs "$EPOCHS" --lr "$LR" --out "$RUNS/e2" 2>&1 | tee "$RUNS/e2.log" ;;
  e3)      $PY train --data "$DATA" --train train.oracle.jsonl --val val.oracle.jsonl --epochs "$EPOCHS" --lr "$LR" --out "$RUNS/e3" 2>&1 | tee "$RUNS/e3.log" ;;
  predict)
    $PY predict --model "$RUNS/e2/best" --data "$DATA" --split val.ocr.jsonl --out "$RUNS/e2/predict_val"
    $PY predict --model "$RUNS/e2/best" --data "$DATA" --split val.ocr_pretrained.jsonl --out "$RUNS/e2/predict_val_e1"
    $PY predict --model "$RUNS/e3/best" --data "$DATA" --split val.oracle.jsonl --out "$RUNS/e3/predict_val" ;;
  all)
    bash "$0" e2
    bash "$0" e3
    bash "$0" predict > "$RUNS/predict.log" 2>&1
    bash "$0" pack
    echo B10_DONE ;;
  pack)    tar -czf "$RUNS/../b10_results_$(date +%Y%m%dT%H%M%S).tar.gz" -C "$RUNS" --exclude='smoke' . ;;
  *) echo "usage: bash run_b10.sh smoke|e2|e3|predict|all|pack"; exit 1 ;;
esac
