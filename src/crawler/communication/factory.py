"""
Communication Factory
=====================
Factory pattern for creating communication service instances based on configuration.
"""

import os
import logging
from typing import Optional
from .interface import CommunicationInterface

LOGGER = logging.getLogger("crawler.communication.factory")


class CommunicationFactory:
    """
    Factory for creating communication service instances.

    This factory reads environment variables to determine which communication
    method to use and instantiates the appropriate implementation.

    Supported methods:
    - rabbitmq: RabbitMQ with queue system
    - none: No communication (silent mode)

    Environment variables:
    - COMMUNICATION_METHOD: "rabbitmq" or "none" (default: "none")
    - COMMUNICATION_ENABLED: "true" or "false" (default: "true")

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
            LOGGER.info("Communication disabled", extra={"job_id": job_id})
            return None

        # Get communication method
        method = os.getenv("COMMUNICATION_METHOD", "none").lower()
        LOGGER.info("Creating communication service", extra={"job_id": job_id, "method": method})

        if method == "rabbitmq":
            return CommunicationFactory._create_rabbitmq(job_id)
        elif method == "none":
            LOGGER.info("Communication method set to none", extra={"job_id": job_id})
            return None
        else:
            LOGGER.warning(
                "Unknown communication method, defaulting to none",
                extra={"job_id": job_id, "method": method},
            )
            return None

    @staticmethod
    def _create_rabbitmq(job_id: str) -> Optional[CommunicationInterface]:
        """Create RabbitMQ communication service."""
        try:
            from .rabbitmq_service import RabbitMQCommunicationService

            rabbitmq_host = os.getenv("RABBITMQ_HOST")
            if not rabbitmq_host:
                LOGGER.error("RABBITMQ_HOST not configured", extra={"job_id": job_id})
                return None

            rabbitmq_port = int(os.getenv("RABBITMQ_PORT", "5672"))
            rabbitmq_user = os.getenv("RABBITMQ_USER", "guest")
            rabbitmq_password = os.getenv("RABBITMQ_PASSWORD", "guest")
            rabbitmq_exchange = os.getenv("RABBITMQ_EXCHANGE", "scrape-events")
            rabbitmq_exchange_type = os.getenv("RABBITMQ_EXCHANGE_TYPE")
            if not rabbitmq_exchange_type:
                rabbitmq_exchange_type = "topic" if rabbitmq_exchange == "scrape-events" else "direct"
            rabbitmq_queue = os.getenv("RABBITMQ_QUEUE", f"job-{job_id}")

            LOGGER.info(
                "Creating RabbitMQ communication service",
                extra={
                    "job_id": job_id,
                    "host": rabbitmq_host,
                    "port": rabbitmq_port,
                    "exchange": rabbitmq_exchange,
                    "exchange_type": rabbitmq_exchange_type,
                },
            )

            return RabbitMQCommunicationService(
                job_id=job_id,
                host=rabbitmq_host,
                port=rabbitmq_port,
                user=rabbitmq_user,
                password=rabbitmq_password,
                exchange=rabbitmq_exchange,
                queue=rabbitmq_queue,
                exchange_type=rabbitmq_exchange_type,
            )
        except ImportError as e:
            LOGGER.exception(
                "Failed to import RabbitMQ service (is aio-pika installed?)",
                extra={"job_id": job_id, "error": str(e)},
            )
            return None
        except Exception as e:
            LOGGER.exception(
                "Failed to create RabbitMQ service",
                extra={"job_id": job_id, "error": str(e)},
            )
            return None
