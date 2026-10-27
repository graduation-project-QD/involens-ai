# Gom nhóm hậu xử lý (kie_grouping_v1) — 10/10/2026

Đánh giá bước gom các box đã có nhãn thành trường hóa đơn và dòng hàng. Đầu vào là **box GT** (nhãn đúng); `line_item_id` chỉ dùng làm đáp án. Đây là trần của bước gom khi mô hình phân loại đúng hoàn toàn.

- Code: `ai-service/src/invoice_ai/kie/grouping.py`
- Chạy lại: `cd ai-service && PYTHONPATH=src python -m invoice_ai.kie.evaluate_grouping --dataset ../dataset_hoadon/dataset_merge --out ../experiments/reports/kie_grouping_v1_2026-10-10`
- Tham số mặc định (`gap=2.5`, `empty=4.0`, `continuation_penalty=1.0`) được chọn **chỉ trên train**; val chạy một lần sau khi chốt.

## Kết quả dòng hàng

| Phương pháp | Split | Ảnh đúng hoàn toàn | Món đúng (recall / precision) | Pair F1 |
|---|---|---:|---:|---:|
| Mỗi hàng ngang = 1 món (baseline) | train | 16.4% | 20.6% / 11.4% | 0.743 |
| Duyệt theo hàng + luật bố cục | train | 96.9% | 96.8% / 96.3% | 0.988 |
| **Neo LINE_TOTAL + căn chỉnh DP** | train | **98.4%** | **98.3% / 98.3%** | **0.994** |
| Mỗi hàng ngang = 1 món (baseline) | val | 13.9% | 15.6% / 8.3% | 0.719 |
| Duyệt theo hàng + luật bố cục | val | 95.7% | 96.7% / 95.8% | 0.986 |
| **Neo LINE_TOTAL + căn chỉnh DP** | val | **98.1%** | **98.0% / 97.9%** | **0.992** |

Train: 991 ảnh / 2.801 món; val: 324 ảnh / 939 món (ảnh không có dòng hàng không tính). Bảng trên dùng split gốc của MC-OCR.

### Trên split mới 80/10/10 (`dataset_split_80_10_10`, thư mục `split_80_10_10/`)

| Phương pháp | train (1.052 ảnh) | val (138) | test (125) |
|---|---:|---:|---:|
| Mỗi hàng ngang = 1 món | 16.3% | 13.0% | 14.4% |
| Duyệt theo hàng + luật bố cục | 96.2% | 98.6% | 97.6% |
| **Neo LINE_TOTAL + căn chỉnh DP** | **98.3%** | **98.6%** | **98.4%** |

(Tỉ lệ ảnh gom đúng toàn bộ món.) Quét lại tham số trên train mới cho cùng bộ mặc định (98,3%, tốt nhất 98,4%), nên giữ nguyên. Khoảng 200 ảnh val/test mới từng thuộc train cũ dùng để chọn tham số, nên số val/test có thể lạc quan nhẹ.

## Thuật toán (neo)

1. Neo = box của nhãn số xuất hiện nhiều nhất (thường là LINE_TOTAL); mỗi neo là một món.
2. QUANTITY/UNIT_PRICE được căn với neo theo thứ tự dọc bằng DP (kiểu edit distance) với độ lệch trung vị của tài liệu, nên chịu được ảnh nghiêng/phối cảnh.
3. Các dòng ITEM_NAME (theo thứ tự đọc) được chia thành các đoạn liên tiếp, mỗi đoạn thuộc một neo. Dòng đầu đoạn phải nằm ở độ lệch nhất quán so với neo (thử mọi độ lệch ứng viên, lấy chi phí nhỏ nhất); dòng bắt đầu bằng chữ thường hoặc "(" bị phạt khi làm dòng đầu.
4. Trường cấp hóa đơn: nối các box cùng nhãn theo thứ tự đọc (địa chỉ nhiều dòng, ngày + giờ); TOTAL_COST nhiều ứng viên thì giữ box có score cao nhất.

## Lỗi còn lại

`grouping_failures.csv` liệt kê 16 ảnh train và 6 ảnh val. Nhóm chính:

- Tên 3 dòng có số in ở dòng giữa ("Sữa chua trân / châu đường + số / đen") xen với tên 1 dòng: hình học không đủ phân biệt.
- Món thiếu LINE_TOTAL/thiếu box số làm lệch thứ tự căn chỉnh của cả hóa đơn.
- Box GT chồng nhau quá nhiều (hóa đơn rất dày như `145014mppzy`, 31 món).

## Thứ tự nối trường cấp hóa đơn

`document_field_order` so thứ tự đọc với thứ tự box trong CSV. Ở val thứ tự CSV là thứ tự người gán vẽ (ví dụ "13.53" trước "30.03.2019"), nên chỉ số này **không** phải độ chính xác. Kiểm tra thủ công các trường hợp khác nhau cho thấy thứ tự đọc đúng. Khi tạo giá trị GT để đánh giá field, nối box theo thứ tự đọc, không theo thứ tự CSV.
