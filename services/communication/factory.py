"""
Communication Factory
=====================
Factory pattern for creating communication service instances based on configuration.
"""

import os
from typing import Optional
from .interface import CommunicationInterface


class CommunicationFactory:
    """
    Factory for creating communication service instances.

    This factory reads environment variables to determine which communication
    method to use and instantiates the appropriate implementation.

    Supported methods:
    - redis: Redis Pub/Sub (default)
    - rabbitmq: RabbitMQ with queue system
    - none: No communication (silent mode)

    Environment variables:
    - COMMUNICATION_METHOD: "redis", "rabbitmq", or "none" (default: "redis")
    - COMMUNICATION_ENABLED: "true" or "false" (default: "true")

    For Redis:
    - REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD, REDIS_CHANNEL

    For RabbitMQ:
    - RABBITMQ_HOST, RABBITMQ_PORT, RABBITMQ_USER, RABBITMQ_PASSWORD
    - RABBITMQ_EXCHANGE, RABBITMQ_QUEUE
    """

    @staticmethod
    def create(job_id: str) -> Optional[CommunicationInterface]:
        """
        Create a communication service instance based on environment configuration.

        Args:
            job_id: Unique identifier for the job

        Returns:
            CommunicationInterface instance or None if communication is disabled
        """
        # Check if communication is enabled
        enabled = os.getenv("COMMUNICATION_ENABLED", "true").lower() == "true"
        if not enabled:
            print(f"[CommunicationFactory] Communication disabled for job {job_id}")
            return None

        # Get communication method
        method = os.getenv("COMMUNICATION_METHOD", "redis").lower()

        if method == "redis":
            return CommunicationFactory._create_redis(job_id)
        elif method == "rabbitmq":
            return CommunicationFactory._create_rabbitmq(job_id)
        elif method == "none":
            print(f"[CommunicationFactory] Communication method set to 'none' for job {job_id}")
            return None
        else:
            print(f"[CommunicationFactory] Unknown communication method '{method}', falling back to Redis")
            return CommunicationFactory._create_redis(job_id)

    @staticmethod
    def _create_redis(job_id: str) -> Optional[CommunicationInterface]:
        """Create Redis communication service."""
        try:
            from .redis_service import RedisCommunicationService

            redis_host = os.getenv("REDIS_HOST")
            if not redis_host:
                print(f"[CommunicationFactory] REDIS_HOST not configured, communication disabled for job {job_id}")
                return None

            redis_port = int(os.getenv("REDIS_PORT", "6379"))
            redis_db = int(os.getenv("REDIS_DB", "0"))
            redis_password = os.getenv("REDIS_PASSWORD")
            redis_channel = os.getenv("REDIS_CHANNEL", "scrape-events")

            print(f"[CommunicationFactory] Creating Redis communication service for job {job_id}")
            return RedisCommunicationService(
                job_id=job_id,
                redis_host=redis_host,
                redis_port=redis_port,
                redis_db=redis_db,
                redis_password=redis_password,
                channel=redis_channel
            )
        except ImportError as e:
            print(f"[CommunicationFactory] Failed to import Redis service: {e}")
            return None
        except Exception as e:
            print(f"[CommunicationFactory] Failed to create Redis service: {e}")
            return None

    @staticmethod
    def _create_rabbitmq(job_id: str) -> Optional[CommunicationInterface]:
        """Create RabbitMQ communication service."""
        try:
            from .rabbitmq_service import RabbitMQCommunicationService

            rabbitmq_host = os.getenv("RABBITMQ_HOST")
            if not rabbitmq_host:
                print(f"[CommunicationFactory] RABBITMQ_HOST not configured, communication disabled for job {job_id}")
                return None

            rabbitmq_port = int(os.getenv("RABBITMQ_PORT", "5672"))
            rabbitmq_user = os.getenv("RABBITMQ_USER", "guest")
            rabbitmq_password = os.getenv("RABBITMQ_PASSWORD", "guest")
            rabbitmq_exchange = os.getenv("RABBITMQ_EXCHANGE", "scrape-events")
            rabbitmq_queue = os.getenv("RABBITMQ_QUEUE", f"job-{job_id}")

            print(f"[CommunicationFactory] Creating RabbitMQ communication service for job {job_id}")
            return RabbitMQCommunicationService(
                job_id=job_id,
                host=rabbitmq_host,
                port=rabbitmq_port,
                user=rabbitmq_user,
                password=rabbitmq_password,
                exchange=rabbitmq_exchange,
                queue=rabbitmq_queue
            )
        except ImportError as e:
            print(f"[CommunicationFactory] Failed to import RabbitMQ service (is aio-pika installed?): {e}")
            return None
        except Exception as e:
            print(f"[CommunicationFactory] Failed to create RabbitMQ service: {e}")
            return None
