"""RabbitMQ loop of the AI worker: one request at a time, result published before the request is acknowledged.

Reuses the team's RabbitMQ code unchanged: connection settings (``rabitMQService.build_connection_parameters``,
``configRabbitMQ``), request mapping (``requestDTO.from_json``) and result publishing (``rabitMQService.send_message``).

Delivery rules:

* valid request → result message published (success or ``status: 1``) → ack;
* unreadable request (bad JSON, missing ``id``/``url``) → logged and acked: no result can be addressed to a
  document and redelivering it would fail the same way;
* publishing the result fails → ``ResultPublishError`` stops the loop without ack, so RabbitMQ redelivers the
  request once the worker (restarted by its supervisor) reconnects.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from invoice_ai.rabbitMQ import configRabbitMQ as config
from invoice_ai.rabbitMQ.requestDTO import requestDTO

logger = logging.getLogger(__name__)

Handler = Callable[[requestDTO], dict[str, Any]]
Publisher = Callable[[str], None]


class ResultPublishError(RuntimeError):
    """The result of a processed request could not be published; the request stays unacknowledged."""


def process_delivery(channel: Any, delivery_tag: int, body: bytes, handle: Handler, publish: Publisher) -> None:
    """Handles one delivery: map the request, build the result, publish it, then acknowledge the request."""
    try:
        request = requestDTO.from_json(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, TypeError) as error:
        logger.error("Unreadable extraction request acknowledged without result (%s).", type(error).__name__)
        channel.basic_ack(delivery_tag=delivery_tag)
        return
    message = handle(request)
    try:
        publish(json.dumps(message, ensure_ascii=False))
    except Exception as error:
        logger.error("Result publishing failed; request left unacknowledged. documentId=%s", request.id)
        raise ResultPublishError(f"result of document {request.id} was not published") from error
    channel.basic_ack(delivery_tag=delivery_tag)
    logger.info("Extraction request acknowledged. documentId=%s, status=%s", request.id, message["status"])


def run_consumer(handle: Handler) -> None:
    """Consumes the extraction request queue forever, one message at a time (``prefetch_count=1``)."""
    import pika

    from invoice_ai.rabbitMQ.rabitMQService import build_connection_parameters, send_message

    if not config.RABBITMQ_ENABLED:
        logger.error("Cannot consume: RabbitMQ integration is disabled.")
        raise RuntimeError("RabbitMQ integration is disabled")
    logger.info("Starting AI worker consumer. queue=%s", config.RABBITMQ_EXTRACT_QUEUE)
    with pika.BlockingConnection(build_connection_parameters()) as connection:
        channel = connection.channel()
        channel.basic_qos(prefetch_count=1)  # one heavy extraction at a time per worker
        for method, _, body in channel.consume(queue=config.RABBITMQ_EXTRACT_QUEUE, auto_ack=False):
            process_delivery(channel, method.delivery_tag, body, handle, send_message)
