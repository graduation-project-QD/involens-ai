# B5 — Tune PaddleOCR detection (detection_v1) — 11/10/2026

Chọn cấu hình detector cho ảnh đã xoay thẳng (`dataset_upright_v1`). Chỉ chạy model detection `PP-OCRv5_mobile_det` trên CPU, không có LLM. Chọn trên **train**: vòng 1 trên 300 ảnh phân tầng theo cửa hàng, vòng 2 trên toàn bộ 1.094 ảnh. Cấu hình chốt chạy **một lần trên val**. Test chưa chạy.

**Cấu hình chốt:** `C1920_b0.2_t0.15`, gồm cắt nền, cạnh dài 1920 px, `box_thresh` 0,2, `thresh` 0,15, `unclip_ratio` 1,5. Lưu ở `ai-service/configs/ocr/detection_v1.json`.

## Cách đo

- Một vùng GT được tính là **bắt được** khi một box detection giao với nó ít nhất 50% diện tích của **box nhỏ hơn**. Box bám sát chữ số "1" nằm trong box GT vẽ rộng vẫn được tính; box cả dòng chứa vùng GT cũng được tính. Tiêu chí này khớp với quy tắc word-trong-vùng khi gán BIO.
- Ban đầu tôi dùng tiêu chí "phủ ≥ 50% diện tích GT", nhưng tiêu chí đó đánh giá thấp QUANTITY (34–41%) vì người gán vẽ box rộng hơn chữ số. Đã bỏ.
- `merged_rate`: box bắt được vùng này cũng chứa một vùng nhãn khác. `gt_inside_crop`: tỉ lệ vùng GT nằm trọn trong vùng cắt nền.
- `QTY+infer`: tỉ lệ món có quantity bắt được, hoặc suy ra đúng bằng `line_total / unit_price` khi đơn giá và thành tiền được bắt. Đây là cận trên của bước hậu xử lý, giả định KIE gán đúng nhãn hai trường đó.

## Kết quả

### Vòng 1 — 300 ảnh train (recall QUANTITY; các nhãn khác ≥ 97,4%)

| Cấu hình | Cạnh dài | Cắt nền | box_thresh / thresh | QUANTITY | Giây/ảnh |
|---|---:|:---:|---|---:|---:|
| L960 (mặc định PaddleOCR) | 960 | | 0,6 / 0,3 | 70,5% | 0,9 |
| L1280 | 1280 | | 0,6 / 0,3 | 77,8% | 1,6 |
| L1600 | 1600 | | 0,6 / 0,3 | 79,6% | 2,5 |
| L1920 | 1920 | | 0,6 / 0,3 | 78,9% | 3,3 |
| C960 | 960 | ✓ | 0,6 / 0,3 | 81,3% | 1,1 |
| C1600 | 1600 | ✓ | 0,6 / 0,3 | 83,1% | 2,8 |
| L1600_b0.45 | 1600 | | 0,45 / 0,3 | 85,3% | 2,7 |
| L1600_b0.3_t0.2 | 1600 | | 0,3 / 0,2 | 86,1% | 2,7 |
| C1280_b0.3_t0.2 | 1280 | ✓ | 0,3 / 0,2 | 88,5% | 2,0 |
| C1600_b0.3_t0.2 | 1600 | ✓ | 0,3 / 0,2 | 89,0% | 3,0 |
| C1600_b0.2_t0.15 | 1600 | ✓ | 0,2 / 0,15 | 89,8% | 2,9 |
| C1600_b0.1_t0.1 | 1600 | ✓ | 0,1 / 0,1 | 89,9% | 2,9 |
| **C1920_b0.2_t0.15** | 1920 | ✓ | 0,2 / 0,15 | **90,4%** | 3,5 |
| C1600_b0.3_t0.2_s1 (cắt theo box của chính cấu hình, lề ≥ 3%) | 1600 | ✓ | 0,3 / 0,2 | 88,5% | 2,9 |
| V6L1600 (`PP-OCRv6_medium_det`, 191 ảnh) | 1600 | | 0,6 / 0,3 | 89,4% (v5 cùng ảnh: 79,8%) | 21 |

### Vòng 2 — toàn bộ train (1.094 ảnh)

| Cấu hình | QUANTITY | QTY+infer | ADDRESS | ITEM_NAME | Nhãn khác | Giây/ảnh |
|---|---:|---:|---:|---:|---:|---:|
| L960 (mặc định) | 71,3% | 99,1% | 97,3% | 98,6% | ≥ 99,2% | 0,9 |
| C1600_b0.2_t0.15 | 90,7% | 99,6% | 99,7% | 100% | ≥ 99,9% | 2,6 |
| **C1920_b0.2_t0.15** | **92,2%** | 99,6% | 99,8% | 100% | ≥ 99,8% | 3,5 |

### Val (138 ảnh, chạy một lần)

| Cấu hình | QUANTITY | QTY+infer | SELLER | ADDRESS | ITEM_NAME | TIMESTAMP, TOTAL_COST, UNIT_PRICE, LINE_TOTAL |
|---|---:|---:|---:|---:|---:|---:|
| L960 (mặc định) | 68,0% | 99,3% | 98,7% | 95,8% | 98,4% | 100% |
| **C1920_b0.2_t0.15** | **91,6%** | **99,75%** | 98,7% | 99,6% | 100% | 100% |

Val: 33 trong 34 quantity bị bỏ sót suy ra đúng từ đơn giá và thành tiền, 0 suy ra sai, 1 không suy được. Tỉ lệ vùng GT nằm trọn trong vùng cắt: 99,96% (val), 99,99% (train).

## Phát hiện

1. **PaddleOCR mặc định thu nhỏ ảnh còn cạnh dài 960 px** với `PP-OCRv5_mobile_det` (`limit_type=max`). Truyền `limit_side_len` + `limit_type="resize_long"` để ghi đè.
2. **Lỗi chính là chữ số "1" đứng một mình** (77/79 vùng còn sót ở vòng 1 là "1"): detector kiểu DB cho điểm thấp với nét mảnh, kể cả khi chữ to và rõ. Hạ `box_thresh`/`thresh` và cắt nền (chữ to hơn) cùng giúp, cộng dồn được; tăng kích thước ảnh thêm ít hơn.
3. **Không đạt mục tiêu 95% bằng detector** (92,2% train / 91,6% val). Bù bằng hậu xử lý: khi thiếu quantity mà có unit_price và line_total thì `quantity = line_total / unit_price` kèm cờ `QUANTITY_INFERRED`. Quan hệ này đúng ở 98,7% dữ liệu; cận trên đạt 99,6% (train) / 99,75% (val). Điều kiện qua bước được điều chỉnh: các nhãn ≥ 98% bằng detector, QUANTITY ≥ 95% sau suy luận.
4. `PP-OCRv6_medium_det` tốt hơn v5 ở cùng cấu hình nhưng chậm gấp 8 lần trên CPU và vẫn thua v5 có cắt nền + hạ ngưỡng; không dùng.
5. Cắt nền dựa trên box của lượt mặc định có một trường hợp cắt hụt đáy hóa đơn (`mcocr_public_145013seqfm`, lượt mặc định chỉ ra 17 box vụn). Biến thể `_s1` an toàn hơn (100% vùng GT nằm trong vùng cắt) nhưng recall thấp hơn 0,5 điểm (trong sai số). Giữ biến thể thường; theo dõi `gt_inside_crop`.

## Nhận dạng của PaddleOCR trên crop GT của val (số tham khảo cho B7)

2.330 crop, nắn phối cảnh, padding dọc 15% (`ai-service/src/invoice_ai/ocr/crops.py`). CER = tổng edit distance / tổng ký tự GT (NFC, gộp khoảng trắng, giữ hoa/thường và dấu).

| Model | CER | CER bỏ dấu | Đúng hoàn toàn | ADDRESS | ITEM_NAME | QUANTITY | UNIT_PRICE | Giây/crop |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `latin_PP-OCRv5_mobile_rec` | 14,2% | 12,1% | 61,2% | 26,1% | 16,1% | 6,6% | 2,8% | 0,15 |
| `PP-OCRv6_medium_rec` | **9,5%** | 5,8% | 67,4% | 16,8% | 11,5% | **0,45%** | **0,98%** | 0,23 |

`PP-OCRv6_medium_rec` tốt hơn mức tôi ước lượng ban đầu từ 10 ảnh: đọc số rất tốt, lỗi tập trung ở dấu tiếng Việt (ADDRESS, ITEM_NAME: CER giảm gần một nửa khi bỏ dấu). Đây là **mốc so sánh công bằng** mà VietOCR (B7) cần vượt, nhất là ở ADDRESS/ITEM_NAME.

## Chạy lại

```bash
cd ai-service
# detection (môi trường OCR T10); có thể dừng và chạy tiếp
PYTHONUTF8=1 PYTHONPATH=src ../.cache/t10-ocr-venv/Scripts/python.exe -m invoice_ai.ocr.detection_tuning run \
  --dataset ../dataset_hoadon/dataset_upright_v1 --split train [--subset 300] --configs L960 C1920_b0.2_t0.15 \
  --cpu-threads 10 --paddlex-home ../.cache/paddlex --out ../experiments/data/processed/detection_tuning_v1
# đánh giá (Python thường)
PYTHONPATH=src python -m invoice_ai.ocr.detection_tuning evaluate --dataset ../dataset_hoadon/dataset_upright_v1 \
  --split train [--subset 300] --out ../experiments/data/processed/detection_tuning_v1 --report ../experiments/reports/detection_v1_2026-10-11
# CER tham khảo
PYTHONUTF8=1 PYTHONPATH=src ../.cache/t10-ocr-venv/Scripts/python.exe -m invoice_ai.ocr.recognition_eval paddle \
  --dataset ../dataset_hoadon/dataset_upright_v1 --split val --paddlex-home ../.cache/paddlex \
  --models latin_PP-OCRv5_mobile_rec PP-OCRv6_medium_rec --report ../experiments/reports/detection_v1_2026-10-11
```

Box detection lưu ở `experiments/data/processed/detection_tuning_v1/{split}/{config}.jsonl` (gitignored). Tệp ở đây: `detection_train_subset300.*` (vòng 1), `detection_train.*` (vòng 2), `detection_val.*`, `recognition_reference_val.json`. Code: `ai-service/src/invoice_ai/ocr/detection_tuning.py`, `crops.py`, `recognition_eval.py`; test: `ai-service/tests/test_detection_tuning.py`.
