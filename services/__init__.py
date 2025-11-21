"""
Services Package
================
This package contains all service layer components for the crawler.

Components:
- EventEmitter: Handles real-time event communication via WebSocket
- JobStateManager: Manages persistent job state on disk
- StorageManager: Handles all file I/O operations

These services are designed to be used together but remain independent,
following the Single Responsibility Principle.
"""

from .event_emitter import EventEmitter
from .job_state_manager import JobStateManager
from .storage_manager import StorageManager

__all__ = [
    'EventEmitter',
    'JobStateManager',
    'StorageManager'
]
