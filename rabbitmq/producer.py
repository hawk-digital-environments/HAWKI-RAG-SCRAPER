"""Compatibility import for pipeline RabbitMQ producer."""

from hawki_crawler.rabbitmq.producer import (
    PipelinePublishResult,
    RabbitMQEventProducer,
    RabbitMQEventProducerConfig,
)

__all__ = ["PipelinePublishResult", "RabbitMQEventProducer", "RabbitMQEventProducerConfig"]

