# Services Layer Documentation

## Overview

The services layer provides modular, scalable components for the crawler application. Services are organized into three main categories: **communication**, **state**, and **storage**.

## Directory Structure

```
services/
├── communication/          # Communication layer (Redis, RabbitMQ, etc.)
│   ├── interface.py        # CommunicationInterface (ABC)
│   ├── factory.py          # CommunicationFactory
│   ├── redis_service.py    # Redis Pub/Sub implementation
│   └── rabbitmq_service.py # RabbitMQ queue implementation
│
├── state/                  # State management
│   ├── job_state.py        # JobState (unified state object)
│   └── progress_tracker.py # ProgressTracker (rate-limited updates)
│
├── storage/                # Storage services
│   ├── storage_manager.py  # StorageManager (file I/O)
│   ├── url_tracking_manager.py  # URLTrackingManager (URL tracking)
│   └── summary_manager.py  # SummaryManager (job summaries)
│
├── __init__.py             # Main exports
├── redis_event_emitter.py  # Legacy Redis implementation
└── job_state_manager.py    # Legacy state manager
```

## Core Components

### 1. Communication Layer (`communication/`)

Provides flexible, pluggable communication services for broadcasting job events.

#### **CommunicationInterface** (`interface.py`)

Abstract base class that all communication implementations must follow.

**Key Methods:**
- `async connect() -> bool` - Establish connection
- `async disconnect()` - Close connection gracefully
- `async send_state_update(state: JobStateData) -> bool` - Send state update
- `async send_event(event_type: str, data: Dict) -> bool` - Send custom event

#### **CommunicationFactory** (`factory.py`)

Factory for creating communication service instances based on environment configuration.

**Usage:**
```python
from services import CommunicationFactory

comm = CommunicationFactory.create(job_id="123")
if comm:
    await comm.connect()
    await comm.send_state_update(job_state)
    await comm.disconnect()
```

**Configuration** (`.env`):
```bash
COMMUNICATION_METHOD=redis      # Options: redis, rabbitmq, none
COMMUNICATION_ENABLED=true
```

#### **RedisCommunicationService** (`redis_service.py`)

Redis Pub/Sub implementation for real-time event broadcasting.

**Features:**
- Fast, lightweight messaging
- Automatic reconnection
- Publisher confirms
- Graceful degradation

**Configuration:**
```bash
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=
REDIS_CHANNEL=scrape-events
```

#### **RabbitMQCommunicationService** (`rabbitmq_service.py`)

RabbitMQ implementation with queue-based reliability.

**Features:**
- Persistent messages (survive broker restart)
- Publisher confirms
- No message loss
- Job-specific queues
- Dead letter exchange support

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
from services import JobState

job_state = JobState(job_id="123", base_path="/app/data/jobs")
await job_state.initialize()

# Register observer for auto-broadcasting
job_state.add_observer(lambda state: comm.send_state_update(state))

# Update state (automatically persists and notifies observers)
await job_state.set_status("running")
await job_state.set_total_urls(100)
await job_state.increment_completed()
```

**JobStateData Structure:**
```python
@dataclass
class JobStateData:
    job_id: str
    status: str                    # pending, running, completed, failed
    total_urls: int
    completed_urls: int
    failed_urls: int
    started_at: Optional[str]
    updated_at: Optional[str]
    completed_at: Optional[str]
    current_url: Optional[str]
    output_directory: str
    error: Optional[str]
```

**Key Methods:**
- `await initialize()` - Initialize job directory and state file
- `await set_status(status)` - Update job status
- `await set_total_urls(total)` - Set total URL count
- `await increment_completed()` - Increment completed count
- `await increment_failed()` - Increment failed count
- `await set_error(error)` - Set error and mark as failed
- `await get_snapshot()` - Get current state snapshot
- `add_observer(observer)` - Register state change observer

#### **ProgressTracker** (`progress_tracker.py`)

Rate-limited progress tracking with background emission loop.

**Features:**
- Rate-limited updates (max 1/second)
- Background task for automatic emission
- Aggregates rapid state changes
- Thread-safe

**Usage:**
```python
from services import ProgressTracker

tracker = ProgressTracker(job_id, event_emitter, total_urls=100)
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

Centralized file I/O operations for job data.

**Features:**
- Hash-based directory structure
- Path traversal prevention
- Async file operations
- Image and file management

**Directory Structure:**
```
{job_id}/
└── {hash[0]}/
    └── {hash[1]}/
        └── {hash[2]}/
            └── {hash[3]}/
                └── {full_hash}/
                    ├── data.json
                    ├── content.md
                    ├── images/
                    └── files/
```

**Usage:**
```python
from services import StorageManager

storage = StorageManager(job_id, base_path="/app/data/jobs")
hash_dir = storage.create_hash_directory(url_hash)
await storage.save_hash_json(url_hash, metadata)
await storage.save_hash_content(url_hash, markdown_content)
```

#### **URLTrackingManager** (`url_tracking_manager.py`)

Manages URL discovery and tracking with date metadata.

**Features:**
- Chunked storage (2000 URLs per chunk)
- Duplicate detection
- Date tracking (sitemap, header dates)
- Status tracking per URL

**Usage:**
```python
from services import URLTrackingManager

tracker = URLTrackingManager(job_id)
await tracker.add_url(
    url="https://example.com",
    url_hash="abc123",
    sitemap_date="2025-01-01",
    status="pending"
)
url_info = await tracker.get_url("https://example.com")
await tracker.update_status(url, "completed")
```

#### **SummaryManager** (`summary_manager.py`)

Generates and saves job summaries with statistics.

**Summary Structure:**
```json
{
  "job_id": "123",
  "status": "completed",
  "timing": {
    "started_at": "...",
    "completed_at": "...",
    "duration_seconds": 300
  },
  "urls": {
    "total": 100,
    "completed": 98,
    "failed": 2,
    "success_rate": 98.0
  },
  "statistics": {
    "sessions": 10,
    "requests": 500,
    "errors": 15,
    "warnings": 25,
    "pdfs_downloaded": 20,
    "images_downloaded": 450
  }
}
```

**Usage:**
```python
from services import SummaryManager

summary_mgr = SummaryManager(job_id)
await summary_mgr.save_summary(
    status="completed",
    timing=timing_dict,
    urls=urls_dict,
    statistics=stats_dict
)
```

---

## Usage Patterns

### Pattern 1: Basic Job Execution

```python
from services import JobState, CommunicationFactory, StorageManager

async def run_job(job_id: str):
    # Initialize services
    job_state = JobState(job_id)
    await job_state.initialize()

    comm = CommunicationFactory.create(job_id)
    if comm:
        await comm.connect()

    storage = StorageManager(job_id)

    try:
        await job_state.set_status("running")

        # Do work...
        for url in urls:
            await process_url(url)
            await job_state.increment_completed()

            if comm:
                await comm.send_state_update(await job_state.get_snapshot())

        await job_state.set_status("completed")

    finally:
        if comm:
            await comm.disconnect()
```

### Pattern 2: Observer Pattern (Auto-broadcast)

```python
async def run_job_with_observer(job_id: str):
    job_state = JobState(job_id)
    await job_state.initialize()

    comm = CommunicationFactory.create(job_id)
    if comm:
        await comm.connect()

        # Register observer - state changes auto-broadcast
        async def broadcast(state):
            await comm.send_state_update(state)

        job_state.add_observer(broadcast)

    try:
        # Updates automatically broadcast
        await job_state.set_status("running")
        await job_state.increment_completed()  # Auto-broadcasts!

    finally:
        if comm:
            await comm.disconnect()
```

### Pattern 3: Complete Integration

```python
from services import (
    JobState, CommunicationFactory,
    ProgressTracker, StorageManager,
    URLTrackingManager, SummaryManager
)

async def full_crawl_job(job_id: str, urls: List[str]):
    # Initialize all services
    job_state = JobState(job_id)
    await job_state.initialize()

    comm = CommunicationFactory.create(job_id)
    if comm:
        await comm.connect()
        job_state.add_observer(lambda s: comm.send_state_update(s))

    storage = StorageManager(job_id)
    url_tracker = URLTrackingManager(job_id)
    progress = ProgressTracker(job_id, comm, total_urls=len(urls))
    await progress.start()

    try:
        await job_state.set_status("running")
        await job_state.set_total_urls(len(urls))

        for url in urls:
            # Process URL
            content = await fetch_url(url)
            url_hash = hashlib.sha256(url.encode()).hexdigest()

            # Save content
            await storage.save_hash_content(url_hash, content)

            # Track URL
            await url_tracker.update_status(url, "completed")

            # Update state
            await job_state.increment_completed()
            await progress.increment_completed()

        # Generate summary
        summary_mgr = SummaryManager(job_id)
        await summary_mgr.save_summary(
            status="completed",
            timing={"duration_seconds": 300},
            urls={"total": len(urls), "completed": len(urls)},
            statistics=await progress.get_summary()
        )

        await job_state.set_status("completed")

    except Exception as e:
        await job_state.set_error(str(e))

    finally:
        await progress.stop()
        if comm:
            await comm.disconnect()
```

---

## Legacy Components

For backward compatibility, the following legacy components are still available:

### **RedisEventEmitter** (`redis_event_emitter.py`)

Legacy Redis implementation. Use `CommunicationFactory` instead.

```python
# Old way (still works)
from services import RedisEventEmitter
emitter = RedisEventEmitter(job_id, redis_host="redis")
await emitter.connect()

# New way (recommended)
from services import CommunicationFactory
comm = CommunicationFactory.create(job_id)
await comm.connect()
```

### **JobStateManager** (`job_state_manager.py`)

Legacy state manager. Use `JobState` instead.

```python
# Old way (still works)
from services import JobStateManager
manager = JobStateManager(job_id)
await manager.initialize()

# New way (recommended)
from services import JobState
job_state = JobState(job_id)
await job_state.initialize()
```

---

## Testing

### Run Test Suite

```bash
# In Docker (recommended)
docker-compose run web python test_new_architecture.py

# Locally (requires dependencies)
python3 test_new_architecture.py
```

### Run Examples

```bash
docker-compose run web python examples/new_architecture_example.py
```

---

## Documentation

- **REFACTORING_GUIDE.md** - Detailed migration guide
- **REFACTORING_SUMMARY.md** - High-level overview
- **examples/new_architecture_example.py** - Usage examples

---

## Support

For questions or issues:
1. Review documentation files
2. Check examples directory
3. Run test suite to verify setup
4. Check environment variables

---

**Version:** 1.0.0
**Last Updated:** 2025-12-03
