"""
Communication Interface - Abstract Base for Communication Services
===================================================================
Defines the interface that all communication implementations must follow.
This allows for easy swapping between RabbitMQ or other messaging systems.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from enum import Enum
from ..state.job_state import JobStateData


class Stage(Enum):
    """Valid job stages for stage events."""
    INITIALIZATION = "initialization"
    SITEMAP_DETECTED = "sitemap_detected"
    URLS_DISCOVERED = "urls_discovered"
    CRAWLING_STARTED = "crawling_started"
    SCRAPING = "scraping"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class ReportType(Enum):
    """Valid report types for report events."""
    PROGRESS = "progress"
    URL_COMPLETION = "url_completion"


class CommunicationInterface(ABC):
    """
    Abstract base class for communication services.

    All communication implementations must implement this interface.
    This ensures consistent behavior and makes it easy to swap communication methods.
    """

    def __init__(self, job_id: str):
        """
        Initialize the communication service.

        Args:
            job_id: Unique identifier for the job
        """
        self.job_id = job_id
        self._connected = False

    @abstractmethod
    async def connect(self) -> bool:
        """
        Establish connection to the messaging service.

        Returns:
            bool: True if connected successfully, False otherwise
        """
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """
        Close the connection gracefully.
        """
        pass

    @abstractmethod
    async def send_event(self, event_type: str, data: Dict[str, Any]) -> bool:
        """
        Send a custom event with additional data (low-level method).

        Use the high-level methods (send_stage, send_report_*, send_summary) instead.

        Args:
            event_type: Type of event (e.g., "stage", "report", "summary")
            data: Event-specific data

        Returns:
            bool: True if sent successfully, False otherwise
        """
        pass

    @property
    def is_connected(self) -> bool:
        """Check if the service is currently connected."""
        return self._connected

    # New Event System - Primary Methods

    @abstractmethod
    async def send_stage(self, stage: Stage, details: Optional[Dict[str, Any]] = None) -> bool:
        """
        Send a stage transition event.

        Args:
            stage: Stage enum value
            details: Optional stage-specific details

        Returns:
            bool: True if sent successfully
        """
        pass

    @abstractmethod
    async def send_report_progress(self, progress_data: Dict[str, Any]) -> bool:
        """
        Send a progress report.

        Args:
            progress_data: Progress information from ProgressTracker

        Returns:
            bool: True if sent successfully
        """
        pass

    @abstractmethod
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
        pass

    @abstractmethod
    async def send_summary(self, summary_data: Dict[str, Any]) -> bool:
        """
        Send final job summary.

        Args:
            summary_data: Complete job summary

        Returns:
            bool: True if sent successfully
        """
        pass
