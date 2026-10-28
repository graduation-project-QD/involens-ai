# B4 — Tự xoay ảnh (orientation_v1) — 10/10/2026

Module đoán góc cần xoay để ảnh hóa đơn đứng thẳng, dùng khi chạy thật (không có file góc xoay GT). Đáp án để đo là `mcocr_{split}_rotation.csv` của `dataset_split_80_10_10`. Tham số chọn trên **train**; **val** báo cáo; **test chưa chạy** (để dành cho lần đánh giá cuối).

## Kết quả

| Tập | Ảnh | Đúng hướng 0/90/180/270 | MAE góc (có khử nghiêng) | MAE (chỉ xoay thô) | Lệch ≤ 1° | Lệch ≤ 2° |
|---|---:|---:|---:|---:|---:|---:|
| train | 1.094 | **100%** | **0,45°** | 0,77° | 79,3% | 97,5% |
| val | 138 | **100%** | **0,46°** | 0,90° | 81,2% | 97,8% |

Điều kiện qua bước trong kế hoạch (đúng hướng ≥ 98%, MAE ≤ 1°): **đạt**.

Theo lớp góc GT (train / val): 0° 1.031 / 130, 90° 45 / 6, 180° 5 / 0, 270° 13 / 2 — tất cả đúng.

## Cách hoạt động

Góc theo quy ước labeler: độ, chiều kim đồng hồ.

1. **Xoay thô**: `PP-LCNet_x1_0_doc_ori` (PaddleOCR) phân loại 0/90/180/270. Nhãn của model là góc ngược chiều kim đồng hồ: `coarse_cw = (360 − nhãn) mod 360`.
2. **Kiểm tra lật 180°**: đọc 3 dòng chữ dài nhất (tối đa 12× chiều cao) bằng `latin_PP-OCRv5_mobile_rec` theo chiều hiện tại và sau khi xoay 180°. Nếu điểm nhận dạng trung bình tăng hơn 0,1 khi xoay thì cộng thêm 180°.
3. **Khử nghiêng**: `PP-OCRv5_mobile_det` trên ảnh đã xoay thô; lấy trung vị (trọng số theo độ dài) góc của các box chữ dài (dài/cao ≥ 2, dài ≥ 30 px, ít nhất 3 box). Nghiêng < 1° thì để nguyên; > 20° thì bỏ qua.

Tham số mặc định (`DeskewParams`): `min_aspect=2.0`, `min_abs_skew=1.0`, `max_abs_skew=20`, `min_boxes=3`, `flip_margin=0.1`. Lưới quét trên train: `sweep_train/orientation_metrics.json`.

## Phát hiện

- Model phân loại một mình đạt 98,99% (train) / 99,28% (val). **Mọi lỗi của nó đều là lật 180°** (8 ảnh thẳng → 180°, 3 ảnh 90° → 270° trên train; 1 ảnh val), thường là hóa đơn nhỏ trên nền nhiều họa tiết. Bước kiểm tra lật sửa hết.
- Độ chênh điểm nhận dạng tách hai nhóm rất rõ: ảnh bị lật +0,63, mọi ảnh khác ≤ −0,35 (val). Các ngưỡng 0,05/0,1/0,2 cho cùng kết quả trên train; chọn 0,1 ở giữa.
- Sai số góc còn lại phần lớn do nhãn: góc GT chọn theo từng độ và có ảnh nghiêng nhẹ vẫn ghi 0° (ví dụ `mcocr_val_145115bcojo`: chữ nghiêng khoảng 3°, GT 0°, module đo 3,4°). Không nên tối ưu thêm MAE dưới mức này.

## Thời gian (CPU Ryzen 5 5500U, 6 luồng)

- Phân loại + detect: khoảng 0,85 giây/ảnh. (Số của val trong `orientation_metrics.json` lớn hơn vì bị cộng dồn thời gian lần kiểm tra lật 10 dòng ban đầu.)
- Kiểm tra lật 3 dòng: khoảng 1,7–1,9 giây/ảnh.
- oneDNN phải tắt cho model detect/nhận dạng trên Paddle 3.3 CPU (lỗi `ConvertPirAttribute2RuntimeAttribute`), giống T05.

## Chạy lại

```bash
cd ai-service
# 1) quan sát bằng model (môi trường OCR T10), có thể dừng và chạy tiếp
PYTHONUTF8=1 PYTHONPATH=src ../.cache/t10-ocr-venv/Scripts/python.exe -m invoice_ai.preprocessing.evaluate_orientation observe \
  --dataset ../dataset_hoadon/dataset_split_80_10_10 --splits train val \
  --paddlex-home ../.cache/paddlex --observations ../experiments/data/processed/orientation_v1
# 2) quyết định + chỉ số (Python thường)
PYTHONPATH=src python -m invoice_ai.preprocessing.evaluate_orientation evaluate \
  --dataset ../dataset_hoadon/dataset_split_80_10_10 --splits train val \
  --observations ../experiments/data/processed/orientation_v1 --out ../experiments/reports/orientation_v1_2026-10-10
```

Quan sát lưu ở `experiments/data/processed/orientation_v1/{split}.jsonl` (gitignored). Code: `ai-service/src/invoice_ai/preprocessing/orientation.py`, `evaluate_orientation.py`; test: `ai-service/tests/test_orientation.py`.

Trong pipeline: `OrientationModels(...).estimate(image_bgr).total_cw` là góc xoay theo chiều kim đồng hồ để ảnh thẳng.
