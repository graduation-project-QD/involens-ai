# B6 — Benchmark tiền xử lý CLAHE và UVDoc — 14/10/2026

Kiểm tra hai phương pháp tiền xử lý có giúp pipeline OCR đã chốt ở B5 (detector `C1920_b0.2_t0.15` + nhận dạng tham khảo `PP-OCRv6_medium_rec`) hay không. Đo trên tập con **train** phân tầng theo cửa hàng. Chỉ chạy CPU (Ryzen 5 5500U, 10 luồng), không dùng LLM.

**Kết luận: không dùng CLAHE, không dùng UVDoc.** Cả hai đều không cải thiện, thậm chí làm giảm chất lượng. Vì không có phương pháp nào được chọn nên không chạy xác nhận trên val; cấu hình tiền xử lý giữ nguyên như sau B5. Super-resolution đã được bỏ khỏi B6 từ trước (tốn tài nguyên, nguy cơ "bịa" nét chữ số; detector sau B5 đã bắt gần đủ).

## Phương pháp

| Phương pháp | Cách làm | Cách đo |
|---|---|---|
| **CLAHE** | Cân bằng histogram thích ứng có giới hạn (OpenCV), áp trên kênh độ sáng L của không gian màu LAB; `clipLimit` 2,0, lưới 8×8 | Không đổi hình học → (1) recall detection theo nhãn, (2) CER nhận dạng trên crop GT; so với không dùng CLAHE trên cùng 300 ảnh |
| **UVDoc** | Model nắn phẳng ảnh tài liệu của PaddleOCR (`TextImageUnwarping`, model `UVDoc`); đầu ra là RGB nên đổi lại BGR | Làm cong/kéo ảnh nên box GT không còn đúng vị trí → đo **đầu-cuối**: detector + nhận dạng trên cả trang, với mỗi vùng GT tìm đoạn khớp gần nhất của text GT trong các dòng OCR (edit distance trên chuỗi con); 100 ảnh |

Chỉ số đầu-cuối không phụ thuộc hình học nên áp dụng giống nhau cho bản gốc và bản UVDoc. Hạn chế: với text rất ngắn (QUANTITY như "1") luôn tìm được ở đâu đó trong trang, nên chỉ có ý nghĩa với text dài (SELLER, ADDRESS, TIMESTAMP, ITEM_NAME).

## Kết quả (train)

### CLAHE — 300 ảnh

| Chỉ số | Không tiền xử lý | CLAHE | Thay đổi |
|---|---:|---:|---:|
| Recall detection QUANTITY | **90,4%** | 86,8% | −3,6 điểm |
| Recall trung bình 8 nhãn | **98,6%** | 98,2% | −0,5 điểm |
| CER trên crop GT (4.593 vùng) | **10,00%** | 10,03% | ≈ 0 |
| Tỉ lệ đọc đúng hoàn toàn | 65,1% | 65,6% | ≈ 0 |

CLAHE làm tăng tương phản cả nền giấy nên detector bắt kém chữ số mảnh hơn; nhận dạng gần như không đổi (CER từng nhãn lệch < 0,2 điểm).

### UVDoc — 100 ảnh (đầu-cuối)

| Chỉ số | Không tiền xử lý | UVDoc |
|---|---:|---:|
| CER đầu-cuối (1.559 vùng) | **9,75%** | 10,45% |
| Tỉ lệ vùng khớp hoàn toàn | **68,6%** | 68,2% |
| CER SELLER / TIMESTAMP / ITEM_NAME | 5,5% / 3,3% / 10,4% | 6,6% / 4,3% / 12,0% |
| Số ảnh tốt hơn / kém hơn / như nhau (±1 điểm) | | 22 / 36 / 42 |
| Thời gian thêm | | khoảng 1,7 giây/ảnh |

UVDoc giúp một số ảnh giấy cong (tốt nhất giảm 15 điểm CER) nhưng làm hỏng nhiều ảnh hơn, nhất là hóa đơn nhỏ trên nền: model cố nắn cả nền, làm méo vùng chữ. Dùng có chọn lọc sẽ cần một bộ phát hiện giấy cong riêng – ngoài phạm vi MVP.

## Chi phí

| Bước | Thời gian |
|---|---|
| Detection có CLAHE, 300 ảnh | khoảng 18 phút |
| Nhận dạng crop GT, không/có CLAHE, 300 ảnh | khoảng 41 phút |
| Đầu-cuối không/có UVDoc, 100 ảnh | khoảng 52 phút |
| **Tổng** | **khoảng 1,9 giờ CPU** (model UVDoc tải một lần, vài chục MB) |

Kết quả detection không tiền xử lý dùng lại từ B5 (cùng cấu hình, cùng ảnh).

## Chạy lại

```bash
cd ai-service
PYTHONUTF8=1 PYTHONPATH=src ../.cache/t10-ocr-venv/Scripts/python.exe -m invoice_ai.ocr.preprocess_benchmark run \
  --mode det|crop|e2e --variants none clahe2 uvdoc --subset 300 --dataset ../dataset_hoadon/dataset_upright_v1 \
  --split train --paddlex-home ../.cache/paddlex --out ../experiments/data/processed/b6_preprocess
PYTHONPATH=src python -m invoice_ai.ocr.preprocess_benchmark summarize --dataset ../dataset_hoadon/dataset_upright_v1 \
  --split train --subset 300 --out ../experiments/data/processed/b6_preprocess --report ../experiments/reports/b6_preprocess_2026-10-14
```

Code: `ai-service/src/invoice_ai/preprocessing/enhance.py`, `ai-service/src/invoice_ai/ocr/preprocess_benchmark.py`; test: `ai-service/tests/test_preprocess_benchmark.py`. Số liệu: `b6_train_subset300.json`, `b6_train_subset100.json`.
