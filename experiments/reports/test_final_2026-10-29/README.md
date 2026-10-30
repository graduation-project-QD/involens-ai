# Đánh giá cuối trên tập test (2026-10-29)

Chạy **một lần** trên 136 ảnh test, sau khi mọi lựa chọn đã chốt trên train/val (B4–B12). Không chỉnh tham số nào sau khi xem điểm test. Thí nghiệm: **E2** (detector + VietOCR fine-tune + LayoutXLM), **E1** (cùng mô hình LayoutXLM của E2, nhưng OCR bằng VietOCR gốc), **B12** (luật thay LayoutXLM trên OCR của E2). E3 (oracle) không chạy trên test.

## Quy trình

| Bước | Nơi chạy | Ghi chú |
|---|---|---|
| B4 tự xoay | CPU máy cá nhân | góc **tự đoán**, không dùng góc GT; tham số chọn trên train |
| Ảnh + GT xoay theo góc tự đoán | CPU | `dataset_hoadon/dataset_upright_test_auto` (GT xoay cùng ảnh để chấm đúng khung pipeline nhìn thấy) |
| Detector `C1920_b0.2_t0.15` (sau L960 cắt nền) | CPU, cùng môi trường Paddle như lúc chọn tham số | 5.414 crop, bỏ 19 box quá nhỏ |
| VietOCR gốc và fine-tune | VM RTX 5060 Ti | 0,046–0,047 giây/crop |
| Lọc chữ ảo, gán BIO, tokenize | VM | tham số như train/val |
| LayoutXLM (trọng số E2 của B10) | VM | 0,012 giây/hóa đơn |
| B11 hậu xử lý, B12 luật, `evaluate_e2e` | CPU | |

Tái lập: `ai-service/runtime/test/README.md`, `run_test.sh`. Kết quả VM: `experiments/artifacts/test/test_results_20261029/`.

## Kết quả theo tầng

### B4 – Tự xoay

| | Test | Val |
|---|---:|---:|
| Đúng hướng 0/90/180/270 | **136/136 (100%)** | 100% |
| Sai số góc trung bình (MAE) | **0,47°** | 0,46° |
| Lệch ≤ 2° | 98,5% | 97,8% |

### OCR – CER trên crop detector so với chữ GT

| | Test | Val (B7) |
|---|---:|---:|
| VietOCR gốc | 6,11% | 6,16% |
| **VietOCR fine-tune** | **1,63%** | 1,78% |
| Vùng GT bị detector bỏ sót | 1,6% (chủ yếu QUANTITY 9,1%) | |

### Gán BIO trên OCR test

Vùng GT có nhãn 98,2% (val 97,9%), 0 chuỗi BIO sai.

### LayoutXLM – F1 thực thể (theo từ, không chấm nội dung chữ)

| | Test | Val |
|---|---:|---:|
| E2 | **97,58%** | 98,05% |
| E1 | 97,60% | 97,64% |

F1 thực thể chỉ chấm vị trí nhãn, nên E1 ≈ E2: mô hình vẫn gán đúng **vùng** trên chữ OCR kém hơn. Khác biệt của OCR thể hiện ở bảng đầu-cuối dưới đây.

## Kết quả đầu-cuối (sau B11)

| Chỉ số | **E2 test** | E2 val | E1 test | E1 val | B12 luật test | B12 luật val |
|---|---:|---:|---:|---:|---:|---:|
| Ô phải sửa / hóa đơn | **1,35** | 1,46 | 2,82 | 2,91 | 3,97 | 4,17 |
| Tỉ lệ ô sai | **9,2%** | 9,2% | 19,1% | 18,4% | 25,2% | 25,0% |
| Hóa đơn không phải sửa gì | **41,2%** | 35,5% | 12,5% | 3,6% | 11,0% | 15,2% |
| Dòng hàng đúng cả 4 ô (F1) | **72,0%** | 74,7% | 44,6% | 48,7% | 35,4% | 37,8% |
| SELLER khớp | **86,8%** | 84,1% | 77,9% | 75,4% | 75,7% | 72,5% |
| ADDRESS khớp | **71,3%** | 68,1% | 31,6% | 28,3% | 58,8% | 56,5% |
| TIMESTAMP khớp | **94,1%** | 94,1% | 87,5% | 88,1% | 85,3% | 95,6% |
| TOTAL_COST khớp | **98,5%** | 97,8% | 98,5% | 96,4% | 90,4% | 93,5% |

E2 trên test trước B11 (chữ OCR đã ghép, chưa chuẩn hóa): 1,82 ô sai / hóa đơn, F1 dòng hàng 62,4% → B11 giảm còn 1,35 và tăng lên 72,0%.

Số lượng suy ra ở B11 trên test: **đúng 34/37** (val 40/40). Ô sai theo trường (E2 test, sau B11): ITEM_NAME 84, ADDRESS 39, SELLER 18, QUANTITY 14, LINE_TOTAL 11, TIMESTAMP 8, UNIT_PRICE 8, TOTAL_COST 2.

### Mức chắc chắn (bootstrap ghép cặp theo hóa đơn, 10.000 lần, test)

| So sánh | Chênh ô sai / hóa đơn | Khoảng tin cậy 95% | Hóa đơn kém hơn / bằng / tốt hơn |
|---|---:|---|---|
| Luật (B12) − LayoutXLM (E2) | +2,62 | [+2,07; +3,22] | 94 / 42 / 0 |
| VietOCR gốc (E1) − fine-tune (E2) | +1,47 | [+1,20; +1,78] | 100 / 28 / 8 |

### Cửa hàng chưa có trong train (6 hóa đơn test)

| | E2 | E1 | Luật |
|---|---:|---:|---:|
| Ô sai / hóa đơn | 4,33 | 7,50 | 7,33 |
| Tỉ lệ ô sai | 18,1% (26/144) | | |
| Dòng hàng đúng (trên 30) | 15 | 6 | 7 |

Hóa đơn của cửa hàng đã có trong train: 1,22 ô sai / hóa đơn. Với cửa hàng mới, tỉ lệ ô sai của E2 tăng khoảng gấp đôi (18% so với 9%), dù vẫn tốt hơn luật và E1. Chỉ 6 hóa đơn nên con số dao động lớn, nhưng xu hướng cho thấy giới hạn tổng quát hóa sang bố cục chưa gặp.

### Định tuyến duyệt (E2 test)

38 hóa đơn có cảnh báo (`needs_review`), 80 hóa đơn có ít nhất một ô sai. Như trên val, cảnh báo hiện tại (`FIELD_ABSENT`, `QUANTITY_INFERRED`) không bắt được lỗi chữ.

## Kết luận

1. **Test khớp val**: E2 1,35 ô sai / hóa đơn (val 1,46), F1 dòng hàng 72,0% (val 74,7%), OCR CER 1,63% (val 1,78%). Không có dấu hiệu chọn tham số quá khớp val.
2. **LayoutXLM vượt baseline luật** rõ rệt (−2,62 ô sai / hóa đơn, khoảng tin cậy không chứa 0; không hóa đơn nào luật tốt hơn), chủ yếu ở dòng hàng (72,0% so với 35,4%).
3. **Fine-tune VietOCR giảm một nửa số ô sai** đầu-cuối (2,82 → 1,35), dù F1 thực thể của LayoutXLM gần như không đổi: lợi ích nằm ở nội dung chữ (địa chỉ 31,6% → 71,3%, người bán 77,9% → 86,8%).
4. **Hạn chế**: lỗi chữ ở tên hàng và địa chỉ vẫn là nhóm lớn nhất; cửa hàng chưa gặp kém hơn rõ; cảnh báo chưa bắt được lỗi chữ.

## Tệp

| Tệp | Nội dung |
|---|---|
| `e2/`, `e1/`, `b12/` | `metrics_test.json` (thô / chuẩn hóa / B11), `errors_b11.csv`, `per_document_b11.csv` |
| `b12/predictions_test.jsonl` | nhãn của luật (không commit, tạo lại bằng `rule_baseline predict`) |
| `ocr_cer_ft.json`, `ocr_cer_pretrained.json` | CER crop detector theo nhãn |
| `comparison_test.json` | bootstrap ghép cặp, nhóm cửa hàng chưa có trong train |
| `val_e1/` | E1 trên val sau B11 (để đặt cạnh test; chạy sau, không dùng để chọn gì) |
| `../orientation_test_2026-10-29/` | B4 trên test |
