"""
Communication Services
======================
Modular communication layer supporting multiple messaging systems.

Supported implementations:
- Redis Pub/Sub
- RabbitMQ with queue system

Usage:
    from services.communication import CommunicationFactory

    # Create communication service based on .env configuration
    comm = CommunicationFactory.create(job_id="123")
    if comm:
        await comm.connect()
        await comm.send_state_update(job_state)
        await comm.disconnect()
"""

from .interface import CommunicationInterface
from .factory import CommunicationFactory
from .redis_service import RedisCommunicationService

__all__ = [
    'CommunicationInterface',
    'CommunicationFactory',
    'RedisCommunicationService',
]

# Conditional export of RabbitMQ service (if aio-pika is installed)
try:
    from .rabbitmq_service import RabbitMQCommunicationService
    __all__.append('RabbitMQCommunicationService')
except ImportError:
    pass
