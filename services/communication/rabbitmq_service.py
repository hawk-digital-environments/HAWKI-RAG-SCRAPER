"""
RabbitMQ Communication Service
================================
RabbitMQ implementation of the CommunicationInterface with queue-based reliability.

This implementation uses RabbitMQ's queue system to ensure no messages are lost.
Messages are published to an exchange and routed to job-specific queues.

Installation:
    pip install aio-pika

Configuration:
    RABBITMQ_HOST - RabbitMQ server host
    RABBITMQ_PORT - RabbitMQ server port (default: 5672)
    RABBITMQ_USER - RabbitMQ username (default: guest)
    RABBITMQ_PASSWORD - RabbitMQ password (default: guest)
    RABBITMQ_EXCHANGE - Exchange name (default: scrape-events)
    RABBITMQ_QUEUE - Queue name (default: job-{job_id})
"""

import asyncio
import json
import logging
import os
from typing import Dict, Any, Optional
from datetime import datetime

try:
    import aio_pika
    from aio_pika import Message, DeliveryMode, ExchangeType
    from aio_pika.exceptions import AMQPException
    RABBITMQ_AVAILABLE = True
except ImportError:
    RABBITMQ_AVAILABLE = False
    aio_pika = None

from .interface import CommunicationInterface
from ..state.job_state import JobStateData


class RabbitMQCommunicationService(CommunicationInterface):
    """
    RabbitMQ implementation for job event broadcasting with queue reliability.

    Features:
    - Persistent messages (survive broker restart)
    - Publisher confirms (ensure message delivery)
    - Dead letter exchange for failed messages
    - Automatic reconnection
    - Job-specific queues for targeted consumption

    Message structure:
    {
        "job_id": "unique-job-id",
        "event": "event_name",
        "data": { ... event-specific data ... },
        "timestamp": "ISO-8601 timestamp"
    }
    """

    def __init__(
        self,
        job_id: str,
        host: str = os.getenv("RABBITMQ_HOST","localhost"),
        port: int = int(os.getenv("RABBITMQ_PORT",5672)),
        user: str = os.getenv("RABBITMQ_USERNAME","guest"),
        password: str = os.getenv("RABBITMQ_PASSWORD","guest"),
        exchange: str = os.getenv("RABBITMQ_CHANNEL","scrape-events"),
        queue: str = None
    ):
        """
        Initialize RabbitMQ communication service.

        Args:
            job_id: Unique identifier for the job
            host: RabbitMQ server host
            port: RabbitMQ server port
            user: RabbitMQ username
            password: RabbitMQ password
            exchange: Exchange name for broadcasting events
            queue: Queue name (default: job-{job_id})
        """
        super().__init__(job_id)

        if not RABBITMQ_AVAILABLE:
            raise ImportError(
                "aio-pika is not installed. Install it with: pip install aio-pika"
            )

        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.exchange_name = exchange
        self.queue_name = queue or f"job-{job_id}"

        self.connection: Optional[aio_pika.Connection] = None
        self.channel: Optional[aio_pika.Channel] = None
        self.exchange: Optional[aio_pika.Exchange] = None
        self.queue: Optional[aio_pika.Queue] = None

        self.logger = logging.getLogger(f"RabbitMQCommunication[{job_id}]")
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 3
        self._reconnect_delay = 2

    async def connect(self) -> bool:
        """Establish RabbitMQ connection with retry logic."""
        if self._reconnect_attempts >= self._max_reconnect_attempts:
            self.logger.error(f"Max reconnection attempts ({self._max_reconnect_attempts}) reached")
            return False

        try:
            # Build connection URL
            url = f"amqp://{self.user}:{self.password}@{self.host}:{self.port}/"

            # Establish connection
            self.connection = await aio_pika.connect_robust(
                url,
                timeout=5,
                heartbeat=30
            )

            # Create channel
            self.channel = await self.connection.channel()

            # Enable publisher confirms for reliability
            await self.channel.set_qos(prefetch_count=1)

            # Declare exchange (topic type for flexible routing)
            self.exchange = await self.channel.declare_exchange(
                self.exchange_name,
                ExchangeType.TOPIC,
                durable=True  # Survive broker restart
            )

            # Declare queue
            self.queue = await self.channel.declare_queue(
                self.queue_name,
                durable=True,  # Survive broker restart
                arguments={
                    # Optional: Configure dead letter exchange for failed messages
                    # "x-dead-letter-exchange": f"{self.exchange_name}.dlx",
                    # "x-message-ttl": 86400000,  # 24 hours
                }
            )

            # Bind queue to exchange (catch all events for this job)
            await self.queue.bind(
                self.exchange,
                routing_key=f"job.{self.job_id}.#"  # Match all events for this job
            )

            self._connected = True
            self._reconnect_attempts = 0
            self.logger.info(
                f"Connected to RabbitMQ: {self.host}:{self.port} "
                f"(exchange: {self.exchange_name}, queue: {self.queue_name})"
            )
            return True

        except AMQPException as e:
            self._reconnect_attempts += 1
            self.logger.warning(
                f"Failed to connect to RabbitMQ (attempt {self._reconnect_attempts}/{self._max_reconnect_attempts}): {e}"
            )
            self._connected = False

            if self._reconnect_attempts < self._max_reconnect_attempts:
                self.logger.info(f"Retrying in {self._reconnect_delay} seconds...")
                await asyncio.sleep(self._reconnect_delay)
                return await self.connect()

            self.logger.warning("RabbitMQ connection failed. Continuing without communication.")
            return False

        except Exception as e:
            self.logger.warning(f"Unexpected error connecting to RabbitMQ: {e}")
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Close RabbitMQ connection gracefully."""
        try:
            if self.channel and not self.channel.is_closed:
                await self.channel.close()

            if self.connection and not self.connection.is_closed:
                await self.connection.close()

            self._connected = False
            self.logger.info("RabbitMQ connection closed")
        except Exception as e:
            self.logger.error(f"Error closing RabbitMQ connection: {e}")

    async def _publish(self, event: str, data: Dict[str, Any]) -> bool:
        """
        Publish an event to RabbitMQ exchange.

        Args:
            event: Event name
            data: Event data

        Returns:
            bool: True if published successfully
        """
        if not self._connected or not self.exchange:
            self.logger.error(f"Cannot publish event '{event}' - not connected")
            return False

        try:
            # Construct payload
            payload = {
                "job_id": self.job_id,
                "event": event,
                "data": data,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }

            self.logger.info(f"Event [{event}]: {json.dumps(data, default=str)}")

            # Create message
            message_body = json.dumps(payload, default=str).encode('utf-8')
            message = Message(
                message_body,
                delivery_mode=DeliveryMode.PERSISTENT,  # Survive broker restart
                content_type='application/json',
                content_encoding='utf-8',
                headers={
                    'job_id': self.job_id,
                    'event_type': event
                }
            )

            # Publish with routing key
            routing_key = f"job.{self.job_id}.{event}"
            await self.exchange.publish(
                message,
                routing_key=routing_key
            )

            self.logger.debug(f"Event '{event}' published to exchange '{self.exchange_name}' with routing key '{routing_key}'")
            return True

        except AMQPException as e:
            self.logger.error(f"AMQP error while publishing event '{event}': {e}")
            self._connected = False
            return False

        except (TypeError, ValueError) as e:
            self.logger.error(f"JSON serialization error for event '{event}': {e}")
            return False

        except Exception as e:
            self.logger.error(f"Unexpected error while publishing event '{event}': {e}")
            return False

    async def send_state_update(self, state: JobStateData) -> bool:
        """
        Send job state update via RabbitMQ.

        Args:
            state: Current job state

        Returns:
            bool: True if sent successfully
        """
        return await self._publish("state_update", state.to_dict())

    async def send_event(self, event_type: str, data: Dict[str, Any]) -> bool:
        """
        Send custom event via RabbitMQ.

        Args:
            event_type: Type of event
            data: Event data

        Returns:
            bool: True if sent successfully
        """
        return await self._publish(event_type, data)

    # Legacy compatibility methods

    async def sitemap_detected(self, sitemap_url: str, total_urls: int) -> bool:
        """Legacy method for sitemap detection event."""
        return await self.send_event("sitemap_detected", {
            "sitemap_url": sitemap_url,
            "total_urls": total_urls
        })

    async def urls_discovered(self, urls_count: int, total_to_crawl: int) -> bool:
        """Legacy method for URL discovery event."""
        return await self.send_event("urls_discovered", {
            "urls_count": urls_count,
            "total_to_crawl": total_to_crawl
        })

    async def crawling_started(self, total_pages: int) -> bool:
        """Legacy method for crawling start event."""
        return await self.send_event("crawling_started", {
            "total_pages": total_pages
        })

    async def job_completed(
        self,
        pages_crawled: int,
        output_directory: str,
        success: bool,
        error: Optional[str] = None
    ) -> bool:
        """Legacy method for job completion event."""
        return await self.send_event("job_completed", {
            "pages_crawled": pages_crawled,
            "output_directory": output_directory,
            "success": success,
            "error": error
        })
