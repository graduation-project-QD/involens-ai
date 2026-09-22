"""Content/config/model addressed OCR cache."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from invoice_ai.preprocessing import PageImage

from .adapter import OcrEngine, extract_ocr
from .config import OcrConfig
from .schema import OCRPage, OcrError, OcrRuntimeIdentity


@dataclass(frozen=True)
class CachedOcrResult:
    page: OCRPage
    raw_engine_output: Any
    cache_key: str
    cache_path: Path
    cache_hit: bool


class OcrCache:
    def __init__(self, root: Path, config: OcrConfig, identity: OcrRuntimeIdentity) -> None:
        self.root = root
        self.config = config
        self.identity = identity

    def key_for(self, page: PageImage) -> str:
        payload = {
            "cache_version": self.config.cache_version,
            "ocr_config_sha256": self.config.config_sha256,
            "model_manifest_sha256": self.identity.model_manifest_sha256,
            "source_sha256": page.source_sha256,
            "pixel_sha256": page.pixel_sha256,
            "preprocessing_version": page.pipeline_version,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def path_for(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def load(self, page: PageImage) -> CachedOcrResult | None:
        key = self.key_for(page)
        path = self.path_for(key)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("cache_key") != key or payload.get("schema_version") != self.config.cache_version:
                raise ValueError("cache identity mismatch")
            canonical = OCRPage.from_dict(payload["canonical"])
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise OcrError("OCR_CACHE_CORRUPT", "OCR cache entry is invalid", path=str(path)) from error
        return CachedOcrResult(canonical, payload["raw_engine_output"], key, path, True)

    def get_or_run(self, page: PageImage, engine: OcrEngine) -> CachedOcrResult:
        cached = self.load(page)
        if cached is not None:
            return cached
        canonical, raw = extract_ocr(page, self.config, self.identity, engine)
        key = self.key_for(page)
        path = self.path_for(key)
        payload = {
            "schema_version": self.config.cache_version,
            "cache_key": key,
            "identity": {
                "ocr_config_sha256": self.config.config_sha256,
                "runtime": self.identity.to_dict(),
            },
            "canonical": canonical.to_dict(),
            "raw_engine_output": raw,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f".tmp.{os.getpid()}")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        os.replace(temporary, path)
        return CachedOcrResult(canonical, raw, key, path, False)
