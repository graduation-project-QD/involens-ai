# B10 — Fine-tune LayoutXLM trên VM GPU thuê

Huấn luyện `microsoft/layoutxlm-base` phân loại 17 nhãn BIO trên dữ liệu B9 (`layoutxlm_v1`). Train trên train, chọn epoch theo F1 thực thể trên val; test không có trong gói.

## Gói tải lên

`experiments/artifacts/b10/b10_bundle.zip`: code (`ai-service/src`, `ai-service/runtime/b10`) và `data/layoutxlm_v1` (mẫu đã tokenize, 1.232 ảnh 224 × 224, tokenizer). Trọng số gốc LayoutXLM (khoảng 1,5 GB) tải trên VM từ Hugging Face ở lần chạy đầu.

| Tệp dữ liệu | Dùng cho |
|---|---|
| `train.ocr.jsonl`, `val.ocr.jsonl` | **E2**: chữ OCR thật (PaddleOCR detection + VietOCR fine-tune) |
| `train.oracle.jsonl`, `val.oracle.jsonl` | **E3**: chữ GT trong các vùng có nhãn (trần "OCR hoàn hảo") |
| `val.ocr_pretrained.jsonl` | **E1**: model E2 chạy trên OCR của VietOCR gốc (đo lợi ích đầu-cuối của fine-tune VietOCR) |

## Các bước trên VM (Ubuntu, GPU ≥ 16 GB)

```bash
unzip b10_bundle.zip -d b10 && cd b10
bash ai-service/runtime/b10/setup_ubuntu.sh        # 10–20 phút (dựng detectron2); dừng ở mã 2 nếu thiếu g++/Python.h
bash ai-service/runtime/b10/run_b10.sh smoke       # 20 bước + đánh giá: kiểm tra tải model, bộ nhớ, tốc độ
nohup bash ai-service/runtime/b10/run_b10.sh all > b10.log 2>&1 &
```

- Nếu setup báo thiếu công cụ build, bạn tự chạy (gõ mật khẩu VM): `sudo apt-get update && sudo apt-get install -y build-essential python3-dev python3-venv git`, rồi chạy lại setup.
- `all` chạy lần lượt E2 → E3 → dự đoán (E2, E3, E1) → nén `b10_results_*.tar.gz`. Không chạy song song trên GPU (B7: song song chậm hơn).
- Theo dõi: `tail -f runs_b10/e2.log` (mỗi epoch một dòng: loss, F1/precision/recall trên val, số phút).

## Tham số

| Tham số | Giá trị | Ghi chú |
|---|---|---|
| Model | `microsoft/layoutxlm-base` | chữ + box 2D + ảnh 224 × 224 |
| Epoch tối đa | 30 (1 epoch ≈ 139 bước với batch 8) | dừng sớm nếu F1 val không tăng sau 8 epoch; giữ epoch tốt nhất |
| Batch | 8 | |
| Tốc độ học | 5·10⁻⁵, khởi động tuyến tính 10% rồi giảm tuyến tính về 0 | trong khoảng thường dùng khi fine-tune mô hình kiểu BERT (2·10⁻⁵–5·10⁻⁵); đổi bằng `LR=3e-5` |
| Weight decay / clip gradient | 0,01 / 1,0 | |
| Độ chính xác | bf16 autocast | `--no-amp` để tắt |
| Seed | 42 | |
| Chọn model | F1 thực thể (micro) trên val, so khớp chính xác cả cụm từ | gold `IGNORE` không tính |

## Đầu ra (mỗi thí nghiệm `runs_b10/e2`, `e3`)

`best/` (trọng số tốt nhất), `train_config.json`, `history.json` (từng epoch), `best_val_scores.json` (F1 theo nhãn), `train_summary.json`, `predict_val*/scores.json` và `predictions.jsonl` (nhãn và điểm tin cậy theo từ, cho B11).

**Tải về trước khi trả máy**: `b10_results_*.tar.gz` (khoảng 3 GB vì gồm trọng số E2 và E3).

## Môi trường

PyTorch 2.8.0 cu129 (như B7), transformers 4.57.1, detectron2 commit `1e3e13bb` (30/09/2026) dựng từ mã nguồn với phần mở rộng CPU (chỉ dùng backbone ResNeXt-FPN, không cần nvcc). Setup kiểm tra bằng một lượt forward/backward của model cỡ LayoutXLM trên GPU.
