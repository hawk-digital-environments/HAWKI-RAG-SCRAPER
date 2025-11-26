"""
Services Package
================
This package contains all service layer components for the crawler.

Components:
- RedisEventEmitter: Handles real-time event communication via Redis Pub/Sub
- JobStateManager: Manages persistent job state on disk
- StorageManager: Handles all file I/O operations
- URLTrackingManager: Manages URL discovery and tracking with dates
- ProgressTracker: Handles rate-limited progress broadcasting
- SummaryManager: Manages job summary creation and export

These services are designed to be used together but remain independent,
following the Single Responsibility Principle.
"""

from .redis_event_emitter import RedisEventEmitter
from .job_state_manager import JobStateManager
from .storage_manager import StorageManager
from .url_tracking_manager import URLTrackingManager
from .progress_tracker import ProgressTracker
from .summary_manager import SummaryManager

__all__ = [
    'RedisEventEmitter',
    'JobStateManager',
    'StorageManager',
    'URLTrackingManager',
    'ProgressTracker',
    'SummaryManager'
]
