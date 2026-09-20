"""Dataset loaders and canonical records."""

from .mcocr import load_mcocr
from .sroie import load_sroie

__all__ = ["load_mcocr", "load_sroie"]
