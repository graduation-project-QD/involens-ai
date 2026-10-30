from __future__ import annotations

import json
import logging
from typing import Any, Callable

import pika

from . import configRabbitMQ as config
from .requestDTO import requestDTO


logger = logging.getLogger(__name__)


def build_connection_parameters() -> pika.ConnectionParameters:
    """Prepare non-TLS RabbitMQ parameters using the configured server settings."""
    logger.info("Preparing RabbitMQ connection settings.")
    for name in (
        "RABBITMQ_HOST",
        "RABBITMQ_USERNAME",
        "RABBITMQ_PASSWORD",
        "RABBITMQ_VIRTUAL_HOST",
    ):
        value = getattr(config, name)
        if not isinstance(value, str) or not value.strip() or value.startswith("<YOUR_"):
            logger.error("RabbitMQ configuration must be filled in: %s", name)
            raise ValueError(f"Invalid configuration: {name}")

    try:
        parameters = pika.ConnectionParameters(
            host=config.RABBITMQ_HOST,
            port=config.RABBITMQ_PORT,
            virtual_host=config.RABBITMQ_VIRTUAL_HOST,
            credentials=pika.PlainCredentials(
                config.RABBITMQ_USERNAME, config.RABBITMQ_PASSWORD
            ),
            ssl_options=None,
            connection_attempts=1,
        )
    except Exception as error:
        # Exception text may contain connection details; log only its type.
        logger.error("Preparing RabbitMQ settings failed (%s).", type(error).__name__)
        raise
    logger.info("RabbitMQ connection settings are ready; TLS is disabled.")
    return parameters


def send_message(message: str) -> None:
    """send message kết quả trích xuất gọi hàm này

    Publish a UTF-8 result using the configured exchange and routing key.
    """
   
    logger.info("Starting RabbitMQ result message publishing.")
    if not config.RABBITMQ_ENABLED:
        logger.error("Cannot publish: RabbitMQ integration is disabled.")
        raise RuntimeError("RabbitMQ integration is disabled")
    if not isinstance(message, str):
        logger.error("Cannot publish: message must be a string.")
        raise TypeError("message must be a string")

    try:
        parameters = build_connection_parameters()
        with pika.BlockingConnection(parameters) as connection:
            channel = connection.channel()
            channel.confirm_delivery()
            channel.basic_publish(
                exchange=config.RABBITMQ_RESULT_EXCHANGE,
                routing_key=config.RABBITMQ_RESULT_ROUTING_KEY,
                body=message.encode("utf-8"),
                mandatory=True,
            )
            logger.info(
                "RabbitMQ confirmed result publishing to exchange=%s, routing_key=%s.",
                config.RABBITMQ_RESULT_EXCHANGE,
                config.RABBITMQ_RESULT_ROUTING_KEY,
            )
        logger.info("Result message publishing completed; connection closed.")
    except Exception as error:
        logger.error("Result message publishing failed (%s).", type(error).__name__)
        raise

class ResultPublishError(RuntimeError):
    """The result of a processed request could not be published; the request stays unacknowledged."""


def process_delivery(
    channel: Any,
    delivery_tag: int,
    body: bytes,
    handle: Callable[[requestDTO], dict[str, Any]],
    publish: Callable[[str], None] | None = None,
) -> None:
    """Handle one request: map it, run the extraction handler, publish the result, then acknowledge.

    An unreadable request (bad JSON, missing id/url) is logged and acknowledged without a result: no
    document can be addressed and redelivering it would fail the same way. When publishing the result
    fails, ``ResultPublishError`` is raised and the request is not acknowledged, so RabbitMQ redelivers it.
    """
    publish = publish or send_message
    try:
        request = requestDTO.from_json(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, TypeError) as error:
        logger.error("Unreadable request message acknowledged without result (%s).", type(error).__name__)
        channel.basic_ack(delivery_tag=delivery_tag)
        return
    logger.info("Received RabbitMQ request: id=%s", request.id)
    result = handle(request)
    try:
        publish(json.dumps(result, ensure_ascii=False))
    except Exception as error:
        logger.error("Result publishing failed (%s); request left unacknowledged: id=%s", type(error).__name__, request.id)
        raise ResultPublishError(f"result of document {request.id} was not published") from error
    channel.basic_ack(delivery_tag=delivery_tag)
    logger.info("Request acknowledged after publishing the result: id=%s, status=%s", request.id, result.get("status"))


"""
hàm này dùng để nhận message từ rabbitMQ và gọi hàm trích xuất (handle) cho từng message.
AI worker gọi: receive_messages(lambda request: handle_request(request, pipeline))
"""
def receive_messages(handle: Callable[[requestDTO], dict[str, Any]]) -> None:
    """Consume extraction requests one at a time, publish each extraction result, then acknowledge it."""
    logger.info("Starting RabbitMQ request message consumption.")
    if not config.RABBITMQ_ENABLED:
        logger.error("Cannot consume: RabbitMQ integration is disabled.")
        raise RuntimeError("RabbitMQ integration is disabled")

    try:
        parameters = build_connection_parameters()
        with pika.BlockingConnection(parameters) as connection:
            channel = connection.channel()
            channel.basic_qos(prefetch_count=1)  # one heavy extraction at a time per worker
            logger.info(
                "Listening for request messages on queue=%s.",
                config.RABBITMQ_EXTRACT_QUEUE,
            )
            for method, _, body in channel.consume(
                queue=config.RABBITMQ_EXTRACT_QUEUE, auto_ack=False
            ):
                process_delivery(channel, method.delivery_tag, body, handle)
    except KeyboardInterrupt:
        logger.error("Request message consumption interrupted; connection cleanup finished.")
        raise
    except Exception as error:
        logger.error("Request message consumption failed (%s).", type(error).__name__)
        raise
