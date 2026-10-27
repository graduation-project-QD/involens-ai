# B7 đợt 2 — VietOCR trên crop detector và ablation augmentation — 17/10/2026

Tiếp theo `b7_vietocr_2026-10-15/`. Mục tiêu: đo VietOCR trong điều kiện thật của pipeline (đọc crop từ box detector B5 `C1920_b0.2_t0.15` trên ảnh thẳng), và kiểm tra augmentation có cần không. Mọi số đo trên **val**; test chưa dùng.

## Bốn cấu hình

| # | Recognizer | Crop đọc |
|---|---|---|
| 1 | VietOCR gốc `vgg_transformer` | detector |
| 2 | Fine-tune, augmentation bật (trọng số đợt 1) | detector |
| 3 | Fine-tune, augmentation tắt (huấn luyện mới, 20.000 vòng, cùng cấu hình còn lại) | GT |
| 4 | Như 3 | detector |

Chấm điểm trên crop detector (`ocr.det_crops evaluate`): với mỗi vùng GT, ghép chữ của các box detector phủ ≥ 50% diện tích nhỏ hơn theo thứ tự đọc, CER tính với chuỗi con khớp nhất (chữ thừa của box gộp không bị phạt). Vùng không có box nào: tính sai toàn bộ (`missed`).

## Kết quả trên val

### Crop GT (2.330 crop) — chỉ đo nhận dạng

| Recognizer | CER | CER bỏ dấu | Đúng hoàn toàn |
|---|---:|---:|---:|
| VietOCR gốc (đợt 1) | 6,19% | 5,02% | 71,9% |
| Fine-tune, augmentation bật (đợt 1) | **1,41%** | **1,06%** | 90,2% |
| Fine-tune, augmentation tắt (#3) | 1,48% | 1,10% | 90,2% |

### Crop detector (5.932 crop, 2.331 vùng GT, 1,6% vùng không có box) — detector + nhận dạng

| Recognizer | CER | Đúng hoàn toàn |
|---|---:|---:|
| VietOCR gốc (#1) | 6,16% | 71,6% |
| **Fine-tune, augmentation bật (#2)** | **1,78%** | **88,0%** |
| Fine-tune, augmentation tắt (#4) | 1,87% | 87,3% |

### CER theo nhãn trên crop detector

| Nhãn | Bỏ sót | Gốc (#1) | **Aug bật (#2)** | Aug tắt (#4) |
|---|---:|---:|---:|---:|
| SELLER | 1,3% | 7,8% | 2,4% | 2,2% |
| ADDRESS | 0,4% | 8,0% | 2,3% | 2,4% |
| TIMESTAMP | 0% | 3,5% | 1,8% | 1,8% |
| TOTAL_COST | 0% | 3,3% | **0,8%** | 1,1% |
| ITEM_NAME | 0% | 7,7% | 1,6% | 1,8% |
| QUANTITY | 8,4% | 10,9% | 11,1% | 12,1% |
| UNIT_PRICE | 0% | 1,0% | 0,6% | 0,6% |
| LINE_TOTAL | 0% | 1,6% | 0,2% | 0,4% |

## Nhận xét

- **Chọn bản fine-tune có augmentation (#2)** cho pipeline: tốt nhất trên crop detector (CER 1,78%), tốt hơn hoặc ngang bản tắt augmentation ở hầu hết nhãn.
- Augmentation chỉ giúp ít (CER 1,41% so với 1,48% trên crop GT; 1,78% so với 1,87% trên crop detector). Chỉ số VietOCR tự đo trong lúc train còn nhỉnh hơn ở bản tắt augmentation (93,6% đúng hoàn toàn ở vòng 20.000 so với 93,3%), nên hai bản về thực chất là ngang nhau.
- Chuyển từ crop GT sang crop detector chỉ làm CER tăng khoảng 0,4 điểm (1,41% → 1,78%). Phần lớn chênh lệch đến từ QUANTITY: 8,4% vùng số lượng không có box (đã biết từ B5; xử lý bằng suy luận `line_total / unit_price`). Số lượng chỉ 1–2 ký tự nên mỗi vùng bỏ sót đẩy CER của nhãn lên rất mạnh; tỉ lệ đọc đúng hoàn toàn vẫn 88%.
- Bản tắt augmentation có CER QUANTITY trên crop GT là 4,1% dù đúng hoàn toàn 99,5%: gần như toàn bộ do 1 crop 27 × 28 px, số "5" bị đọc thành "Phúc Anh Minimart" (lỗi "ảo giác" của seq2seq). Bản có augmentation đọc crop đó thành "6".
- VietOCR gốc cho kết quả gần như nhau trên crop GT và crop detector (6,19% / 6,16%), cho thấy crop detector không làm khó hơn nhiều; fine-tune vẫn là cải thiện chính.

## Đầu ra cho B8

`experiments/data/processed/ocr_v2_cache/{train,val}/` — OCR cache theo định dạng T10 (khung ảnh thẳng), chữ do **bản #2** đọc trên box detector: train 1.094 ảnh, val 138 ảnh. Dùng cho `kie.build_bio --ocr-frame upright`.

## Chi phí (VM RTX 5060 Ti, 17/10/2026)

| Bước | Thời gian |
|---|---|
| Tải gói 829 MB lên | 21 giây |
| Cài môi trường | khoảng 6 phút |
| Huấn luyện tắt augmentation 20.000 vòng | 25,9 phút (0,078 giây/vòng) |
| Đọc 50.313 crop detector (train + val) | khoảng 25 phút khi chạy một mình (0,03 giây/crop) |
| Tổng thời gian thuê | khoảng 1 giờ 25 phút |

Ghi chú vận hành: chạy song song huấn luyện và đọc crop trên cùng GPU **chậm hơn** chạy lần lượt (đọc crop từ 0,03 lên 0,1 giây/crop); hai tiến trình cùng tải trọng số gốc vào `/tmp` làm hỏng file. `run_b7.sh benchmark2` đã sửa thành chạy lần lượt.

## Tệp

Kết quả đầy đủ (gitignored): `experiments/artifacts/b7/b7_results_20261017_full/` (từ `b7_results_20261017T151648.tar.gz`, SHA-256 `9e41cf28…f048`; gồm trọng số bản tắt augmentation 152 MB và `predictions_det_all.csv`). Ở đây: các `eval_*.json`, `train_noaug.log`, `train_summary_noaug.json`.
