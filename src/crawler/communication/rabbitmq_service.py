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
import importlib
import json
import logging
import os
from typing import Dict, Any, Optional, cast
from datetime import datetime

try:
    aio_pika = importlib.import_module("aio_pika")
    Message = getattr(aio_pika, "Message")
    DeliveryMode = getattr(aio_pika, "DeliveryMode")
    ExchangeType = getattr(aio_pika, "ExchangeType")
    AMQPException = importlib.import_module("aio_pika.exceptions").AMQPException
    RABBITMQ_AVAILABLE = True
except ImportError:
    class AMQPException(Exception):
        """Fallback AMQP exception when aio-pika is unavailable."""

    RABBITMQ_AVAILABLE = False
    aio_pika = None
    Message = None
    DeliveryMode = None
    ExchangeType = None

from .interface import CommunicationInterface, Stage, ReportType
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
        host: str = os.getenv("RABBITMQ_HOST", "localhost"),
        port: int = int(os.getenv("RABBITMQ_PORT", 5672)),
        user: str = os.getenv("RABBITMQ_USER", "guest"),
        password: str = os.getenv("RABBITMQ_PASSWORD", "guest"),
        exchange: str = os.getenv("RABBITMQ_EXCHANGE", "scrape-events"),
        queue: str = None,
        exchange_type: Optional[str] = os.getenv("RABBITMQ_EXCHANGE_TYPE"),
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
            exchange_type: Exchange type (topic|direct|fanout|headers)
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
        default_exchange_type = "topic" if exchange == "scrape-events" else "direct"
        self.exchange_type_name = (exchange_type or default_exchange_type).strip().lower()

        # Safe because the service raises immediately above if aio-pika is unavailable.
        self._aio_pika = cast(Any, aio_pika)
        self._message_cls = cast(Any, Message)
        self._delivery_mode = cast(Any, DeliveryMode)
        self._exchange_type = cast(Any, ExchangeType)

        self.connection: Optional[Any] = None
        self.channel: Optional[Any] = None
        self.exchange: Optional[Any] = None
        self.queue: Optional[Any] = None

        self.logger = logging.getLogger(f"RabbitMQCommunication[{job_id}]")
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 3
        self._reconnect_delay = 2

    def _resolve_exchange_type(self) -> Any:
        exchange_map = {
            "topic": self._exchange_type.TOPIC,
            "direct": self._exchange_type.DIRECT,
            "fanout": self._exchange_type.FANOUT,
            "headers": self._exchange_type.HEADERS,
        }
        return exchange_map.get(self.exchange_type_name, self._exchange_type.TOPIC)

    def _bind_routing_key(self) -> str:
        # Direct exchanges do exact key matching. Topic exchanges support wildcards.
        if self.exchange_type_name == "direct":
            return f"job.{self.job_id}"
        return f"job.{self.job_id}.#"

    def _event_routing_key(self, event: str) -> str:
        if self.exchange_type_name == "direct":
            return f"job.{self.job_id}"
        return f"job.{self.job_id}.{event}"

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
            self.connection = await self._aio_pika.connect_robust(
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

            exchange_type = self._resolve_exchange_type()
            self.logger.info(
                f"Declaring exchange: {self.exchange_name} (type={self.exchange_type_name})"
            )
            self.exchange = await self.channel.declare_exchange(
                self.exchange_name,
                exchange_type,
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
            routing_key = self._bind_routing_key()
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
            message = self._message_cls(
                message_body,
                delivery_mode=self._delivery_mode.PERSISTENT,  # Survive broker restart
                content_type='application/json',
                content_encoding='utf-8',
                headers={
                    'job_id': self.job_id,
                    'event_type': event
                }
            )

            # Publish with routing key
            routing_key = self._event_routing_key(event)
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

    # New Event System Implementation

    async def send_stage(self, stage: Stage, details: Optional[Dict[str, Any]] = None) -> bool:
        """
        Send a stage transition event.

        Args:
            stage: Stage enum value
            details: Optional stage-specific details

        Returns:
            bool: True if sent successfully
        """
        data = {
            "stage": stage.value,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "details": details or {}
        }
        return await self._publish("stage", data)

    async def send_report_progress(self, progress_data: Dict[str, Any]) -> bool:
        """
        Send a progress report.

        Args:
            progress_data: Progress information from ProgressTracker
                          (includes completed_urls, failed_urls, stats, and optionally url_completion)

        Returns:
            bool: True if sent successfully
        """
        data = {
            "report_type": ReportType.PROGRESS.value,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            **progress_data  # Merge progress_data directly into the data dict
        }
        return await self._publish("report", data)

    async def send_report_url_completion(
        self,
        url: str,
        url_hash: str,
        status: str,
        page_number: int,
        files_created: Dict[str, Any],
        error: Optional[str] = None,
        processing_time: float = 0.0
    ) -> bool:
        """
        Send a URL completion report.

        Args:
            url: Completed URL
            url_hash: SHA256 hash of the URL
            status: "success" or "failed"
            page_number: Page number
            files_created: Dictionary of created files
            error: Error message if failed
            processing_time: Time taken to process

        Returns:
            bool: True if sent successfully
        """
        data = {
            "report_type": ReportType.URL_COMPLETION.value,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "url_completion": {
                "url": url,
                "url_hash": url_hash,
                "status": status,
                "page_number": page_number,
                "files_created": files_created,
                "error": error,
                "processing_time": processing_time
            }
        }
        return await self._publish("report", data)

    async def send_summary(self, summary_data: Dict[str, Any]) -> bool:
        """
        Send final job summary.

        Args:
            summary_data: Complete job summary

        Returns:
            bool: True if sent successfully
        """
        return await self._publish("summary", summary_data)
