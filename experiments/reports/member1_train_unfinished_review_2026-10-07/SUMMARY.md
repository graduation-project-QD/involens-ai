# Kiểm tra 13 ảnh train member 1 chưa hoàn tất, không có cờ

Ngày: **07/10/2026**

Điều kiện chọn: có dữ liệu nhãn CSV, không nằm trong completed_images và không nằm trong flagged_images. Đã đối chiếu trực tiếp cả 13 ảnh; sửa mọi loại nhãn có nội dung đọc được.

Có 9 phiếu giao dịch treo: không tạo dòng hàng giả, ghi TOTAL_COST và 4 trường mặt hàng vắng mặt (nhóm 1 theo giao diện). Bốn hóa đơn còn lại được bổ sung vùng thiếu; tên hàng nhiều dòng tách bbox, cùng line_item_id. Timestamp và tiền ghi đúng bản in, không chuẩn hóa và không khôi phục dấu bằng suy diễn.

Giữ nguyên hoàn tất, cờ, góc xoay, image quality, ảnh gốc và 546 dòng CSV khác. Không đánh dấu hoàn tất các ảnh đã sửa.

## Thay đổi

- bbox: 70.
- add: 110.
- text: 25.
- delete: 4.
- absent: 46.

Chi tiết: [CHANGES.csv](CHANGES.csv). Danh sách 13 ảnh: [REVIEWED_IMAGES.csv](REVIEWED_IMAGES.csv).

## Cần người dùng duyệt lại

- #138 `mcocr_public_145013satyz.jpg`: Phiếu giao dịch treo: không có mặt hàng hay tổng tiền. Ghi các trường vắng mặt, giữ nguyên cờ và trạng thái chưa hoàn tất.
- #169 `mcocr_public_145013xafsi.jpg`: Phiếu giao dịch treo: không có mặt hàng hay tổng tiền. Ghi các trường vắng mặt, giữ nguyên cờ và trạng thái chưa hoàn tất.
- #186 `mcocr_public_145014ahsfe.jpg`: Phiếu giao dịch treo: không có mặt hàng hay tổng tiền. Ghi các trường vắng mặt, giữ nguyên cờ và trạng thái chưa hoàn tất.
- #249 `mcocr_public_145014epvwk.jpg`: Phiếu giao dịch treo: không có mặt hàng hay tổng tiền. Ghi các trường vắng mặt, giữ nguyên cờ và trạng thái chưa hoàn tất.
- #260 `mcocr_public_145014fbixi.jpg`: Phiếu giao dịch treo: không có mặt hàng hay tổng tiền. Ghi các trường vắng mặt, giữ nguyên cờ và trạng thái chưa hoàn tất.
- #327 `mcocr_public_145014kcbzk.jpg`: Phiếu giao dịch treo: không có mặt hàng hay tổng tiền. Ghi các trường vắng mặt, giữ nguyên cờ và trạng thái chưa hoàn tất.
- #357 `mcocr_public_145014mghmv.jpg`: Phiếu giao dịch treo: không có mặt hàng hay tổng tiền. Ghi các trường vắng mặt, giữ nguyên cờ và trạng thái chưa hoàn tất.
- #399 `mcocr_public_145014owdgs.jpg`: Phiếu giao dịch treo: không có mặt hàng hay tổng tiền. Ghi các trường vắng mặt, giữ nguyên cờ và trạng thái chưa hoàn tất.
- #421 `mcocr_public_145014qofcz.jpg`: Phiếu giao dịch treo: không có mặt hàng hay tổng tiền. Ghi các trường vắng mặt, giữ nguyên cờ và trạng thái chưa hoàn tất.
- #96 `mcocr_public_145013lrksq.jpg`: Bổ sung 11 dòng dịch vụ. Dòng Thẻ VISA CARD *9402 là giao dịch thanh toán âm, không phải mặt hàng, nên không gán nhãn item. Text khach chuyen p trên dòng đầu bị cắt tại mép cột, giữ phần nhìn thấy.
- #238 `mcocr_public_145014eamas.jpg`: Giá trị timestamp bị mất mực hoàn toàn sau Ngày:, chưa tạo nhãn và không suy diễn từ mã giao dịch. Chữ ở tên hàng/số lượng hơi nhạt, cần duyệt lại trước hoàn tất.
- #373 `mcocr_public_145014nbtki.jpg`: Dòng địa chỉ giữa Số 32 ngõ Láng và P. Láng Hạ mất mực, chỉ thêm phần nhìn thấy. Đuôi 200G của tên hàng đầu khá nhạt, cần duyệt lại; không phục hồi nét chữ bằng suy diễn.

## Sao lưu

Bản trước sửa: `D:\graduation-project-2\dataset_hoadon\annotation_review_backups\member1_train_unfinished_20261007T053336016348Z`.

PASS: aligned arrays, categories, source-coordinate bounds, product ids, unchanged other 546 rows, quality, original images, completion/flags, rotations, other datasets and workspace config
