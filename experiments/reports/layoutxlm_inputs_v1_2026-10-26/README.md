# B9 — Tokenize cho LayoutXLM (layoutxlm_inputs_v1) — 26/10/2026

Chuyển dữ liệu BIO (`kie_bio_v3`) thành đầu vào của `microsoft/layoutxlm-base`. Chạy CPU, khoảng 15 giây.

```bash
cd ai-service
PYTHONPATH=src python -m invoice_ai.kie.tokenize_layoutxlm --bio ../experiments/data/processed/kie_bio_v3 \
  --dataset ../dataset_hoadon/dataset_upright_v1 --out ../experiments/data/processed/layoutxlm_v1
```

## Cách làm

- Mỗi từ tách thành token con SentencePiece của LayoutXLM (bộ từ vựng 250.002 token). Token con đầu tiên của từ mang nhãn (17 lớp), các token sau và mọi token của từ `IGNORE` mang -100 (không tính loss). Mọi token của một từ dùng chung box của từ (0–1000).
- Nhãn token được gán theo `word_ids()` của tokenizer, không dùng `word_labels`: tokenizer nhanh của HuggingFace gán nhãn cả token thứ hai khi một từ tách thành `▁` rỗng + phần chữ ("PONTE" → `▁ PON TE`, "50,000" → `▁ 50,000`), vì cả hai token đều bắt đầu ở vị trí 0.
- Hóa đơn dài hơn 512 token được cắt thành nhiều cửa sổ theo ranh giới từ, hai cửa sổ liền nhau chung khoảng 128 token ngữ cảnh; `word_ids` giữ chỉ số từ trong hóa đơn để gộp dự đoán khi suy luận.
- Ảnh thẳng lưu sẵn ở 224 × 224 (kích thước nhánh ảnh của LayoutXLM nhận), nên VM không cần ảnh gốc. Tokenizer lưu kèm (`tokenizer/`) để chạy offline.

## Kết quả

| | Train (OCR) | Val (OCR) | Train (oracle) | Val (oracle) |
|---|---:|---:|---:|---:|
| Hóa đơn | 1.094 | 138 | 1.094 | 138 |
| Mẫu (cửa sổ) | 1.105 | 140 | 1.104 | 139 |
| Hóa đơn cắt nhiều cửa sổ | 11 | 2 | 10 | 1 |
| Token/mẫu (trung bình / tối đa) | 203 / 512 | 216 / 512 | 202 / 512 | 216 / 512 |
| Mẫu lỗi | 0 | 0 | 0 | 0 |

- Trung bình 1,95 token/từ (tiếng Việt bị tách vụn: "sườn" → `▁sư ờ n`). Trước khi cắt: trung vị 186 token/hóa đơn (train), p95 363, dài nhất 716.
- Kiểm tra: mọi từ có trong ít nhất một cửa sổ; ở mọi hóa đơn một cửa sổ, số token mang nhãn bằng số từ không `IGNORE`; box token khớp box từ; token đặc biệt không mang nhãn. Cửa sổ liền nhau chung 50–73 từ.
- Token mang nhãn (train, OCR): `O` 61,8%; nhãn hiếm: `I-QUANTITY` 1, `I-TOTAL_COST` 62, `I-UNIT_PRICE` 117, `I-LINE_TOTAL` 124 (các trường số thường chỉ một từ).

## Tệp

`experiments/data/processed/layoutxlm_v1/` (120 MB): `{train,val}.{ocr,oracle}.jsonl` (input_ids, bbox, labels, word_ids, word_range, image), `images/{train,val}/*.png` (1.232 ảnh 224 × 224), `tokenizer/`, `summary.json`. Code: `ai-service/src/invoice_ai/kie/tokenize_layoutxlm.py`; test: `ai-service/tests/test_tokenize_layoutxlm.py`.
