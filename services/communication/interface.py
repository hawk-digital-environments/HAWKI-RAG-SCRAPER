"""
Communication Interface - Abstract Base for Communication Services
===================================================================
Defines the interface that all communication implementations must follow.
This allows for easy swapping between Redis, RabbitMQ, or other messaging systems.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from ..state.job_state import JobStateData


class CommunicationInterface(ABC):
    """
    Abstract base class for communication services.

    All communication implementations (Redis, RabbitMQ, etc.) must implement this interface.
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
    async def send_state_update(self, state: JobStateData) -> bool:
        """
        Send a job state update.

        This is the primary method for broadcasting state changes.
        The state object contains all job information in a unified format.

        Args:
            state: The current job state

        Returns:
            bool: True if sent successfully, False otherwise
        """
        pass

    @abstractmethod
    async def send_event(self, event_type: str, data: Dict[str, Any]) -> bool:
        """
        Send a custom event with additional data.

        Use this for events that need extra context beyond the job state
        (e.g., specific URL completion, file creation, etc.)

        Args:
            event_type: Type of event (e.g., "url_completed", "file_created")
            data: Event-specific data

        Returns:
            bool: True if sent successfully, False otherwise
        """
        pass

    @property
    def is_connected(self) -> bool:
        """Check if the service is currently connected."""
        return self._connected

    # Convenience methods (can be overridden by implementations)

    async def send_stage_change(self, stage: str, details: Optional[Dict[str, Any]] = None) -> bool:
        """
        Send a stage change event.

        Args:
            stage: One of "initialization", "scraping", "completed", "failed"
            details: Optional additional details

        Returns:
            bool: True if sent successfully
        """
        data = {"stage": stage}
        if details:
            data.update(details)
        return await self.send_event("stage_changed", data)

    async def send_url_completed(
        self,
        url: str,
        page_number: int,
        files_created: list,
        state: JobStateData
    ) -> bool:
        """
        Send URL completion event with current state.

        Args:
            url: The completed URL
            page_number: Page number
            files_created: List of created files
            state: Current job state

        Returns:
            bool: True if sent successfully
        """
        data = {
            "url": url,
            "page_number": page_number,
            "files_created": files_created,
            "state": state.to_dict()
        }
        return await self.send_event("url_completed", data)

    async def send_job_summary(self, summary: Dict[str, Any]) -> bool:
        """
        Send job summary event.

        Args:
            summary: Complete job summary with statistics

        Returns:
            bool: True if sent successfully
        """
        return await self.send_event("job_summary", summary)
