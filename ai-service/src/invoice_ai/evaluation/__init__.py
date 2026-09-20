"""Shared field and entity evaluation for rule and LayoutXLM extractors."""

from .core import (
    EVALUATOR_VERSION,
    EntityDocument,
    EntitySpan,
    EvaluationDocument,
    FieldGroundTruth,
    FieldPrediction,
    evaluate_entities,
    evaluate_fields,
    metrics_table_rows,
    write_metrics_csv,
)

__all__ = [
    "EVALUATOR_VERSION",
    "EntityDocument",
    "EntitySpan",
    "EvaluationDocument",
    "FieldGroundTruth",
    "FieldPrediction",
    "evaluate_entities",
    "evaluate_fields",
    "metrics_table_rows",
    "write_metrics_csv",
]
