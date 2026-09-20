# T05 — Chuẩn bị local trước khi thuê GPU

**Trạng thái chuẩn bị:** `COMPLETED`; T05 sau đó đã `PASS` trên rented GPU ngày 2026-09-20  
**Ngày chuẩn bị:** 2026-09-19  
**GPU execution:** xem `experiments/reports/runtime_smoke.md`  
**Training:** chưa chạy

## 1. Kết quả

Phần có thể thực hiện trước khi EzyCloudX bắt đầu tính giờ đã hoàn tất. Một ZIP độc lập đã được tạo để upload lên Ubuntu 24.04 của instance RTX 5060 Ti 16 GB. Bundle chỉ chứa script, dependency candidate, một fixture nhỏ và hướng dẫn; không chứa full dataset.

Ghi chú lịch sử: tại thời điểm chuẩn bị, T05 chưa hoàn tất. Bundle sau đó đã chạy trên rented GPU và final lock/chỉ số được lưu trong `experiments/artifacts/t05/ezycloudx-rtx5060ti-20260920T040954Z/`.

## 2. Candidate runtime

| Thành phần | Candidate chuẩn bị |
|---|---|
| Python | 3.11–3.12; dùng `python3` thực tế của Ubuntu nếu nằm trong khoảng này |
| PyTorch | 2.8.0, CUDA 12.9 wheel |
| Torchvision | 0.23.0, CUDA 12.9 wheel |
| Transformers | 4.40.0 |
| PaddlePaddle GPU | 3.3.0, CUDA 12.9 index |
| PaddleOCR | 3.7.0 |
| LayoutXLM | `microsoft/layoutxlm-base` |
| Model revision | `b95ef788341ccd507115d74e10c4bb7137559f19` |
| Batch trials | 1, sau đó 2 nếu batch 1 pass |
| Sequence length smoke | 128 |

Đây là tổ hợp cần được kiểm chứng, không phải tuyên bố tương thích. Detectron2 được cài từ candidate ref và commit thực tế sẽ được ghi bằng `pip freeze`, `pip inspect` và `direct_url.json` sau khi cài. Khi smoke pass, toàn bộ phiên bản và checksum metadata mới được freeze thành runtime manifest cuối.

## 3. Nội dung bundle

- Bootstrap Ubuntu, kiểm tra `nvidia-smi` trước khi cài package và không tự thay NVIDIA driver.
- Thu thập OS/kernel/CPU/RAM/disk/GPU/driver/CUDA/compute capability.
- Kiểm tra PyTorch và PaddlePaddle dùng CUDA trong cùng Python environment.
- LayoutXLM load tokenizer/processor/model bằng immutable revision.
- Tạo multimodal batch có image, tokens, bbox và BIO labels.
- Forward, finite loss, backward, đo latency/RAM/VRAM cho physical batch 1 và 2.
- Save/reload model bằng safetensors và kiểm tra logits trong tolerance.
- PaddleOCR tiếng Việt trên một ảnh MC-OCR accepted; yêu cầu text, scores và polygons.
- Sinh dependency locks, pip inspection, installed-distribution metadata checksums, runtime manifest và báo cáo Markdown.
- Đóng gói kết quả nhỏ để tải về trước khi xóa VM; saved model lớn không nằm trong archive nhưng có file hashes và immutable source revision.

## 4. Fixture

Fixture là `mcocr_public_145013anmiz.jpg` thuộc MC-OCR validation `t06_v1`, không thuộc quarantine.

- Size: 138.010 bytes.
- SHA-256: `e5a349bfce39e5f54eea871b56bd1e1cb61a18ff78478342729364db5d803dc0`.
- Bundle không cần full dataset và không sửa split T06.

## 5. Local verification

Preflight đạt `PASS`:

- 13 required bundle files có đủ;
- tất cả Python smoke scripts parse được;
- shell scripts có shebang Bash và LF line endings;
- LayoutXLM model ID không thay đổi;
- fixture hash khớp frozen validation record;
- không có full dataset trong bundle;
- deterministic ZIP build test pass;
- toàn bộ project test suite hiện có 23 test và đều pass.

Shell execution và package installation chỉ được xác nhận trên Linux instance. Local preflight không được dùng để suy kết luận CUDA/GPU compatibility.

## 6. Artifact để upload

- ZIP: `experiments/artifacts/t05/t05_gpu_smoke_bundle_v1.zip`
- ZIP SHA-256: `da74dacf9b430b668079a79ee590a39c2d743291d2978ae82394b293338a6e33`
- Checksum sidecar: `experiments/artifacts/t05/t05_gpu_smoke_bundle_v1.zip.sha256`
- Local preparation verification: `experiments/manifests/t05_preparation_verification.json`
- Prepared bundle manifest: `experiments/manifests/t05_prepared_bundle.json`
- Hướng dẫn trong ZIP: `t05_gpu_smoke/README.md`

Sau khi thuê máy, upload ZIP, giải nén và chạy:

```bash
cd t05_gpu_smoke
chmod +x scripts/*.sh scripts/*.py
bash scripts/bootstrap_ubuntu.sh 2>&1 | tee bootstrap.log
bash scripts/run_smoke.sh
```

Trước khi xóa máy phải tải `t05-results-*.tar.gz` và file `.sha256` về local, kiểm tra hash, rồi mới terminate instance. Nếu bất kỳ smoke step nào fail, giữ nguyên logs và không đánh dấu T05 hoàn tất.
