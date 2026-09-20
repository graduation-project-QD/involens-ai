from __future__ import annotations

import unittest

from invoice_ai.datasets.split import (
    assign_groups,
    build_groups,
    classify_sroie_near_candidates,
    ensure_disjoint,
)


def document(document_id: str, image_hash: str, date: str = "2026-01-01", total: str = "100") -> dict:
    return {
        "schema_version": "1.0",
        "dataset": "test",
        "dataset_version": "test",
        "document_id": document_id,
        "source_partition": "train",
        "image_path": f"{document_id}.jpg",
        "image_sha256": image_hash,
        "fields": {
            "company": {"status": "annotated", "raw_value": "Company"},
            "address": {"status": "annotated", "raw_value": "Address"},
            "date": {"status": "annotated", "raw_value": date},
            "total": {"status": "annotated", "raw_value": total},
        },
        "qa_flags": [],
        "source_metadata": {"annotation_quality": 0.8},
    }


class SplitTests(unittest.TestCase):
    def test_exact_duplicate_group_is_kept_together_deterministically(self) -> None:
        documents = [document("a.jpg", "same"), document("b.jpg", "same"), document("c.jpg", "other")]
        exact = [{"paths": ["train/a.jpg", "train/b.jpg"], "sha256": "same"}]
        groups, by_id = build_groups("unit", documents, exact)
        self.assertEqual(by_id["a.jpg"], by_id["b.jpg"])
        self.assertNotEqual(by_id["a.jpg"], by_id["c.jpg"])
        docs_by_id = {item["document_id"]: item for item in documents}
        first = assign_groups(groups, docs_by_id, {"train": 0.5, "validation": 0.5}, 42, True)
        second = assign_groups(groups, docs_by_id, {"train": 0.5, "validation": 0.5}, 42, True)
        self.assertEqual(first, second)
        self.assertEqual(first[by_id["a.jpg"]], first[by_id["b.jpg"]])

    def test_sroie_strong_near_duplicate_requires_matching_key_fields(self) -> None:
        docs = {
            "a": document("a", "a"),
            "b": document("b", "b"),
            "c": document("c", "c", total="200"),
        }
        candidates = [
            {"paths": ["train/img/a.jpg", "train/img/b.jpg"], "splits": ["train", "train"],
             "dhash_hamming": 1, "phash_hamming": 0},
            {"paths": ["train/img/a.jpg", "test/img/c.jpg"], "splits": ["train", "test"],
             "dhash_hamming": 1, "phash_hamming": 0},
        ]
        classified, confirmed = classify_sroie_near_candidates(candidates, [], docs)
        self.assertEqual(confirmed, [("a", "b")])
        statuses = {tuple(item["document_ids"]): item["t06_status"] for item in classified}
        self.assertEqual(statuses[("a", "c")], "DISTINCT_RECEIPTS_DIFFERENT_DATE_OR_TOTAL")

    def test_leakage_guard_rejects_hash_overlap(self) -> None:
        with self.assertRaises(ValueError):
            ensure_disjoint({
                "train": [{"document_id": "a", "group_id": "g1", "image_sha256": "same"}],
                "test": [{"document_id": "b", "group_id": "g2", "image_sha256": "same"}],
            })


if __name__ == "__main__":
    unittest.main()
