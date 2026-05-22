"""Compatibility package for RabbitMQ producer modules."""

from hawki_crawler.rabbitmq.producer import (
    PipelinePublishResult,
    RabbitMQEventProducer,
    RabbitMQEventProducerConfig,
)

__all__ = ["PipelinePublishResult", "RabbitMQEventProducer", "RabbitMQEventProducerConfig"]

