"""Starts the AI worker: loads the inference models once, then consumes extraction requests.

Usage::

    python -m invoice_ai.worker --weights ../weights --paddlex-home ../paddlex

RabbitMQ settings come from ``rabbitMQ/configRabbitMQ.py`` (environment variables ``SPRING_RABBITMQ_*`` and
``RABBITMQ_*``). The process exits when the connection is lost or a result cannot be published; run it under
a supervisor that restarts it (Docker ``restart: always``, systemd).
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Sequence

from invoice_ai.inference import InvoicePipeline
from invoice_ai.worker.consumer import run_consumer
from invoice_ai.worker.handler import handle_request

logger = logging.getLogger("invoice_ai.worker")


def main(argv: Sequence[str] | None = None) -> None:
    """Parses the model locations, loads the pipeline and runs the consumer loop."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--weights", type=Path, required=True, help="folder with ft_vgg_transformer_20000.pth and layoutxlm_e2/")
    parser.add_argument("--paddlex-home", type=Path, required=True, help="folder holding official_models/ (PaddleOCR)")
    parser.add_argument("--device", default=None, help="cuda or cpu (default: cuda when available)")
    parser.add_argument("--cpu-threads", type=int, default=6)
    parser.add_argument("--tokenizer", default="microsoft/layoutxlm-base")
    args = parser.parse_args(argv)
    logger.info("AI worker starting")
    pipeline = InvoicePipeline(args.weights, args.paddlex_home, args.device, args.cpu_threads, args.tokenizer)
    try:
        run_consumer(lambda request: handle_request(request, pipeline))
    except Exception:
        logger.error("AI worker stopped", exc_info=True)
        raise


if __name__ == "__main__":
    main()
