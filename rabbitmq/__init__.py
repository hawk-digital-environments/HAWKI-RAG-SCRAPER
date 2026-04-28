"""Compatibility package for RabbitMQ producer modules."""

from src.rabbitmq.producer import (
    PipelinePublishResult,
    RabbitMQEventProducer,
    RabbitMQEventProducerConfig,
)

__all__ = ["PipelinePublishResult", "RabbitMQEventProducer", "RabbitMQEventProducerConfig"]

