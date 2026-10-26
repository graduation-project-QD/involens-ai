from __future__ import annotations

import logging

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

"""
hàm này  dùng để nhận message từ rabbitMQ, 
khi có hàm xử lý chỉ import vào gọi hàm xử lý trong hàm này là đc nhé 
"""
def receive_messages() -> None:
    logger.info("Starting RabbitMQ request message consumption.")
    if not config.RABBITMQ_ENABLED:
        logger.error("Cannot consume: RabbitMQ integration is disabled.")
        raise RuntimeError("RabbitMQ integration is disabled")

    try:
        parameters = build_connection_parameters()
        with pika.BlockingConnection(parameters) as connection:
            channel = connection.channel()
            logger.info(
                "Listening for request messages on queue=%s.",
                config.RABBITMQ_EXTRACT_QUEUE,
            )
            for method, _, body in channel.consume(
                queue=config.RABBITMQ_EXTRACT_QUEUE, auto_ack=False
            ):
                try:
                    message = body.decode("utf-8")
                    request = requestDTO.from_json(message)
                    logger.info(
                        "Received RabbitMQ request: id=%s, fileName=%s",
                        request.id,
                        request.file_name,
                    )
                    #gọi hàm xử lý message tiếp ở đây nhé
                except Exception as error:
                    logger.error(
                        "Request message handling failed (%s); requesting requeue.",
                        type(error).__name__,
                    )
                    channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
                    logger.info("Requested requeue for the failed request message.")
                    continue

                channel.basic_ack(delivery_tag=method.delivery_tag)
    except KeyboardInterrupt:
        logger.error("Request message consumption interrupted; connection cleanup finished.")
        raise
    except Exception as error:
        logger.error("Request message consumption failed (%s).", type(error).__name__)
        raise
