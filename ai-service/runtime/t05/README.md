# T05 rented-GPU smoke bundle

This package was prepared locally for an EzyCloudX Ubuntu 24.04 RTX 5060 Ti 16 GB instance. T05 passed on 2026-09-20; the retained runtime report and immutable result archive are under `experiments/reports/runtime_smoke.md` and `experiments/artifacts/t05/`.

## Before renting

The ZIP contains one accepted MC-OCR validation fixture only. It does not contain the full dataset, source annotations, credentials or local absolute paths. The dependency versions in `candidate.env` and `requirements-candidate.txt` are candidates; the actual passing environment is captured after the GPU smoke.

## On the rented instance

Upload and extract the ZIP, then run:

```bash
unzip t05_gpu_smoke_bundle_v1.zip
cd t05_gpu_smoke
chmod +x scripts/*.sh scripts/*.py
bash scripts/bootstrap_ubuntu.sh 2>&1 | tee bootstrap.log
bash scripts/run_smoke.sh
```

The bootstrap does not install or replace the NVIDIA driver. If `nvidia-smi` fails, stop and ask the provider to fix the instance instead of changing the driver during billed time.

If system packages are already present and `sudo apt-get` should be skipped:

```bash
T05_SKIP_APT=1 bash scripts/bootstrap_ubuntu.sh 2>&1 | tee bootstrap.log
```

The smoke sequence is:

1. Capture hardware, driver, CUDA, Python and package inventory.
2. Load the immutable `microsoft/layoutxlm-base` revision.
3. Build external-OCR multimodal inputs containing image, tokens, bounding boxes and BIO labels.
4. Run forward and backward for physical batch 1, then batch 2 when batch 1 passes.
5. Save and reload the model; compare logits within the configured tolerance.
6. Import PyTorch and PaddlePaddle in the same environment and allocate a probe tensor on each framework.
7. Run Vietnamese PaddleOCR on the accepted receipt fixture and validate text, scores and polygons.
8. Capture dependency locks, installed-distribution metadata checksums, peak RAM/VRAM and latency.
9. Build a small result archive that excludes the 1.5 GB saved model while retaining its file hashes.

## Download before deleting the instance

After either PASS or FAIL, download both files created in the package root:

```text
t05-results-<hostname>-<UTC timestamp>.tar.gz
t05-results-<hostname>-<UTC timestamp>.tar.gz.sha256
```

Example from the local machine:

```bash
scp ubuntu@SERVER_IP:~/t05_gpu_smoke/t05-results-*.tar.gz .
scp ubuntu@SERVER_IP:~/t05_gpu_smoke/t05-results-*.sha256 .
```

Verify the SHA-256 locally before deleting the EzyCloudX instance. Do not paste passwords, private SSH keys or access tokens into the result archive.

## Pass criteria

- `hardware_inventory.json` confirms the rented GPU and CUDA driver.
- `layoutxlm_smoke.json` is PASS for load, one-batch forward/backward, save/reload and parity.
- `paddleocr_smoke.json` is PASS with non-empty text, valid scores and polygons.
- `runtime_manifest.json` is PASS and records a tested physical batch.
- `runtime_smoke.md`, dependency locks and logs are in the downloaded archive.

Only then may the main plan mark T05 complete. A failure remains useful evidence and must not be relabeled PASS.
