# Kiểm tra ảnh trùng của phân công 50/50 — 06/10/2026

Đối chiếu trực tiếp 1546 ảnh thuộc CSV hiện tại của member 1 và member 2. Không sửa/xóa ảnh, nhãn hoặc trạng thái hoàn tất.

- SHA-256: 53 nhóm trùng, 108 ảnh thuộc các nhóm này, 55 bản dư nếu giữ mỗi ảnh duy nhất một lần.
- Tổng ảnh duy nhất: 1491.
- Trùng giữa member 1 và member 2: 0 nhóm.
- Trùng giữa train và valid: 20 nhóm, có 20 ảnh valid trùng với train.
- Hash trong assignment_manifest.csv khớp ảnh hiện tại: True.
- Kiểm tra pixel RGB giải mã: 53 nhóm; 0 nhóm có ảnh khác hash tệp nhưng cùng pixel.

## Trùng bên trong từng phần

| Phần | Số ảnh | Ảnh duy nhất | Nhóm trùng | Bản dư trong phần |
|---|---:|---:|---:|---:|
| member_1/train | 577 | 559 | 16 | 18 |
| member_1/val | 195 | 195 | 0 | 0 |
| member_2/train | 578 | 563 | 15 | 15 |
| member_2/val | 196 | 194 | 2 | 2 |

## Nhóm trùng giữa train và valid

- member_1/train: `mcocr_public_145013bpcpt.jpg`; member_1/val: `mcocr_val_145115roove.jpg`
- member_1/train: `mcocr_public_145013jechb.jpg`; member_1/val: `mcocr_val_145115fqwje.jpg`
- member_1/train: `mcocr_public_145014aglyp.jpg`; member_1/val: `mcocr_val_145115jbayx.jpg`
- member_1/train: `mcocr_public_145014avuac.jpg`; member_1/val: `mcocr_val_145114aszbc.jpg`
- member_1/train: `mcocr_public_145014divcp.jpg`; member_1/val: `mcocr_val_145115yecqs.jpg`
- member_1/train: `mcocr_public_145014dkmtx.jpg`; member_1/val: `mcocr_val_145115aohoe.jpg`
- member_1/train: `mcocr_public_145014fltno.jpg`; member_1/val: `mcocr_val_145115zpaiz.jpg`
- member_1/train: `mcocr_public_145014upass.jpg`; member_1/val: `mcocr_val_145115bttrw.jpg`
- member_1/train: `mcocr_public_145014vxrob.jpg`; member_1/val: `mcocr_val_145115jxfng.jpg`
- member_1/train: `mcocr_public_145014wpnpe.jpg`; member_1/val: `mcocr_val_145115nypff.jpg`
- member_1/train: `mcocr_public_145014xsppi.jpg`; member_1/val: `mcocr_val_145115ishek.jpg`
- member_2/train: `mcocr_public_145013adyee.jpg`; member_2/val: `mcocr_val_145115thtzv.jpg`
- member_2/train: `mcocr_public_145013geohx.jpg`; member_2/val: `mcocr_val_145115fcnxy.jpg`
- member_2/train: `mcocr_public_145013nwbcg.jpg`; member_2/val: `mcocr_val_145115kexzv.jpg`
- member_2/train: `mcocr_public_145014jgtbj.jpg`; member_2/val: `mcocr_val_145115bxrpi.jpg`
- member_2/train: `mcocr_public_145014mdhan.jpg`; member_2/val: `mcocr_val_145115rrirk.jpg`
- member_2/train: `mcocr_public_145014mnwrz.jpg`; member_2/val: `mcocr_val_145115pwzhy.jpg`
- member_2/train: `mcocr_public_145014qjkba.jpg`; member_2/val: `mcocr_val_145115upgly.jpg`
- member_2/train: `mcocr_public_145014wvmqh.jpg`; member_2/val: `mcocr_val_145115hupmg.jpg`
- member_2/train: `mcocr_public_145014xsefn.jpg`; member_2/val: `mcocr_val_145115scqcn.jpg`

README của phân công ghi quy tắc gom ảnh trùng vào cùng người, giữ nguyên nguồn và CSV master. Đây là phân công công việc, không phải thao tác loại bản trùng hay chia train/valid chống rò rỉ.

Danh sách mọi bản trùng: [duplicate_groups.csv](duplicate_groups.csv). Báo cáo này kiểm tra trùng tuyệt đối theo byte và pixel; không xác nhận toàn bộ trường hợp ảnh gần giống do nén khác, cắt, đổi kích thước hoặc xoay.
