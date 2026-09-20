# T02 SROIE inspection status và benchmark protocol

Ngày lập/cập nhật: 2026-09-14. Protocol ID: `sroie_mcocr_zero_shot_v1`. Owner: Member A. Trạng thái: **local inspection completed with open findings; protocol specification bound to local dataset**. Chưa chạy model benchmark T25; provenance, decoder/marker và semantic label QA còn mở trước scoring.

## 1. Kết luận và bằng chứng local

Sau khi người dùng cung cấp đường dẫn, tìm thấy SROIE ở `D:\graduation-project-2\dataset_hoadon\SROIE2019` (không phải `dataset\_hoadon\SROIE2019`). Bản kiểm tra trước “not found” là trạng thái lịch sử trước khi thư mục này có mặt, đã được cập nhật. Xem [báo cáo actual inspection](sroie_inspection.md) cho thống kê và findings đầy đủ.

Actual provided split: **626 train/347 test**, 973 ảnh đều decode được và có paired OCR/KIE TXT; 52.331 OCR regions. Có 7 exact duplicate groups giữa train/test, một missing address/empty total trên train, một test degenerate quad và một test OCR non-UTF8. Không dùng published counts thay actual N. File/image/split hashes và findings được lưu trong manifests. Chưa viết production loader, train hoặc chạy benchmark model; chỉ parse/kiểm tra phục vụ inspection và ghi provided split manifests, không chia tập mới.

External dependency về path/data đã được giải quyết. Source URL/release/guide/license còn unknown vì local không có README/LICENSE; bản local chỉ được nhận diện bằng content digest, không suy từ 626/347 rằng biết chính xác mirror. Annotation QA và encoding/marker policy tiếp tục ở T04/T11, không sửa GT nguồn trong T02.

## 2. Đối chiếu nguồn và khác biệt phiên bản

Paper của nhóm tổ chức mô tả 1.000 receipt scan với trainval/test 600/400; OCR annotation có bốn đỉnh và transcript từng vùng, KIE dùng JSON field values. OCR challenge xếp hạng bằng word P/R/F1, khác CER/WER mà đồ án yêu cầu. Vì vậy không gọi CER/WER của đồ án là official SROIE leaderboard score. [Paper SROIE, mục II–III](https://arxiv.org/html/2103.10213v1).

Hai URL RRC trong DOCX (`https://rrc.cvc.uab.es/?ch=13` và `?ch=13&com=tasks`) không truy cập được qua web tool ở lần kiểm tra này; không kết luận website đã ngừng hoạt động. Paper là nguồn chính cho mô tả challenge, không thay actual release.

Dataset card do maintainer bản `jsdnrs/ICDAR2019-SROIE` công bố mô tả receipt tiếng Anh ở Malaysia, bổ sung 14 test annotations, có corrections và schema image/image_size/entities/words/bboxes; metadata card ghi 626 train, 361 test. Đây là **bản dẫn xuất đã sửa/bổ sung**, không gọi là bản nguyên gốc 600/400 hay gộp với benchmark 626/347. Card công bố CC-BY-4.0; thông tin nguồn/revision và điều khoản thực của bản được chọn vẫn phải ghi khi acquisition. [Dataset card của bản dẫn xuất](https://huggingface.co/datasets/jsdnrs/ICDAR2019-SROIE/blob/main/README.md).

**Decision:** dùng bản local người dùng cung cấp cho benchmark sau QA, giữ source/release unknown đến khi có provenance. Không tải mirror khác hay gọi local là bản jsdnrs corrected/extended. Bản jsdnrs trong nguồn tham khảo không phải actual dataset đang dùng. Content digest và provided split manifests trong `sroie_inventory.json` gắn specification với bộ local; runtime/model version vẫn cần freeze trước T25.

## 3. Protocol chính đã chọn

**MVP đối chứng cross-dataset/zero-shot:** dùng LayoutXLM đã fine-tune trên MC-OCR và rule baseline đã freeze trên MC-OCR để đánh giá SROIE held-out, **không dùng SROIE labels để train hoặc tune**. Model KIE vẫn LayoutXLM, không LayoutLMv3. Đây là quyết định thiết kế của T02 theo implementation plan, chưa là kết quả thực nghiệm hay quyết định đã được Member B ký xác nhận.

- Giữ nguyên architecture, preprocessing config, OCR checkpoint/language config, tokenizer, label map, window/reconstruction rules, normalization/confidence code và thresholds của MC-OCR release.
- Hai extractor dùng cùng OCR cache, image hashes và test IDs; đổi field extraction logic là biến so sánh chính.
- Locale/date/currency metadata cho evaluation được khai báo trước chạy bằng dataset guide, không tune từ test labels. Raw primary metrics không phụ thuộc suy đoán locale.
- Không thêm keyword tiếng Anh riêng bằng cách đọc SROIE test. Nếu baseline thiếu keywords hay OCR tiếng Việt kém trên receipts tiếng Anh, báo đó là domain-shift limitation của frozen pipeline.
- OCR English configuration, rules dành SROIE hoặc SROIE fine-tune nếu thử sau phải có experiment ID/config riêng, gọi **adapted/in-domain**, không thay score frozen zero-shot.
- Threshold đã chọn trên MC-OCR validation không được chọn lại bằng SROIE test; SROIE threshold sweep nếu làm là phân tích exploratory sau scoring, không claim một selected operating point độc lập.

SROIE không là blocker của MVP MC-OCR end-to-end theo điều kiện thời gian D§1.3. Status benchmark hiện là `NOT_RUN`: dataset đã có nhưng còn gold-policy/provenance QA và chưa có frozen MC-OCR-trained release. Không trình bày inventory/inspection như metrics model.

## 4. Split policy và leakage

1. Giữ official/provided split của **release thực chọn**, lưu actual IDs và counts. Không tự chia ngẫu nhiên lại test original/converted.
2. T02 audit exact image hashes, duplicate/near-duplicate receipts và cross-split groups trước xác nhận split độc lập. Filename-disjoint không đủ chống leakage, như đã thấy ở MC-OCR.
3. Trong zero-shot protocol, SROIE train/validation không dùng học parameters hoặc rules. Nếu cần kiểm tra parser, dùng synthetic fixtures và mẫu train, không xem test labels để thiết kế rules.
4. Nếu sau này cần in-domain supervised run: tách validation khoảng 15% theo receipt groups từ provided train, seed 42; giữ test và checkpoint riêng. Đây là nhánh có điều kiện, không triển khai/train trong T02.
5. Nếu release thiếu test GT: ghi coverage/unknown, không tự fill bằng prediction hay sample outputs. Evaluation subset có GT phải có ID manifest/denominator và ghi rõ subset, không gọi score full test.
6. Nếu duplicate xuyên split: lưu findings và đánh giá primary trên release split có disclosure; thêm clean subset sensitivity nếu cần. Không âm thầm bỏ/sửa test. Zero-shot không train SROIE vẫn cần audit để tránh hiểu sai số receipt độc lập.
7. Freeze release/split/evaluator/config hashes trước lần chạy T25. Không dùng SROIE test để sửa OCR/normalizer hay chọn checkpoint MC-OCR.

## 5. Mapping, representation và locale/currency

| Source field sau xác minh release | Canonical MVP field | Policy |
|---|---|---|
| company | company | Giữ raw Unicode; seller/company semantics |
| address | address | Giữ comma và multiline; không chia text chỉ bằng comma |
| date | date | Giữ raw; parse theo date policy verified |
| total | total | Decimal string, không float; không mặc định VND |

Không giả SROIE có gold BIO, token labels hoặc entity IDs. Có field JSON và OCR transcript/boxes không đồng nghĩa biết từng token thuộc field. Field-to-region alignment nếu cần thuộc T04/T15; token/entity gold F1 chỉ báo khi có gold/QA spans thật, không gọi weak labels là gold.

Locale của MC-OCR (`vi-VN`) **không** áp mặc định cho SROIE. Malaysia/English trong card không tự xác nhận mọi date dùng DD/MM hay mọi receipt có currency MYR. Đề xuất profile SROIE English/Malaysia khi release guide/ảnh-source đủ bằng chứng, giữ day-first chỉ khi xác minh trước scoring; nếu chưa rõ, ngày có nhiều diễn giải hợp lệ → normalized null + AMBIGUOUS_DATE. Amount separator/grouping parse theo pattern rõ; currency null nếu không xác định. `RM`/MYR chỉ được dùng khi context/source profile đã xác nhận.

GT normalized rubric được lập độc lập và QA từ train/guide, không dùng cùng bug normalizer cho prediction và GT để tạo match giả. Nếu chưa xác minh date/currency semantics, báo raw metrics chính và normalized coverage/N/A; không tự sửa GT.

## 6. Evaluation specification

| Track | Inputs | Metric/output | Guard |
|---|---|---|---|
| OCR end-to-end | Raster receipt → frozen PaddleOCR, gold transcripts/geometry | CER/WER micro chính, macro phụ; GT chars/words, N | Chỉ gọi full-page khi GT coverage đã xác minh; miss/extra không bị bỏ |
| Rules baseline | Cùng OCR cache → frozen rules → normalization | 4-field P/R/F1, raw/normalized EM, document EM | Không chỉnh keyword bằng test |
| LayoutXLM zero-shot | Cùng image/OCR → MC-OCR checkpoint → reconstruction/normalization | Cùng field metrics, delta baseline | Không fine-tune SROIE |
| GT-OCR diagnostic (optional) | Gold OCR + image → cùng checkpoint | Paired subset field metrics | Không thay main deployment track; không coi chênh lệch là attribution nhân quả tuyệt đối |
| Threshold transfer (optional) | Frozen MC-OCR threshold → SROIE predictions | Simulated coverage/review/residual, sample counts | Actual MVP vẫn human review; empty accepted set=N/A |

CER/WER dùng Unicode NFC, whitespace-token WER, strict/normalized text comparison theo plan §11; CER/WER có thể >1. GT rỗng có policy rõ, không chia 0. Reading order phải freeze theo geometry trước evaluation. Không lấy word-list F1 challenge thay CER/WER bắt buộc; optional official-style score chỉ khi evaluator thật/version được xác minh và tên metric tách biệt.

Field counts theo plan §18: non-empty prediction sai khi GT có là FP+FN; thiếu prediction là FN; spurious khi GT annotated absent là FP. Missing annotation khác absent và bị mask có denominator. Raw EM sau NFC/trim/collapse whitespace giữ case/dấu; normalized EM riêng. Document EM trên subset có đủ 4 gold annotation statuses, báo support. Không bỏ ảnh OCR lỗi để nâng KIE score; pipeline runtime failure phải có count và ảnh hưởng evaluation được mô tả.

Báo latency AI p50/p95, hardware, batch/concurrency và warmup policy; không đưa queue/network vào processing_ms AI. So sánh published supervised scores chỉ làm background với disclosure về release/training/evaluator, không gọi zero-shot score tương đương leaderboard.

## 7. Artifacts cần giữ khi chạy T25

- Dataset source/revision/archive SHA-256 và file inventory.
- Image/annotation SHA-256, split manifests, correspondence/GT coverage/duplicate audit.
- Exact OCR+KIE+rules+preprocessing+normalization+confidence manifests.
- Predictions raw/normalized/evidence/warnings cho từng model, cùng document IDs.
- OCR CER/WER và field P/R/F1/EM tables, supports/exclusions/failure counts.
- Error samples: OCR miss/substitution/segmentation, KIE label/boundary, reconstruction, normalization/date ambiguity, domain shift.
- Run report phân biệt zero-shot/adapted/supervised, raw/normalized và official/local metrics.

T02 đã tạo report/protocol, actual inventory/hash/findings và manifests phản ánh provided train/test. Không tạo giả predictions/checkpoint/metrics hoặc random split mới. Danh sách artifacts chi tiết nằm trong `sroie_inspection.md` và inventory JSON.

## 8. Local inspection checklist khi có SROIE

- [x] Actual root/content checksums và provided split manifests đã ghi; source/release/license còn unknown.
- [x] Kiểm kê toàn bộ files, full decode 973 ảnh, kiểm tra ảnh/annotation missing-extra.
- [x] Actual OCR quadrilateral pixel và KIE JSON schema đã đọc, bbox/encoding anomalies đã ghi.
- [x] Comma/empty/missing-field/nonfinite inspection fixtures pass; không claim production loader tests.
- [x] Actual N 626/347 và paired OCR/KIE counts có bằng chứng local.
- [x] Exact/pixel duplicate audit và near candidate screening đã thực hiện; chưa claim candidate QA hoàn toàn.
- [x] Mixed date format và thiếu currency metadata được ghi; không mặc định vi-VN/VND cho SROIE.
- [x] Specification đã bind local digest/split manifests; runtime model/config freeze ở T18/T21/T25.
- [ ] Source/release/guide/license cần người dùng cung cấp, không suy từ folder name/counts.
- [ ] Gold marker/encoding, duplicate label semantics và degenerate quad policy cần QA trước scoring.

## 9. Acceptance status T02

| Requirement T02 | Trạng thái lần này |
|---|---|
| Tìm và xác định SROIE local | Đã tìm thấy dưới dataset_hoadon/SROIE2019 |
| Provided actual split/files và N | Đã kiểm kê, 626 train/347 test, nguồn release chưa xác minh |
| OCR/field GT, decode, inspection parser và overlap | Đã kiểm tra toàn bộ; schema/encoding/duplicate findings được ghi |
| Chọn zero-shot vs supervised protocol | MC-OCR zero-shot primary, gắn local content digest; supervised optional riêng |
| Locale/currency note | Mixed date/no currency key được kiểm tra; guide chưa có, giữ nullable policy |
| NOT_RUN và lý do | Đã cập nhật: chưa có frozen trained release, còn annotation/provenance QA trước scoring |
| Inventory và protocol artifacts | Actual per-file/image/annotation/split manifests và detailed report đã tạo |

**T02 local inspection đã thực hiện, trạng thái COMPLETED_WITH_OPEN_FINDINGS.** Không đồng nghĩa dataset đã QA hoàn toàn hoặc benchmark đã chạy. Tiếp tục T03 độc lập và T04 loader/QA cho cả hai dataset; SROIE data path không còn là blocker. Không đánh dấu T04/T25 complete bằng kết quả inspection.
