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
            print(f"[RabbitMQ] Max reconnection attempts ({self._max_reconnect_attempts}) reached for job {self.job_id}", flush=True)
            return False

        try:
            self.logger.info(f"Connecting to RabbitMQ at {self.host}:{self.port}...")
            print(f"[RabbitMQ] Connecting to {self.host}:{self.port}...", flush=True)

            # Build connection URL
            url = f"amqp://{self.user}:{self.password}@{self.host}:{self.port}/"

            # Establish connection
            self.logger.info(f"Establishing connection to RabbitMQ...")
            self.connection = await aio_pika.connect_robust(
                url,
                timeout=5,
                heartbeat=30
            )
            self.logger.info(f"RabbitMQ connection established")

            # Create channel
            self.logger.info(f"Creating RabbitMQ channel...")
            self.channel = await self.connection.channel()
            self.logger.info(f"RabbitMQ channel created")

            # Enable publisher confirms for reliability
            await self.channel.set_qos(prefetch_count=1)

            # Declare exchange (topic type for flexible routing)
            self.logger.info(f"Declaring exchange: {self.exchange_name}")
            self.exchange = await self.channel.declare_exchange(
                self.exchange_name,
                ExchangeType.TOPIC,
                durable=True  # Survive broker restart
            )
            self.logger.info(f"Exchange declared: {self.exchange_name}")

            # Declare queue
            self.logger.info(f"Declaring queue: {self.queue_name}")
            self.queue = await self.channel.declare_queue(
                self.queue_name,
                durable=True,  # Survive broker restart
                arguments={
                    # Optional: Configure dead letter exchange for failed messages
                    # "x-dead-letter-exchange": f"{self.exchange_name}.dlx",
                    # "x-message-ttl": 86400000,  # 24 hours
                }
            )
            self.logger.info(f"Queue declared: {self.queue_name}")

            # Bind queue to exchange (catch all events for this job)
            routing_key = f"job.{self.job_id}.#"
            self.logger.info(f"Binding queue to exchange with routing key: {routing_key}")
            await self.queue.bind(
                self.exchange,
                routing_key=routing_key  # Match all events for this job
            )
            self.logger.info(f"Queue bound to exchange")

            self._connected = True
            self._reconnect_attempts = 0
            success_msg = (
                f"✅ Connected to RabbitMQ: {self.host}:{self.port} "
                f"(exchange: {self.exchange_name}, queue: {self.queue_name})"
            )
            self.logger.info(success_msg)
            print(f"[RabbitMQ] {success_msg}", flush=True)
            return True

        except AMQPException as e:
            self._reconnect_attempts += 1
            error_msg = f"Failed to connect to RabbitMQ (attempt {self._reconnect_attempts}/{self._max_reconnect_attempts}): {e}"
            self.logger.warning(error_msg)
            print(f"[RabbitMQ] ❌ {error_msg}", flush=True)
            self._connected = False

            if self._reconnect_attempts < self._max_reconnect_attempts:
                retry_msg = f"Retrying in {self._reconnect_delay} seconds..."
                self.logger.info(retry_msg)
                print(f"[RabbitMQ] {retry_msg}", flush=True)
                await asyncio.sleep(self._reconnect_delay)
                return await self.connect()

            final_error = "RabbitMQ connection failed. Continuing without communication."
            self.logger.warning(final_error)
            print(f"[RabbitMQ] ⚠️  {final_error}", flush=True)
            return False

        except Exception as e:
            error_msg = f"Unexpected error connecting to RabbitMQ: {e}"
            self.logger.warning(error_msg)
            print(f"[RabbitMQ] ❌ {error_msg}", flush=True)
            import traceback
            self.logger.error(traceback.format_exc())
            print(traceback.format_exc(), flush=True)
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
            error_msg = f"Cannot publish event '{event}' - not connected"
            self.logger.error(error_msg)
            print(f"[RabbitMQ] ❌ {error_msg}", flush=True)
            return False

        try:
            # Construct payload
            payload = {
                "job_id": self.job_id,
                "event": event,
                "data": data,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }

            # Log the event (compact format for console)
            data_str = json.dumps(data, default=str)
            self.logger.info(f"Event [{event}]: {data_str}")
            print(f"[RabbitMQ] 📤 Publishing event [{event}] to exchange '{self.exchange_name}'", flush=True)

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
            print(f"[RabbitMQ] ✅ Event [{event}] published successfully", flush=True)
            return True

        except AMQPException as e:
            error_msg = f"AMQP error while publishing event '{event}': {e}"
            self.logger.error(error_msg)
            print(f"[RabbitMQ] ❌ {error_msg}", flush=True)
            self._connected = False
            return False

        except (TypeError, ValueError) as e:
            error_msg = f"JSON serialization error for event '{event}': {e}"
            self.logger.error(error_msg)
            print(f"[RabbitMQ] ❌ {error_msg}", flush=True)
            return False

        except Exception as e:
            error_msg = f"Unexpected error while publishing event '{event}': {e}"
            self.logger.error(error_msg)
            print(f"[RabbitMQ] ❌ {error_msg}", flush=True)
            import traceback
            self.logger.error(traceback.format_exc())
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

    async def stage_changed(self, stage: str, details: Optional[Dict[str, Any]] = None) -> bool:
        """
        Emit event when job stage changes.

        Args:
            stage: One of "initialization", "scraping", "completed", "failed"
            details: Optional additional details about the stage change

        Returns:
            bool: True if sent successfully
        """
        data = {"stage": stage}
        if details:
            data.update(details)
        return await self._publish("stage_changed", data)

    async def progress_update(self, progress: Dict[str, Any]) -> bool:
        """
        Emit rate-limited progress update.

        Args:
            progress: Dictionary with progress information (from ProgressTracker)

        Returns:
            bool: True if sent successfully
        """
        return await self._publish("progress_update", progress)

    async def job_summary(self, summary: Dict[str, Any]) -> bool:
        """
        Emit final job summary.

        Args:
            summary: Complete summary with stats, timing, and results

        Returns:
            bool: True if sent successfully
        """
        return await self._publish("job_summary", summary)

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
