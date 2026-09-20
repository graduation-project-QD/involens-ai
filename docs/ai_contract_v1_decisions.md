# AI Service Contract v1 Decisions

Trạng thái: **đã chốt bởi người dùng cho T03**  
Ngày ghi nhận: 2026-09-19  
Phạm vi: các quyết định bắt buộc cho AI service MVP. Tài liệu này là nguồn chuẩn khi triển khai T03, T09, T12, T19, T21, T22 và T24.

## Quyết định đã chốt

| Hạng mục | Quyết định cho v1 |
|---|---|
| AI endpoint | `POST /v1/extract` |
| Input | JPG, PNG, PDF |
| PDF | **1 hóa đơn / 1 trang**; PDF nhiều hơn 1 trang bị reject |
| Max size | 10 MiB và 20 MP |
| Locale | `vi-VN` |
| Fields | **company, address, date, total** |
| Company | Text sau OCR/KIE; chỉ normalize whitespace |
| Address | Text; cho phép nối nhiều dòng |
| Date | Normalize `DD/MM/YYYY` thành `YYYY-MM-DD` |
| Total | Normalize thành chuỗi số, ví dụ `125.000 đ` thành `"125000"` |
| Field không tìm thấy | Trả `null`; không dùng chuỗi rỗng `""` |
| Confidence | Giá trị hữu hạn trong `[0,1]`, lấy từ score KIE; **không diễn giải là xác suất field đúng** |
| Human review | Bắt buộc trong MVP |
| Auto approve | Không có trong v1 |
| Products/line-items | Không có trong v1 |
| VAT/subtotal | Không có trong v1; có thể xem xét ở extension |
| AI → DB | AI không ghi database |
| Retry | Backend chịu trách nhiệm |
| Versioning | Lưu `model_version` và `pipeline_version` |

## Invariants khi triển khai

- Response có đúng bốn field canonical: `company`, `address`, `date`, `total`.
- `raw_value` phải được giữ riêng với giá trị đã normalize; normalize không được ghi đè hoặc làm mất text gốc.
- Field không được trích xuất thành công dùng `null` cho value. Không dùng `""`, `0`, hoặc giá trị suy đoán để thay thế.
- Date output đã normalize dùng chuỗi ISO `YYYY-MM-DD`. Input mơ hồ hoặc không hợp lệ không được ép thành một ngày chắc chắn; giữ raw và trả warning/null theo contract chi tiết.
- Total output đã normalize là chuỗi số để tránh mất precision; không trả kiểu floating-point chỉ vì giá trị là tiền.
- Confidence phải đi kèm semantics/version của phương pháp tính. Không dùng confidence để auto approve trong v1.
- AI service không quản lý workflow, retry, persistence, approval hoặc trạng thái nghiệp vụ.
- Thay đổi một quyết định trong bảng cần tạo revision contract mới và ghi ảnh hưởng compatibility.

## Chi tiết T03 còn phải chốt

Các nội dung sau chưa được quyết định trong thông báo này, nên vẫn là open items thay vì tự xem là đã chốt:

- Request fields và correlation identifiers như `document_id`, `job_id`, `attempt`, `request_id`.
- Response envelope đầy đủ, `schema_version`, warning/status/evidence và semantics nullable của từng member.
- MIME sniffing, xử lý extension không khớp MIME, cách tính 20 MP đối với PDF render và thứ tự kiểm tra limits.
- HTTP status/error envelope, mã lỗi, cờ `retryable` và mapping timeout/overload.
- Timeout, concurrency, health/readiness/model-info, logging và privacy.
- Version format cụ thể và compatibility policy cho `model_version`/`pipeline_version`.
- Decimal/grouping/date ambiguity rules chi tiết ngoài ví dụ đã chốt.

Các đề xuất trong `docs/ai_implementation_plan.md` chỉ có hiệu lực sau khi không xung đột với bảng quyết định này và được chốt ở revision T03 tương ứng.
