# Rà soát 81 ảnh tiếp theo tập train member 2

Ngày hoàn thành: **07/10/2026** (bắt đầu 06/10/2026)

Đã đối chiếu trực tiếp **81 ảnh (vị trí 483–563 trong 563 ảnh)**, từ `mcocr_public_145014umhqi.jpg` đến `mcocr_public_145014zzzej.jpg`, theo thứ tự CSV sau lọc trùng. Rà tất cả 8 loại nhãn, gồm 1164 vùng ban đầu; sửa ở **81 ảnh**.

## Thay đổi

- text: 206.
- bbox: 463.
- add: 289.
- delete: 12.
- line_item_id: 21.
- category: 3.
- rotation: 7.
- absent: 5.

Sửa lỗi chép text/số tiền, chữ hoa, dấu câu, phần tên hàng bị thiếu; tách tên nhiều dòng thành các box cùng line_item_id; sửa bbox, nhãn sai và nhóm mặt hàng; bổ sung vùng đọc rõ bị bỏ sót. Text giữ cách in trên hóa đơn, chưa chuẩn hóa. Chữ đ thuộc giá trị được giữ. Mã hàng thuần không thay cho ITEM_NAME; ghi trường vắng mặt tương ứng.

Góc xoay để đọc ảnh ngang được ghi vào mcocr_train_rotation.csv; tọa độ vẫn thuộc ảnh gốc. Không sửa ảnh gốc, chất lượng ảnh, cờ hay trạng thái hoàn tất. Không thay các dòng 1–482 hoặc tập dữ liệu khác.

Chỉ sửa khi có căn cứ từ ảnh. Phần mờ/bị che giữ lại hoặc chưa thêm; trường hợp cần kiểm tra thủ công ghi dưới đây. Báo cáo POS/Payoo vẫn giữ giá trị tổng tiền đã có; không thay chính sách đưa loại ảnh này vào huấn luyện.

Chi tiết: [CHANGES.csv](CHANGES.csv). Danh sách ảnh: [REVIEWED_IMAGES.csv](REVIEWED_IMAGES.csv).

## Cần lưu ý khi kiểm tra lại

- #486 `mcocr_public_145014uqhki.jpg`: Header/địa chỉ khá nhạt; giữ cách in, model và tên hàng nhiều dòng được tách cùng nhóm.
- #487 `mcocr_public_145014uzdqt.jpg`: Phiếu thanh toán thẻ, tên merchant nhòe; giữ tổng tiền giao dịch và ghi chú để duyệt lại.
- #489 `mcocr_public_145014vfape.jpg`: Ảnh bị out-focus; đã đối chiếu nhưng một số dấu trên tên hàng mờ, cần duyệt lại trước hoàn tất.
- #491 `mcocr_public_145014vitnu.jpg`: Giao dịch treo không in hàng, số lượng hay giá; không tạo nhóm hàng giả.
- #495 `mcocr_public_145014vwnco.jpg`: Hai dòng địa chỉ in 1060-1062 và 1080-1082; giữ đúng chữ in, không tự đồng bộ số nhà.
- #496 `mcocr_public_145014vyosv.jpg`: Báo cáo doanh số/thuế POS, không phải hóa đơn từng giao dịch; giữ tổng có sẵn và cần quyết định chính sách dùng ảnh này.
- #500 `mcocr_public_145014wcjoc.jpg`: UNIQLO chỉ có một cột tiền cho các dòng không giảm giá: giữ LINE_TOTAL, không suy diễn thêm UNIT_PRICE trùng vùng.
- #507 `mcocr_public_145014wmjil.jpg`: Mép hóa đơn cắt giờ sau 19:, giữ phần nhìn thấy và không suy diễn phút.
- #508 `mcocr_public_145014wnpbo.jpg`: Báo cáo doanh thu POS, phần ngày khá nhòe; giữ tổng thanh toán đã có, không gán các mệnh giá tiền thành hàng hóa.
- #509 `mcocr_public_145014woqkn.jpg`: Phiếu giao dịch treo không có mặt hàng, không tạo nhãn/nhóm hàng suy diễn.
- #510 `mcocr_public_145014wowmj.jpg`: Ảnh mất nét, không tự bổ sung dấu mờ trên tên sản phẩm.
- #511 `mcocr_public_145014wpplc.jpg`: Giao dịch treo không có item/giá/số lượng, không tự tạo nhóm hàng.
- #513 `mcocr_public_145014wscvw.jpg`: Ảnh cắt dưới trước timestamp, không suy đoán ngày/giờ từ mã giao dịch.
- #515 `mcocr_public_145014wvxfq.jpg`: Logo tên cửa hàng mất nhiều nét; chưa thêm seller theo tên thương hiệu suy đoán.
- #519 `mcocr_public_145014xbjfb.jpg`: Phiếu chế biến, không có seller/địa chỉ/giá/tổng tiền; không tạo giá trị đoán.
- #520 `mcocr_public_145014xcxaw.jpg`: Phiếu mã QR ưu đãi không có hàng hay số tiền, không suy diễn nhãn tiền/hàng.
- #525 `mcocr_public_145014xmngo.jpg`: Số 2 ở cột VAT là mã thuế, không phải số lượng. Chỉ bổ sung số lượng 10 và đơn giá 5.700d nơi in riêng; không suy diễn số lượng cho các dòng khác.
- #531 `mcocr_public_145014xwajt.jpg`: Ảnh cắt phần dưới hóa đơn sau tiền khách đưa, không đọc được timestamp.
- #536 `mcocr_public_145014yfexx.jpg`: Biên nhận trả tiền nước qua Payoo; địa chỉ bị cắt cuối, không dùng địa chỉ khách hàng thay địa chỉ cửa hàng.
- #541 `mcocr_public_145014yjivr.jpg`: Giờ sau 11: bị mất/cắt nét trên bản in, không tự đoán phút.
- #545 `mcocr_public_145014yrxvd.jpg`: Timestamp bị mất hoàn toàn sau chữ Ngày ở mép phải, không suy diễn theo mã giao dịch.
- #546 `mcocr_public_145014ysbpa.jpg`: Ảnh mất nét và có vùng chữ bị xóa ở dòng 6–9: chỉ thêm phần đọc được, còn tên/giá/số lượng khó đọc để duyệt thủ công. Không tự đoán các ký tự bị xóa.
- #549 `mcocr_public_145014yxijr.jpg`: Phiếu treo không có item/số lượng/giá, không tạo nhóm hàng.
- #554 `mcocr_public_145014zkxjr.jpg`: Ảnh gấp che phần tổng thanh toán, không tính tiền từ các dòng để tạo nhãn. Header địa chỉ/chi nhánh quá nhỏ và nhòe, chỉ thêm tên Co.opmart đọc rõ; cần duyệt lại các ký tự bị nét bút đè.
- #495 `mcocr_public_145014vwnco.jpg`: Hai dòng địa chỉ in số nhà khác nhau: VM+ 1060-1062 và Số 1080-1082. Giữ đúng từng dòng, cần người duyệt xác nhận, không sửa cho khớp nhau.
- #554 `mcocr_public_145014zkxjr.jpg`: Tên dòng Quay banh DONUS có hậu tố YTD992 bị nét bút đè; cần xác nhận ký tự cuối. Không tự bổ sung địa chỉ hay tổng tiền bị nếp gấp che.

## Sao lưu

Bản trước sửa: `D:\graduation-project-2\dataset_hoadon\annotation_review_backups\member2_train_483_563_20261007T024952506140Z`.

PASS: aligned arrays, categories, original-coordinate bounds, positive item groups, unchanged rows 1–482, image hashes, image quality, completion, flags, other datasets and workspace config
