# Pilot gán BIO cho LayoutXLM (kie_bio_v1) — 10/10/2026

Chạy thử bước ghép box GT với word OCR và gán nhãn BIO, dùng **OCR cache cũ của T10** (PP-OCRv5 mobile det + `latin_PP-OCRv5_mobile_rec`, chạy trên ảnh gốc chưa xoay). Cache chỉ có 220 ảnh train trùng với `dataset_merge`, không có ảnh val. Kết quả dùng để kiểm tra code và ước lượng tỉ lệ alignment; **không** phải dữ liệu train cuối.

- Code: `ai-service/src/invoice_ai/kie/bio.py`, `build_bio.py`
- Output (gitignored): `experiments/data/processed/kie_bio_pilot_2026-10-10/{split}.ocr.jsonl`, `{split}.oracle.jsonl`
- Chạy lại: `cd ai-service && PYTHONPATH=src python -m invoice_ai.kie.build_bio --dataset ../dataset_hoadon/dataset_merge --ocr-cache ../experiments/runs/ocr_v1/cache --ocr-frame source --out <thư mục>`

## Quy tắc gán nhãn

- Mỗi box GT là một entity: word đầu `B-`, các word sau `I-`. Gộp dòng/dòng hàng để cho `grouping`.
- Word thuộc box GT phủ ≥ 50% diện tích word; phủ 20–50% → `IGNORE` (-100); còn lại `O`.
- Box word ước lượng theo vị trí ký tự trên quad của dòng OCR. Token dạng `Ngày:15/08/2020` được tách tại dấu ":" sau chữ cái.
- Tiền tố trong ADDRESS/TIMESTAMP ("ĐC:", "Ngày bán:") gán `O` vì nhãn không nhất quán.
- Word lạc chen giữa một box làm phần sau thành `B-` mới để chuỗi luôn hợp lệ (2 trường hợp / 3.345 entity).
- 17 nhãn: `O` + B/I × 8 trường. Box chuẩn hóa 0–1000 theo ảnh đã xoay thẳng.
- File `oracle`: giữ word OCR nền (`O`), thay mọi vùng GT bằng text + box GT. Dùng cho thí nghiệm "OCR hoàn hảo" mà vẫn có token nền thật.

## Kết quả (205 ảnh gần thẳng, |góc| ≤ 10°)

| Nhãn | Vùng ghép được | CER trung vị | Text khớp chính xác |
|---|---:|---:|---:|
| SELLER | 99.5% | 0.00 | 65.7% |
| ADDRESS | 98.6% | 0.14 | 8.3% |
| TIMESTAMP | 99.0% | 0.00 | 91.8% |
| TOTAL_COST | 99.5% | 0.00 | 73.2% |
| ITEM_NAME | 99.8% | 0.08 | 21.6% |
| **QUANTITY** | **72.1%** | 0.00 | 94.3% |
| UNIT_PRICE | 99.8% | 0.00 | 96.6% |
| LINE_TOTAL | 100% | 0.00 | 76.2% |
| Tổng | 94.8% | | |

Word `IGNORE`: 0,9%. Không có tài liệu nào có chuỗi BIO lỗi.

## Nhận xét

- **QUANTITY bị detector bỏ sót** (số 1 chữ số). Cần chỉnh detection (ảnh vào lớn hơn, `box_thresh`, `unclip_ratio`) trước khi train; mục tiêu ≥ 95% như kế hoạch.
- CER của ADDRESS/ITEM_NAME cao do model nhận dạng latin làm mất dấu tiếng Việt → cần VietOCR (fine-tune trên crop GT train).
- 15 ảnh xoay 90°/180° có OCR chạy trên ảnh nằm nghiêng nên box word sai trục; pipeline mới phải chạy OCR trên ảnh đã xoay thẳng (`--ocr-frame upright`).
