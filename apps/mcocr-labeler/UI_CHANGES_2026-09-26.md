# Tóm tắt thay đổi giao diện ngày 26/09/2026

## Cập nhật ngày 30/09/2026

- Chuyển ảnh sẽ cuộn thanh bên phải lên đầu; lưu nhãn giữ nguyên zoom và không kéo giao diện về ảnh cũ khi người dùng đã chuyển ảnh.
- Sửa lỗi mất dấu hoàn tất khi đổi CSV: lưu trạng thái riêng trong `<tên-csv>.completed.json`, tự chuyển trạng thái từ cấu hình phiên cũ và tạo bản sao lưu khi cập nhật.
- Khôi phục 200 dấu hoàn tất Train từ bản trạng thái lúc 22:00, giữ 1 dấu mới: tổng cộng 201 ảnh. Nội dung CSV nhãn không thay đổi.
- Kiểm tra backend: 21/21 bài đạt, bao gồm chuyển CSV rồi mở lại, khôi phục từ file trạng thái khi mất cấu hình phiên và bảo vệ file trạng thái bị lỗi.

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

## Cập nhật ngày 27/09/2026

- Bổ sung xoay tinh chỉnh từng `1°` và nhập trực tiếp góc xoay từ `0–359°`, bên cạnh thao tác xoay nhanh `90°`.
- Góc xoay chỉ tác động đến cách hiển thị khi gán nhãn; tọa độ annotation vẫn được lưu theo ảnh gốc.
- Cho phép xác nhận và lưu mọi góc nguyên từ `0–359°` vào file `*_rotation.csv` để phục vụ preprocessing.
- Chuyển badge số thứ tự sang cạnh trái của khung, giảm kích thước và chỉ hiện tên trường khi chọn hoặc di chuột để hạn chế che nội dung hóa đơn.
- Loại bỏ hoàn toàn tab **03 · Kiểm tra nhãn LLM** và các thành phần backend liên quan.
- Sửa lỗi lưu góc xoay tùy ý do nhiều backend cũ cùng sử dụng cổng `8765`: chuyển cổng mặc định sang `8766` và ngăn nhiều phiên backend cùng chiếm một cổng.

### Kiểm tra ngày 27/09/2026

- Đã xác nhận lưu thành công góc `357°` và đọc lại đúng từ file rotation CSV.
- JavaScript và Python đã vượt qua kiểm tra cú pháp.
- Toàn bộ 18 bài kiểm tra backend đều đạt.
