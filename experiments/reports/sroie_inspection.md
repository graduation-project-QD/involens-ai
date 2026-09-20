# T02 SROIE2019 local inspection

Ngày kiểm tra: 2026-09-14. Owner: Member A. Dataset thực tế: `D:\graduation-project-2\dataset_hoadon\SROIE2019`. Đường dẫn `D:\graduation-project-2\dataset\_hoadon\SROIE2019` người dùng nhắc không tồn tại; thư mục tương ứng đã được tìm thấy dưới `dataset_hoadon`.

**Đã thực hiện local inspection T02 và gắn benchmark protocol với bản local.** Đây không phải chạy benchmark T25 hay QA sửa nhãn T04. Nguồn tải/release và một số annotation semantics vẫn cần xác minh; không ghi dataset là đã QA hoàn toàn hoặc split là sạch leakage. Không sửa file nguồn, không train, không triển khai loader/model/API.

## 1. Inventory và actual split

Toàn thư mục có **2.925 files**, dung lượng **1.016.463.701 bytes** gồm **973 ảnh JPG, 1.946 annotation TXT**, và 6 assets trong `layoutlm-base-uncased`. Không cộng assets model vào annotation hay quy mô receipt dataset. Không có README/LICENSE, archive nguồn hoặc revision metadata để xác định bản mirror chính xác.

| Provided split | Ảnh | OCR box TXT | KIE entities TXT | Decode lỗi | JSON parse lỗi | OCR numeric/delimiter parse lỗi |
|---|---|---|---|---|---|---|
| train | 626 | 626 | 626 | 0 | 0 | 0 |
| test | 347 | 347 | 347 | 0 | 0 | 0* |

`*` Một file OCR test không UTF-8; sau decoder tạm phục vụ inspection, tọa độ/delimiter đọc được, nhưng transcript chưa được chốt decoder gold. Không gọi đây là encoding-validation pass hoàn toàn.

Không có provided validation split. 973 ảnh có đủ file OCR và KIE đi kèm, không có ID thiếu/extra giữa img/box/entities, không có filename ID giao train/test. Số actual là **626/347**, không ép thành 600/400 của overview DOCX, cũng không gọi bản local là bản corrected 626/361.

Ảnh width 435–4.961 px, height 605–7.016 px; tất cả 973 ảnh đã load/decode hoàn chỉnh. Không có image-quality score trong KIE JSON; độ phân giải không thay quality score gold. Nhiều scan có chữ nhỏ, nền trắng rộng hoặc nội dung ngoài Latin trong ảnh mẫu; chưa có full manual QA.

Theo giới hạn service v1 **đã chốt ở T03** là 20 MP/10 MiB: 81 ảnh train và 52 ảnh test vượt 20 MP; không ảnh nào vượt 10 MiB. 973 decoded/paired images không có nghĩa 973 request sẽ qua service cap. T03/T07 vẫn cần chốt cách tính 20 MP đối với PDF/render và policy offline benchmark; evaluator phải báo failure/exclusion, không đổi limits riêng theo từng ảnh test để nâng score.

## 2. OCR annotation thực tế

`train/box/{id}.txt` và `test/box/{id}.txt` là text files; mỗi dòng có **8 tọa độ pixel của 4 đỉnh + transcript**. Không phải xywh/xyxy có 4 số, không phải normalized [0,1000]. Inspection parse 8 comma đầu, giữ phần còn lại nguyên transcript; có **1.679 dòng train và 940 dòng test chứa comma trong text**, nên không split tất cả comma rồi lấy một cột text duy nhất.

| OCR statistic | train | test |
|---|---|---|
| Parsed regions | 33.626 | 18.705 |
| Empty transcripts | 0 | 0 |
| Blank lines giữa record | 0 | 1 |
| Transcript đúng chuỗi `***` | 8 | 4 |
| Transcript đúng chuỗi `*` | 21 | 29 |

Tổng **52.331 vùng OCR**. Không thấy tọa độ nonfinite hay polygon vượt bounds ảnh trong các checks; có **1 quadrilateral suy biến** tại `test/box/X51006008092.txt`, dòng 32 (GT text `TOTAL RM`, các đỉnh cùng y). Không tự mở rộng box hay loại GT. Text còn có thể dùng OCR string diagnostic, nhưng crop/geometry alignment phải đưa vào QA.

**Encoding issue:** `test/box/X51006619503.txt` có bytes `A3 AC` sau `KEPONG BARU`. UTF-8 strict thất bại; cp1252 tạo `U+00A3 U+00AC`, GB18030 tạo fullwidth comma `U+FF0C`. Inspection từng dùng cp1252 **provisional**, không chọn nó làm decoder training/evaluation. Visual review ảnh thấy dấu phẩy sau địa danh, phù hợp giả thuyết GB18030 nhưng chưa có guide xác nhận source encoding. T04 cần ghi decoder/QA decision riêng; không dùng `errors=ignore/replace`, không ghi đè file. Các char/word counts thô trong inventory của file này là diagnostic trước decoder/marker policy, không denominators CER/WER final.

**Coverage:** OCR TXT có transcripts nhiều vùng trên receipt, gồm vùng ngoài 4 fields; khác CSV field-only MC-OCR. Tuy nhiên `***` trong mẫu có thể đánh dấu nội dung khó đọc/ngoài Latin; không có local guide xác nhận semantics. Không coi `***` là chữ thật hay tự drop mọi `*` (asterisk đơn có thể là ký tự in thật). Freeze rubric ignored/illegible regions trước T11/T25, lưu coverage và ảnh hưởng predictions trong ignored regions. Chỉ báo OCR trên annotation scope đã kiểm chứng, không claim đọc mọi chữ trên ảnh hoặc mọi ngôn ngữ.

## 3. KIE schema và mapping

Entities TXT có nội dung JSON object, không cần đọc bằng OCR. Key mục tiêu: **company, date, address, total**, giá trị string. Không có BIO/token semantic labels hay gold word-to-field/entity links trong file. File extensions TXT không quyết định parser; nhóm entities dùng JSON, nhóm box dùng tọa độ+transcript.

| Source key | Canonical field | train key có mặt | test key có mặt | Policy |
|---|---|---|---|---|
| company | company | 626 | 347 | Giữ raw, không thay bằng customer/header đầu tiên |
| address | address | 625 | 347 | Missing annotation khác annotated absent |
| date | date | 626 | 347 | Nhiều format; giữ raw, normalized theo rubric |
| total | total | 626, trong đó 1 empty | 347, tất cả non-empty | Không biến empty thành 0 |

Hai findings train: `X51005663280` thiếu key address; `X51005433522` có total rỗng. Giữ nguyên nguồn, đánh dấu QA. Test có đủ 4 keys string non-empty ở toàn bộ 347 records, nhưng vẫn có duplicate labels/encoding/geometry issues; không suy ra GT đúng ngữ nghĩa 100%.

Diagnostic literal presence: sau uppercase/collapse whitespace, company/address/date/total value xuất hiện như substring trong chuỗi OCR gold nối theo file order lần lượt **608/485/622/624** trên train và **339/261/343/347** trên test. Đây **không phải accuracy model hay chứng minh labels sai**; ordering, OCR-vs-KIE spelling, spacing, boundaries và repeated text đều có thể gây mismatch/match giả. Không suy ra gold BIO bằng substring match không QA. T04/T15 cần alignment provenance và ignore ambiguity, không gán O cho mọi vùng không match.

## 4. Date, amount và locale

Đã thống kê cấu trúc date để inspection, không tune parser/checkpoint bằng test. Các nhóm dưới đây chỉ classifier đơn giản đối với numeric date, không phải date normalization đầy đủ:

| Numeric date category | train | test |
|---|---|---|
| DD/MM là diễn giải lịch hợp lệ duy nhất | 252 | 130 |
| MM/DD là diễn giải hợp lệ duy nhất | 2 | 1 |
| DD/MM và MM/DD đều hợp lệ nhưng khác ngày | 146 | 96 |
| Day=month, không khác diễn giải | 9 | 4 |
| Numeric date có năm 2 chữ số | 144 | 66 |
| Format khác (gồm textual month/ISO và các trường hợp khác) | 73 | 50 |

Train có `12/28/2017` và `12/13/2016`; có textual month như `05 MAR 2018` và ISO `2018-03-23`. Không được mặc định mọi SROIE date là DD/MM chỉ vì receipts Malaysia. Unknown locale/ambiguous date giữ raw và warning/null normalized; các dạng đủ rõ có thể parse theo rule đã freeze bằng train/guide. Năm 2 chữ số cần century policy riêng, không tự chọn từ test GT.

Total dạng numeric dot + đúng 2 decimal: 535 train, 282 test; các format khác: 91 train, 65 test. JSON total không có currency key. Ảnh mẫu có `RM` và cũng có template dùng `$`; không suy ra VND, MYR hay USD cho mọi receipt từ symbol/quốc gia. Currency null nếu thiếu bằng chứng; raw total metric vẫn khả thi. Chuỗi decimal giữ precision, không float. Không làm normalized GT bằng cùng bug parser của prediction.

## 5. Exact duplicates, label disagreement và near-duplicate screening

SHA-256 ảnh và hash decoded RGB pixels cho cùng kết quả: **15 duplicate groups**, trong đó **7 groups giao train/test**, 5 nội bộ train, 3 nội bộ test. Unique image byte hashes: **958** toàn bộ, **621** train, **344** test. Không có exact hash giao với raw MC-OCR inventory đã kiểm ở T01; đây là byte-hash check, không chứng minh không có near-duplicate cross-dataset.

| Train ID | Test ID — cùng ảnh bytes |
|---|---|
| X51006329399 | X51006328937 |
| X51006332575 | X51006328967 |
| X51006328913 | X51006329388 |
| X51007135247 | X51006401853 |
| X51006008095 | X51009008095 |
| X51005453729 | X51009453729 |
| X51005568881 | X51009568881 |

Trong 15 groups có **5 groups JSON entities khác nhau**, và cả 15 groups OCR annotation bytes khác nhau. Byte khác chưa đồng nghĩa OCR text sai (có thể khác order/format/boxes); entity JSON khác cần QA. Không tự chọn labels từ train để sửa test, không merge source hay kết luận split sạch chỉ vì IDs khác.

Near screening: dHash64, Hamming≤4 và aspect ratio delta≤0,03 cho **2.589 candidate pairs**; lọc thêm cosine pHash Hamming≤6 còn **436 pairs**, gồm **175 cross-split**. Đây là **candidates, không phải 436 ảnh/receipt trùng**, không là proof audit hoàn chỉnh. Nền trắng và template giống nhau gây false positives. Đã review cặp `test/X51005442334` và `train/X51005442386`: cùng template nhưng ngày/invoice/items/total khác, xác nhận **receipt khác nhau** dù pHash bằng nhau. Còn 435 candidate pairs chưa QA; không group dựa perceptual hash một mình. Lưu review riêng.

**Split recommendation công khai:** benchmark zero-shot chính giữ provided test 347 IDs và disclosure duplicates/GT issues; thêm clean sensitivity subset nếu nhóm chốt tiêu chí và version manifest, không tự giảm sample size hay đổi split trong T02. Nếu fine-tune SROIE sau này, phải group/remove leakage từ development data trước train và audit lại; cannot use untouched provided split as leakage-free supervised benchmark. Giữ các bản cùng receipt/crops/dẫn xuất cùng group. Không có train SROIE trong protocol primary nên 7 cross-split groups không gây SROIE-trained leakage cho zero-shot, nhưng vẫn ảnh hưởng claims về split và independent receipt counts.

## 6. Model assets đi kèm

`layoutlm-base-uncased` có config, vocab/tokenizer assets, weights BIN và training_args BIN. Config có vocab_size 30.522/num_labels 2; **không có bằng chứng đó là checkpoint LayoutXLM MC-OCR fine-tuned cho 4 fields**. Inspection chỉ đọc JSON/text và hash bytes; không torch.load/unpickle BIN, không chạy checkpoint, không gọi model có sẵn này là model chính. Source/training provenance vẫn unknown. Loại assets này khỏi receipt manifests.

## 7. Protocol binding và acceptance T02

Protocol `sroie_mcocr_zero_shot_v1` trong `sroie_protocol.md` được giữ: **frozen PaddleOCR/rules và MC-OCR-trained LayoutXLM → provided SROIE test**. Không train/tune trên SROIE test, không đổi model vì thư mục chứa LayoutLM assets. Trạng thái specification đã gắn content digest/split hashes, runtime/checkpoint freeze cần T18/T21 trước T25.

| T02 requirement | Kết quả |
|---|---|
| Actual local files và N/splits | Đã kiểm kê 2.925 files, 626/347 provided split |
| Correspondence OCR/KIE và usable/decode counts | Đã kiểm tra toàn bộ 973 ảnh/paired files; all images decoded |
| Actual annotation parsing, missingness và quality risks | Đã kiểm tra; 4 record-level findings và marker/locale notes |
| Leakage/overlap | Đã exact/pixel hash audit, candidate near screening; semantics QA còn mở |
| Mapping/locale/currency | Mapping 4 keys xác nhận; mixed date/currency thiếu thông tin được ghi, không invent locale |
| Inspection fixture tests | PASS comma/empty/missing-key/nonfinite/malformed behavior; không phải production loader tests |
| Protocol zero-shot và artifacts | Đã cập nhật; benchmark NOT_RUN chờ trained release T25 |
| Source/release/license | Chưa có local guide/nguồn tải; follow-up cần người dùng xác nhận |

**Status: LOCAL_INSPECTION_COMPLETED_WITH_OPEN_FINDINGS.** Mục tiêu inspection/report/protocol của T02 đã thực hiện. Không đóng annotation QA, provenance hoặc production loader/evaluation readiness thay T04/T06/T11. T02 không phải yêu cầu train SROIE; `NOT_RUN` model evaluation là trạng thái T25, không kết luận inspection chưa làm.

## 8. Artifacts và follow-up

Trong `experiments/manifests` đã lưu summary `sroie_inventory.json`, detailed `sroie_local_audit.json`; JSONL per-file hashes, image metadata/status, OCR region counts/encoding, KIE missingness, 4 findings, exact/pixel duplicates, duplicate annotation comparisons, near candidates/refinement/hashes/reviews; marker/encoding JSONs; **provided train/test manifests** có image/OCR/KIE checksums. Không tạo random split mới.

Follow-up bắt buộc trước scoring: source/version note; missing/empty/duplicate label QA; decoder và illegible-marker rubric; degenerate box policy; service cap thống nhất và locale/currency policy. Near candidate review cần trước claim supervised split sạch. T03 API contract có thể bắt đầu độc lập; T04 loader/QA cho cả MC-OCR và SROIE nay có actual-format evidence.

Lần kiểm tra đã đọc annotation test phục vụ audit format/completeness, không xem predictions model hay tune model/rules. Phải ghi test-inspection access trong experiment log, không gọi test là chưa từng đọc annotation. Audit này không thay gold transcription/semantic manual QA toàn tập. Toàn bộ source được giữ nguyên, hashes là record tham chiếu để lần sau xác minh.

Kiểm tra artifacts cuối cùng **PASS**: account đủ 2.925 files, JSON/JSONL hợp lệ, 973 image records và 52.331 OCR regions khớp summary, 4 record-level findings khớp issue log, provided manifest SHA-256 khớp bytes thực trên Windows, zero-shot model policy nhất quán. Đã tính lại SHA-256 toàn bộ source files sau inspection và xác nhận **không file nguồn nào thay đổi**. Kết quả trong `experiments/manifests/sroie_inspection_checks.json`; không phải production loader/model tests.
