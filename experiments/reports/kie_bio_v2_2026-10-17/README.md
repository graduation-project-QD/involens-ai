# B8 — Gán nhãn BIO trên OCR thật (kie_bio_v2) — 17/10/2026

Dữ liệu huấn luyện LayoutXLM: chữ và box do pipeline thật tạo ra (PaddleOCR `C1920_b0.2_t0.15` tìm box trên ảnh thẳng → VietOCR fine-tune có augmentation đọc, xem `b7_benchmark2_2026-10-17/`), nhãn lấy từ GT bằng so khớp hình học. Không gán tay.

```bash
cd ai-service
# 1. OCR cache theo ảnh (lọc chữ ảo giác)
PYTHONPATH=src python -m invoice_ai.ocr.det_crops export-cache --dataset ../dataset_hoadon/dataset_upright_v1 \
  --crops ../dataset_hoadon/det_crops_v1 --predictions <b7_results_20261017_full>/ft_vgg_transformer_20000_bundled/predictions_det_all.csv \
  --split train --out ../experiments/data/processed/ocr_v2_cache/train        # tương tự cho val
# 2. BIO
PYTHONPATH=src python -m invoice_ai.kie.build_bio --dataset ../dataset_hoadon/dataset_upright_v1 \
  --ocr-cache ../experiments/data/processed/ocr_v2_cache --ocr-frame upright --out ../experiments/data/processed/kie_bio_v2
```

Đầu ra: `experiments/data/processed/kie_bio_v3/` (bản v3, dùng cho B9; v2 giữ để so sánh) — `{train,val}.ocr.jsonl` (word, box 0–1000, tag, điểm OCR, chỉ số vùng / dòng hàng), `{train,val}.oracle.jsonl` (E3: vùng GT thay bằng chữ GT), `alignment_stats.json`. Chạy khoảng 30 giây trên CPU.

## Quy tắc (kie_bio_v2)

- Word thuộc vùng GT nếu ≥ 50% diện tích word nằm trong vùng; 20–50% → `IGNORE` (không tính loss); còn lại `O`. Word đầu vùng `B-`, sau đó `I-`.
- **Mới:** vùng GT không có word nào (thường là số lượng 1–2 chữ số mà box detector rộng gấp đôi, ví dụ ôm cả "| 10") nhận word còn tự do phủ ≥ 50% diện tích vùng, nếu độ dài word ≤ 2 × độ dài chữ GT + 2 (tránh gán "VAT10%" cho số lượng "1").
- **Mới, ở bước xuất OCR cache:** bỏ chữ của box quá nhỏ so với số ký tự đọc ra (> 5 ký tự cho mỗi đơn vị chiều cao box). VietOCR "ảo giác" trên box li ti (trung vị 10 × 8 px, phần lớn là chấm nhiễu hoặc một chữ số): 363 crop đọc thành "Phúc Anh Minimart", ngoài ra "Anh Anh Anh…". Bộ lọc bắt 458 trường hợp, gần như không bỏ nhầm chữ thật (ngưỡng 3,5 từng bỏ nhầm các dòng chữ nhỏ dày như "Số GD: … Ngày: …"). Đây cũng là lỗi của pipeline lúc chạy thật, nên bộ lọc phải có ở bước suy luận.

## Kết quả (bản cuối kie_bio_v3; số của v2 ở mục cập nhật cuối file)

| | Train | Val |
|---|---:|---:|
| Ảnh | 1.094 | 138 |
| Word | 115.381 | 15.239 |
| Vùng GT ghép được | 98,2% | 97,9% |
| Word `IGNORE` | 0,49% | 0,52% |
| Word `O` (nền) | 61,4% | 60,9% |
| Chuỗi BIO sai | 0 | 0 |

| Nhãn | Ghép được (train) | Ghép được (val) | CER chữ ghép (val) | Khớp chính xác (val) |
|---|---:|---:|---:|---:|
| SELLER | 99,8% | 98,7% | 2,1% | 88,8% |
| ADDRESS | 99,6% | 99,2% | 2,3% | 73,6% |
| TIMESTAMP | 99,9% | 100% | 1,7% | 87,7% |
| TOTAL_COST | 99,9% | 100% | 0,9% | 98,5% |
| ITEM_NAME | 100% | 100% | 1,3% | 81,4% |
| QUANTITY | 90,1% | 88,9% | 3,1% | 97,5% |
| UNIT_PRICE | 100% | 100% | 0,9% | 96,3% |
| LINE_TOTAL | 99,9% | 100% | 0,4% | 98,3% |

Bản oracle: 100% vùng, 0 chuỗi sai ở cả hai tập.

### QUANTITY

Trước các sửa đổi, QUANTITY trên val chỉ ghép được 85,5% và CER chữ ghép là 59,6% (do chữ ảo giác). Sau sửa (v3): 88,9% và 3,1%. Còn lại trên 406 vùng val:

| Nguyên nhân | Số vùng |
|---|---:|
| Không có box detector (lỗi B5, mức trần ~90,4%) | 39 |
| Có box nhưng không gán được | 6 |
| Ghép được nhưng đọc sai (ví dụ "3" → "6") | 8 |

Số lượng bị thiếu được bù ở bước hậu xử lý bằng `line_total / unit_price` (B5: 99,75% có số lượng sau suy luận).

## Ảnh kiểm tra

`mcocr_public_145013hfxkr_bio.jpg`, `mcocr_public_145014sqltv_bio.jpg`: tô màu theo nhãn (viền đậm = `B-`, xám = `O`, vàng = `IGNORE`).

## Lưu ý

- VietOCR đã học trên crop GT của train, nên chữ OCR trên ảnh train sạch hơn trên ảnh mới một chút; val không bị ảnh hưởng.
- Bản cache chưa lọc vẫn giữ ở `experiments/data/processed/ocr_v2_cache_unfiltered/` để so sánh.

## Cập nhật kie_bio_v3 (20/10/2026)

Box từ trước đây chia đều theo số ký tự, nên lệch khi một box detector chứa cả chữ ngoài vùng: mã vạch + tên hàng (VinMart), "Thời gian: <ngày> Số HĐ: …", số nhà + tên đường. Từ đầu của vùng rơi ra ngoài và bị gán `O` ("Mì omachi tôm 79g" → "omachi tôm 79g"); trên val 49/55 ca là dòng có mã vạch. Nhãn GROUND TRUTH không sai, không cần gán lại.

Sửa trong `kie/bio.py`:
- Box từ theo độ rộng ký tự (`char_width`: chữ số 0,56, chữ hoa 0,68, chữ thường 0,53, "m/w" 0,85, dấu cách và "i l . , :" 0,28 em).
- Kiểm tra bằng chữ: trong các dòng OCR chạm vùng (giao ≥ 50% diện tích nhỏ hơn), tìm đoạn chữ khớp chữ GT nhất (`substring_alignment`) và gán nhãn cho các từ có ≥ 1/2 số ký tự nằm trong đoạn đó; chỉ thay kết quả theo vị trí khi CER mới thấp hơn và < 34%, và không lấy từ của vùng khác.

| Val | v2 | v3 |
|---|---:|---:|
| ITEM_NAME: CER chữ ghép / khớp chính xác | 3,3% / 72,5% | **1,3% / 81,4%** |
| TIMESTAMP: CER / khớp chính xác | 1,9% / 87,0% | 1,7% / 87,7% |
| Vùng ghép được (toàn bộ) | 97,8% | 97,9% |
| Từ `IGNORE` | 0,84% | 0,52% |
| Vùng tốt lên / kém đi | | 60 / 0 |

Train: ITEM_NAME 2,4% / 81,4% → 0,8% / 90,3%; 398 vùng tốt lên, 1 kém đi. Ảnh so sánh: `docs/hinh_minh_hoa_BIO/bio_2_vi_du_that.png` (v2) và `bio_3_vi_du_that_sau_sua.png` (v3).

## Độ nhạy theo ngưỡng (23/10/2026)

Quét `assign_threshold` 0,3–0,7 và `ignore_threshold` 0,1–0,3 (14 cặp), đo chất lượng nhãn so với GT trên val (138 ảnh, 2.331 vùng). "Khớp chính xác" tính trên tất cả vùng GT (vùng không có nhãn tính là không khớp).

| Ngưỡng gán | Chỉ theo vị trí: vùng có nhãn / khớp chính xác / ITEM_NAME | v3 đầy đủ (vị trí + kiểm tra bằng chữ + cứu vùng nhỏ) |
|---:|---|---|
| 0,3 | 97,9% / 88,2% / 80,2% | 97,9% / 88,7% / 81,4% |
| 0,4 | 97,3% / 88,0% / 80,5% | 97,9% / 88,7% / 81,4% |
| **0,5** | 97,0% / 87,6% / 79,5% | **97,9% / 88,7% / 81,4%** |
| 0,6 | 96,6% / 86,5% / 76,5% | 97,9% / 88,7% / 81,4% |
| 0,7 | 95,5% / 84,7% / 71,8% | 97,9% / 88,7% / 81,4% |

- Chỉ theo vị trí: 0,3–0,5 gần như bằng nhau, từ 0,6 trở lên chất lượng giảm rõ (box detector thường rộng hơn chữ nên ngưỡng cao làm mất từ). 0,5 nằm giữa vùng ổn định.
- Với v3, kết quả không đổi trên cả dải 0,3–0,7: bước kiểm tra bằng chữ và cứu vùng nhỏ sửa các ca biên mà ngưỡng quyết định.
- So với cặp 50/20, các cặp khác đổi nhãn trường (B-/I-) của ≤ 0,03% số từ; phần còn lại chỉ là chuyển qua lại giữa `O` và `IGNORE` (0,1–1,6% số từ, tùy `ignore_threshold`).
- Box từ theo độ rộng ký tự tự nó đã nâng ITEM_NAME (chỉ theo vị trí, ngưỡng 0,5) từ 72,5% (v2, chia đều) lên 79,5%; bước kiểm tra bằng chữ thêm đến 81,4%.

## Rà soát cuối (23/10/2026)

- Test: `test_kie` (20 test, gồm `match_key`, box theo độ rộng ký tự, kiểm tra bằng chữ, cứu vùng nhỏ), `test_detection_tuning`, `test_orientation`, `test_preprocess_benchmark` đều đạt.
- Dữ liệu: 1.094/1.094 ảnh train và 138/138 ảnh val có OCR; 0 ảnh trùng nội dung giữa train và val; mọi bản ghi đủ trường, độ dài khớp nhau, box trong 0–1000; nhãn trường luôn khớp loại của vùng (`region_index`); 0 chuỗi BIO sai (cả bản OCR và oracle); chữ của bản oracle khớp chữ GT ở mọi vùng.
- Kiểm tra bằng chữ đổi vùng của 101 từ (train) và 14 từ (val). 25 từ được gán dù nằm < 5% trong vùng GT; xem từng ca (10 vùng): đều đúng — khung GT vẽ ngắn hơn chữ GT (SELLER chỉ trùm "Phúc" của "Phúc Anh Minimart"), hoặc số lượng chung box với đơn giá ("1 22.000").
- Quy tắc chấm `match_key` (bỏ qua hoa/thường và khoảng trắng quanh dấu câu) cố định trước khi chạy test; lần chạy đầu có lỗi chuỗi thay thế (mọi dấu câu bị coi như nhau, trường số tăng ảo), đã sửa và thêm test `"5,000" != "5.000"`.

Việc cần nhớ cho các bước sau:
- Pipeline suy luận (B11) phải dùng đúng các bước như khi tạo dữ liệu: bộ lọc chữ ảo giác `det_crops.plausible_text`, tách từ `bio.split_line` (box theo độ rộng ký tự), cùng thứ tự đọc. Bước kiểm tra bằng chữ chỉ dùng khi tạo nhãn (cần chữ GT), không có lúc suy luận.
- Test chưa có OCR cache/BIO: chỉ dựng (detector + VietOCR E2 + cùng bộ lọc) khi đánh giá cuối.
- Hạn chế: VietOCR học trên crop GT của train nên chữ OCR trên train sạch hơn ảnh mới; một số nhãn GT gõ sai được giữ nguyên để tránh sửa thiên lệch.
