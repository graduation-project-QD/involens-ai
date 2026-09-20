"""Deterministic field normalization shared by baseline and KIE pipelines."""

from .core import NORMALIZATION_VERSION, NormalizationResult, normalize_field, normalize_fields

__all__ = ["NORMALIZATION_VERSION", "NormalizationResult", "normalize_field", "normalize_fields"]
