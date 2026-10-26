import os


# Connection settings shared with the Spring application.
RABBITMQ_HOST = os.getenv("SPRING_RABBITMQ_HOST", "localhost")
RABBITMQ_PORT = int(os.getenv("SPRING_RABBITMQ_PORT", "5672"))
RABBITMQ_USERNAME = os.getenv("SPRING_RABBITMQ_USERNAME", "involens")
RABBITMQ_PASSWORD = os.getenv("SPRING_RABBITMQ_PASSWORD", "involens_rabbit_local_2026")
RABBITMQ_VIRTUAL_HOST = os.getenv("SPRING_RABBITMQ_VIRTUAL_HOST", "involens")
RABBITMQ_ENABLED = True

# Extraction request destination and routing configuration.
RABBITMQ_EXTRACT_EXCHANGE = os.getenv("RABBITMQ_EXTRACT_EXCHANGE", "involens")
RABBITMQ_EXTRACT_QUEUE = os.getenv("RABBITMQ_EXTRACT_QUEUE", "involens.request")
RABBITMQ_EXTRACT_ROUTING_KEY = os.getenv(
    "RABBITMQ_EXTRACT_ROUTING_KEY", "involens.request"
)

# Result destinations; declaring queues and dead-letter policies is separate.
RABBITMQ_RESULT_EXCHANGE = os.getenv("RABBITMQ_RESULT_EXCHANGE", "involens")
RABBITMQ_RESULT_ROUTING_KEY = os.getenv(
    "RABBITMQ_RESULT_ROUTING_KEY", "involens.result"
)
RABBITMQ_RESULT_QUEUE = os.getenv("RABBITMQ_RESULT_QUEUE", "involens.result")
RABBITMQ_RESULT_DEAD_LETTER_QUEUE = os.getenv(
    "RABBITMQ_RESULT_DEAD_LETTER_QUEUE", "involens.dlt"
)
