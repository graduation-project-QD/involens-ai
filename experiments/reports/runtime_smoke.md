# T05 — Rented GPU environment setup & smoke test

**Trạng thái:** `COMPLETED — PASS`  
**Ngày chạy:** 2026-09-20  
**Nhà cung cấp:** EzyCloudX  
**Artifact bất biến:** `experiments/artifacts/t05/t05-results-ezycloudx-admin-20260920T040954Z.tar.gz`  
**SHA-256:** `212bcfadaccfea6ae17b9babdc119b147331bf74854ee61eb6589d51cd3372ca`

## Kết quả

- GPU: NVIDIA GeForce RTX 5060 Ti 16 GB; driver 580.173.02; compute capability 12.0.
- OS/Python: Ubuntu 24.04, Python 3.12.3.
- LayoutXLM: `microsoft/layoutxlm-base` tại revision `b95ef788341ccd507115d74e10c4bb7137559f19`; PyTorch 2.8.0+cu129; Transformers 4.40.0.
- Forward/backward mixed precision đạt PASS với physical batch 1 và 2, sequence length 128. Batch 1 mất 0.763 giây và peak Torch allocated khoảng 2.98 GB; batch 2 mất 0.083 giây sau warm-up và peak Torch allocated khoảng 2.98 GB. Batch 2 là giá trị lớn nhất đã thử, không phải tuyên bố giới hạn VRAM tối đa.
- Save/reload đạt PASS; max absolute logits difference bằng 0 với `atol=rtol=1e-4`.
- PaddleOCR 3.7.0 + PaddlePaddle 3.3.0 CPU đạt PASS trên fixture MC-OCR: 42 text, 42 score và 42 polygon; thời gian load + inference 11.518 giây; peak process RAM khoảng 1.39 GB.
- `pip check` cuối cùng: không có dependency bị hỏng.

## Compatibility decisions

PaddlePaddle GPU 3.3.0 cu129 yêu cầu các bản CUDA component chính xác khác với PyTorch 2.8.0 cu129. Theo phương án đã có trong kế hoạch, runtime dùng PaddleOCR CPU và LayoutXLM GPU trong cùng virtual environment. Cấu hình này tránh thay thế CUDA stack của PyTorch và không thay đổi kiến trúc AI hay model LayoutXLM.

`AutoProcessor` của Transformers 4.40.0 resolve tokenizer phần processor thành `LayoutLMv2TokenizerFast`, không nhận đúng special token IDs của LayoutXLM. Smoke test vì vậy ghép `LayoutXLMTokenizerFast` với `LayoutLMv2ImageProcessor`; model vẫn là checkpoint LayoutXLM và class token classification tương thích. PaddleOCR CPU cần tắt oneDNN cho model PP-OCRv6 trên runtime này.

Trong lúc cài dependency, user-space NVIDIA library và kernel module tạm lệch phiên bản. Reboot instance đã đồng bộ driver 580.173.02; CUDA smoke sau reboot đạt PASS.

## Artifacts đã lưu local

Thư mục giải nén `experiments/artifacts/t05/ezycloudx-rtx5060ti-20260920T040954Z/` chứa runtime manifest, final dependency lock, pip inspect, hardware inventory, logs và JSON kết quả. Hash của archive đã được kiểm tra trùng với file `.sha256` tải từ instance. Saved-model khoảng 1.48 GB không nằm trong archive; manifest ghi checksum từng file và checkpoint có thể tái tạo từ revision bất biến.

T05 chỉ xác nhận runtime và physical batch nhỏ trên fixture. Tiny training, full fine-tuning, checkpoint resume và chi phí GPU thuộc T18.
