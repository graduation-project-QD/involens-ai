# T05 — Rented GPU runtime smoke

**Status:** `PASS`  
**Candidate:** `ezycloudx_rtx5060ti_cu129_v1`  
**Host:** `ezycloudx-admin`  
**GPU:** `NVIDIA GeForce RTX 5060 Ti, GPU-dab1a7b2-428d-2184-3813-689f7fd89434, 580.173.02, 16311, 12.0`

## LayoutXLM

- Status: `PASS`
- Model: `microsoft/layoutxlm-base`
- Revision: `b95ef788341ccd507115d74e10c4bb7137559f19`
- Load seconds: 6.617963715999998
- Largest tested physical batch: 2
- Reload parity: `True`

| Batch | Status | Loss | Forward+backward seconds | Peak Torch allocated bytes | Peak GPU used MiB |
|---:|---|---:|---:|---:|---:|
| 1 | PASS | 2.381103515625 | 0.7629454790000025 | 2987994112 | 2335 |
| 2 | PASS | 2.5281982421875 | 0.08318193899999926 | 2984392192 | 1765 |

## PaddleOCR

- Status: `PASS`
- API variant: `paddleocr_3_predict`
- Load + inference seconds: 11.518111243000007
- Recognized texts: 42
- Polygons: 42
- Peak process RAM bytes: 1394769920
- Peak GPU used MiB: 203

## Reproducibility

The machine-readable `runtime_manifest.json`, dependency locks, pip inspect output, hardware inventory, logs and checksums are included in the result archive. The large saved model is intentionally excluded; its files are hashed and it is reproducible from the immutable LayoutXLM revision.

T05 can be marked complete only when this report is PASS and the result archive has been copied to persistent/local storage before the rented instance is deleted.
