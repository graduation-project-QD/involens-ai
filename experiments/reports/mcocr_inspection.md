# T01 MC-OCR local dataset inspection

Ngày kiểm tra: 2026-09-14. Đường dẫn thực tế: `D:\graduation-project-2\dataset_hoadon`. Đường dẫn được nhắc `D:\graduation-project-2\dataset\_hoadon` không tồn tại. Dataset nguồn được giữ nguyên; không sửa nhãn, không tạo split, không train model hay viết loader trong T01.

## Kết luận

Có thể tiến hành T01 và chuẩn bị T04/T06 với CSV train sau QA. Bộ local chứa receipt MC-OCR và nhiều dữ liệu xử lý sẵn; không được coi tất cả file JPG là receipt độc lập. **Chưa đủ điều kiện gọi bộ local là gold OCR toàn trang hoặc dùng CSV validation làm ground truth KIE.** Cần xác minh nguồn/release, nhãn bất thường và nguồn tạo các file dẫn xuất.

## Kiểm kê và chất lượng ảnh

Toàn cây có **61.340 files**, gồm 54.402 JPG, 5.777 TXT, 1.151 TSV, 4 CSV, 2 PKL và 4 files không đuôi (gitkeep). File manifest account toàn bộ paths/size; hashes metadata bao phủ CSV/TXT/TSV. Không cộng 54.402 JPG thành quy mô receipt dataset.

| Phạm vi ảnh full decode + SHA-256 | Files | Hash độc lập | Decode lỗi |
|---|---|---|---|
| Raw train | 1.155 | 1.122 | 0 |
| Raw validation | 391 | 389 | 0 |
| KIE images dẫn xuất | 1.155 | Không dùng làm receipt mới | 0 |

Raw train+val hợp lại có **1.491 hash ảnh độc lập**; đây là số unique bytes, chưa phải số receipt độc lập sau near-duplicate audit. Train width 352–1.024 px, height 480–2.860 px; validation width 472–1.024 px, height 576–3.684 px. KIE images có dimensions khác raw trong nhiều trường hợp; chưa xác minh transform chain nên không gắn trực tiếp boxes KIE lên raw images.

CSV có **6.585 annotated field regions**, mỗi receipt 0–29 regions; quality score 0,134141–0,906890, trung bình khoảng 0,669605. Số region theo label: SELLER 1.171, ADDRESS 1.952, TIMESTAMP 1.347, TOTAL_COST 2.114 và TOTAL_TOTAL_COST 1. Số record không chứa label chuẩn: company 84, address 78, date 67, total 74 (bao gồm trường hợp nhãn total bất thường). Không tự coi những record này là gold field absent.

Kiểm tra toàn CSV không thấy duplicate img_id, parser mismatch sau xử lý empty lists đúng, annotation-image width/height mismatch, bbox ngoài ảnh quá dung sai 2 px, bbox kích thước không dương, polygon thiếu số điểm/chẵn-lẻ sai hoặc tọa độ không finite. Đây là kiểm tra cấu trúc/hình học, không chứng minh text hay vị trí annotation đúng về ngữ nghĩa.

## Exact duplicates và ảnh hưởng split

SHA-256 trên raw/KIE images có 84 duplicate groups trong phạm vi đã kiểm. Trong raw train+val có **53 groups**: 31 nội bộ train, 20 giao giữa train và val, 2 nội bộ val. KIE images có thêm 31 duplicate groups nội bộ. Không thấy exact duplicate bytes giữa raw train và KIE image copy, nhưng cùng filename là dẫn xuất cùng receipt, không độc lập.

Ví dụ cross-folder: `train_images/train_images/mcocr_public_145013adyee.jpg` và `val_images/val_images/mcocr_val_145115thtzv.jpg` có SHA-256 giống nhau. Vì vậy filename-disjoint **không** chứng minh split độc lập. Toàn bộ 20 groups cross train/val được lưu trong manifest.

Cả 31 nhóm ảnh duplicate nội bộ train có annotation serialization khác nhau (polygon/text/labels/count). Chưa phân loại khác biệt do re-annotation hợp lệ hay annotation xung đột; T04 cần QA trước chọn gold. Không tự chọn record đầu hoặc merge labels thành ground truth. T06 phải group duplicates và các ảnh gần trùng; train/val crop lists filename-disjoint vẫn chưa đủ chống leakage do duplicate receipt dưới tên khác.

## Annotation CSV train

File `mcocr_train_df.csv` có 1.155 record. Cột thực tế: `img_id, anno_polygons, anno_texts, anno_labels, anno_num, anno_image_quality`. `anno_polygons` là chuỗi Python literal list of dictionaries, đã đọc bằng parser literal an toàn; text và labels dùng `|||`.

Polygon record chứa category_id, segmentation (có thể nhiều polygon), area, bbox dạng **x,y,width,height**, width/height ảnh. Không giả segmentation luôn là quadrilateral; ảnh ví dụ có polygon nhiều điểm và multipart segmentation. Khi chuyển sang xyxy, phải tính x1=x+w/y1=y+h. Không lấy segmentation đầu tiên rồi bỏ phần còn lại im lặng.

Hai record có `anno_num=0`, polygons `[]`, text/labels rỗng:

- `mcocr_public_145014iwhec.jpg`
- `mcocr_public_145014jndnz.jpg`

CSV rỗng phải parse thành list rỗng, **không** thành list một phần tử chuỗi rỗng. Sau cách xử lý đúng, không có mismatch độ dài polygon/text/label/anno_num trong toàn bộ 1.155 records. Hai record trên chưa chứng minh 4 fields thực sự absent; đưa vào QA, không tự tạo O/missing GT hay xóa source.

Một label bất thường: `TOTAL_TOTAL_COST` ở `mcocr_public_145013kzjew.jpg`. Không tự sửa thành TOTAL_COST; cần đối chiếu ảnh/polygon/text và audit mapping riêng.

| Category ID quan sát | Label quan sát | Canonical field đề xuất | Trạng thái |
|---|---|---|---|
| 15 | SELLER | company | Quan sát từ CSV; cần QA trước freeze mapping |
| 16 | ADDRESS | address | Quan sát từ CSV; không có label_dict local |
| 17 | TIMESTAMP | date | Có cả prefix/giờ trong transcript; giữ raw |
| 18 | TOTAL_COST | total | Có thể gồm keyword và amount ở nhiều vùng |
| 18 | TOTAL_TOTAL_COST | unresolved | Không sửa label nguồn |

## CSV validation và results

`val_images/val_images` có 391 ảnh. `mcocr_val_sample_df.csv` và `results.csv` có cùng nội dung: cột img_id/anno_image_quality/anno_texts, transcript mẫu `abc abc abc`. Đây là submission/sample content, **không dùng làm GT OCR hay GT fields**. Quality 0,5 trong template không được xem là quality score gold.

T06 nên giữ nhóm ảnh này ngoài local gold evaluation nếu không bổ sung GT. Chia train/validation/test từ phần train có nhãn đã QA theo grouping/seed/protocol trong implementation plan. Không gộp CSV validation sample vào labeled train.

## Dữ liệu dẫn xuất

| Nhóm | Kết quả inspection | Cách dùng an toàn |
|---|---|---|
| `kie_data/kie_data/boxes_and_transcripts` | 1.151 file đuôi TSV, nội dung comma-separated; 40.868 dòng, 20.085 transcript trống | Chưa coi là human GT toàn trang; cần provenance và đối chiếu CSV/ảnh |
| Nhãn TSV | OTHER=33.481, TIMESTAMP=1.769, TOTAL_COST=2.532, ADDRESS=1.935, SELLER=1.151 | Không tự dùng OTHER làm gold background |
| TSV parsing | ID + 8 tọa độ đầu, phần text có thể chứa comma, nhãn ở comma cuối | Không split mọi comma rồi giả text không chứa delimiter; không dùng tab parser chỉ vì extension |
| `dataset/text_detector/txt` | 1.155 files, 47.626 regions, toàn bộ text rỗng | Geometry-only; chưa chứng minh bbox là human GT detection |
| `text_detector/text_detector/txt` | Cũng 1.155 files, 47.626 regions, text rỗng | Có khả năng copy; phải dùng hash/provenance trước chọn canonical source |
| `text_recognition_train_data.txt` | 5.285 crop entries, 922 receipt parents | Chỉ có crop text; kiểm tra nguồn text và geometry mapping trước OCR eval |
| `text_recognition_val_data.txt` | 1.300 crop entries, 231 receipt parents | Là split crop từ labeled train receipts, khác 391 official val images |
| Recognition crops | 6.585 JPG, tất cả file được list đều tồn tại; parents của hai lists không overlap theo filename | Không coi crop là receipt độc lập; split mới phải theo receipt parent |
| `data0.7` | 1.044 JPG | Chưa có provenance; không gộp vào train như ảnh độc lập |
| `data0_or_180` | 35.987 JPG | Tên gợi ý dữ liệu orientation/crop; nội dung/nguồn chưa xác minh, không đưa vào split |
| `preprocessor` | 1.155 JPG, 1.155 TXT và một file không đuôi | Dẫn xuất chưa xác minh; không thay raw images ngầm |
| `pre_dict.pkl`, `post_dict.pkl` | Có file local | Không unpickle trong inspection; không xem là GT khi chưa xác minh nguồn |

Bốn CSV train receipts không có TSV tương ứng: `mcocr_public_145013uqtmx.jpg`, `mcocr_public_145014iwhec.jpg`, `mcocr_public_145014jndnz.jpg`, `mcocr_public_145014mwhyh.jpg`. Không có TSV ngoài train CSV. Không có ảnh train thiếu CSV hoặc record CSV thiếu ảnh train. Train/391 val không có filename trùng; không đủ để kết luận không có ảnh gần trùng.

## Coverage OCR và KIE

CSV train annotation bao phủ các vùng nhãn field, không có transcript OTHER toàn trang. Sample trực quan `mcocr_public_145013ddcph.jpg` có tên hàng, giá và thông tin khác không xuất hiện trong 5 regions CSV. TOTAL_COST chứa cả keyword và số tiền, TIMESTAMP chứa cả prefix/giờ. Không thể zip labels rồi coi mỗi line là chỉ value đã clean.

TSV ví dụ cùng receipt có nhiều dòng không transcript và chứa text khác OCR-looking. Đây là lý do cần provenance; **không kết luận chắc chắn chúng do OCR tạo hoặc là human labels chỉ từ hình thức**. Hiện có thể chuẩn bị đánh giá field extraction từ CSV đã QA và CER/WER vùng field có transcript gold. Chưa thể báo CER/WER toàn trang, full-page token/entity F1 gold, hay recognition-only gold từ crop list chưa kiểm chứng.

Không tự nối tất cả vùng TOTAL_COST thành final amount, không gọi category field regions là gold word-level boxes. T04/T15 cần xác lập entity/value-span rubric, alignment policy và giữ annotation coverage/missingness.

## Provenance và giới hạn inspection

Không có README, LICENSE hoặc label_dict trong cây file local đã kiểm kê. Chưa có nguồn tải/release/archive checksum hoặc thông tin tác giả tạo dữ liệu dẫn xuất. Ngày timestamp file khoảng 2022 không xác nhận version. Cần người dùng cung cấp nguồn tải khi tiện; việc này không chặn kiểm tra file local, nhưng còn mở trước công bố nguồn/reuse.

Không tải dữ liệu mới hay dùng thông tin web thay cho actual inventory. Không train, không tạo processed dataset hoặc split. Chỉ dùng Python kiểm tra đọc CSV/TSV, literal parsing, ảnh và hashes, không tạo code module AI. Inventory metadata có text IDs/paths/hashes, không lưu full receipt text trong report.

Near-duplicate/perceptual audit, QA thủ công mẫu đa dạng, và decode mọi crop/ảnh dẫn xuất ngoài KIE images chưa thực hiện; thuộc bước chuẩn bị T04/T06 trước freeze split. Chỉ một receipt đã được xem trực quan, không tuyên bố hoàn tất QA 50 receipt. Quan sát nội dung ảnh bằng mắt không thay thế gold transcription.

## Open tasks để đi tiếp

1. Xác minh nguồn tải/release và provenance các thư mục dẫn xuất.
2. QA nhãn TOTAL_TOTAL_COST và hai records anno_num=0; giữ correction/mapping audit, không sửa source.
3. T04 xây canonical loader từ CSV field annotations; label mapping/version và coverage rõ.
4. Xác minh hoặc tìm transcript gold toàn trang nếu cần CER/WER end-to-end; trước đó chỉ báo field-region OCR và coverage.
5. T06 exact/near-duplicate grouping trên raw receipts, giữ toàn bộ crops/dẫn xuất của một receipt trong cùng split; không reuse crop split như receipt test split.
6. Xác minh nguồn TSV/background trước dùng O; nếu chỉ weak labels thì ghi rõ và QA.

## Artifacts

- `experiments/manifests/mcocr_files.csv`: toàn bộ file paths/size trong cây dataset.
- `experiments/manifests/mcocr_inventory.json`: summary, statistics và phạm vi image checks.
- `experiments/manifests/mcocr_image_inventory.jsonl`: hashes, kích thước và decode status của raw train/val và KIE images.
- `experiments/manifests/mcocr_annotation_inventory.jsonl`: record IDs, region counts, labels và quality.
- `experiments/manifests/mcocr_issues.jsonl`: 3 records cần QA (2 empty annotations, 1 unknown label); không có parser/hình học lỗi trong phạm vi checks đã nêu.
- `experiments/manifests/mcocr_metadata_hashes.jsonl`: checksums CSV/TXT/TSV.
- `experiments/manifests/mcocr_exact_duplicates.jsonl`: exact image hash groups trong phạm vi ảnh đã kiểm.
- `experiments/manifests/mcocr_tsv_coverage.jsonl`: counts và transcript-empty counts theo receipt TSV.
- `experiments/manifests/mcocr_supplemental_checks.json`: empty-string-aware count checks, field anomalies, correspondence và crop parent split audit.

**Trạng thái:** inspection local được thực hiện; follow-up về provenance, annotation QA và gold OCR coverage còn mở. Không đồng nghĩa toàn bộ dataset đã sẵn sàng để training/evaluation.
