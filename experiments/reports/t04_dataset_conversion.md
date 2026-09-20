# T04 — Canonical loaders, field mapping và QA labels

**Trạng thái:** `COMPLETED_WITH_QUARANTINE`  
**Ngày chốt:** 2026-09-19  
**Processed dataset:** `t04_v1`  
**Canonical schema:** `1.0`  
**Runtime build/verify:** Python `3.12.14` tại `C:\Users\ACER\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`, Pillow `12.3.0`

## 1. Phạm vi đã thực hiện

T04 đã chuyển dữ liệu MC-OCR và SROIE đã kiểm tra ở T01/T02 sang một schema canonical dùng chung cho bốn field `company`, `address`, `date`, `total`. Loader chỉ giữ raw annotation; chưa normalize date/total, chưa tạo BIO alignment cho SROIE và chưa tạo split mới. Hai thư mục dataset nguồn chỉ được đọc.

Các adapter nằm tại `ai-service/src/invoice_ai/datasets/`. Lệnh build:

```powershell
$env:PYTHONPATH='D:\graduation-project-2\ai-service\src'
python -m invoice_ai.datasets.build --workspace D:\graduation-project-2
```

## 2. Schema và semantics

Mỗi document lưu provenance của dataset/version/partition, đường dẫn ảnh tương đối, SHA-256, kích thước ảnh, bốn field canonical, toàn bộ region có polygon/bbox, QA flags và metadata nguồn.

Field status được giữ tách biệt:

| Status | Ý nghĩa |
|---|---|
| `annotated` | Nguồn có giá trị GT; `raw_value` giữ nguyên chuỗi nguồn |
| `annotated_empty` | Key có trong nguồn nhưng giá trị là chuỗi rỗng; canonical dùng `null` |
| `source_missing` | Nguồn đáng lẽ có schema field nhưng thiếu key; canonical dùng `null` |
| `unlabeled` | Dataset không cung cấp nhãn cho field/document đó |
| `absent` | Dành cho trường hợp nguồn xác nhận field không xuất hiện; chưa được suy diễn trong T04 |

Region status chỉ gồm `mapped`, `unlabeled`, `uncertain_marker`. SROIE không có gold field-to-line alignment nên các OCR region không bị gán nhãn `O`. Marker `***` được giữ là `uncertain_marker`.

## 3. Field mapping đã dùng

| Dataset | Source | Canonical |
|---|---|---|
| MC-OCR | `SELLER` / category 15 | `company` |
| MC-OCR | `ADDRESS` / category 16 | `address` |
| MC-OCR | `TIMESTAMP` / category 17 | `date` |
| MC-OCR | `TOTAL_COST` / category 18 | `total` |
| SROIE | JSON key `company` | `company` |
| SROIE | JSON key `address` | `address` |
| SROIE | JSON key `date` | `date` |
| SROIE | JSON key `total` | `total` |

Loader MC-OCR kiểm tra đồng thời semantic label và `category_id`; label không biết hoặc cặp category/label không khớp sẽ bị quarantine. Parser dùng `ast.literal_eval`, kiểm tra độ dài `polygon/text/label/anno_num`, giữ multipart segmentation và nối các region cùng field theo thứ tự nguồn bằng ký tự xuống dòng.

Loader SROIE đọc UTF-8 strict, tách đúng 8 tọa độ đầu để không làm mất dấu phẩy trong transcript, kiểm tra polygon không suy biến và giữ source split `train`/`test`.

## 4. Kết quả chuyển đổi

| Dataset | Source documents | Accepted | Quarantine | Regions accepted |
|---|---:|---:|---:|---:|
| MC-OCR train có annotation | 1.155 | 1.152 | 3 | 6.581 |
| SROIE train + test | 973 | 971 | 2 | 52.219 |
| **Tổng** | **2.128** | **2.123** | **5** | **58.800** |

MC-OCR field coverage:

| Field | `annotated` | `unlabeled` |
|---|---:|---:|
| company | 1.070 | 82 |
| address | 1.076 | 76 |
| date | 1.087 | 65 |
| total | 1.081 | 71 |

SROIE có 970 address annotated và 1 `source_missing`; 970 total annotated và 1 `annotated_empty`; company/date đều annotated ở 971 document. Có 11 region `uncertain_marker` thuộc 8 document.

## 5. Quarantine và quyết định QA

| Dataset | Document | Lý do | Xử lý |
|---|---|---|---|
| MC-OCR | `mcocr_public_145013kzjew.jpg` | `TOTAL_TOTAL_COST` không có trong mapping nguồn đã xác minh | Quarantine; không tự sửa thành `TOTAL_COST` |
| MC-OCR | `mcocr_public_145014iwhec.jpg` | Annotation rỗng, `anno_num=0` | Quarantine |
| MC-OCR | `mcocr_public_145014jndnz.jpg` | Annotation rỗng, `anno_num=0` | Quarantine |
| SROIE | `X51006008092` | Polygon suy biến | Quarantine chờ geometry QA |
| SROIE | `X51006619503` | OCR annotation không phải UTF-8 hợp lệ | Quarantine; không decode replacement hoặc tự chọn encoding |

Hai trường hợp SROIE không bị loại:

- `X51005663280`: giữ document với `address.status=source_missing` và `raw_value=null`.
- `X51005433522`: giữ document với `total.status=annotated_empty` và `raw_value=null`.

Duplicate/perceptual duplicate candidates từ T02 được giữ nguyên; T06 sẽ xử lý group-aware split để chống leakage.

## 6. Verification

Verification độc lập đã đọc lại toàn bộ JSONL và đạt `PASS`:

- 2.128/2.128 source document được phân loại đúng một lần vào accepted hoặc quarantine; hai tập không giao nhau.
- 58.800 region được kiểm tra polygon, bbox và giới hạn ảnh.
- Mọi field reference đều trỏ tới region tồn tại; mỗi document có đúng bốn field canonical.
- Không có `raw_value=""`; missing/empty/unlabeled đều dùng `null` với status riêng.
- Không có region chưa được xác minh bị gán `O`.
- Hash/kích thước ảnh canonical khớp inventory T01/T02.
- Hash nguồn hiện tại khớp inventory: 1.155 ảnh MC-OCR, CSV MC-OCR và 2.919 file SROIE được T04 sử dụng; không có mismatch.
- Hash của bốn JSONL khớp `conversion_report.json`.

Test suite gồm 6 test parser/QA và đã pass: transcript SROIE có dấu phẩy, polygon suy biến, distinction missing/empty/unlabeled, non-UTF8 quarantine, multipart MC-OCR/multiline field, empty/unknown MC-OCR quarantine.

Lệnh verification:

```powershell
$env:PYTHONPATH='D:\graduation-project-2\ai-service\src'
python -m invoice_ai.datasets.verify --workspace D:\graduation-project-2
python -m unittest discover -s ai-service/tests -v
```

## 7. Artifacts bàn giao

- `experiments/data/processed/t04_v1/mcocr.jsonl`
- `experiments/data/processed/t04_v1/mcocr_quarantine.jsonl`
- `experiments/data/processed/t04_v1/sroie.jsonl`
- `experiments/data/processed/t04_v1/sroie_quarantine.jsonl`
- `experiments/data/processed/t04_v1/conversion_report.json`
- `experiments/manifests/field_mapping.json`
- `experiments/manifests/t04_qa_decisions.json`
- `experiments/manifests/t04_verification.json`
- `experiments/manifests/t04_canonical_dataset_manifest.json`
- `experiments/data/quarantine/t04_v1/manifest.json` và bản sao ảnh/annotation của 5 document bị loại
- `ai-service/configs/datasets/t04_qa_policy.json`

Năm document quarantine đã được đóng gói riêng tại `experiments/data/quarantine/t04_v1/`. Chúng không xuất hiện trong `mcocr.jsonl` hoặc `sroie.jsonl`; file nguồn vẫn giữ nguyên và hash bản sao khớp nguồn.

MC-OCR chưa được chia train/validation/test trong T04. SROIE chỉ ghi lại split do dataset cung cấp. T06 sở hữu quyết định split và chống leakage; T05 có thể bắt đầu độc lập để khóa runtime LayoutXLM/PaddleOCR.
