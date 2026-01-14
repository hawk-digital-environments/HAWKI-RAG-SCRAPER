# Services Layer Documentation

## Overview

The services layer provides modular, scalable components for the crawler application. Services are organized into three main categories: **communication**, **state**, and **storage**.

## Directory Structure

```
src/crawler/
├── communication/          # Communication layer (RabbitMQ or none)
│   ├── interface.py        # CommunicationInterface (ABC)
│   ├── factory.py          # CommunicationFactory
│   └── rabbitmq_service.py # RabbitMQ queue implementation
│
├── state/                  # State management
│   ├── job_state.py        # JobState (unified state object)
│   └── progress_tracker.py # ProgressTracker (rate-limited updates)
│
├── storage/                # Storage services
│   ├── storage_manager.py      # StorageManager (file I/O)
│   ├── url_tracking_manager.py # URLTrackingManager (URL tracking)
│   └── summary_manager.py      # SummaryManager (job summaries)
│
├── core/                   # Crawler core logic
│   └── service.py
└── models.py               # Pydantic models
```

## Core Components

### 1. Communication Layer (`communication/`)

Provides flexible, pluggable communication services for broadcasting job events.

#### **CommunicationInterface** (`interface.py`)

Abstract base class that all communication implementations must follow.

**Key Methods:**
- `async connect() -> bool` - Establish connection
- `async disconnect()` - Close connection gracefully
- `async send_stage(stage: Stage, details: Dict) -> bool` - Stage transitions
- `async send_report_progress(progress_data: Dict) -> bool` - Progress reports
- `async send_report_url_completion(...) -> bool` - URL completion reports
- `async send_summary(summary_data: Dict) -> bool` - Final summary

#### **CommunicationFactory** (`factory.py`)

Factory for creating communication service instances based on environment configuration.

**Usage:**
```python
from src.crawler.communication import CommunicationFactory

comm = CommunicationFactory.create(job_id="123")
if comm:
    await comm.connect()
    await comm.send_summary(summary_dict)
    await comm.disconnect()
```

**Configuration** (`.env`):
```bash
COMMUNICATION_METHOD=rabbitmq   # Options: rabbitmq, none
COMMUNICATION_ENABLED=true
```

#### **RabbitMQCommunicationService** (`rabbitmq_service.py`)

RabbitMQ implementation with queue-based reliability.

**Configuration:**
```bash
RABBITMQ_HOST=rabbitmq
RABBITMQ_PORT=5672
RABBITMQ_USER=guest
RABBITMQ_PASSWORD=guest
RABBITMQ_EXCHANGE=scrape-events
RABBITMQ_QUEUE=  # Optional, defaults to job-{job_id}
```

**Installation:**
```bash
pip install aio-pika
```

---

### 2. State Management (`state/`)

Manages job state and progress tracking with persistence and observation.

#### **JobState** (`job_state.py`)

Unified job state object with observer pattern for automatic synchronization.

**Features:**
- Observable state changes
- Automatic persistence to `job_state.json`
- Thread-safe with asyncio locks
- Property accessors for clean API

**Usage:**
```python
from src.crawler.state import JobState

job_state = JobState(job_id="123", base_path="/app/data/jobs")
await job_state.initialize()

# Register observer for auto-broadcasting
job_state.add_observer(lambda state: comm.send_state_update(state))

# Update state (automatically persists and notifies observers)
await job_state.set_status("running")
await job_state.set_total_urls(100)
await job_state.increment_completed()
```

#### **ProgressTracker** (`progress_tracker.py`)

Rate-limited progress tracking with background emission loop.

**Features:**
- Rate-limited updates (max 1/second)
- Background task for automatic emission
- Aggregates rapid state changes
- Thread-safe

**Usage:**
```python
from src.crawler.state import ProgressTracker

tracker = ProgressTracker(event_emitter=comm, emit_interval=1.0)
await tracker.start()

await tracker.set_stage("scraping")
await tracker.increment_completed()
await tracker.increment_requests()

summary = await tracker.get_summary()
await tracker.stop()
```

---

### 3. Storage Services (`storage/`)

Manages file storage, URL tracking, and job summaries.

#### **StorageManager** (`storage_manager.py`)

Centralized file I/O operations for job data with hash-based directories.

**Usage:**
```python
from src.crawler.storage import StorageManager

storage = StorageManager(job_id, base_path="/app/data/jobs")
hash_dir = storage.create_hash_directory(url_hash)
await storage.save_hash_json(url_hash, metadata)
await storage.save_hash_content(url_hash, markdown_content)
```

#### **URLTrackingManager** (`url_tracking_manager.py`)

Manages URL discovery and tracking with date metadata.

#### **SummaryManager** (`summary_manager.py`)

Generates and saves job summaries with statistics.

---

## Testing & Examples

- Examples: `examples/example_client.py`, `examples/new_architecture_example.py`
- Run examples in Docker: `docker compose run --rm crawler python examples/new_architecture_example.py`

---

**Version:** 1.0.0
