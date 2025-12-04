"""
Services Package
================
This package contains all service layer components for the crawler.

Organized into subdirectories:
- communication/: Communication services (Redis, RabbitMQ, etc.)
- state/: Job state and progress tracking
- storage/: File storage, URL tracking, and summaries

New Architecture:
- JobState: Unified observable job state object
- CommunicationFactory: Creates communication services based on .env config
- CommunicationInterface: Abstract interface for all communication implementations

Legacy Components (for backward compatibility):
- RedisEventEmitter: Old Redis implementation (use CommunicationFactory instead)
- JobStateManager: Old state manager (use JobState instead)
- StorageManager, URLTrackingManager, ProgressTracker, SummaryManager: Still active

These services are designed to be modular, scalable, and follow the
Single Responsibility Principle.
"""

# New architecture exports
from .communication import CommunicationFactory, CommunicationInterface
from .state import JobState, JobStateData, ProgressTracker
from .storage import StorageManager, URLTrackingManager, SummaryManager

# Legacy exports for backward compatibility
from .redis_event_emitter import RedisEventEmitter
from .job_state_manager import JobStateManager

__all__ = [
    # New architecture
    'CommunicationFactory',
    'CommunicationInterface',
    'JobState',
    'JobStateData',

    # Still active services
    'StorageManager',
    'URLTrackingManager',
    'ProgressTracker',
    'SummaryManager',

    # Legacy (backward compatibility)
    'RedisEventEmitter',
    'JobStateManager',
]
