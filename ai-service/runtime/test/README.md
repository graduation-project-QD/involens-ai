# Chạy test một lần trên VM GPU (E2 + E1)

Lần đánh giá cuối trên tập test (136 ảnh). Mọi tham số giữ nguyên như đã chọn trên train/val; không chỉnh gì sau khi xem điểm test.

## Chuẩn bị trên máy cá nhân (CPU)

```bash
cd ai-service
# B4 tự xoay (môi trường OCR T10) và quyết định góc (tham số chọn trên train)
PYTHONUTF8=1 PYTHONPATH=src ../.cache/t10-ocr-venv/Scripts/python.exe -m invoice_ai.preprocessing.evaluate_orientation observe \
  --dataset ../dataset_hoadon/dataset_split_80_10_10 --splits test --paddlex-home ../.cache/paddlex \
  --observations ../experiments/data/processed/orientation_v1
PYTHONPATH=src python -m invoice_ai.preprocessing.evaluate_orientation evaluate --dataset ../dataset_hoadon/dataset_split_80_10_10 \
  --splits train test --observations ../experiments/data/processed/orientation_v1 --out ../experiments/reports/orientation_test_2026-10-29
# Ảnh test + polygon GT xoay theo góc tự đoán
PYTHONPATH=src python -m invoice_ai.datasets.build_upright --source ../dataset_hoadon/dataset_split_80_10_10 \
  --dest ../dataset_hoadon/dataset_upright_test_auto --splits test \
  --rotation-csv ../experiments/reports/orientation_test_2026-10-29/test_predictions.csv
# Detector (L960 để cắt nền, rồi cấu hình đã chọn) và crop
PYTHONUTF8=1 PYTHONPATH=src ../.cache/t10-ocr-venv/Scripts/python.exe -m invoice_ai.ocr.detection_tuning run \
  --dataset ../dataset_hoadon/dataset_upright_test_auto --split test --configs L960 C1920_b0.2_t0.15 \
  --paddlex-home ../.cache/paddlex --out ../experiments/data/processed/detection_test_auto
PYTHONPATH=src python -m invoice_ai.ocr.det_crops build --dataset ../dataset_hoadon/dataset_upright_test_auto \
  --detections ../experiments/data/processed/detection_test_auto --splits test --out ../dataset_hoadon/det_crops_test
```

## Gói upload `experiments/artifacts/test/test_bundle.zip`

| Đường dẫn trong gói | Nguồn |
|---|---|
| `ai-service/src`, `ai-service/runtime` | code |
| `data/dataset_upright_test_auto` | ảnh test đã xoay + GT |
| `data/det_crops_test` | crop detector + `det_crops.csv` |
| `weights/ft_vgg_transformer_20000.pth` | VietOCR fine-tune (B7, cùng SHA-256 với bản dùng cho train/val) |
| `weights/layoutxlm_e2/` | `config.json` + `model.safetensors` của E2 (B10) |

## Trên VM

```bash
unzip test_bundle.zip -d test && cd test
bash ai-service/runtime/b7/setup_ubuntu.sh     # VietOCR (b7-venv)
bash ai-service/runtime/b10/setup_ubuntu.sh    # LayoutXLM + detectron2 (b10-venv)
nohup bash ai-service/runtime/test/run_test.sh all > run_test.log 2>&1 &
```

`all` = `recognize` → `prepare` → `predict` → `pack`. Kết quả: `test_results_*.tar.gz` (không có trọng số): nhận dạng VietOCR, `kie_bio_v3/test.*.jsonl`, `kie_bio_v3_pretrained/test.ocr.jsonl`, `e2/predict_test*/{scores.json,predictions.jsonl}`, log.

## Sau khi tải về (máy cá nhân)

B11 + `evaluate_e2e` cho E2/E1, luật B12 trên OCR test, rồi báo cáo test.
