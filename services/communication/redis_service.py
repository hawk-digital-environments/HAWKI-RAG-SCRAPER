"""
Redis Communication Service
============================
Redis Pub/Sub implementation of the CommunicationInterface.
"""

import asyncio
import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime
import redis.asyncio as redis
from redis.exceptions import RedisError, ConnectionError as RedisConnectionError

from .interface import CommunicationInterface, Stage, ReportType
from ..state.job_state import JobStateData


class RedisCommunicationService(CommunicationInterface):
    """
    Redis Pub/Sub implementation for job event broadcasting.

    All events are published through Redis Pub/Sub channels with the structure:
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
        redis_host: str = "host.docker.internal",
        redis_port: int = 6379,
        redis_db: int = 0,
        redis_password: Optional[str] = None,
        channel: str = "scrape-events"
    ):
        """
        Initialize Redis communication service.

        Args:
            job_id: Unique identifier for the job
            redis_host: Redis server host
            redis_port: Redis server port
            redis_db: Redis database number
            redis_password: Redis password (optional)
            channel: Redis Pub/Sub channel name
        """
        super().__init__(job_id)
        self.redis_host = redis_host
        self.redis_port = redis_port
        self.redis_db = redis_db
        self.redis_password = redis_password
        self.channel = channel

        self.redis_client: Optional[redis.Redis] = None
        self.logger = logging.getLogger(f"RedisCommunication[{job_id}]")
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 2
        self._reconnect_delay = 1

    async def connect(self) -> bool:
        """Establish Redis connection with retry logic."""
        if self._reconnect_attempts >= self._max_reconnect_attempts:
            self.logger.error(f"Max reconnection attempts ({self._max_reconnect_attempts}) reached")
            return False

        try:
            self.redis_client = await redis.Redis(
                host=self.redis_host,
                port=self.redis_port,
                db=self.redis_db,
                password=self.redis_password,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_keepalive=True,
                health_check_interval=30
            )

            # Test connection
            await self.redis_client.ping()

            self._connected = True
            self._reconnect_attempts = 0
            self.logger.info(f"Connected to Redis: {self.redis_host}:{self.redis_port} on channel '{self.channel}'")
            return True

        except RedisConnectionError as e:
            self._reconnect_attempts += 1
            self.logger.warning(
                f"Failed to connect to Redis (attempt {self._reconnect_attempts}/{self._max_reconnect_attempts}): {e}"
            )
            self._connected = False

            if self._reconnect_attempts < self._max_reconnect_attempts:
                self.logger.info(f"Retrying in {self._reconnect_delay} seconds...")
                await asyncio.sleep(self._reconnect_delay)
                return await self.connect()

            self.logger.warning("Redis connection failed. Continuing without communication.")
            return False

        except Exception as e:
            self.logger.warning(f"Unexpected error connecting to Redis: {e}")
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Close Redis connection gracefully."""
        if self.redis_client:
            try:
                await self.redis_client.close()
                await self.redis_client.connection_pool.disconnect()
                self._connected = False
                self.logger.info("Redis connection closed")
            except Exception as e:
                self.logger.error(f"Error closing Redis connection: {e}")

    async def _ensure_connection(self) -> bool:
        """Ensure Redis connection is active, reconnect if needed."""
        if self._connected and self.redis_client:
            try:
                await self.redis_client.ping()
                return True
            except RedisError:
                self.logger.warning("Redis connection lost, attempting to reconnect...")
                self._connected = False

        if not self._connected:
            return await self.connect()

        return False

    async def _publish(self, event: str, data: Dict[str, Any]) -> bool:
        """
        Publish an event to Redis channel.

        Args:
            event: Event name
            data: Event data

        Returns:
            bool: True if published successfully
        """
        # Construct payload
        payload = {
            "job_id": self.job_id,
            "event": event,
            "data": data,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

        self.logger.info(f"Event [{event}]: {json.dumps(data, default=str)}")

        # Ensure connection
        if not await self._ensure_connection():
            self.logger.error(f"Cannot publish event '{event}' - no Redis connection")
            return False

        try:
            message_json = json.dumps(payload, default=str)
            subscribers_count = await self.redis_client.publish(self.channel, message_json)

            if subscribers_count > 0:
                self.logger.debug(f"Event published to {subscribers_count} subscriber(s)")
            else:
                self.logger.warning(f"Event published but no subscribers on channel '{self.channel}'")

            return True

        except RedisError as e:
            self.logger.error(f"Redis error while publishing event '{event}': {e}")
            self._connected = False
            return False

        except (TypeError, ValueError) as e:
            self.logger.error(f"JSON serialization error for event '{event}': {e}")
            return False

        except Exception as e:
            self.logger.error(f"Unexpected error while publishing event '{event}': {e}")
            return False

    async def send_event(self, event_type: str, data: Dict[str, Any]) -> bool:
        """
        Send custom event via Redis.

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
