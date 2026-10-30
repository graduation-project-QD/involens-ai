# B12 – Baseline luật so với LayoutXLM (2026-10-29)

## Mục đích

Đo xem LayoutXLM có thực sự cần thiết hay không: thay bước gán nhãn LayoutXLM bằng **luật cố định** (từ khóa, regex, vị trí), giữ nguyên mọi phần còn lại.

```
ảnh → detector → VietOCR ─┬─ LayoutXLM (E2) ─┬─→ ghép trường/dòng hàng + chuẩn hóa B11 → evaluate_e2e
                          └─ Luật (B12) ──────┘
```

Cùng OCR (`kie_bio_v3`), cùng `postprocess.py` (B11), cùng `evaluate_e2e.py`; chỉ khác bước gán nhãn. Luật xuất nhãn BIO theo từ, đúng định dạng `predictions.jsonl` của LayoutXLM (`score = null`). Không dùng danh sách tên cửa hàng.

## Luật

| Trường | Luật |
|---|---|
| TIMESTAMP | ngày đầu tiên theo thứ tự đọc (khớp trên cả dòng, nên bắt được ngày bị tách thành nhiều từ) + giờ in ngay trước/sau |
| TOTAL_COST | dòng có từ khóa ưu tiên cao nhất ("tổng số tiền thanh toán" > "tổng thanh toán" > … > "tổng cộng" > "tổng"), bỏ dòng "khách đưa", "tiền thừa", "phương thức", "giảm", VAT…; lấy số tiền ngoài cùng bên phải cùng hàng, hoặc ở hàng kế |
| Vùng đầu / vùng hàng | vùng hàng bắt đầu sau dòng tiêu đề bảng (≥ 2 từ khóa cột: "tên hàng", "SL", "đơn giá", "thành tiền", "STT", "ĐVT"…); nếu không có thì sau dòng ngày giờ hoặc dòng tiền đầu tiên; kết thúc ở dòng tổng |
| ADDRESS | dòng vùng đầu có tín hiệu địa chỉ (ĐC, đường, phường, quận, TP, P., Q., số nhà + tên đường…), bỏ nhãn "ĐC:" ở đầu |
| SELLER | trong 4 dòng chữ đầu tiên còn lại của vùng đầu (loại địa chỉ, điện thoại, ngày, "hóa đơn", "khách hàng", tiêu đề cột…), chọn dòng chữ cao nhất |
| Dòng hàng | mỗi hàng: bỏ mã vạch (8–14 chữ số, kể cả khi OCR đọc 0 thành O), mã VAT, dòng giảm giá/giá gốc/VAT; chữ trước số đầu tiên → ITEM_NAME (bỏ đơn vị cuối như GÓI, HỘP, KG); số tiền ngoài cùng bên phải → LINE_TOTAL; cặp số thỏa `SL × ĐG = TT` (sai lệch ≤ 1 đồng) → QUANTITY/UNIT_PRICE, nếu không thì số nhỏ → QUANTITY, số tiền còn lại → UNIT_PRICE; số 0 (cột chiết khấu) bị bỏ qua |

"Số tiền": có dấu phân cách nghìn hoặc ký hiệu đ, hoặc 4–7 chữ số không bắt đầu bằng 0 (loại số lượng, số cân `0,498`, số điện thoại, mã vạch).

### Quá trình chỉnh luật trên train (1.094 hóa đơn, sau B11)

| Phiên bản | Ô sai / hóa đơn | F1 dòng hàng | Ghi chú |
|---|---:|---:|---|
| v0 | 4,49 | 29,8% | |
| + mã vạch bị đọc thành chữ, mã VAT, đơn vị, số cân không phải tiền, vùng đầu kết thúc ở dòng tiền đầu tiên, gán số lượng cho hàng chỉ có một số | 5,78 | 27,1% | hàng chỉ có một số tạo nhiều dòng hàng thừa |
| + số điện thoại không phải tiền | 4,37 | 43,6% | số điện thoại ở đầu hóa đơn làm vùng hàng bắt đầu quá sớm |
| − bỏ luật "hàng chỉ có một số là số lượng" | 3,84 | 45,8% | số đứng một mình thường là STT; B11 tự suy ra số lượng |
| + ngày giờ khớp trên cả dòng, loại thêm dòng "khách hàng", "hotline" khỏi SELLER | **3,77** | 43,8% | TIMESTAMP 86,4% → 89,9% |

Dừng ở phiên bản cuối theo giới hạn công sức (1–2 buổi). Val chỉ chạy một lần với phiên bản cuối.

## Kết quả

### Val (138 hóa đơn), cả hai sau B11

| Chỉ số | Luật (B12) | LayoutXLM (E2) |
|---|---:|---:|
| Ô phải sửa / hóa đơn | 4,17 | **1,46** |
| Tỉ lệ ô sai | 25,0% | **9,2%** |
| Hóa đơn không phải sửa gì | 15,2% | **35,5%** |
| Dòng hàng đúng cả 4 ô (F1) | 37,8% (P 35,7%, R 40,3%) | **74,7%** |
| SELLER khớp | 72,5% | **84,1%** |
| ADDRESS khớp | 56,5% | **68,1%** |
| TIMESTAMP khớp | **95,6%** | 94,1% |
| TOTAL_COST khớp | 93,5% | **97,8%** |
| Số lượng suy ra ở B11 (đúng / tổng) | 35 / 35 | 40 / 40 |

Luật trên train (tập chỉnh luật): 3,77 ô sai / hóa đơn, F1 dòng hàng 43,8%, SELLER 78,2%, ADDRESS 58,4%, TIMESTAMP 89,9%, TOTAL_COST 91,6%.

### Mức chắc chắn của chênh lệch (bootstrap ghép cặp theo hóa đơn, 10.000 lần)

| | Chênh lệch (luật − LayoutXLM) | Khoảng tin cậy 95% |
|---|---:|---|
| Ô sai / hóa đơn | +2,71 | [+2,04; +3,47] |
| Tỉ lệ dòng hàng tìm đúng (recall) | −34,4 điểm | [−39,9; −28,9] |

So từng hóa đơn: luật kém hơn ở 89, bằng ở 48, tốt hơn ở 1 hóa đơn.

### Ô sai theo trường (val)

| Trường | Luật | LayoutXLM |
|---|---:|---:|
| ITEM_NAME | 280 | 93 |
| LINE_TOTAL | 90 | 4 |
| ADDRESS | 60 | 44 |
| UNIT_PRICE | 52 | 11 |
| QUANTITY | 40 | 16 |
| SELLER | 38 | 22 |
| TOTAL_COST | 9 | 3 |
| TIMESTAMP | 6 | 8 |

## Nhận xét

- **Dòng hàng là khác biệt lớn nhất.** F1 37,8% so với 74,7%. Lỗi chính của luật: tên hàng lẫn chữ của cột khác hoặc của hàng bên cạnh (199 ô), dòng hàng thừa từ các hàng không phải món như tạm tính, khuyến mãi (68 thành tiền thừa), thiếu đơn giá khi phép kiểm tra `SL × ĐG = TT` không khớp (43 ô). Bố cục hóa đơn MC-OCR quá đa dạng (tên trên/dưới/cùng hàng với số, cột STT, ĐVT, chiết khấu) để luật bao quát.
- **SELLER, ADDRESS** kém hơn 12 điểm: không biết tên cửa hàng thì luật phải đoán theo vị trí và cỡ chữ; dòng logo hoặc dòng chi nhánh thường bị chọn nhầm.
- **TIMESTAMP** luật ngang LayoutXLM (95,6% so với 94,1%, chênh 2 hóa đơn): ngày giờ có định dạng rất rõ nên regex đủ mạnh. **TOTAL_COST** luật 93,5%, LayoutXLM 97,8%.
- Kết luận: LayoutXLM vượt baseline luật rõ rệt và có ý nghĩa thống kê, chủ yếu nhờ dòng hàng và tên người bán/địa chỉ; với trường có định dạng cố định (ngày giờ) luật đã gần đủ.

## Tái lập

```bash
cd ai-service
python -m invoice_ai.kie.rule_baseline predict --ocr ../experiments/data/processed/kie_bio_v3/val.ocr.jsonl \
    --out ../experiments/reports/b12_rule_baseline_2026-10-29/predictions_val.jsonl
python -m invoice_ai.kie.evaluate_e2e evaluate --dataset ../dataset_hoadon/dataset_upright_v1 --split val \
    --predictions ../experiments/reports/b12_rule_baseline_2026-10-29/predictions_val.jsonl \
    --ocr ../experiments/data/processed/kie_bio_v3/val.ocr.jsonl --out ../experiments/reports/b12_rule_baseline_2026-10-29
```

(train: thay `val` bằng `train`.)

| Tệp | Nội dung |
|---|---|
| `predictions_{train,val}.jsonl` | nhãn BIO của luật (không commit vì `*.jsonl` bị bỏ qua; chạy lại lệnh trên để tạo) |
| `metrics_{train,val}.json` | chỉ số ba chế độ (thô / chuẩn hóa / B11) cho luật |
| `errors_b11.csv`, `per_document_b11.csv` | ô sai và thống kê theo hóa đơn của luật trên **val** sau B11 |

Code: `ai-service/src/invoice_ai/kie/rule_baseline.py`; test `ai-service/tests/test_rule_baseline.py`. Số của LayoutXLM lấy từ `experiments/reports/b11_postprocess_2026-10-29/`.
