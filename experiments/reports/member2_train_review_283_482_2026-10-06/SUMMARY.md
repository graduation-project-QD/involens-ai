# Rà soát 200 ảnh tiếp theo tập train member 2

Ngày: **06/10/2026**

Đã đối chiếu trực tiếp **200 ảnh (vị trí 283–482 trong 563 ảnh)**, từ `mcocr_public_145014gqlrt.jpg` đến `mcocr_public_145014uimoq.jpg`, theo thứ tự CSV sau lọc trùng. Rà tất cả 8 loại nhãn, gồm 2980 vùng ban đầu; sửa ở **199 ảnh**.

## Thay đổi

- bbox: 608.
- text: 537.
- add: 267.
- delete: 54.
- line_item_id: 81.
- category: 1.
- rotation: 8.
- absent: 1.

Sửa lỗi chép text/số tiền, chữ hoa, dấu câu, phần tên hàng bị thiếu; tách tên nhiều dòng thành các box cùng line_item_id; sửa bbox, nhãn sai và nhóm mặt hàng; bổ sung vùng đọc rõ bị bỏ sót. Text giữ cách in trên hóa đơn, chưa chuẩn hóa. Chữ đ thuộc giá trị được giữ. Mã hàng thuần không thay cho ITEM_NAME; ghi trường vắng mặt tương ứng.

Góc xoay để đọc ảnh ngang được ghi vào mcocr_train_rotation.csv; tọa độ vẫn thuộc ảnh gốc. Không sửa ảnh gốc, chất lượng ảnh, cờ hay trạng thái hoàn tất. Không thay các dòng 1–282 và 483–563 hoặc tập dữ liệu khác.

Chỉ sửa khi có căn cứ từ ảnh. Phần mờ/bị che giữ lại hoặc chưa thêm; trường hợp cần kiểm tra thủ công ghi dưới đây. Báo cáo POS/Payoo vẫn giữ giá trị tổng tiền đã có; không thay chính sách đưa loại ảnh này vào huấn luyện.

Chi tiết: [CHANGES.csv](CHANGES.csv). Danh sách ảnh: [REVIEWED_IMAGES.csv](REVIEWED_IMAGES.csv).

## Cần lưu ý khi kiểm tra lại

- #295 `mcocr_public_145014htnck.jpg`: Báo cáo doanh thu POS nhiều giao dịch; giữ tổng hiện có, cần quyết định chính sách sử dụng riêng.
- #300 `mcocr_public_145014hyfyd.jpg`: Báo cáo tổng kết giao dịch; tháng của dòng thời gian và ký tự cuối địa chỉ hơi nhòe, cần kiểm tra lại trước hoàn tất.
- #302 `mcocr_public_145014ihdjg.jpg`: Hai dòng địa chỉ in khác nhau: header 1060-1062 và dòng Số 1080-1062. Giữ nguyên chữ nhìn thấy, không sửa theo logic số nhà.
- #306 `mcocr_public_145014irdem.jpg`: Phiếu ngân hàng bị cắt phần dưới của tổng tiền; giá trị/mã merchant và phân cách ngày hơi nhòe, cần đối chiếu trước hoàn tất.
- #308 `mcocr_public_145014ivclx.jpg`: Dòng + Trân châu trắng bị rách tại vài nét; giữ chữ cũ còn phù hợp phần nhìn thấy, cần duyệt lại đoạn rách.
- #311 `mcocr_public_145014iznli.jpg`: Từ sau Giấy trong tên Posy có dấu khó phân biệt (cân/cần); chưa tự thay dấu, cần duyệt thủ công.
- #312 `mcocr_public_145014jakjq.jpg`: Báo cáo tổng kết Payoo nhiều giao dịch, giữ tổng đang có.
- #320 `mcocr_public_145014jkegi.jpg`: Phiếu giao dịch treo không có mặt hàng/tổng; hai dòng địa chỉ có số đầu khác nhau, giữ chữ in.
- #323 `mcocr_public_145014jqlcm.jpg`: Giờ sau ngày nằm ngoài bbox cũ và khá nhạt; cần đọc crop phóng lớn để bổ sung nếu chắc chắn.
- #328 `mcocr_public_145014kdvhb.jpg`: Tổng kết nhiều giao dịch ngân hàng, giữ số tiền đã gán; duyệt chính sách sử dụng riêng.
- #345 `mcocr_public_145014lkccn.jpg`: Phiếu tổng kết Payoo; giữ tổng giao dịch, cần duyệt loại chứng từ.
- #347 `mcocr_public_145014lohnm.jpg`: Phía dưới có mảnh phiếu khác ghi 38.800đ; giữ tổng 8.000đ thuộc phiếu có mặt hàng đang đánh.
- #363 `mcocr_public_145014mjhvf.jpg`: Ảnh nhỏ, nhòe và nhăn: tên mặt hàng đầu, địa chỉ, phần giờ bị cắt và số lượng các dòng chưa đọc chắc. Bổ sung phần đọc được; cần kiểm tra các tên dài trước hoàn tất.
- #367 `mcocr_public_145014mnwrz.jpg`: Header địa chỉ in 463, dòng dưới in 483; giữ theo từng dòng. Đầu chữ ậu/ệ bị thiếu nét, không phục hồi tự động.
- #369 `mcocr_public_145014mppzy.jpg`: Bổ sung 31 mặt hàng bị bỏ sót. Chữ tiêu đề và vài tên sách nhỏ/nhòe; cần đối chiếu crop mới, không thêm nội dung bị che.
- #375 `mcocr_public_145014nccit.jpg`: Chữ số thứ ba của số nhà trên header nhòe (1060/1080); dòng dưới đọc 1060. Cần duyệt header trước hoàn tất.
- #380 `mcocr_public_145014njsyx.jpg`: Số nhà trên hai dòng in khác nhau; giữ riêng, cần đối chiếu chữ số nhòe trước hoàn tất.
- #384 `mcocr_public_145014npyol.jpg`: Giờ bị cắt ở mép giấy sau 11:, giữ phần đọc thấy; không điền phút suy đoán.
- #388 `mcocr_public_145014nukhy.jpg`: Tên mặt hàng đường bị thủng che một phần chữ xuất; giữ phần text đang phù hợp nét còn lại, cần duyệt chỗ thủng.
- #389 `mcocr_public_145014nwpjb.jpg`: Ảnh gốc cắt phần dưới phiếu trước timestamp; không suy ra thời gian từ mã giao dịch.
- #393 `mcocr_public_145014ofrbt.jpg`: Header địa chỉ nhòe; bổ sung hai dòng còn thiếu theo nét đọc được, cần duyệt lại dấu của Thanh Niên/Cẩm Thành.
- #392 `mcocr_public_145014ofcbe.jpg`: Báo cáo POS/CA; giữ tổng đã có, bổ sung ngày hệ thống. Phần giờ hơi nhòe, cần duyệt trước hoàn tất.
- #400 `mcocr_public_145014onrob.jpg`: Báo cáo ca POS; giữ tổng doanh thu đã gán, giờ hệ thống nhòe cần duyệt.
- #405 `mcocr_public_145014oxghl.jpg`: Header khá nhòe; tên hàng đọc được, địa chỉ cần đối chiếu nét mờ trước hoàn tất.
- #418 `mcocr_public_145014ptuuq.jpg`: Dấu ở từ trấn trên bản in nhòe; không sửa theo tên sản phẩm, cần duyệt dấu trước hoàn tất.
- #419 `mcocr_public_145014pudoo.jpg`: Timestamp bị cắt ở mép giấy sau 17:, giữ phần nhìn thấy.
- #443 `mcocr_public_145014rqund.jpg`: Ảnh gốc cắt sát seller ở trên và cắt tổng/thời gian ở dưới. Không bổ sung tổng tiền bằng phép cộng các dòng.
- #445 `mcocr_public_145014rsbuj.jpg`: Các chữ số địa chỉ khác nhau giữa header và dòng dưới; phần 1052/1062 khá nhòe cần duyệt.
- #447 `mcocr_public_145014rsxlc.jpg`: Chữ Ga satin, số lượng và tiền dòng hàng khá nhạt; bổ sung theo nét đọc được và cần duyệt lại crop trước hoàn tất.
- #452 `mcocr_public_145014ryyyw.jpg`: Mã merchant và phân cách ngày hơi mờ; cần đối chiếu trước hoàn tất, không đổi tên sang Vietcombank.
- #456 `mcocr_public_145014sfktp.jpg`: Ảnh mất mực: seller/header và một số phần đầu tên hàng rất nhạt. Bổ sung 9 dòng đọc được, giữ tên không dấu; KM 2 không có số tiền nên không tạo mặt hàng tiền giả.
- #459 `mcocr_public_145014smasw.jpg`: Phần phút timestamp bị cắt ở mép giấy; giữ fragment ngày-11: hiện có.
- #471 `mcocr_public_145014tobyw.jpg`: Tên cơm có đoạn viết tắt S. THÌ hơi mờ; giữ phần đọc thấy, không mở rộng thành tên suy đoán.
- #470 `mcocr_public_145014tnnoi.jpg`: Ảnh gốc cắt phần dưới phiếu trước timestamp; không suy ra ngày từ mã giao dịch.
- #475 `mcocr_public_145014ttrrd.jpg`: Vị trí QUANTITY bị rách che hoàn toàn; không điền 1 chỉ từ phép tính tiền.
- #480 `mcocr_public_145014udqjt.jpg`: Ảnh merchant/giờ khá nhòe; text bổ sung cần duyệt lại crop trước hoàn tất.
- #477 `mcocr_public_145014twoee.jpg`: Phiếu chế biến không in giá và không có seller/địa chỉ; không dùng CHẾ BIẾN làm seller.
- #481 `mcocr_public_145014ugcvq.jpg`: Ảnh cắt phần dưới dòng timestamp; không thêm thời gian đoán theo mã giao dịch.
- #323 `mcocr_public_145014jqlcm.jpg`: Đã bổ sung giờ 09:21 CH ở phần bên phải; giờ lặp bên trái bị mất nét nên không tự điền.

## Sao lưu

Bản trước sửa: `D:\graduation-project-2\dataset_hoadon\annotation_review_backups\member2_train_283_482_20261006T153449060044Z`.

PASS: aligned arrays, categories, original-coordinate bounds, positive item groups, unchanged rows 1–282 and 483–563, image hashes, image quality, completion, flags, other datasets and workspace config
