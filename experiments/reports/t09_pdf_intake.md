# T09 — PDF intake and file limits

**Status:** `COMPLETED — PASS`  
**Date:** 2026-09-20  
**Version:** `t09_pdf_intake_v1`

## Result

T09 accepts a single-page `application/pdf`, renders it to a bounded RGB PNG, then passes that raster through the frozen T07 `PageImage` preprocessing pipeline. PDF text layers are never read or substituted for PaddleOCR input.

The renderer runs in an isolated subprocess with a 15-second hard timeout. The locked backend is `pypdfium2==5.13.0`, already present in the final T05 runtime lock. The original PDF hash and byte count remain separate from the intermediate PNG hash and T07 transform metadata.

## Frozen policy

| Rule | T09 v1 behavior |
|---|---|
| Upload size | Maximum 10 MiB, checked before decoding |
| Page count | Exactly one page; more or fewer pages are rejected |
| Rendered size | Maximum 20 MP, checked before and after rasterization |
| Encrypted/password PDF | Rejected |
| MIME/signature | Declared `application/pdf` and `%PDF-` signature required |
| Renderer | `pypdfium2==5.13.0`, 200 DPI, white background, PNG |
| Timeout | 15 seconds in an isolated subprocess |
| PDF text layer | Not used |
| Downstream | Rendered page continues through T07; T10 receives the same `PageImage` abstraction as JPG/PNG |

## Verification

Six focused tests passed:

- valid one-page render and reversible T07 geometry;
- deterministic raster pixels across repeated runs;
- exact error codes for multipage, encrypted, corrupt and oversized-page PDFs;
- byte-limit and MIME checks before rendering;
- bounded renderer timeout mapping;
- config agreement with the frozen T03/T07 10 MiB and 20 MP limits.

The synthetic one-page fixture rendered to `1654×2339` pixels at 200 DPI and T07 resized it to `1414×2000`. Three audit runs produced the same pixel SHA-256, `46bbe455d40ea70c23535802678a51e77daeb7189f4cc1272981552745c01351`.

On this local Windows QA environment, median renderer time was 298.371 ms, median end-to-end intake time was 877.591 ms, and maximum renderer-process peak RSS was 81,149,952 bytes (77.39 MiB). These fixture measurements verify bounded execution; they are not a production latency SLA.

All four negative fixture outcomes matched their expected codes:

| Fixture | Expected and observed code |
|---|---|
| Two pages | `PDF_PAGE_COUNT_UNSUPPORTED` |
| Password protected | `PDF_ENCRYPTED` |
| Corrupt structure | `PDF_DECODE_ERROR` |
| Predicted 30,869,136-pixel page | `PIXEL_LIMIT_EXCEEDED` |

The valid fixture was also rendered with Poppler for independent visual QA. Text, border and page margins were readable, aligned and unclipped.

## Scope boundary

T09 implements intake and canonical error codes. HTTP status mapping and the public error envelope remain T22/T24 responsibilities. OCR accuracy is unchanged and will be measured in T10/T11. No dataset document, T06 split or T07/T08 configuration was modified.

## Artifacts

- Config: `ai-service/configs/preprocessing/pdf_v1.json`
- Intake API: `ai-service/src/invoice_ai/preprocessing/pdf_intake.py`
- Isolated renderer: `ai-service/src/invoice_ai/preprocessing/pdf_render_worker.py`
- Audit runner: `ai-service/src/invoice_ai/preprocessing/pdf_audit.py`
- Tests and synthetic fixtures: `ai-service/tests/test_pdf_intake.py`, `ai-service/tests/fixtures/pdf/`
- Machine-readable audit: `experiments/reports/t09_pdf_intake_audit.json`
- Verification manifest: `experiments/manifests/t09_verification.json`

