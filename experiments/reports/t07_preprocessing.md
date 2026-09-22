# T07 — Image preprocessing và transform bookkeeping

**Trạng thái:** `COMPLETED — PASS`  
**Pipeline version:** `t07_preprocess_v1`  
**Config:** `ai-service/configs/preprocessing/v1.json`

## Quyết định v1

Pipeline thực hiện decode có giới hạn an toàn → áp EXIF orientation đúng một lần → chuẩn hóa RGB → resize LANCZOS giữ tỷ lệ khi cạnh dài vượt 2.000 px. Ảnh nhỏ không upscale, không crop. Ảnh alpha được composite trên nền trắng. Raw encoded bytes, source SHA-256, mode/format ban đầu, pixel hash đầu ra và toàn bộ transform chain đều được giữ trong `PageImage`.

Mỗi geometric step lưu ma trận thuận/nghịch 3×3, input/output size và parameters. Polygon và bbox có thể map source → processed → source; tọa độ ngoài frame bị reject thay vì tự clip im lặng.

Automated orientation detection, deskew và contrast vẫn tắt. Các phép này chỉ được bật sau khi T10 có OCR cache và validation CER/WER chứng minh lợi ích.

## Validation trên split T06

| Dataset | Validation docs | PASS | Resize | Vượt 20 MP request limit | Max round-trip error |
|---|---:|---:|---:|---:|---:|
| MC-OCR | 173 | 173 | 2 | 0 | 2,274e-13 px |
| SROIE | 93 | 93 | 27 | 8 | 9,095e-13 px |
| **Tổng** | **266** | **266** | **29** | **8** | **9,095e-13 px** |

Tất cả polygon và bbox canonical trên validation đều round-trip trong tolerance 1e-6 pixel; không có decode failure và raw dataset không bị sửa.

Tám ảnh SROIE có 32,58–34,81 MP. Chúng được phép qua decoder nội bộ giới hạn 50 MP để split training/evaluation không mất mẫu, sau đó resize về cạnh dài 2.000 px. Chúng vẫn bị reject trong chế độ API request theo contract T03 là 20 MP; pipeline không nới giới hạn `/v1/extract`.

## So sánh cấu hình hình học

| Candidate | Docs bị resize | Min linear scale | Mean retained pixel ratio | OCR CER/WER |
|---|---:|---:|---:|---|
| Max edge 1.600 | 63 | 0,2281 | 0,9087 | NOT_RUN |
| Max edge 2.000 | 29 | 0,2851 | 0,9576 | NOT_RUN |
| Không resize | 0 | 1,0000 | 1,0000 | NOT_RUN |

Mốc 2.000 px được giữ làm initial setting từ kế hoạch. Bảng này chỉ mô tả tác động hình học; chưa phải bằng chứng OCR quality. CER/WER được để `NOT_RUN` thay vì suy diễn khi T10 chưa tồn tại.

## Kiểm thử và artifacts

Unit tests bao phủ resize/no-upscale, EXIF orientations 1–8 gồm 90°/180°/270° và mirror, polygon/bbox corners, alpha, grayscale, raw preservation, determinism, request-vs-internal limits, out-of-bounds và corrupt input.

- Machine report: `experiments/reports/t07_preprocessing_audit.json`
- Per-document manifest: `experiments/manifests/t07_preprocessing_validation.jsonl`
- Golden fixture rubric: `ai-service/tests/fixtures/preprocessing_v1.json`
- Source: `ai-service/src/invoice_ai/preprocessing/`

T07 hoàn tất phần preprocessing/geometry. OCR ablation của resize và mọi optional image enhancement tiếp tục ở T10, không được coi là đã hoàn thành trong T07.
