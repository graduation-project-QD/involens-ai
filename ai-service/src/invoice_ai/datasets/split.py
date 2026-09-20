"""Build deterministic, group-aware T06 split manifests from T04 records."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageChops, ImageStat


SPLIT_VERSION = "t06_v1"
SEED = 42
FIELDS = ("company", "address", "date", "total")


class DisjointSet:
    def __init__(self, values: Iterable[str]) -> None:
        self.parent = {value: value for value in values}

    def find(self, value: str) -> str:
        parent = self.parent[value]
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, left: str, right: str) -> None:
        root_left, root_right = self.find(left), self.find(right)
        if root_left == root_right:
            return
        smaller, larger = sorted((root_left, root_right))
        self.parent[larger] = smaller

    def groups(self) -> list[list[str]]:
        result: dict[str, list[str]] = defaultdict(list)
        for value in sorted(self.parent):
            result[self.find(value)].append(value)
        return sorted((sorted(group) for group in result.values()), key=lambda group: group[0])


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def json_line(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            line = json_line(record)
            stream.write(line)
            digest.update(line.encode("utf-8"))
            count += 1
    return {"path": path.as_posix(), "records": count, "sha256": digest.hexdigest()}


def write_json(path: Path, value: Any) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")
    return {"path": path.as_posix(), "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hamming(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def ahash(image: Image.Image) -> int:
    resized = image.convert("L").resize((8, 8), Image.Resampling.LANCZOS)
    pixels = list(resized.get_flattened_data())
    mean = sum(pixels) / len(pixels)
    value = 0
    for pixel in pixels:
        value = (value << 1) | int(pixel >= mean)
    return value


def dhash(image: Image.Image) -> int:
    resized = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    pixels = list(resized.get_flattened_data())
    value = 0
    for row in range(8):
        offset = row * 9
        for column in range(8):
            value = (value << 1) | int(pixels[offset + column] > pixels[offset + column + 1])
    return value


def grayscale_rms(left_path: Path, right_path: Path) -> float:
    with Image.open(left_path) as left_image, Image.open(right_path) as right_image:
        left = left_image.convert("L").resize((128, 128), Image.Resampling.LANCZOS)
        right = right_image.convert("L").resize((128, 128), Image.Resampling.LANCZOS)
        return ImageStat.Stat(ImageChops.difference(left, right)).rms[0] / 255.0


@dataclass(frozen=True)
class ImageFingerprint:
    document_id: str
    path: Path
    width: int
    height: int
    image_sha256: str
    ahash: int
    dhash: int

    @property
    def aspect_ratio(self) -> float:
        return self.width / self.height


def fingerprint_documents(documents: list[dict[str, Any]], source_root: Path) -> list[ImageFingerprint]:
    values: list[ImageFingerprint] = []
    for document in sorted(documents, key=lambda item: item["document_id"]):
        path = source_root / document["image_path"]
        with Image.open(path) as image:
            values.append(ImageFingerprint(
                document_id=document["document_id"],
                path=path,
                width=image.width,
                height=image.height,
                image_sha256=document["image_sha256"],
                ahash=ahash(image),
                dhash=dhash(image),
            ))
    return values


def mcocr_near_duplicate_audit(
    documents: list[dict[str, Any]], source_root: Path
) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    fingerprints = fingerprint_documents(documents, source_root)
    documents_by_id = {document["document_id"]: document for document in documents}
    candidates: list[dict[str, Any]] = []
    confirmed_pairs: list[tuple[str, str]] = []
    for index, left in enumerate(fingerprints):
        for right in fingerprints[index + 1:]:
            if left.image_sha256 == right.image_sha256:
                continue
            aspect_delta = abs(left.aspect_ratio - right.aspect_ratio) / max(left.aspect_ratio, right.aspect_ratio)
            if aspect_delta > 0.08:
                continue
            dhash_distance = hamming(left.dhash, right.dhash)
            if dhash_distance > 4:
                continue
            ahash_distance = hamming(left.ahash, right.ahash)
            if ahash_distance > 4:
                continue
            rms = grayscale_rms(left.path, right.path)
            confirmed = (
                dhash_distance <= 1
                and ahash_distance <= 1
                and aspect_delta <= 0.01
                and rms <= 0.01
            )
            left_document = documents_by_id[left.document_id]
            right_document = documents_by_id[right.document_id]
            date_differs = left_document["fields"]["date"]["raw_value"] != right_document["fields"]["date"]["raw_value"]
            total_differs = left_document["fields"]["total"]["raw_value"] != right_document["fields"]["total"]["raw_value"]
            if confirmed:
                status = "CONFIRMED_STRONG_NEAR_DUPLICATE"
            elif date_differs and total_differs and rms > 0.03:
                status = "DISTINCT_RECEIPTS_DIFFERENT_DATE_AND_TOTAL"
            else:
                status = "CANDIDATE_REQUIRES_REVIEW"
            candidates.append({
                "document_ids": [left.document_id, right.document_id],
                "dhash_hamming": dhash_distance,
                "ahash_hamming": ahash_distance,
                "relative_aspect_ratio_difference": round(aspect_delta, 8),
                "normalized_grayscale_rms": round(rms, 8),
                "status": status,
            })
            if confirmed:
                confirmed_pairs.append((left.document_id, right.document_id))
    candidates.sort(key=lambda item: (
        item["status"] != "CONFIRMED_STRONG_NEAR_DUPLICATE",
        item["dhash_hamming"] + item["ahash_hamming"],
        item["normalized_grayscale_rms"],
        item["document_ids"],
    ))
    return candidates, confirmed_pairs


def classify_sroie_near_candidates(
    candidates: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    documents_by_id: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    reviewed_paths = {tuple(sorted(record["paths"])): record for record in reviews}
    enriched: list[dict[str, Any]] = []
    confirmed_pairs: list[tuple[str, str]] = []
    for source in candidates:
        candidate = dict(source)
        key = tuple(sorted(candidate["paths"]))
        ids = [Path(path).stem for path in candidate["paths"]]
        candidate["document_ids"] = ids
        review = reviewed_paths.get(key)
        if review is not None:
            candidate["review"] = review
            candidate["t06_status"] = review["review_status"]
        else:
            left, right = (documents_by_id[document_id] for document_id in ids)
            same_company = left["fields"]["company"]["raw_value"] == right["fields"]["company"]["raw_value"]
            same_date = left["fields"]["date"]["raw_value"] == right["fields"]["date"]["raw_value"]
            same_total = left["fields"]["total"]["raw_value"] == right["fields"]["total"]["raw_value"]
            if (
                candidate["dhash_hamming"] <= 1
                and candidate["phash_hamming"] <= 1
                and same_company
                and same_date
                and same_total
            ):
                candidate["t06_status"] = "CONFIRMED_STRONG_NEAR_DUPLICATE_MATCHING_COMPANY_DATE_TOTAL"
                confirmed_pairs.append((ids[0], ids[1]))
            elif not same_date or not same_total:
                candidate["t06_status"] = "DISTINCT_RECEIPTS_DIFFERENT_DATE_OR_TOTAL"
            else:
                candidate["t06_status"] = "CANDIDATE_REQUIRES_REVIEW"
        enriched.append(candidate)
    enriched.sort(key=lambda item: (item["t06_status"], item["document_ids"]))
    return enriched, confirmed_pairs


def ids_from_paths(paths: list[str], accepted_ids: set[str]) -> list[str]:
    ids = []
    for path in paths:
        document_id = Path(path).name
        if document_id in accepted_ids:
            ids.append(document_id)
        elif Path(document_id).stem in accepted_ids:
            ids.append(Path(document_id).stem)
    return sorted(set(ids))


def stable_group_id(dataset: str, members: list[str]) -> str:
    digest = hashlib.sha256((dataset + "\n" + "\n".join(sorted(members))).encode("utf-8")).hexdigest()[:16]
    return f"{dataset}_{digest}"


def build_groups(
    dataset: str,
    documents: list[dict[str, Any]],
    exact_records: list[dict[str, Any]],
    confirmed_near_pairs: list[tuple[str, str]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    ids = {document["document_id"] for document in documents}
    dsu = DisjointSet(ids)
    reasons: dict[frozenset[str], set[str]] = defaultdict(set)
    for record in exact_records:
        members = ids_from_paths(record["paths"], ids)
        for member in members[1:]:
            dsu.union(members[0], member)
        if len(members) > 1:
            reasons[frozenset(members)].add("exact_image_sha256")
    for left, right in confirmed_near_pairs or []:
        if left in ids and right in ids:
            dsu.union(left, right)

    groups: list[dict[str, Any]] = []
    document_to_group: dict[str, str] = {}
    for members in dsu.groups():
        group_id = stable_group_id(dataset, members)
        group_reasons: set[str] = set()
        if len(members) > 1:
            for reason_members, reason_values in reasons.items():
                if reason_members.issubset(set(members)):
                    group_reasons.update(reason_values)
            if any(left in members and right in members for left, right in (confirmed_near_pairs or [])):
                group_reasons.add("confirmed_strong_near_duplicate")
        if not group_reasons:
            group_reasons.add("singleton")
        groups.append({
            "group_id": group_id,
            "document_ids": members,
            "size": len(members),
            "group_reasons": sorted(group_reasons),
        })
        for document_id in members:
            document_to_group[document_id] = group_id
    return groups, document_to_group


def quality_bin(document: dict[str, Any]) -> str:
    quality = document.get("source_metadata", {}).get("annotation_quality")
    if not isinstance(quality, (int, float)):
        return "quality:unknown"
    if quality < 0.5:
        return "quality:low"
    if quality < 0.75:
        return "quality:medium"
    return "quality:high"


def feature_counts(documents: Iterable[dict[str, Any]], include_quality: bool) -> Counter[str]:
    result: Counter[str] = Counter()
    for document in documents:
        result["documents"] += 1
        for field in FIELDS:
            result[f"field:{field}:{document['fields'][field]['status']}"] += 1
        if include_quality:
            result[quality_bin(document)] += 1
    return result


def assign_groups(
    groups: list[dict[str, Any]],
    documents_by_id: dict[str, dict[str, Any]],
    ratios: dict[str, float],
    seed: int,
    include_quality: bool,
) -> dict[str, str]:
    split_names = list(ratios)
    all_features = feature_counts(documents_by_id.values(), include_quality)
    targets = {
        split: {feature: total * ratios[split] for feature, total in all_features.items()}
        for split in split_names
    }
    current = {split: Counter() for split in split_names}
    assignment: dict[str, str] = {}

    group_features = {
        group["group_id"]: feature_counts(
            (documents_by_id[document_id] for document_id in group["document_ids"]), include_quality
        )
        for group in groups
    }
    ordered = sorted(
        groups,
        key=lambda group: hashlib.sha256(f"{seed}:{group['group_id']}".encode("utf-8")).hexdigest(),
    )
    feature_weights = {feature: (2.0 if feature == "documents" else 0.35) for feature in all_features}
    for group in ordered:
        features = group_features[group["group_id"]]
        choices: list[tuple[float, str]] = []
        for candidate in split_names:
            score = 0.0
            for split in split_names:
                for feature, target in targets[split].items():
                    projected = current[split][feature] + (features[feature] if split == candidate else 0)
                    denominator = max(target, 1.0)
                    score += feature_weights[feature] * ((projected - target) / denominator) ** 2
                    if projected > target and feature == "documents":
                        score += 0.5 * ((projected - target) / denominator) ** 2
            choices.append((score, candidate))
        _, selected = min(choices, key=lambda item: (
            round(item[0], 14),
            hashlib.sha256(f"{seed}:{group['group_id']}:{item[1]}".encode("utf-8")).hexdigest(),
        ))
        assignment[group["group_id"]] = selected
        current[selected].update(features)
    return assignment


def split_record(document: dict[str, Any], group_id: str, split: str, intended_use: str) -> dict[str, Any]:
    return {
        "dataset": document["dataset"],
        "dataset_version": document["dataset_version"],
        "canonical_schema_version": document["schema_version"],
        "document_id": document["document_id"],
        "group_id": group_id,
        "split": split,
        "source_partition": document["source_partition"],
        "image_path": document["image_path"],
        "image_sha256": document["image_sha256"],
        "field_status": {field: document["fields"][field]["status"] for field in FIELDS},
        "qa_flags": document.get("qa_flags", []),
        "intended_use": intended_use,
    }


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    field_status: Counter[str] = Counter()
    source_partitions: Counter[str] = Counter()
    group_sizes: Counter[str] = Counter()
    for record in records:
        source_partitions[record["source_partition"]] += 1
        group_sizes[record["group_id"]] += 1
        for field, status in record["field_status"].items():
            field_status[f"{field}:{status}"] += 1
    return {
        "documents": len(records),
        "groups": len(group_sizes),
        "source_partitions": dict(sorted(source_partitions.items())),
        "field_status": dict(sorted(field_status.items())),
        "max_group_size": max(group_sizes.values(), default=0),
    }


def ensure_disjoint(split_records: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    names = list(split_records)
    id_sets = {name: {record["document_id"] for record in records} for name, records in split_records.items()}
    group_sets = {name: {record["group_id"] for record in records} for name, records in split_records.items()}
    hash_sets = {name: {record["image_sha256"] for record in records} for name, records in split_records.items()}
    pair_checks: dict[str, Any] = {}
    for index, left in enumerate(names):
        for right in names[index + 1:]:
            pair = f"{left}__{right}"
            pair_checks[pair] = {
                "document_id_overlap": sorted(id_sets[left] & id_sets[right]),
                "group_id_overlap": sorted(group_sets[left] & group_sets[right]),
                "image_sha256_overlap": sorted(hash_sets[left] & hash_sets[right]),
            }
            if any(pair_checks[pair].values()):
                raise ValueError(f"Leakage detected between {left} and {right}: {pair_checks[pair]}")
    return pair_checks


def relative(path: Path, workspace: Path) -> str:
    return path.relative_to(workspace).as_posix()


def rebase_artifact(artifact: dict[str, Any], workspace: Path) -> dict[str, Any]:
    result = dict(artifact)
    result["path"] = relative(Path(result["path"]), workspace)
    return result


def build(workspace: Path, output_dir: Path) -> dict[str, Any]:
    processed = workspace / "experiments" / "data" / "processed" / "t04_v1"
    manifests = workspace / "experiments" / "manifests"
    mcocr_documents = read_jsonl(processed / "mcocr.jsonl")
    sroie_documents = read_jsonl(processed / "sroie.jsonl")
    mcocr_by_id = {document["document_id"]: document for document in mcocr_documents}
    sroie_by_id = {document["document_id"]: document for document in sroie_documents}
    mcocr_exact = read_jsonl(manifests / "mcocr_exact_duplicates.jsonl")
    sroie_exact = read_jsonl(manifests / "sroie_exact_duplicates.jsonl")

    near_candidates, confirmed_near = mcocr_near_duplicate_audit(
        mcocr_documents, workspace / "dataset_hoadon"
    )
    mcocr_groups, mcocr_group_by_id = build_groups(
        "mcocr", mcocr_documents, mcocr_exact, confirmed_near
    )
    mcocr_assignment = assign_groups(
        mcocr_groups,
        mcocr_by_id,
        {"train": 0.70, "validation": 0.15, "test": 0.15},
        SEED,
        include_quality=True,
    )
    mcocr_splits: dict[str, list[dict[str, Any]]] = {name: [] for name in ("train", "validation", "test")}
    for document_id, document in sorted(mcocr_by_id.items()):
        group_id = mcocr_group_by_id[document_id]
        split = mcocr_assignment[group_id]
        mcocr_splits[split].append(split_record(document, group_id, split, "mcocr_supervised_mvp"))
    mcocr_leakage = ensure_disjoint(mcocr_splits)

    mcocr_val_inventory = [
        record for record in read_jsonl(manifests / "mcocr_image_inventory.jsonl")
        if record["path"].startswith("val_images/val_images/")
    ]
    mcocr_official_val_records = [{
        "dataset": "mcocr_2021",
        "document_id": record["id"],
        "source_partition": "provided_validation",
        "image_path": record["path"],
        "image_sha256": record["sha256"],
        "evaluation_eligible": False,
        "reason": "NO_VERIFIED_GOLD_LOCAL_SAMPLE_OUTPUT_ONLY",
    } for record in sorted(mcocr_val_inventory, key=lambda item: item["id"])]

    sroie_near_source = read_jsonl(manifests / "sroie_near_duplicate_refined.jsonl")
    sroie_near_reviews = read_jsonl(manifests / "sroie_near_duplicate_reviews.jsonl")
    sroie_near_candidates, sroie_confirmed_near = classify_sroie_near_candidates(
        sroie_near_source, sroie_near_reviews, sroie_by_id
    )
    sroie_groups, sroie_group_by_id = build_groups(
        "sroie", sroie_documents, sroie_exact, sroie_confirmed_near
    )
    test_ids = {document_id for document_id, document in sroie_by_id.items() if document["source_partition"] == "test"}
    train_ids = {document_id for document_id, document in sroie_by_id.items() if document["source_partition"] == "train"}
    test_group_ids = {sroie_group_by_id[document_id] for document_id in test_ids}
    excluded_train_ids = sorted(
        document_id for document_id in train_ids
        if sroie_group_by_id[document_id] in test_group_ids
    )
    adapted_train_ids = train_ids - set(excluded_train_ids)
    adapted_documents = [sroie_by_id[document_id] for document_id in sorted(adapted_train_ids)]
    adapted_by_id = {document["document_id"]: document for document in adapted_documents}
    adapted_groups = [
        {**group, "document_ids": [item for item in group["document_ids"] if item in adapted_train_ids]}
        for group in sroie_groups
        if any(item in adapted_train_ids for item in group["document_ids"])
    ]
    adapted_groups = [
        {**group, "size": len(group["document_ids"])} for group in adapted_groups if group["document_ids"]
    ]
    adapted_assignment = assign_groups(
        adapted_groups,
        adapted_by_id,
        {"train": 0.85, "validation": 0.15},
        SEED,
        include_quality=False,
    )
    sroie_splits: dict[str, list[dict[str, Any]]] = {name: [] for name in ("train", "validation", "test")}
    for document_id in sorted(adapted_train_ids):
        document = sroie_by_id[document_id]
        group_id = sroie_group_by_id[document_id]
        split = adapted_assignment[group_id]
        sroie_splits[split].append(split_record(document, group_id, split, "sroie_adapted_optional_not_trained"))
    for document_id in sorted(test_ids):
        document = sroie_by_id[document_id]
        group_id = sroie_group_by_id[document_id]
        sroie_splits["test"].append(split_record(document, group_id, "test", "sroie_zero_shot_official_test"))
    sroie_leakage = ensure_disjoint(sroie_splits)

    sroie_official_train = [
        split_record(sroie_by_id[document_id], sroie_group_by_id[document_id], "official_train", "reference_only")
        for document_id in sorted(train_ids)
    ]
    exclusions = [{
        "dataset": "sroie_2019",
        "document_id": document_id,
        "group_id": sroie_group_by_id[document_id],
        "source_partition": "train",
        "reason": "EXACT_DUPLICATE_OF_PRESERVED_OFFICIAL_TEST_DOCUMENT",
        "disposition": "excluded_from_optional_adapted_train_validation; retained_in_official_train_reference",
    } for document_id in excluded_train_ids]

    cross_unreviewed = sum(
        sorted(candidate["splits"]) == ["test", "train"]
        and candidate["t06_status"] == "CANDIDATE_REQUIRES_REVIEW"
        for candidate in sroie_near_candidates
    )

    artifacts: dict[str, Any] = {}
    for dataset, split_values in (("mcocr", mcocr_splits), ("sroie", sroie_splits)):
        for split, records in split_values.items():
            artifact = write_jsonl(output_dir / dataset / f"{split}.jsonl", records)
            artifacts[f"{dataset}_{split}"] = rebase_artifact(artifact, workspace)
    artifacts["mcocr_groups"] = rebase_artifact(write_jsonl(output_dir / "mcocr" / "groups.jsonl", mcocr_groups), workspace)
    artifacts["mcocr_near_candidates"] = rebase_artifact(
        write_jsonl(output_dir / "mcocr" / "near_duplicate_candidates.jsonl", near_candidates), workspace
    )
    artifacts["mcocr_unlabeled_official_validation"] = rebase_artifact(
        write_jsonl(output_dir / "mcocr" / "unlabeled_official_validation.jsonl", mcocr_official_val_records), workspace
    )
    artifacts["sroie_groups"] = rebase_artifact(write_jsonl(output_dir / "sroie" / "groups.jsonl", sroie_groups), workspace)
    artifacts["sroie_official_train_reference"] = rebase_artifact(
        write_jsonl(output_dir / "sroie" / "official_train_reference.jsonl", sroie_official_train), workspace
    )
    artifacts["sroie_exclusions"] = rebase_artifact(
        write_jsonl(output_dir / "sroie" / "adapted_exclusions.jsonl", exclusions), workspace
    )
    artifacts["sroie_near_candidates"] = rebase_artifact(
        write_jsonl(output_dir / "sroie" / "near_duplicate_candidates.jsonl", sroie_near_candidates), workspace
    )

    summary = {
        "task": "T06",
        "status": "COMPLETED_WITH_DUPLICATE_DISCLOSURES",
        "split_version": SPLIT_VERSION,
        "seed": SEED,
        "canonical_dataset_version": "t04_v1",
        "mcocr": {
            "protocol": "local_labeled_group_split_70_15_15",
            "splits": {name: summarize(records) for name, records in mcocr_splits.items()},
            "source_accepted_documents": len(mcocr_documents),
            "assigned_documents": sum(len(records) for records in mcocr_splits.values()),
            "exact_or_confirmed_groups_with_multiple_documents": sum(group["size"] > 1 for group in mcocr_groups),
            "confirmed_strong_near_duplicate_pairs": len(confirmed_near),
            "unreviewed_near_duplicate_candidates": sum(
                record["status"] == "CANDIDATE_REQUIRES_REVIEW" for record in near_candidates
            ),
            "near_duplicate_candidates_classified_as_distinct_receipts": sum(
                record["status"] == "DISTINCT_RECEIPTS_DIFFERENT_DATE_AND_TOTAL"
                for record in near_candidates
            ),
            "provided_validation_without_verified_gold": len(mcocr_official_val_records),
            "leakage_checks": mcocr_leakage,
        },
        "sroie": {
            "protocol": "preserved_official_test_plus_optional_grouped_85_15_adapted_development",
            "splits": {name: summarize(records) for name, records in sroie_splits.items()},
            "official_train_reference_documents": len(sroie_official_train),
            "official_test_documents_preserved": len(sroie_splits["test"]),
            "cross_official_exact_duplicate_train_documents_excluded_from_adapted_development": len(exclusions),
            "confirmed_strong_near_duplicate_pairs_grouped": len(sroie_confirmed_near),
            "unreviewed_cross_official_near_duplicate_candidates": cross_unreviewed,
            "zero_shot_primary": True,
            "adapted_split_prepared_not_trained": True,
            "leakage_checks": sroie_leakage,
        },
        "guards": {
            "quarantine_ids_in_splits": [],
            "augmentation_generated": False,
            "source_files_modified": False,
            "unreviewed_near_candidates_grouped": False,
        },
        "inputs": {
            "mcocr_canonical_sha256": file_sha256(processed / "mcocr.jsonl"),
            "sroie_canonical_sha256": file_sha256(processed / "sroie.jsonl"),
            "mcocr_exact_duplicates_sha256": file_sha256(manifests / "mcocr_exact_duplicates.jsonl"),
            "sroie_exact_duplicates_sha256": file_sha256(manifests / "sroie_exact_duplicates.jsonl"),
            "sroie_near_duplicate_refined_sha256": file_sha256(manifests / "sroie_near_duplicate_refined.jsonl"),
            "sroie_near_duplicate_reviews_sha256": file_sha256(manifests / "sroie_near_duplicate_reviews.jsonl"),
            "split_policy_sha256": file_sha256(workspace / "ai-service" / "configs" / "datasets" / "t06_split_policy.json"),
            "split_builder_sha256": file_sha256(workspace / "ai-service" / "src" / "invoice_ai" / "datasets" / "split.py"),
        },
        "artifacts": artifacts,
    }
    summary_artifact = rebase_artifact(write_json(output_dir / "split_summary.json", summary), workspace)
    manifest = {
        "task": "T06",
        "split_version": SPLIT_VERSION,
        "seed": SEED,
        "summary": summary_artifact,
        "artifacts": artifacts,
    }
    write_json(output_dir / "manifest.json", manifest)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    output = (args.output or workspace / "experiments" / "splits" / SPLIT_VERSION).resolve()
    result = build(workspace, output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
