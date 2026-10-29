# B11 – Hậu xử lý kết quả LayoutXLM (2026-10-29)

## Mục đích

Biến nhãn BIO theo từ của LayoutXLM thành kết quả hoàn chỉnh theo hợp đồng backend (`AiExtractionResultMessage`): 4 trường hóa đơn, các dòng hàng, giá trị đã chuẩn hóa, cảnh báo cần duyệt. Đo chất lượng đầu-cuối theo góc nhìn người dùng: **số ô phải sửa trên mỗi hóa đơn**.

## Các bước

1. Nhãn BIO → thực thể (mỗi span một thực thể; độ tin cậy = điểm thấp nhất của các từ).
2. Thực thể → trường hóa đơn và dòng hàng (`grouping.group_document`, không đổi so với B8).
3. Chuẩn hóa giá trị:

| Trường | Quy tắc | Ví dụ |
|---|---|---|
| Tiền (`total_cost`, `unit_price`, `line_total`) | sửa O→0, l/I→1 trong số; bỏ dấu phân cách cuối; đọc phần xu viết bằng dấu phân cách nghìn; bỏ xu bằng 0; giữ số âm (trả hàng); hai số trong một ô → không xác định | `11.00O` → `11000`, `36.600.00` → `36600`, `565,600.00` → `565600` |
| Số lượng | dấu phân cách + 1–3 chữ số là phần thập phân (hàng cân); bỏ số 0 cuối | `1,00` → `1`, `0,322` → `0.322`, `10.000` → `10` |
| Thời gian | ISO `YYYY-MM-DDTHH:MM:SS`; ngày đầu tiên + giờ gần ngày nhất; chấp nhận khoảng trắng quanh dấu, `hh.mm`, AM/PM, SA/CH, "Ngày d tháng m năm yyyy", ISO; không có giờ → `00:00:00` | `19:50:33 - 14/08/2020` → `2020-08-14T19:50:33` |
| Chữ (`seller`, `address`, `item_name`) | Unicode NFC, gộp khoảng trắng | |

4. **Suy ra số lượng** khi ô số lượng trống: `số lượng = thành tiền / đơn giá`, làm tròn 3 chữ số thập phân, chỉ nhận khi tái tạo đúng thành tiền trong phạm vi **1 đồng**.
5. Cảnh báo: `FIELD_ABSENT` (giá trị trống hoặc không chuẩn hóa được), `QUANTITY_INFERRED` (số lượng do suy ra). `needs_review = true` khi và chỉ khi có cảnh báo.

## Chọn quy tắc trên GT của train

Theo nguyên tắc dữ liệu, bước không học được chọn trên **train**; dự đoán E2 trên val chỉ dùng để báo cáo và phân tích lỗi. Kiểm tra trên GT train (1.094 hóa đơn, `audit_gt_train.json`):

| Kiểm tra | Kết quả | Quyết định |
|---|---|---|
| Chuẩn hóa được giá trị GT | tiền 99,96%, số lượng 100%, thời gian 99,5% (1.070/1.075) | 5 mốc thời gian không đọc được: thiếu năm, chỉ có giờ, "Aug 13, 2020" |
| Suy ra số lượng từ đơn giá/thành tiền của GT | làm tròn 2 chữ số, sai lệch ≤ 1%: đúng 2.793, **sai 51** | hàng cân có 3 chữ số thập phân; sai lệch 1% nhận cả dòng giảm giá |
| | 3 chữ số, sai lệch ≤ 1 đồng: **đúng 2.865, sai 15**, không suy ra 15 | chọn cấu hình này; 15 trường hợp sai phần lớn do chính GT (thành tiền bị cụt "30,", số lượng gõ khác) |
| Hóa đơn in nhiều ngày: GT gán ngày nào | gán cả hai 8, chỉ ngày đầu 8, chỉ ngày sau 6, lẫn lộn 1 | chọn **ngày đầu** (đúng 16/23 so với 6/23 nếu chọn ngày sau) |

## Kết quả trên val (138 hóa đơn, dự đoán E2)

Ba chế độ trên cùng dự đoán: **thô** (chữ OCR đã ghép, chưa có B11), **chuẩn hóa** (B11 không suy ra số lượng), **B11 đầy đủ**. GT dùng cùng cách ghép và chuẩn hóa. Chữ so bằng `match_key` (không phân biệt hoa/thường và khoảng trắng quanh dấu câu); số và thời gian so sau chuẩn hóa.

| Chỉ số | Thô | Chuẩn hóa | **B11** |
|---|---:|---:|---:|
| Ô phải sửa / hóa đơn | 1,92 | 1,75 | **1,46** |
| Tỉ lệ ô sai (2.179 ô) | 12,2% | 11,1% | **9,2%** |
| Hóa đơn không phải sửa gì | 31,9% | 32,6% | **35,5%** |
| Dòng hàng đúng cả 4 ô (F1) | 65,6% | 67,6% | **74,7%** |
| SELLER khớp | 84,1% | 84,1% | 84,1% |
| ADDRESS khớp | 68,1% | 68,1% | 68,1% |
| TIMESTAMP khớp | 89,1% | 94,1% | **94,1%** |
| TOTAL_COST khớp | 96,4% | 97,8% | **97,8%** |
| Số lượng suy ra (đúng / tổng) | – | – | **40 / 40** |

Phân bố số ô sai theo hóa đơn (B11): 0 ô: 49 · 1 ô: 42 · 2 ô: 27 · 3 ô: 4 · ≥ 4 ô: 16.

Ô sai theo trường (thô → B11): QUANTITY 57 → 16, TIMESTAMP 15 → 8, UNIT_PRICE 19 → 11, LINE_TOTAL 10 → 4, TOTAL_COST 5 → 3; ITEM_NAME 93, ADDRESS 44, SELLER 22 không đổi (B11 không sửa nội dung chữ).

### Định tuyến duyệt (B11)

| | Số hóa đơn |
|---|---:|
| Có cảnh báo (`needs_review`) | 27 |
| Có ít nhất một ô sai | 89 |
| Có cảnh báo và có lỗi | 21 |
| Có cảnh báo nhưng không có lỗi | 6 |
| Có lỗi nhưng không có cảnh báo | 68 |

Cảnh báo: 40 `QUANTITY_INFERRED`, 20 `FIELD_ABSENT`. Hai loại cảnh báo đã chọn **không phát hiện được lỗi chữ** (tên hàng, địa chỉ, người bán), nên 68 hóa đơn có lỗi vẫn được đánh dấu thành công; người dùng phải tự soát.

## Phân tích 201 ô sai còn lại (`errors_b11.csv`)

| Nhóm (tự động) | Số ô | Ghi chú |
|---|---:|---|
| Chữ lệch 1–2 ký tự | 115 | chủ yếu lỗi dấu và ký tự của OCR; một phần do GT gõ sai (`PHÓ MỎ`, `Cô Thô`) |
| Khác nhiều hơn | 42 | OCR đọc sai nhiều chữ, cặp dòng hàng lệch |
| Thừa hoặc thiếu từ ở biên | 22 | model gán thừa/thiếu từ (`VinMart VINCOM SKYLAKE VinCommerce`), 5 ô do GT có tiền tố `ĐC:` mà dự đoán không có |
| Bỏ sót giá trị | 12 | |
| Dự đoán thừa giá trị GT không có / dòng hàng thừa | 10 | |

Trong 201 ô: **47 ô chỉ khác dấu tiếng Việt** (gồm cả vị trí dấu thanh `Thuỵ`/`Thụy`, theo quyết định ngày 23/10 không chuẩn hóa) và **19 ô chỉ khác dấu câu**. Nhóm lớn nhất là lỗi nhận dạng chữ, không phải hậu xử lý.

Lỗi thời gian còn lại (8): GT chỉ gán ngày nhưng dự đoán có cả giờ (2); hai mốc thời gian, GT chọn mốc sau (2); OCR sai số (2); OCR dính dạng `10/2020-17 30` và `13/8/2020:5:51:28 PM` không đọc được (2).

## Hạn chế và đề xuất (chưa làm)

- Số trên val được báo cáo sau khi đã xem lỗi E2 val (không chỉnh quy tắc theo val), nên vẫn có thể hơi lạc quan; con số khách quan là lần chạy test.
- Cảnh báo không bắt được lỗi chữ. Có thể thêm cảnh báo theo độ tin cậy, hoặc kiểm tra `số lượng × đơn giá = thành tiền` (đúng ~98,7% dữ liệu) nếu muốn đưa thêm hóa đơn nghi ngờ sang duyệt.
- Bỏ tiền tố `ĐC:`, `Ngày bán:` khi chuẩn hóa (5 ô), như ghi trong kế hoạch B11 ban đầu.
- Số lượng suy ra không có vùng chữ riêng; `evidence` là vùng đơn giá và thành tiền dùng để tính.

## Tái lập

```bash
cd ai-service
python -m invoice_ai.kie.evaluate_e2e audit-gt --dataset ../dataset_hoadon/dataset_upright_v1 --split train \
    --ocr ../experiments/data/processed/kie_bio_v3/train.ocr.jsonl --out ../experiments/reports/b11_postprocess_2026-10-29
python -m invoice_ai.kie.evaluate_e2e evaluate --dataset ../dataset_hoadon/dataset_upright_v1 --split val \
    --predictions ../experiments/artifacts/b10/b10_results_20261026/e2/predict_val/predictions.jsonl \
    --ocr ../experiments/data/processed/kie_bio_v3/val.ocr.jsonl --out ../experiments/reports/b11_postprocess_2026-10-29
```

| Tệp | Nội dung |
|---|---|
| `audit_gt_train.json` | kiểm tra chuẩn hóa, suy ra số lượng, chọn ngày trên GT train |
| `metrics_val.json` | chỉ số ba chế độ |
| `errors_b11.csv` | mọi ô sai của B11 (GT, dự đoán, chữ OCR gốc) |
| `per_document_b11.csv` | số ô sai, dòng hàng và cảnh báo theo hóa đơn |

Code: `ai-service/src/invoice_ai/kie/postprocess.py`, `kie/evaluate_e2e.py`, chuẩn hóa mới trong `normalization/core.py` (`normalize_amount`, `normalize_quantity`, `normalize_timestamp`); test `ai-service/tests/test_postprocess.py`.
