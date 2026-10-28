# Rà soát 50% đầu tập train member 2

Ngày: **06/10/2026**

Đã đối chiếu trực tiếp **282/563 ảnh**, từ `mcocr_public_145013acjke.jpg` đến `mcocr_public_145014gndox.jpg`, theo thứ tự CSV sau lọc trùng. Rà tất cả 8 loại nhãn, gồm 4275 vùng ban đầu; sửa ở **267 ảnh**.

## Thay đổi

- Sửa text (gồm nội dung và cách chép dấu câu/chữ hoa): 804.
- Sửa tọa độ vùng đã có: 354.
- Đổi loại nhãn gán sai: 11.
- Sửa nhóm mặt hàng: 145.
- Bổ sung vùng nhãn: 293.
- Bỏ vùng gán sai hoặc chỉ chứa chữ mô tả: 61.
- Lưu góc đọc thẳng: 21.
- Ghi trường tên mặt hàng vắng mặt: 4.

Sửa lỗi chép text/số tiền, chữ hoa, dấu câu, phần tên hàng bị thiếu; tách tên nhiều dòng thành các box cùng line_item_id; sửa bbox, nhãn sai và nhóm mặt hàng; bổ sung vùng đọc rõ bị bỏ sót. Text giữ cách in trên hóa đơn, chưa chuẩn hóa. Chữ đ thuộc giá trị được giữ. Mã hàng thuần không thay cho ITEM_NAME; ghi trường vắng mặt tương ứng.

Góc xoay để đọc ảnh ngang được ghi vào mcocr_train_rotation.csv; tọa độ vẫn thuộc ảnh gốc. Không sửa ảnh gốc, chất lượng ảnh, cờ hay trạng thái hoàn tất. Không thay các dòng 283–563 hoặc tập dữ liệu khác.

Chỉ sửa khi có căn cứ từ ảnh. Phần mờ/bị che giữ lại hoặc chưa thêm; trường hợp cần kiểm tra thủ công ghi dưới đây. Báo cáo POS/Payoo vẫn giữ giá trị tổng tiền đã có; không thay chính sách đưa loại ảnh này vào huấn luyện.

Chi tiết: [CHANGES.csv](CHANGES.csv). Danh sách ảnh: [REVIEWED_IMAGES.csv](REVIEWED_IMAGES.csv).

## Cần lưu ý khi kiểm tra lại

- #15 `mcocr_public_145013bybgv.jpg`: Giao dịch treo không có bảng mặt hàng hay số tiền; không suy ra các nhãn mặt hàng/TOTAL_COST.
- #16 `mcocr_public_145013byufi.jpg`: Dấu đỏ đè một phần lên dòng hàng; giữ text nhìn thấy, không gán chữ của dấu đỏ vào tên sản phẩm.
- #17 `mcocr_public_145013cezfv.jpg`: Ngày và phần còn lại của seller bị mất nét nặng; ngày 08/08/2020 được giữ từ nhãn cũ nhưng chưa xác nhận đủ ký tự. Hóa đơn gọi món không có đơn giá/thành tiền/tổng tiền.
- #19 `mcocr_public_145013chgcz.jpg`: Hóa đơn trả hàng: giữ dấu âm tại QUANTITY, LINE_TOTAL và TOTAL_COST đúng ảnh.
- #38 `mcocr_public_145013dtobm.jpg`: Dòng KM là chiết khấu đã được gán riêng trong dữ liệu: giữ giá trị âm và không tự thêm QUANTITY/UNIT_PRICE không xuất hiện.
- #39 `mcocr_public_145013dxavh.jpg`: Giao dịch treo không có mặt hàng/tổng tiền; không suy ra nhãn còn thiếu.
- #46 `mcocr_public_145013eicdg.jpg`: Hậu tố sau tên Sữa VNM ở dòng 10 bị lỗi nét; giữ phần tên rõ và không đoán ký tự hỏng.
- #49 `mcocr_public_145013esetg.jpg`: KM -22.108 là dòng giảm giá; không suy ra QUANTITY/UNIT_PRICE cho dòng này.
- #51 `mcocr_public_145013ezyfw.jpg`: Dòng (8929) là mã riêng phía dưới tên sản phẩm, không gán riêng thành ITEM_NAME.
- #50 `mcocr_public_145013eyjmn.jpg`: Dòng + Nha Đam có số lượng, đơn giá, thành tiền riêng: tách nhóm để không trộn hai bộ giá trong cùng một line_item_id. Chữ số cuối năm ở giờ vào hơi mất nét; giữ ngày cũ, không sửa dựa vào suy đoán.
- #53 `mcocr_public_145013fkkfr.jpg`: Hóa đơn lỗi in làm đứt và lệch dòng. Đã gán các đoạn nhìn rõ, nhóm phần tên đúng mặt hàng; đơn giá bị tách thành các đoạn ở hai vị trí nên chưa gán UNIT_PRICE bằng suy đoán. Cần người dùng xem lại ảnh này.
- #55 `mcocr_public_145013fskld.jpg`: Hóa đơn chỉ in SL và TT; không tự tính UNIT_PRICE từ phép chia thành tiền/số lượng.
- #62 `mcocr_public_145013haeps.jpg`: Dòng mặt hàng chỉ có mã QN1-JP1L16-026: bỏ ITEM_NAME, giữ ba trường số của dòng 1 và ghi trường tên hàng vắng mặt.
- #63 `mcocr_public_145013hewxu.jpg`: Dòng đầu địa chỉ in 463 nhưng dòng sau in 483; giữ đúng từng dòng, không tự đồng nhất.
- #65 `mcocr_public_145013hvjbj.jpg`: Phiếu thanh toán thẻ không có bảng hàng; lấy seller theo tên đại lý, không theo logo ngân hàng.
- #71 `mcocr_public_145013imbop.jpg`: Báo cáo POS/ca: giữ số tổng đã gán; chính sách sử dụng loại chứng từ này cần quyết định riêng, không đổi trong lần rà nhãn.
- #83 `mcocr_public_145013kacze.jpg`: Phiếu có giờ vào 20:53 và giờ ra 21:31; giữ TIMESTAMP hiện có tại giờ vào vì khớp đúng chữ, chưa đổi chính sách chọn thời điểm.
- #89 `mcocr_public_145013kokcl.jpg`: Vết bẩn che phần ngày/tháng; giữ ngày cũ 08/08/2020 nhưng cần người dùng xác nhận. Phần giờ 09:47 còn đọc được.
- #104 `mcocr_public_145013ndqdl.jpg`: Báo cáo POS: giữ số tổng đã gán, không đổi chính sách loại chứng từ trong lần rà này.
- #136 `mcocr_public_145013sqwxo.jpg`: Giao dịch treo không có bảng mặt hàng hay tổng tiền; không suy ra nhãn không xuất hiện.
- #138 `mcocr_public_145013tgayt.jpg`: Nửa trên giấy không in chữ; chỉ đọc được tổng phải trả và phần chân phiếu. Không suy ra seller/ngày/mặt hàng.
- #140 `mcocr_public_145013tljfn.jpg`: Giao dịch treo, không có bảng mặt hàng/tổng tiền.
- #149 `mcocr_public_145013uwdpy.jpg`: Tên mặt hàng thực in thiếu Đ đầu, giữ ùi gà như giấy, không tự khôi phục chữ mất nét.
- #153 `mcocr_public_145013vilkn.jpg`: Báo cáo POS có hai tổng khác nhau; giữ các giá trị đã gán, chỉ xóa mô tả, không đổi chính sách loại chứng từ.
- #157 `mcocr_public_145013vullg.jpg`: Báo cáo Payoo: giữ tổng tiền thật; không gán các giao dịch nạp điện/nước thành mặt hàng.
- #175 `mcocr_public_145013yzczt.jpg`: Báo cáo POS, giữ giá trị tổng và không thay chính sách loại chứng từ.
- #180 `mcocr_public_145013zlljn.jpg`: Đơn giá bị rách sau 59; giữ 59 000 hiện có vì hai ô thành tiền/tổng đọc rõ cùng giá, ghi nhận phần đơn giá không đọc trực tiếp trọn vẹn.
- #190 `mcocr_public_145014armln.jpg`: Giữ dòng Tiền giảm giá món theo quy ước các dòng khuyến mại đang có trong dữ liệu; không thêm số lượng/đơn giá không in.
- #196 `mcocr_public_145014bbnco.jpg`: Báo cáo POS; chỉ sửa lỗi đọc số và mô tả, không thay chính sách loại chứng từ.
- #203 `mcocr_public_145014btewf.jpg`: Giữ TIMESTAMP giờ vào 20.45 đang gán đúng; có giờ ra 20.47, không đổi chính sách lựa chọn thời điểm trong lần rà.
- #241 `mcocr_public_145014egqdh.jpg`: Dòng xúc xích bị bạc mực ở G250g và thành tiền; giữ giá trị cũ khớp đơn giá/số lượng, không khôi phục chữ bằng suy đoán.
- #262 `mcocr_public_145014fdjhi.jpg`: Chữ cuối tên Táo Fuji Nam Phi in không rõ (ổ/ỏ); cần người dùng xác nhận, không mở rộng thành từ suy đoán.
- #271 `mcocr_public_145014fvwak.jpg`: Có hai tờ chồng nhau; dòng cuối Q.lut giay nu L(5cai) chỉ đọc trọn tên và số lượng, các số tiền bị che. Không suy ra từ tổng và không thêm U/L chưa đọc chắc.
- #109 `mcocr_public_145013nwbcg.jpg`: Ngày trên dòng timestamp bị nhạt; giữ 11/08/2020 theo phần nét còn thấy, cần người dùng kiểm tra ngày trước khi hoàn tất.
- #112 `mcocr_public_145013ogxhv.jpg`: Mã trong ngoặc cuối tên son đọc là LP01; phần LP hơi nhòe, cần kiểm tra lại khi duyệt.
- #179 `mcocr_public_145013zguhy.jpg`: Phần cuối địa chỉ đại lý bị nhòe và sát mép phiếu; giữ phần đọc được, cần kiểm tra lại text cuối dòng.

## Sao lưu

Bản trước sửa: `D:\graduation-project-2\dataset_hoadon\annotation_review_backups\member2_train_half_20261006T105008351991Z`.

PASS: aligned arrays, categories, original-coordinate bounds, positive item groups, unchanged rows 283–563, image hashes, image quality, completion, flags, other datasets and workspace config
