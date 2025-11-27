"""
Redis Event Emitter - Communication Layer
==========================================
This class handles all event emissions for job progress tracking using Redis Pub/Sub.
It sends structured JSON events through Redis channels.

Why Redis Pub/Sub over WebSockets:
- Better horizontal scalability (multiple publishers/subscribers)
- Built-in reconnection and error handling
- No persistent connection overhead
- Simpler deployment and configuration
- Better integration with Laravel ecosystem

Lifecycle:
- Created when a crawl job starts
- Emits events throughout the job lifecycle via Redis Pub/Sub
- Closes connection when job completes or fails
"""

import asyncio
import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime
import redis.asyncio as redis
from redis.exceptions import RedisError, ConnectionError as RedisConnectionError


class RedisEventEmitter:
    """
    Handles emission of structured job events through Redis Pub/Sub.

    All events follow the structure:
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
        Initialize the Redis event emitter.

        Args:
            job_id: Unique identifier for the job
            redis_host: Redis server host (default: "redis")
            redis_port: Redis server port (default: 6379)
            redis_db: Redis database number (default: 0)
            redis_password: Redis password (optional)
            channel: Redis Pub/Sub channel name (default: "scrape-events")
        """
        self.job_id = job_id
        self.redis_host = redis_host
        self.redis_port = redis_port
        self.redis_db = redis_db
        self.redis_password = redis_password
        self.channel = channel

        self.redis_client: Optional[redis.Redis] = None
        self.logger = logging.getLogger(f"RedisEventEmitter[{job_id}]")
        self._connected = False
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 2  # Reduced to fail faster
        self._reconnect_delay = 1  # Reduced delay for faster failure

    async def connect(self):
        """
        Establish Redis connection with automatic retry logic.
        """
        if self._reconnect_attempts >= self._max_reconnect_attempts:
            self.logger.error(f"Max reconnection attempts ({self._max_reconnect_attempts}) reached")
            return False

        try:
            self.redis_client = await redis.Redis(
                host=self.redis_host,
                port=self.redis_port,
                db=self.redis_db,
                password=self.redis_password,
                decode_responses=True,  # Automatically decode responses to strings
                socket_connect_timeout=2,  # Reduced timeout for faster failure
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
                f"Failed to connect to Redis (attempt {self._reconnect_attempts}/{self._max_reconnect_attempts}): {e}. "
                f"Scraping will continue without real-time events."
            )
            self._connected = False

            if self._reconnect_attempts < self._max_reconnect_attempts:
                self.logger.info(f"Retrying in {self._reconnect_delay} seconds...")
                await asyncio.sleep(self._reconnect_delay)
                return await self.connect()  # Recursive retry

            self.logger.warning("Redis connection failed. Continuing without real-time event updates.")
            return False

        except Exception as e:
            self.logger.warning(f"Unexpected error connecting to Redis: {e}. Continuing without real-time event updates.")
            self._connected = False
            return False

    async def _ensure_connection(self) -> bool:
        """
        Ensure Redis connection is active, attempt reconnection if needed.

        Returns:
            bool: True if connected, False otherwise
        """
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

    async def emit(self, event: str, data: Dict[str, Any]) -> bool:
        """
        Emit a structured event through Redis Pub/Sub.

        Args:
            event: Event name (e.g., "sitemap_detected", "url_scraped")
            data: Event-specific data (must be JSON serializable)

        Returns:
            bool: True if event was published successfully, False otherwise
        """
        # Construct the event payload
        payload = {
            "job_id": self.job_id,
            "event": event,
            "data": data,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

        # Log the event
        self.logger.info(f"Event [{event}]: {json.dumps(data, default=str)}")

        # Ensure connection before publishing
        if not await self._ensure_connection():
            self.logger.error(f"Cannot publish event '{event}' - no Redis connection")
            return False

        try:
            # Publish to Redis channel
            message_json = json.dumps(payload, default=str)
            subscribers_count = await self.redis_client.publish(self.channel, message_json)

            if subscribers_count > 0:
                self.logger.debug(f"Event published to {subscribers_count} subscriber(s)")
            else:
                self.logger.warning(f"Event published but no subscribers are listening on channel '{self.channel}'")

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

    async def close(self):
        """Close the Redis connection gracefully."""
        if self.redis_client:
            try:
                await self.redis_client.close()
                await self.redis_client.connection_pool.disconnect()
                self._connected = False
                self.logger.info("Redis connection closed")
            except Exception as e:
                self.logger.error(f"Error closing Redis connection: {e}")

    # Convenience methods for common events

    async def stage_changed(self, stage: str, details: Optional[Dict[str, Any]] = None):
        """
        Emit event when job stage changes.

        Args:
            stage: One of "initialization", "scraping", "completed", "failed"
            details: Optional additional details about the stage change
        """
        data = {"stage": stage}
        if details:
            data.update(details)

        await self.emit("stage_changed", data)

    async def progress_update(self, progress: Dict[str, Any]):
        """
        Emit rate-limited progress update.

        Args:
            progress: Dictionary with progress information (from ProgressTracker)
        """
        await self.emit("progress_update", progress)

    async def job_summary(self, summary: Dict[str, Any]):
        """
        Emit final job summary.

        Args:
            summary: Complete summary with stats, timing, and results
        """
        await self.emit("job_summary", summary)

    async def sitemap_detected(self, sitemap_url: str, total_urls: int):
        """Emit event when a sitemap is detected."""
        await self.emit("sitemap_detected", {
            "sitemap_url": sitemap_url,
            "total_urls": total_urls
        })

    async def urls_discovered(self, urls_count: int, total_to_crawl: int):
        """Emit event when URLs are discovered from sitemap."""
        await self.emit("urls_discovered", {
            "urls_count": urls_count,
            "total_to_crawl": total_to_crawl
        })

    async def crawling_started(self, total_pages: int):
        """Emit event when crawling begins."""
        await self.emit("crawling_started", {
            "total_pages": total_pages
        })

    async def url_completed(self, url: str, page_number: int, files_created: list):
        """Emit event when a URL processing is complete."""
        await self.emit("url_completed", {
            "url": url,
            "page_number": page_number,
            "files_created": files_created
        })

    async def job_completed(self, pages_crawled: int, output_directory: str, success: bool, error: Optional[str] = None):
        """Emit event when entire job is completed."""
        await self.emit("job_completed", {
            "pages_crawled": pages_crawled,
            "output_directory": output_directory,
            "success": success,
            "error": error
        })
