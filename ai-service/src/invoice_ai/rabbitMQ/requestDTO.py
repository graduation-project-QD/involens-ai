"""Incoming document extraction request mapped from RabbitMQ JSON."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class requestDTO:
    """Document identifier and object storage key supplied by the sender."""

    id: str
    file_name: str

    @classmethod
    def from_json(cls, message: str) -> requestDTO:
        """Map id and fileName from JSON, ignoring additional fields.

        Both fields must be present, non-null and different from an empty
        string. Values are preserved without UUID validation or normalization.
        Invalid JSON or missing required values raise an error to the receiver.
        """
        logger.info("Mapping RabbitMQ request JSON to requestDTO.")
        try:
            payload = json.loads(message)
            if not isinstance(payload, dict):
                logger.error("Request JSON must be an object.")
                raise ValueError("Request JSON must be an object")

            for name in ("id", "fileName"):
                if payload.get(name) is None or payload[name] == "":
                    logger.error("Request field must be present and non-empty: %s", name)
                    raise ValueError(f"Required request field is missing, null or empty: {name}")

            request = cls(id=payload["id"], file_name=payload["fileName"])
        except (TypeError, ValueError) as error:
            logger.error("Request JSON mapping failed (%s).", type(error).__name__)
            raise
        logger.info("RabbitMQ request JSON mapped to requestDTO.")
        return request
