# Kiểm tra khai báo trường không xuất hiện — 08/10/2026

Đối chiếu 1,491 ảnh trong train/val của hai member; bỏ qua 123 ảnh có cờ khó đọc. Kiểm tra cấu trúc trường của 1368 ảnh còn lại, xem ảnh gốc của toàn bộ 53 trường hợp thiếu khai báo.

Đã bổ sung **136 dấu không xuất hiện trên 46 ảnh**. Thay đổi được lưu trong sidecar `.missing_fields.json`, đúng cách giao diện lưu dấu này. CSV nhãn, bbox, nội dung chữ, cờ khó đọc, trạng thái hoàn tất và góc xoay giữ nguyên.

| Tập | Tổng ảnh | Bỏ qua khó đọc | Ảnh bổ sung dấu |
|---|---:|---:|---:|
| member_1 / train | 559 | 49 | 1 |
| member_1 / val | 184 | 13 | 0 |
| member_2 / train | 563 | 45 | 45 |
| member_2 / val | 185 | 16 | 0 |

## Danh sách ảnh đã sửa

Vị trí tính từ 1 theo thứ tự CSV hiện tại. Các trường mặt hàng có hậu tố `:line_item_id`; hóa đơn treo dùng nhóm 1 cho cả bốn trường.

| Member / tập | Vị trí | Ảnh | Các dấu bổ sung |
|---|---:|---|---|
| member_1 / train | 238 | mcocr_public_145014eamas.jpg | TIMESTAMP |
| member_2 / train | 3 | mcocr_public_145013aeriv.jpg | TIMESTAMP |
| member_2 / train | 15 | mcocr_public_145013bybgv.jpg | ITEM_NAME:1, LINE_TOTAL:1, QUANTITY:1, TOTAL_COST, UNIT_PRICE:1 |
| member_2 / train | 17 | mcocr_public_145013cezfv.jpg | ADDRESS, TOTAL_COST |
| member_2 / train | 21 | mcocr_public_145013clltn.jpg | TIMESTAMP |
| member_2 / train | 23 | mcocr_public_145013cnknh.jpg | TIMESTAMP |
| member_2 / train | 30 | mcocr_public_145013cxtop.jpg | ADDRESS |
| member_2 / train | 39 | mcocr_public_145013dxavh.jpg | ITEM_NAME:1, LINE_TOTAL:1, QUANTITY:1, TOTAL_COST, UNIT_PRICE:1 |
| member_2 / train | 46 | mcocr_public_145013eicdg.jpg | TIMESTAMP |
| member_2 / train | 55 | mcocr_public_145013fskld.jpg | UNIT_PRICE:1, UNIT_PRICE:2, UNIT_PRICE:3 |
| member_2 / train | 57 | mcocr_public_145013geohx.jpg | QUANTITY:10, UNIT_PRICE:10 |
| member_2 / train | 59 | mcocr_public_145013gguch.jpg | QUANTITY:2, UNIT_PRICE:2 |
| member_2 / train | 112 | mcocr_public_145013ogxhv.jpg | ADDRESS |
| member_2 / train | 121 | mcocr_public_145013qikxs.jpg | UNIT_PRICE:1 |
| member_2 / train | 136 | mcocr_public_145013sqwxo.jpg | ITEM_NAME:1, LINE_TOTAL:1, QUANTITY:1, TOTAL_COST, UNIT_PRICE:1 |
| member_2 / train | 140 | mcocr_public_145013tljfn.jpg | ITEM_NAME:1, LINE_TOTAL:1, QUANTITY:1, TOTAL_COST, UNIT_PRICE:1 |
| member_2 / train | 166 | mcocr_public_145013wwkrv.jpg | ITEM_NAME:1, LINE_TOTAL:1, QUANTITY:1, TOTAL_COST, UNIT_PRICE:1 |
| member_2 / train | 176 | mcocr_public_145013zcfau.jpg | ITEM_NAME:1, LINE_TOTAL:1, QUANTITY:1, TOTAL_COST, UNIT_PRICE:1 |
| member_2 / train | 189 | mcocr_public_145014aqymg.jpg | TIMESTAMP |
| member_2 / train | 195 | mcocr_public_145014ayyud.jpg | QUANTITY:1, UNIT_PRICE:1 |
| member_2 / train | 205 | mcocr_public_145014bwelu.jpg | QUANTITY:3, UNIT_PRICE:3 |
| member_2 / train | 207 | mcocr_public_145014cfgjy.jpg | QUANTITY:2, UNIT_PRICE:2 |
| member_2 / train | 219 | mcocr_public_145014cuqln.jpg | ITEM_NAME:1, LINE_TOTAL:1, QUANTITY:1, TOTAL_COST, UNIT_PRICE:1 |
| member_2 / train | 254 | mcocr_public_145014etxsp.jpg | ITEM_NAME:1, LINE_TOTAL:1, QUANTITY:1, TOTAL_COST, UNIT_PRICE:1 |
| member_2 / train | 279 | mcocr_public_145014gkduf.jpg | QUANTITY:2, UNIT_PRICE:2 |
| member_2 / train | 320 | mcocr_public_145014jkegi.jpg | ITEM_NAME:1, LINE_TOTAL:1, QUANTITY:1, TOTAL_COST, UNIT_PRICE:1 |
| member_2 / train | 326 | mcocr_public_145014kbcho.jpg | ITEM_NAME:1, LINE_TOTAL:1, QUANTITY:1, TOTAL_COST, UNIT_PRICE:1 |
| member_2 / train | 342 | mcocr_public_145014lfctk.jpg | ITEM_NAME:1, LINE_TOTAL:1, QUANTITY:1, TOTAL_COST, UNIT_PRICE:1 |
| member_2 / train | 349 | mcocr_public_145014lqokm.jpg | ITEM_NAME:1, LINE_TOTAL:1, QUANTITY:1, TOTAL_COST, UNIT_PRICE:1 |
| member_2 / train | 370 | mcocr_public_145014mpsud.jpg | ITEM_NAME:1, LINE_TOTAL:1, QUANTITY:1, TOTAL_COST, UNIT_PRICE:1 |
| member_2 / train | 377 | mcocr_public_145014ngihg.jpg | QUANTITY:4, QUANTITY:6, UNIT_PRICE:4, UNIT_PRICE:6 |
| member_2 / train | 386 | mcocr_public_145014nsqiz.jpg | ITEM_NAME:1, LINE_TOTAL:1, QUANTITY:1, TOTAL_COST, UNIT_PRICE:1 |
| member_2 / train | 389 | mcocr_public_145014nwpjb.jpg | TIMESTAMP |
| member_2 / train | 443 | mcocr_public_145014rqund.jpg | TIMESTAMP |
| member_2 / train | 460 | mcocr_public_145014sncle.jpg | UNIT_PRICE:1 |
| member_2 / train | 468 | mcocr_public_145014tkueb.jpg | ADDRESS |
| member_2 / train | 470 | mcocr_public_145014tnnoi.jpg | TIMESTAMP |
| member_2 / train | 476 | mcocr_public_145014tvfga.jpg | ITEM_NAME:1, LINE_TOTAL:1, QUANTITY:1, TOTAL_COST, UNIT_PRICE:1 |
| member_2 / train | 477 | mcocr_public_145014twoee.jpg | ADDRESS, SELLER, TOTAL_COST |
| member_2 / train | 482 | mcocr_public_145014uimoq.jpg | ITEM_NAME:1, LINE_TOTAL:1, QUANTITY:1, TOTAL_COST, UNIT_PRICE:1 |
| member_2 / train | 491 | mcocr_public_145014vitnu.jpg | ITEM_NAME:1, LINE_TOTAL:1, QUANTITY:1, UNIT_PRICE:1 |
| member_2 / train | 509 | mcocr_public_145014woqkn.jpg | ITEM_NAME:1, LINE_TOTAL:1, QUANTITY:1, UNIT_PRICE:1 |
| member_2 / train | 511 | mcocr_public_145014wpplc.jpg | ITEM_NAME:1, LINE_TOTAL:1, QUANTITY:1, UNIT_PRICE:1 |
| member_2 / train | 513 | mcocr_public_145014wscvw.jpg | TIMESTAMP |
| member_2 / train | 545 | mcocr_public_145014yrxvd.jpg | TIMESTAMP |
| member_2 / train | 549 | mcocr_public_145014yxijr.jpg | ITEM_NAME:1, LINE_TOTAL:1, QUANTITY:1, UNIT_PRICE:1 |

## Trường hợp cần xử lý riêng

Không đánh dấu vắng mặt cho các giá trị có in nhưng thiếu nhãn hoặc bị giấy rách/nếp gấp che. Danh sách chi tiết trong `EXCEPTIONS.csv`.

| Member / tập | Vị trí | Ảnh | Trường | Kết luận |
|---|---:|---|---|---|
| member_1 / train | 82 | mcocr_public_145013jiksh.jpg | TOTAL_COST | Tổng tiền 243.400 có trên ảnh; box tổng tiền bị gán LINE_TOTAL:1. |
| member_1 / train | 315 | mcocr_public_145014jcwux.jpg | ADDRESS | Địa chỉ 104 Trần Phú - phường Cẩm Tây - Thành phố Cẩm Phả - Quảng Ninh có in, thiếu bbox. |
| member_2 / train | 57 | mcocr_public_145013geohx.jpg | ITEM_NAME:10, LINE_TOTAL:4, LINE_TOTAL:7 | Dòng KM không có SL/đơn giá; tên KM bị thiếu nhãn. Box thành tiền nhóm4/7 bị gán UNIT_PRICE. |
| member_2 / train | 69 | mcocr_public_145013idjei.jpg | QUANTITY:4 | Số lượng Ngòi chì 7004 có in; bbox bị gán nhầm line_item_id=3. |
| member_2 / train | 210 | mcocr_public_145014ckynq.jpg | TIMESTAMP | Có in ngày 10/08/2020-09: ở cuối, giờ bị cắt phần sau. |
| member_2 / train | 271 | mcocr_public_145014fvwak.jpg | UNIT_PRICE:6, LINE_TOTAL:6 | Đơn giá/thành tiền mặt hàng6 bị nếp gấp che, không phải không xuất hiện. Không suy ra từ tổng tiền. |
| member_2 / train | 377 | mcocr_public_145014ngihg.jpg | ITEM_NAME:4, ITEM_NAME:6 | Hai dòng KM có tên nhưng thiếu bbox, không in SL và đơn giá. |
| member_2 / train | 475 | mcocr_public_145014ttrrd.jpg | QUANTITY:1 | Giấy rách đúng ô SL, không đọc được số lượng. Không suy đoán từ đơn giá và thành tiền. |
| member_2 / train | 531 | mcocr_public_145014xwajt.jpg | TIMESTAMP | Có in 10/08/2020-19:43 ở cuối hóa đơn, thiếu bbox. |

## Tệp kiểm tra

- `CHANGED_IMAGES.csv`: danh sách ảnh thực sự đã bổ sung dấu.
- `ALL_IMAGES_AUDIT.csv`: kết quả đối chiếu từng ảnh, bao gồm ảnh bỏ qua.
- `EXCEPTIONS.csv`: trường có in thiếu nhãn hoặc không đọc được.
- `verification.json`: thống kê và kiểm tra bảo toàn dữ liệu.

Bản sao trước khi thay đổi: `D:\graduation-project-2\dataset_hoadon\annotation_review_backups\absence_audit_20261008T154805124278Z`.
