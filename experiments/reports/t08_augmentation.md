# T08 — Train-only augmentation audit

**Status:** `COMPLETED — PASS, DISABLED_BY_DEFAULT`  
**Date:** 2026-09-20  
**Version:** `t08_augmentation_v1`

## Decision

T08 implements deterministic, train-only visual and geometry augmentation after the frozen T07 preprocessing transform. The checked-in configuration remains disabled by default. It may be enabled for a later experiment only after the T10 CER/WER and resource ablation gate.

The v1 preview policy is `gt_view_visual_geometry_only`: rotation transforms the image and all label coordinates through the same reversible transform chain; brightness and blur do not change geometry. OCR is not rerun, so this task makes no OCR robustness claim. Validation and test augmentation are rejected by code.

## Frozen configuration

| Operation | Probability | Range/policy |
|---|---:|---|
| Rotation | 0.20 | `[-3°, +3°]`, expand canvas, white fill, bicubic |
| Brightness | 0.20 | factor `[0.8, 1.2]` |
| Gaussian blur | 0.20 | radius `[0.1, 1.0]` |

The random seed is derived from the global seed, document ID, source image hash, augmentation version and configuration hash. Augmented outputs use a separate cache namespace from the T07/T10 baseline.

## Full train audit

| Dataset | Documents | PASS | FAIL | Rotation | Brightness | Blur |
|---|---:|---:|---:|---:|---:|---:|
| MC-OCR | 806 | 806 | 0 | 174 | 152 | 148 |
| SROIE | 526 | 526 | 0 | 101 | 103 | 105 |
| **Total** | **1,332** | **1,332** | **0** | **275** | **255** | **253** |

- Checked 32,862 polygons and 32,769 bounding boxes.
- Invalid transformed boxes: **0**.
- Maximum polygon/bbox-corner round-trip error: **1.819e-12 px**, below the `1e-6 px` tolerance.
- Rotation expands the canvas, so labels near image boundaries are retained.
- All source hashes match the frozen T06 train manifests; raw source files were not modified.
- A second full run produced the same manifest SHA-256: `811265f1597e69452aa9ee5a216b034d930d12f345184700b5c6f028171cf7e5`.

For an arbitrary-angle rotation, an axis-aligned bbox becomes a larger axis-aligned envelope. The audit therefore round-trips the original bbox corners and verifies that the transformed envelope is valid, inside the output image, and contains all transformed corners. It does not inverse-map the lossy envelope itself.

## QA and scope

Four side-by-side overlays were generated locally under `experiments/artifacts/t08/qa/` and are ignored by Git because they contain dataset images. The machine-readable report records their hashes and operations.

T08 remains disabled for the T10 baseline. OCR CER/WER and training-resource ablations are `NOT_RUN_WAITING_FOR_T10`; augmentation must not be presented as improving OCR or model accuracy until those later experiments provide evidence.

## Artifacts

- Config: `experiments/configs/layoutxlm/augmentation_v1.json`
- Implementation: `ai-service/src/invoice_ai/preprocessing/augmentation.py`
- Audit runner: `ai-service/src/invoice_ai/preprocessing/augmentation_audit.py`
- Tests: `ai-service/tests/test_augmentation.py`
- Full manifest: `experiments/manifests/t08_augmentation_train_audit.jsonl`
- Machine-readable audit: `experiments/reports/t08_augmentation_audit.json`
- Verification manifest: `experiments/manifests/t08_verification.json`

