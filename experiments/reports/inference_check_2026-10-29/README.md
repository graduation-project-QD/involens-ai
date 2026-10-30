# Kiểm chứng module suy luận một ảnh (2026-10-29)

Module `invoice_ai.inference.pipeline` (`InvoicePipeline.process(image_bytes)`) chạy toàn bộ pipeline trong bộ nhớ cho một ảnh, nạp model một lần. Kiểm chứng: chạy trên **136 ảnh test gốc** (chưa xoay) và so với kết quả đánh giá test đã lưu (`experiments/artifacts/test/test_results_20261029`, `experiments/reports/test_final_2026-10-29`), là kết quả của các script chạy theo lô.

Tiêu chí đã chốt: nhãn theo từ trùng ≥ 99% và số ô sai / hóa đơn lệch ≤ 0,05.

## Kết quả

| | Kết quả |
|---|---|
| Góc xoay B4 trùng | **136/136** |
| Danh sách từ (và box 0–1000) trùng hoàn toàn | 132/136 hóa đơn |
| Nhãn LayoutXLM trùng hoàn toàn | 132/136 hóa đơn |
| Nhãn theo từ trùng (trên 13.956 từ) | **99,97%** |
| Ô sai / hóa đơn sau B11 (`evaluate_e2e`) | **1,353**, giống hệt đánh giá (1,353; 184 ô sai) |
| Dòng hàng đúng cả 4 ô (F1) | 71,96%, giống hệt |
| Hóa đơn không phải sửa gì | 41,18%, giống hệt |

**Đạt tiêu chí.** 4 hóa đơn khác biệt đều chỉ lệch **một ký tự** VietOCR đọc ở chữ nền, không thuộc trường nào: `Tiên`/`Tên`, `O309129418`/`0309129418`, `0247106860`/`0247106960`, `57:`/`5Z:`. Nguyên nhân: script đánh giá đọc crop theo lô 32 crop trộn giữa các ảnh, module mới đọc theo lô của từng ảnh; VietOCR đệm ảnh theo crop rộng nhất trong lô nên vài ký tự sát ngưỡng đổi kết quả. Không ảnh hưởng điểm đầu-cuối.

## Thời gian (VM RTX 5060 Ti, B4 + detector chạy CPU như lúc đánh giá)

| Bước | Giây / hóa đơn |
|---|---:|
| Tự xoay (B4) | 0,59 |
| Detector (L960 + C1920) | 1,64 |
| Crop + VietOCR | 1,28 |
| Tách từ + LayoutXLM | 0,02 |
| B11 | < 0,01 |
| **Tổng** | **3,5** |

Nạp model khi khởi động: khoảng 10–20 giây, một lần cho cả worker.

## Môi trường

Một môi trường cho cả Paddle và PyTorch (venv B10 + VietOCR + Paddle CPU):

- torch 2.8.0+cu129, transformers 4.57.1, detectron2 (commit `1e3e13bb`), vietocr 0.3.13 (`--no-deps`, các pin trong `runtime/b7/requirements-vietocr.txt`)
- paddlepaddle 3.3.0, paddleocr 3.7.0, paddlex 3.7.2 (cùng phiên bản môi trường đánh giá trên máy cá nhân)
- Cần ghim: `numpy==1.26.4`, `pandas==3.0.6` (pandas 3.1 build cho NumPy 2), `huggingface_hub<1.0` (transformers 4.57), `opencv-contrib-python==4.10.0.84` + `opencv-python-headless==4.10.0.84` và gỡ `opencv-python`.

Model Paddle dùng: `PP-LCNet_x1_0_doc_ori`, `PP-OCRv5_mobile_det`, `latin_PP-OCRv5_mobile_rec` (thư mục `official_models/`, khoảng 20 MB). Trọng số: `ft_vgg_transformer_20000.pth` (B7) và `layoutxlm_e2/` (B10).

## Chạy lại

```bash
cd ai-service
PYTHONPATH=src python -m invoice_ai.inference.pipeline --weights ../weights --paddlex-home ../paddlex \
    --images ../data/test_images --out ../runs/inference_test
python -m invoice_ai.kie.evaluate_e2e evaluate --dataset ../dataset_hoadon/dataset_upright_test_auto --split test \
    --predictions <out>/predictions.jsonl --ocr <out>/words.jsonl --out <báo cáo>
```

| Tệp | Nội dung |
|---|---|
| `run/messages/*.json` | message kết quả theo hợp đồng backend cho từng ảnh (`data.id` = tên ảnh) |
| `run/words.jsonl`, `run/predictions.jsonl` | từ, box, nhãn, điểm (định dạng `evaluate_e2e`) |
| `run/timings.jsonl` | thời gian từng bước |
| `comparison.json` | so sánh với kết quả đánh giá |
| `e2e/` | `evaluate_e2e` trên kết quả module mới |
