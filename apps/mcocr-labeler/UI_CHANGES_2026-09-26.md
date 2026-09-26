# Tóm tắt thay đổi giao diện ngày 26/09/2026

- Bổ sung kiểm tra các trường bắt buộc trước khi đánh dấu hoàn tất; hỗ trợ đánh dấu trường thực sự không xuất hiện trên hóa đơn.
- Thêm Undo/Redo, tự động lưu bản nháp và khôi phục dữ liệu chưa lưu.
- Thêm nút chuyển ảnh trước/sau, **Lưu và sang ảnh tiếp theo** cùng các phím tắt thao tác nhanh.
- Thêm bộ lọc ảnh chưa xác nhận chiều đọc.
- Cho phép sửa và xóa cả các vùng nhãn gốc trong tập Train và Validation.
- Làm rõ trạng thái từng ảnh: chưa có nhãn, đã có dữ liệu CSV, có thay đổi chưa lưu, đã hoàn tất và ảnh khó đọc.
- Chuyển phần nhập đường dẫn CSV/thư mục ảnh lên thanh phía trên để danh sách ảnh hiển thị được dài hơn.
- Hỗ trợ `Ctrl + lăn chuột` để zoom theo vị trí con trỏ và giữ chuột phải để kéo ảnh.
- Thu gọn tên vùng thành badge số; chỉ hiện tên đầy đủ khi chọn hoặc di chuột. Có thể ẩn/hiện toàn bộ badge bằng nút `#` hoặc phím `H`.

Các thao tác zoom, kéo, xoay và ẩn badge chỉ thay đổi cách hiển thị; tọa độ cùng dữ liệu annotation vẫn được lưu theo ảnh gốc.

## Kiểm tra

- JavaScript đã vượt qua kiểm tra cú pháp.
- Toàn bộ 18 bài kiểm tra backend đều đạt.
- Đã chạy thử trực tiếp trên ảnh có nhiều vùng nhãn và xác nhận thao tác thu gọn, mở rộng, ẩn/hiện badge hoạt động đúng.
