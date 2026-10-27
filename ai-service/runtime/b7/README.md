# B7 — Fine-tune VietOCR trên VM GPU thuê

Bộ chạy cho bước B7 (`docs/ke_hoach_ocr_layoutxlm_2026-10-10.md`): fine-tune VietOCR trên crop dòng chữ GT của train, chọn trên val, so với VietOCR gốc (E1) và PaddleOCR rec tham khảo (B5: `PP-OCRv6_medium_rec` CER 9,5% trên val).

## Đã chuẩn bị sẵn (máy cá nhân)

| Thành phần | Vị trí |
|---|---|
| Dữ liệu crop | `dataset_hoadon/vietocr_v1/` – train 17.325 crop, val 2.330 crop (PNG), `train_annotation.txt`, `val_annotation.txt` (định dạng VietOCR `đường_dẫn<TAB>nhãn`), `crops.csv` (nhãn trường của từng crop), `build_summary.json`; 0 ký tự ngoài bộ từ vựng VietOCR; khoảng 222 MB |
| Script dựng dữ liệu | `ai-service/src/invoice_ai/ocr/vietocr_data.py` |
| Script fine-tune / đánh giá | `ai-service/src/invoice_ai/ocr/vietocr_finetune.py` |
| Cài môi trường VM | `ai-service/runtime/b7/setup_ubuntu.sh`, `requirements-vietocr.txt` |
| Chạy từng bước | `ai-service/runtime/b7/run_b7.sh` |
| Gói tải lên | `experiments/artifacts/b7/b7_bundle.zip` (code + dữ liệu) |

Đã kiểm tra trên máy cá nhân (CPU, không huấn luyện): cấu hình `train --dry-run` đúng; `evaluate` với VietOCR gốc chạy được trên 5 crop; mọi dòng nhãn hợp lệ và ảnh tồn tại.

## Các bước trên VM (Ubuntu, GPU ≥ 16 GB)

```bash
unzip b7_bundle.zip -d b7 && cd b7
bash ai-service/runtime/b7/setup_ubuntu.sh            # khoảng 10–15 phút; dừng nếu nvidia-smi lỗi
bash ai-service/runtime/b7/run_b7.sh bench            # 200 vòng: xem "seconds_per_iter" trong runs_b7/bench_*/train_summary.json
bash ai-service/runtime/b7/run_b7.sh baseline         # E1: VietOCR gốc trên val (tải trọng số gốc 548 MB lần đầu)
ITERS=20000 bash ai-service/runtime/b7/run_b7.sh train    # fine-tune; chạy nền: nohup ... &
ITERS=20000 bash ai-service/runtime/b7/run_b7.sh evaluate # CER theo nhãn trên val
bash ai-service/runtime/b7/run_b7.sh pack             # nén kết quả để tải về
```

- Chọn `ITERS` theo kết quả `bench`: 20.000 vòng khoảng 37 epoch với batch 32. Ước tính 30–60 phút trên RTX 5060 Ti (chưa đo).
- Thử thêm (tùy thời gian): `MODEL=vgg_seq2seq` (nhanh hơn), hoặc tắt augmentation bằng cách chạy trực tiếp `python -m invoice_ai.ocr.vietocr_finetune train ... --no-aug`.
- Trong lúc train, VietOCR tự đánh giá trên toàn bộ val mỗi 2.000 vòng và lưu `weights.pth` tốt nhất theo độ chính xác.
- **Tải về trước khi trả máy**: `b7_results_*.tar.gz` (gồm `weights.pth`, `config.yml`, `eval_val.json`, `predictions_val.csv`, `train.log`). Không phụ thuộc ổ đĩa tạm của VM.

## Đợt 2 — benchmark trên crop detector và tắt augmentation

Gói `experiments/artifacts/b7/b7_bundle_v2.zip` (829 MB) gồm code, crop GT (`data/vietocr_v1`), **crop từ box detector** (`data/det_crops_v1`: train 44.381, val 5.932; box của cấu hình B5 `C1920_b0.2_t0.15` trên ảnh thẳng) và trọng số đã fine-tune ở đợt 1 (`weights/ft_vgg_transformer_20000.pth`), nên không phải huấn luyện lại.

```bash
unzip b7_bundle_v2.zip -d b7 && cd b7
B7_SKIP_APT=1 bash ai-service/runtime/b7/setup_ubuntu.sh   # bỏ apt nếu không có sudo
nohup bash ai-service/runtime/b7/run_b7.sh benchmark2 > benchmark2.log 2>&1 &
```

`benchmark2` làm lần lượt (khoảng 1 giờ; đã chạy 17/10/2026, kết quả ở `experiments/reports/b7_benchmark2_2026-10-17/`):
1. VietOCR **gốc** đọc crop detector của val (tải trọng số gốc lần đầu);
2. huấn luyện `vgg_transformer` **tắt augmentation**, đánh giá trên crop GT val, rồi đọc crop detector val;
3. VietOCR **đã fine-tune** đọc crop detector của **train + val** (đầu vào OCR cho LayoutXLM, B8);
4. nén kết quả `b7_results_*.tar.gz`.

Không chạy song song huấn luyện với đọc crop: trên cùng GPU, tổng thời gian còn lâu hơn chạy lần lượt.

Sau khi tải về, đánh giá trên máy cá nhân (ghép box detector với vùng GT, CER theo nhãn, tỉ lệ vùng bị bỏ sót):

```bash
cd ai-service
PYTHONPATH=src python -m invoice_ai.ocr.det_crops evaluate --dataset ../dataset_hoadon/dataset_upright_v1 \
  --crops ../dataset_hoadon/det_crops_v1 --predictions <runs>/ft_vgg_transformer_20000_bundled/predictions_det_all.csv --split val
PYTHONPATH=src python -m invoice_ai.ocr.det_crops export-cache --dataset ../dataset_hoadon/dataset_upright_v1 \
  --crops ../dataset_hoadon/det_crops_v1 --predictions <...>/predictions_det_all.csv --split train --out ../experiments/data/processed/ocr_v2_cache
```

## Chọn mô hình

- So `eval_val.json` của `pretrained_*` (E1) và `ft_*` (E2): CER tổng và CER theo nhãn (ưu tiên ADDRESS, ITEM_NAME là nơi PaddleOCR yếu).
- Mốc cần vượt: `PP-OCRv6_medium_rec` CER 9,5% (ADDRESS 16,8%, ITEM_NAME 11,5%) trên cùng 2.330 crop val (`experiments/reports/detection_v1_2026-10-11/`).
- Test không có trong gói dữ liệu.

## Môi trường

- PyTorch 2.8.0 cu129 (cặp đã PASS ở T05 với RTX 5060 Ti); đổi `TORCH_INDEX_URL`/`TORCH_VERSION` nếu GPU khác thế hệ.
- `vietocr==0.3.13` cài với `--no-deps`: gói này ghim `gdown==4.4.0` (bản wheel bị rỗng với setuptools mới) và `imgaug 0.4.0` cần NumPy 1.x; `requirements-vietocr.txt` ghim một bộ tương thích (đã chạy được trên Python 3.12).
