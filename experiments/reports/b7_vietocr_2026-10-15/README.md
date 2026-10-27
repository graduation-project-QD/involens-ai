# B7 — Fine-tune VietOCR (vietocr_finetune_v1) — 15/10/2026

Nhận dạng chữ (recognition) cho pipeline OCR: PaddleOCR chỉ tìm box (B5), VietOCR đọc chữ trong box. Fine-tune trên crop GT của **train**, chọn trên **val**. Test chưa dùng.

## Cấu hình

| Hạng mục | Giá trị |
|---|---|
| Model | VietOCR `vgg_transformer` (khởi tạo từ trọng số công bố của VietOCR) |
| Dữ liệu | `dataset_hoadon/vietocr_v1`: train 17.325 crop, val 2.330 crop (crop GT nắn phối cảnh, padding dọc 15%) |
| Huấn luyện | 20.000 vòng, batch 32, ảnh cao 32 px / rộng ≤ 512 px, OneCycle `max_lr` 3e-4, augmentation mặc định của VietOCR bật |
| Chọn checkpoint | VietOCR đánh giá trên toàn val mỗi 2.000 vòng, lưu trọng số có tỉ lệ đọc đúng hoàn toàn cao nhất (vòng 18.000: 93,3%) |
| Phần cứng | VM EzyCloudX, RTX 5060 Ti 16 GB, Ubuntu 24.04, PyTorch 2.8.0 cu129 |
| Môi trường | `ai-service/runtime/b7/` (setup_ubuntu.sh, run_b7.sh, requirements-vietocr.txt) |

## Kết quả trên val (2.330 crop, CER cùng định nghĩa với B5)

| Recognizer | CER | CER bỏ dấu | Đúng hoàn toàn | Giây/crop |
|---|---:|---:|---:|---:|
| PaddleOCR `latin_PP-OCRv5_mobile_rec` (B5, CPU) | 14,2% | 12,1% | 61,2% | 0,15 |
| PaddleOCR `PP-OCRv6_medium_rec` (B5, CPU) | 9,5% | 5,8% | 67,4% | 0,23 |
| VietOCR gốc – E1 (GPU) | 6,19% | 5,02% | 71,9% | 0,035 |
| **VietOCR fine-tune – E2 (GPU)** | **1,41%** | **1,06%** | **90,2%** | **0,027** |

### CER theo nhãn

| Nhãn | PP-OCRv6 rec | VietOCR gốc | **VietOCR fine-tune** |
|---|---:|---:|---:|
| SELLER | 4,8% | 7,2% | **1,2%** |
| ADDRESS | 16,8% | 7,0% | **1,8%** |
| TIMESTAMP | 4,7% | 3,9% | **1,7%** |
| TOTAL_COST | 3,4% | 3,0% | **0,9%** |
| ITEM_NAME | 11,5% | 8,9% | **1,7%** |
| QUANTITY | **0,45%** | 3,4% | **0,45%** |
| UNIT_PRICE | 0,98% | 1,1% | **0,69%** |
| LINE_TOTAL | 1,7% | 1,8% | **0,20%** |

Đọc đúng hoàn toàn sau fine-tune: SELLER 90,9%, ADDRESS 71,8%, TIMESTAMP 88,4%, TOTAL_COST 97,8%, ITEM_NAME 76,2%, QUANTITY 99,5%, UNIT_PRICE 96,8%, LINE_TOTAL 98,8%.

### Diễn biến trên val trong lúc train (chỉ số của VietOCR)

| Vòng | Đúng hoàn toàn | Đúng theo ký tự |
|---|---:|---:|
| 10.000 | 92,8% | 98,07% |
| 14.000 | 92,8% | 98,17% |
| 18.000 (được lưu) | **93,3%** | **98,31%** |
| 20.000 | 93,1% | 98,07% |

Từ vòng 10.000 kết quả gần như đi ngang; 20.000 vòng là đủ.

## Nhận xét

- Fine-tune giảm CER 4,4 lần so với VietOCR gốc và 6,7 lần so với PP-OCRv6 rec; cải thiện lớn nhất ở ADDRESS và ITEM_NAME (dấu tiếng Việt, chữ in nhiệt mờ).
- VietOCR gốc đọc chữ số đứng một mình kém (QUANTITY 3,4%); sau fine-tune ngang mức PaddleOCR (0,45%).
- Các số liệu đo trên crop GT, tức là giả định detector khoanh đúng vùng; lỗi do detector (B5) tính riêng. Val cũng là tập đã dùng để chọn checkpoint, nên con số chính thức sẽ báo trên test ở cuối.

## Chi phí

| Bước | Thời gian (VM) |
|---|---|
| Tải gói 186 MB lên VM | 17 giây |
| Cài môi trường | khoảng 6 phút |
| Đo tốc độ (200 vòng) | 15 giây – 0,073 giây/vòng |
| VietOCR gốc trên val | khoảng 1,5 phút (gồm tải trọng số 548 MB) |
| Fine-tune 20.000 vòng | **24,3 phút** |
| Đánh giá trên val | khoảng 1 phút |
| Tổng thời gian thuê đến khi tải kết quả về | khoảng 40 phút (6.000 đ/giờ) |

## Tệp

Kết quả đầy đủ (gồm `weights.pth` 152 MB, gitignored): `experiments/artifacts/b7/b7_results_20261015/` (từ `b7_results_20261015T134704.tar.gz`, SHA-256 `07ae8329…80c`). Ở đây: `eval_val_pretrained.json`, `eval_val_finetuned.json`, `train_summary.json`, `train.log`, `config.yml`.
