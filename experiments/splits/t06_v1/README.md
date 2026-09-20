# T06 fixed splits (`t06_v1`)

All split files contain references to canonical T04 documents; images and source annotations were not copied or modified.

## MC-OCR

- `mcocr/train.jsonl`, `validation.jsonl`, `test.jsonl`: deterministic seed-42 grouped 70/15/15 split of 1,152 accepted labeled records.
- `mcocr/groups.jsonl`: exact/confirmed duplicate groups.
- `mcocr/near_duplicate_candidates.jsonl`: perceptual candidates and T06 disposition.
- `mcocr/unlabeled_official_validation.jsonl`: 391 provided validation images kept outside gold evaluation because local CSV content is only a sample submission without verified GT.

## SROIE

- `sroie/test.jsonl`: every accepted provided test document, unchanged.
- `sroie/train.jsonl`, `validation.jsonl`: optional adapted-development 85/15 split of accepted provided train documents after disclosed cross-official exact-duplicate exclusions. This branch is prepared only; T25 remains zero-shot primary.
- `sroie/official_train_reference.jsonl`: all 626 accepted provided-train documents before adapted-development exclusions.
- `sroie/adapted_exclusions.jsonl`: seven provided-train copies that exactly duplicate a preserved test image.
- `sroie/groups.jsonl` and `near_duplicate_candidates.jsonl`: duplicate evidence and dispositions.

`split_summary.json` contains counts, field status distributions and leakage checks. `manifest.json` freezes artifact hashes. Rebuild and verify from the workspace root:

```powershell
$env:PYTHONPATH='D:\graduation-project-2\ai-service\src'
python -m invoice_ai.datasets.split --workspace D:\graduation-project-2
python -m invoice_ai.datasets.verify_splits --workspace D:\graduation-project-2
```
