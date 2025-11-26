"""
EventEmitter - Communication Layer
==================================
This class handles all event emissions for job progress tracking.
It sends structured JSON events through WebSocket connections.

Why this exists:
- Decouples event communication from scraping business logic
- Provides real-time job progress updates to external systems (Laravel)
- Maintains consistent event format across all events

Lifecycle:
- Created when a crawl job starts
- Emits events throughout the job lifecycle
- Closes connection when job completes or fails
"""

import asyncio
import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime

# Try to import websockets, but make it optional for development
try:
    import websockets
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False
    logging.warning("websockets library not available - events will only be logged")


class EventEmitter:
    """
    Handles emission of structured job events through WebSocket connections.

    All events follow the structure:
    {
        "job_id": "unique-job-id",
        "event": "event_name",
        "data": { ... event-specific data ... },
        "timestamp": "ISO-8601 timestamp"
    }
    """

    def __init__(self, job_id: str, websocket_url: Optional[str] = None):
        """
        Initialize the event emitter.

        Args:
            job_id: Unique identifier for the job
            websocket_url: WebSocket server URL (e.g., "ws://localhost:6001")
                          If None, events are only logged
        """
        self.job_id = job_id
        self.websocket_url = websocket_url
        self.websocket = None
        self.logger = logging.getLogger(f"EventEmitter[{job_id}]")
        self._connected = False

    async def connect(self):
        """
        Establish WebSocket connection.
        Called automatically on first emit if not already connected.
        """
        if not WEBSOCKETS_AVAILABLE or not self.websocket_url:
            self.logger.info("WebSocket not configured - events will only be logged")
            return

        try:
            self.websocket = await websockets.connect(self.websocket_url)
            self._connected = True
            self.logger.info(f"Connected to WebSocket: {self.websocket_url}")
        except Exception as e:
            self.logger.error(f"Failed to connect to WebSocket: {e}")
            self._connected = False

    async def emit(self, event: str, data: Dict[str, Any]):
        """
        Emit a structured event.

        Args:
            event: Event name (e.g., "sitemap_detected", "url_scraped")
            data: Event-specific data (must be JSON serializable)
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

        # Send through WebSocket if connected
        if self._connected and self.websocket:
            try:
                await self.websocket.send(json.dumps(payload))
            except Exception as e:
                self.logger.error(f"Failed to send event through WebSocket: {e}")
                self._connected = False
        elif not self._connected and self.websocket_url and WEBSOCKETS_AVAILABLE:
            # Try to reconnect
            await self.connect()
            if self._connected:
                try:
                    await self.websocket.send(json.dumps(payload))
                except Exception as e:
                    self.logger.error(f"Failed to send event after reconnect: {e}")

    async def close(self):
        """Close the WebSocket connection."""
        if self.websocket and self._connected:
            try:
                await self.websocket.close()
                self._connected = False
                self.logger.info("WebSocket connection closed")
            except Exception as e:
                self.logger.error(f"Error closing WebSocket: {e}")

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
