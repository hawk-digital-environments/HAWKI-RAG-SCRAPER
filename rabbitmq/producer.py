"""Compatibility import for pipeline RabbitMQ producer."""

from src.rabbitmq.producer import (
    PipelinePublishResult,
    RabbitMQEventProducer,
    RabbitMQEventProducerConfig,
)

__all__ = ["PipelinePublishResult", "RabbitMQEventProducer", "RabbitMQEventProducerConfig"]

