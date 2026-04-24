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
            print(f"[CommunicationFactory] Communication disabled for job {job_id}", flush=True)
            return None

        # Get communication method
        method = os.getenv("COMMUNICATION_METHOD", "none").lower()
        print(f"[CommunicationFactory] Creating {method} communication service for job {job_id}", flush=True)

        if method == "rabbitmq":
            return CommunicationFactory._create_rabbitmq(job_id)
        elif method == "none":
            print(f"[CommunicationFactory] Communication method set to 'none' for job {job_id}", flush=True)
            return None
        else:
            print(f"[CommunicationFactory] Unknown communication method '{method}', defaulting to 'none'", flush=True)
            return None

    @staticmethod
    def _create_rabbitmq(job_id: str) -> Optional[CommunicationInterface]:
        """Create RabbitMQ communication service."""
        try:
            from .rabbitmq_service import RabbitMQCommunicationService

            rabbitmq_host = os.getenv("RABBITMQ_HOST")
            if not rabbitmq_host:
                print(f"[CommunicationFactory] ❌ RABBITMQ_HOST not configured, communication disabled for job {job_id}", flush=True)
                return None

            rabbitmq_port = int(os.getenv("RABBITMQ_PORT", "5672"))
            rabbitmq_user = os.getenv("RABBITMQ_USER", "guest")
            rabbitmq_password = os.getenv("RABBITMQ_PASSWORD", "guest")
            rabbitmq_exchange = os.getenv("RABBITMQ_EXCHANGE", "scrape-events")
            rabbitmq_exchange_type = os.getenv("RABBITMQ_EXCHANGE_TYPE")
            if not rabbitmq_exchange_type:
                rabbitmq_exchange_type = "topic" if rabbitmq_exchange == "scrape-events" else "direct"
            rabbitmq_queue = os.getenv("RABBITMQ_QUEUE", f"job-{job_id}")

            print(f"[CommunicationFactory] ✅ Creating RabbitMQ communication service for job {job_id}", flush=True)
            print(
                f"[CommunicationFactory] RabbitMQ Config - Host: {rabbitmq_host}, "
                f"Port: {rabbitmq_port}, Exchange: {rabbitmq_exchange}, "
                f"Type: {rabbitmq_exchange_type}",
                flush=True
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
            print(f"[CommunicationFactory] ❌ Failed to import RabbitMQ service (is aio-pika installed?): {e}", flush=True)
            import traceback
            print(traceback.format_exc(), flush=True)
            return None
        except Exception as e:
            print(f"[CommunicationFactory] ❌ Failed to create RabbitMQ service: {e}", flush=True)
            import traceback
            print(traceback.format_exc(), flush=True)
            return None
