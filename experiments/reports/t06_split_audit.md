# T06 — Fixed split và leakage audit

**Trạng thái:** `COMPLETED_WITH_DUPLICATE_DISCLOSURES`  
**Ngày chốt:** 2026-09-19  
**Split version:** `t06_v1`  
**Canonical input:** `t04_v1`  
**Seed:** `42`

## 1. Phạm vi

T06 đã tạo manifest train/validation/test bất biến từ canonical records T04. Việc chia được thực hiện theo document group, không theo từng file độc lập. Source images, annotations và T04 records không bị sửa. Không tạo augmentation, không chạy OCR/model và không cần GPU.

Năm document quarantine của T04 không xuất hiện trong bất kỳ split nào.

## 2. MC-OCR split

Local MC-OCR chỉ có 1.152 canonical document accepted có nhãn dùng được. Bộ 391 ảnh provided validation có CSV sample output, không có gold đã xác minh, nên được lập manifest riêng và không được gọi là validation/test gold.

| Split | Documents | Groups | Tỷ lệ document | Max group size |
|---|---:|---:|---:|---:|
| train | 806 | 785 | 69,97% | 2 |
| validation | 173 | 166 | 15,02% | 4 |
| test | 173 | 168 | 15,02% | 2 |
| **Tổng** | **1.152** | **1.119** | **100%** | **4** |

31 group có nhiều hơn một document do exact image SHA-256 duplicate. Mọi document trong cùng group nằm cùng split.

Perceptual audit tìm 37 cặp candidate ngoài exact duplicates. Cả 37 cặp khác đồng thời annotated date và total, có normalized grayscale RMS lớn hơn 0,03; kiểm tra trực quan các cặp gần nhất cho thấy hóa đơn khác nhau cùng template. Chúng được ghi `DISTINCT_RECEIPTS_DIFFERENT_DATE_AND_TOTAL`, không bị gộp group. Không còn candidate MC-OCR chưa phân loại.

Field coverage được cân bằng theo status và quality bin trong lúc gán group. Ví dụ số field annotated train/validation/test:

| Field | Train | Validation | Test |
|---|---:|---:|---:|
| company | 748 | 161 | 161 |
| address | 753 | 162 | 161 |
| date | 761 | 163 | 163 |
| total | 757 | 162 | 162 |

## 3. SROIE split

SROIE giữ nguyên toàn bộ 345 accepted document của provided official test. Nhánh primary T25 vẫn là zero-shot: SROIE train/validation không được dùng để học parameters hoặc sửa rules của MC-OCR release.

Để chuẩn bị nhánh adapted supervised có điều kiện, 626 accepted official-train documents được lưu nguyên trong `official_train_reference.jsonl`. Bảy train documents là exact image duplicates của official test được loại khỏi adapted train/validation, nhưng không bị xóa khỏi official reference và không thay đổi test:

- `X51005453729`
- `X51005568881`
- `X51006008095`
- `X51006328913`
- `X51006329399`
- `X51006332575`
- `X51007135247`

619 document còn lại được chia group-aware 85/15:

| Split | Documents | Groups | Ý nghĩa |
|---|---:|---:|---|
| train | 526 | 521 | Optional adapted development; chưa train |
| validation | 93 | 92 | Optional adapted validation; chưa dùng chọn MC-OCR model |
| test | 345 | 342 | Preserved provided official test; zero-shot primary |

Trong 436 perceptual candidates của T02:

- 434 cặp khác date hoặc total, được phân loại là distinct receipts.
- 1 cặp đã review là distinct receipts cùng template.
- 1 cặp `X51006328919`/`X51006329395` có dHash=1, pHash=0 và cùng company/date/total; ảnh là cùng hóa đơn với crop khác nhau, nên được đưa vào cùng group.

Không còn cross-official near-duplicate candidate chưa phân loại.

## 4. Leakage và reproducibility checks

Verification đạt `PASS`:

- Document ID intersection giữa train/validation/test bằng 0.
- Group ID intersection giữa train/validation/test bằng 0.
- Image SHA-256 intersection giữa train/validation/test bằng 0.
- 1.152/1.152 accepted MC-OCR documents được gán đúng một split.
- 345/345 accepted SROIE official-test documents được giữ nguyên.
- 619/619 eligible SROIE adapted-development documents được gán train hoặc validation.
- 5/5 T04 quarantine documents không nằm trong split.
- Rebuild độc lập từ cùng input/seed sinh cùng SHA-256 cho toàn bộ split/group/candidate artifacts.
- Không có augmentation và không sửa source dataset.

Test suite hiện có 9 test và đều pass; ba test T06 kiểm tra deterministic group assignment, near-duplicate classification và leakage guard.

## 5. Artifacts

- `experiments/splits/t06_v1/manifest.json`
- `experiments/splits/t06_v1/split_summary.json`
- `experiments/splits/t06_v1/mcocr/{train,validation,test}.jsonl`
- `experiments/splits/t06_v1/mcocr/groups.jsonl`
- `experiments/splits/t06_v1/mcocr/near_duplicate_candidates.jsonl`
- `experiments/splits/t06_v1/mcocr/unlabeled_official_validation.jsonl`
- `experiments/splits/t06_v1/sroie/{train,validation,test}.jsonl`
- `experiments/splits/t06_v1/sroie/official_train_reference.jsonl`
- `experiments/splits/t06_v1/sroie/adapted_exclusions.jsonl`
- `experiments/splits/t06_v1/sroie/groups.jsonl`
- `experiments/splits/t06_v1/sroie/near_duplicate_candidates.jsonl`
- `experiments/manifests/t06_verification.json`
- `ai-service/configs/datasets/t06_split_policy.json`

Rebuild và verify:

```powershell
$env:PYTHONPATH='D:\graduation-project-2\ai-service\src'
python -m invoice_ai.datasets.split --workspace D:\graduation-project-2
python -m invoice_ai.datasets.verify_splits --workspace D:\graduation-project-2
python -m unittest discover -s ai-service/tests -v
```

T06 freeze danh sách ID và group theo `t06_v1`. Nếu source inventory, quarantine decision hoặc duplicate decision thay đổi, phải tạo split version mới thay vì sửa các manifest này âm thầm.
