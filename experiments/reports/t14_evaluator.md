# T14 — KIE/field evaluator chung

**Trạng thái:** `COMPLETED — verification PASS`  
**Ngày chốt:** 2026-09-19  
**Evaluator version:** `evaluation_v1`  
**GPU cần thiết:** không

## 1. Phạm vi đã hoàn thành

T14 đã triển khai evaluator deterministic dùng chung cho rule baseline và LayoutXLM. Module hỗ trợ:

- field Precision/Recall/F1 theo từng field và micro/macro;
- raw slot Exact Match và normalized slot Exact Match tách biệt;
- document Exact Match trên subset có đủ bốn GT slot đánh giá được;
- exact entity matching theo class và boundary `[start,end)`;
- masking annotation thiếu và normalized GT chưa giải được;
- CSV table exporter ổn định và provenance theo version/hash.

T14 không chạy model. Baseline validation và LayoutXLM validation chưa có prediction tương ứng, nên không tạo điểm số model giả.

## 2. Policy đã freeze

| Tình huống | Cách tính `evaluation_v1` |
|---|---|
| GT non-empty và prediction đúng | TP |
| GT non-empty và prediction thiếu | FN |
| GT non-empty và prediction sai non-empty | FP + FN |
| GT absent/annotated-empty và prediction non-empty | FP |
| Cả GT và prediction absent | Slot EM đúng, không cộng TP |
| GT `unlabeled` hoặc `source_missing` | Mask; không coi là absent |
| Normalized GT invalid/ambiguous/chưa QA | Mask khỏi normalized metrics; raw metric vẫn có thể tính |
| Entity sai class hoặc sai boundary | FP + FN |
| Field có support nhưng không có prediction | Precision/Recall/F1 theo policy cho kết quả 0 phù hợp |
| Field không có positive support | Metric không xác định được ghi `null`, không ghi 0 giả |

Raw matching chính dùng Unicode NFC rồi trim/collapse whitespace, vẫn giữ dấu và phân biệt hoa thường. Diagnostic `strict_preserve_whitespace_exact_match` chỉ NFC và giữ whitespace. Normalized matching là exact string equality với normalized GT độc lập.

Macro metric là trung bình các field có metric được định nghĩa. Micro metric cộng TP/FP/FN trước khi tính. Document EM chỉ dùng document có đủ bốn slot đánh giá được cho comparison đang chọn.

## 3. Reference fixture

Reference fixture độc lập gồm 5 field documents và 3 entity documents, bao phủ perfect, missing, spurious, wrong value, annotated absent, missing annotation, normalized GT unresolved, Unicode, whitespace, boundary sai, masked entity class và zero denominator.

Expected-count verification đạt `PASS`:

| Metric family | TP | FP | FN | Support | Kết quả kiểm tra |
|---|---:|---:|---:|---:|---|
| Raw field micro | 9 | 4 | 4 | 13 | F1 = 0,6923077; slot EM = 14/19 |
| Normalized field micro | 9 | 3 | 3 | 12 | F1 = 0,75; slot EM = 14/18 |
| Exact entity micro | 3 | 2 | 2 | 5 | F1 = 0,60 |

Các số này chỉ xác nhận evaluator tạo đúng expected counts trên fixture. Chúng không phải accuracy của baseline hoặc LayoutXLM.

## 4. Frozen validation coverage

| Dataset | Documents | Field slots | Raw evaluable | Masked annotation |
|---|---:|---:|---:|---:|
| MC-OCR validation | 173 | 692 | 648 | 44 |
| SROIE adapted validation | 93 | 372 | 372 | 0 |
| **Tổng** | **266** | **1.064** | **1.020** | **44** |

Coverage được đọc trực tiếp từ canonical T04 và frozen split T06. 44 MC-OCR slots `unlabeled` sẽ không bị biến thành GT absent.

Trạng thái các metric thực tế:

- baseline validation: `NOT_RUN_WAITING_FOR_T13_PREDICTIONS`;
- LayoutXLM validation: `NOT_RUN_WAITING_FOR_T18_CHECKPOINT`;
- normalized validation accuracy: `N/A_NO_INDEPENDENT_NORMALIZED_VALIDATION_GT`;
- gold entity metrics: `NOT_RUN_WAITING_FOR_QAED_GOLD_SPAN_RUBRIC`.

Field metrics vẫn chạy được khi chưa có gold spans. Entity metrics chỉ được công bố khi span rubric đã được QA; weak alignment không được gọi là gold benchmark.

## 5. Verification

Toàn bộ test suite có 20 test và đều pass. Tám test T14 kiểm tra expected counts, `FP+FN`, masking, document EM, Unicode/whitespace, exact boundary, zero denominator, contract bốn field và CSV deterministic.

Verification rebuild hai lần đạt `PASS`:

- 266 validation documents và 1.064 field slots khớp T06;
- 1.020 raw field slots đánh giá được;
- reference JSON và CSV giữ cùng SHA-256 giữa hai lần build;
- JSON không chứa `NaN`/`Infinity`.

## 6. Artifacts

- `ai-service/src/invoice_ai/evaluation/core.py`
- `ai-service/src/invoice_ai/evaluation/audit.py`
- `ai-service/src/invoice_ai/evaluation/verify.py`
- `experiments/configs/evaluation_v1.json`
- `ai-service/tests/fixtures/evaluation_v1.json`
- `ai-service/tests/test_evaluation.py`
- `experiments/reports/t14_reference_evaluation.json`
- `experiments/reports/t14_reference_metrics.csv`
- `experiments/manifests/t14_verification.json`

Chạy lại:

```powershell
$env:PYTHONPATH='D:\graduation-project-2\ai-service\src'
python -m unittest discover -s ai-service/tests -v
python -m invoice_ai.evaluation.audit --workspace D:\graduation-project-2
python -m invoice_ai.evaluation.verify --workspace D:\graduation-project-2
```

T13 và T18 phải truyền prediction cùng provenance vào đúng evaluator này. Nếu metric semantics thay đổi, cần tạo evaluator version mới thay vì sửa `evaluation_v1` âm thầm.
