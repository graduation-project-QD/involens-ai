# T12 — Normalization và fixtures theo field

**Trạng thái:** `COMPLETED_WITH_NORMALIZED_ACCURACY_NA`  
**Ngày chốt:** 2026-09-19  
**Normalizer version:** `normalization_v1`  
**Verification:** `PASS`

## 1. Phạm vi đã hoàn thành

T12 đã triển khai một bộ normalizer deterministic dùng chung cho baseline và KIE với đúng bốn field của contract v1: `company`, `address`, `date`, `total`. Mỗi kết quả giữ nguyên `raw_value`, trả `normalized_value` dạng string hoặc `null`, kèm `status`, warning code và `normalizer_version`.

Không chạy OCR, model hoặc training. T05 vẫn deferred và không phải dependency của T12.

## 2. Quy tắc đã freeze

| Field | Quy tắc v1 |
|---|---|
| `company` | Unicode NFC; trim và collapse whitespace; không fuzzy-correct nội dung |
| `address` | Unicode NFC; trim/collapse từng dòng; nối các dòng không rỗng bằng một dấu cách |
| `date` | `vi-VN` hiểu `DD/MM/YYYY` và xuất `YYYY-MM-DD`; kiểm tra ngày lịch thật; không suy diễn năm hai chữ số; ngày mơ hồ trả `null` |
| `total` | Bỏ ký hiệu tiền khỏi phần số; kiểm tra grouping/decimal; xuất chuỗi số, không dùng float; nhiều ứng viên hoặc separator không giải được trả `null` |

Giá trị thiếu và chuỗi rỗng được phân biệt bằng `MISSING_VALUE`/`EMPTY_VALUE`. Ngày không hợp lệ, nhiều ngày, ngày mơ hồ theo locale, số tiền sai cú pháp, nhiều số tiền, VND có phần thập phân và total không dương đều có warning code cố định trong config.

## 3. Test fixtures

26 expected cases độc lập đã được chốt trước khi audit validation và đều pass. Các case bao phủ:

- dấu tiếng Việt, Unicode NFC, whitespace và address nhiều dòng;
- leap year, `31/02`, ngày mơ hồ `08/09`, locale `vi-VN`/`en-US`/unknown, năm hai chữ số và nhiều date candidate;
- grouping/decimal dấu chấm hoặc phẩy, mixed separator, VND, zero/negative, multiple/invalid amount;
- missing và empty value.

Toàn bộ test suite hiện có 12 test và đều pass.

## 4. Audit trên frozen validation T06

Audit dùng đúng manifest validation `t06_v1`; đây là coverage/behavior audit, không phải model evaluation.

| Dataset | Documents | Field slots | Kết quả chính |
|---|---:|---:|---|
| MC-OCR | 173 | 692 | company 161/161 parse OK; address 162/162 OK; date 148 OK, 3 ambiguous, 12 invalid trên 163 annotated; total 135 OK, 6 ambiguous, 21 invalid trên 162 annotated |
| SROIE adapted validation | 93 | 372 | company/address/total 93/93 OK; date 42 OK, 26 ambiguous, 25 invalid |
| **Tổng** | **266** | **1.064** | 1.064/1.064 field slots có artifact; field unlabeled được mask thay vì coi là absent |

SROIE audit dùng locale unknown vì API locale `vi-VN` không được áp ngầm lên benchmark nước ngoài. Do đó các ngày có cả day-first và month-first hợp lệ được đánh dấu ambiguous. Năm hai chữ số không được tự chọn century.

Các total/date không parse được vẫn giữ raw để QA hoặc human review. Parse-valid rate chỉ mô tả hành vi rule trên raw GT; nó không phải độ chính xác dự đoán.

## 5. Normalized accuracy

`normalized_accuracy = N/A`. Frozen validation hiện có raw field GT nhưng chưa có normalized GT được QA độc lập. T12 không tự dùng output của chính normalizer làm gold vì cách đó sẽ tạo metric vòng tròn. Khi có normalized GT độc lập, T14 có thể tính metric này với đúng `normalization_v1`.

## 6. Verification và reproducibility

Verification đạt `PASS` với các điều kiện:

- 1.064 expected records bằng đúng 1.064 actual records và không trùng key;
- mọi `raw_value` và annotation status khớp canonical T04;
- unlabeled field được mask, không được normalize thành gold absent;
- normalized output chỉ là string hoặc `null`;
- toàn bộ warning thuộc taxonomy đã freeze;
- hai lần rebuild liên tiếp tạo cùng artifact SHA-256 `1aa69b45790b9829bef2ac69b2286934fb604eee0b024a9587038493a47e7da4`.

## 7. Artifacts

- `ai-service/src/invoice_ai/normalization/core.py`
- `ai-service/src/invoice_ai/normalization/audit.py`
- `ai-service/src/invoice_ai/normalization/verify.py`
- `ai-service/configs/normalization/v1.json`
- `ai-service/tests/fixtures/normalization_v1.json`
- `ai-service/tests/test_normalization.py`
- `experiments/manifests/t12_validation_normalization.jsonl`
- `experiments/reports/t12_normalization_audit.json`
- `experiments/manifests/t12_verification.json`

Chạy lại:

```powershell
$env:PYTHONPATH='D:\graduation-project-2\ai-service\src'
python -m unittest discover -s ai-service/tests -v
python -m invoice_ai.normalization.audit --workspace D:\graduation-project-2
python -m invoice_ai.normalization.verify --workspace D:\graduation-project-2
```

Nếu policy normalization thay đổi, phải tạo version mới thay vì sửa semantics của `normalization_v1` âm thầm.
