# Communication Refactoring Guide

## Overview

The communication layer has been refactored to be more modular, scalable, and maintainable. The new architecture separates concerns and allows easy switching between different communication methods (RabbitMQ or none).

## Key Changes

### 1. **Unified JobState Object**

Instead of managing state through a manager class, we now have a `JobState` object that:
- Represents the complete job state
- Automatically persists changes to disk
- Notifies observers (like communication services) when state changes
- Is thread-safe with asyncio locks

**Old Way (JobStateManager):**
```python
from services import JobStateManager

job_state_manager = JobStateManager(job_id, base_path="/app/shared")
await job_state_manager.initialize()
await job_state_manager.set_status("running")
await job_state_manager.increment_completed()
state = await job_state_manager.get_state()
```

**New Way (JobState):**
```python
from services import JobState

job_state = JobState(job_id, base_path="/app/shared")
await job_state.initialize()
await job_state.set_status("running")
await job_state.increment_completed()
state = await job_state.get_snapshot()
```

### 2. **Communication Factory Pattern**

Instead of manually instantiating clients, use the factory:

**New Way:**
```python
from services import CommunicationFactory

# Automatically creates the right service based on .env config
comm_service = CommunicationFactory.create(job_id)
if comm_service:
    await comm_service.connect()
```

### 3. **Unified Data Packets**

All events now send the complete job state instead of custom data structures:

**Old Way:**
```python
await event_emitter.emit("url_completed", {
    "url": url,
    "page_number": page_number,
    "files_created": files
})
```

**New Way:**
```python
# JobState is sent automatically via observer pattern
# Or manually:
await comm_service.send_state_update(await job_state.get_snapshot())

# For custom events with additional data:
await comm_service.send_url_completed(
    url, page_number, files,
    await job_state.get_snapshot()
)
```

### 4. **Observer Pattern for Auto-Broadcasting**

The JobState can automatically notify communication services:

```python
from services import JobState, CommunicationFactory

job_state = JobState(job_id)
await job_state.initialize()

# Create communication service
comm_service = CommunicationFactory.create(job_id)
if comm_service:
    await comm_service.connect()

    # Register as observer - state changes will auto-broadcast
    job_state.add_observer(
        lambda state: comm_service.send_state_update(state)
    )

# Now any state change automatically broadcasts
await job_state.set_status("running")  # Auto-broadcasts!
await job_state.increment_completed()  # Auto-broadcasts!
```

## Directory Structure

```
services/
├── __init__.py                      # Main exports
├── communication/                   # Communication services
│   ├── __init__.py
│   ├── interface.py                 # Abstract base class
│   ├── factory.py                   # Factory pattern
│   └── rabbitmq_service.py          # RabbitMQ implementation
├── state/                           # State management
│   ├── __init__.py
│   ├── job_state.py                 # Unified job state object
│   └── progress_tracker.py          # Progress tracking
├── storage/                         # Storage services
│   ├── __init__.py
│   ├── storage_manager.py           # File I/O
│   ├── url_tracking_manager.py      # URL tracking
│   └── summary_manager.py           # Job summaries
└── job_state_manager.py             # Legacy (backward compat)
```

## Configuration

### Environment Variables

```bash
# Communication method: "rabbitmq" or "none"
COMMUNICATION_METHOD=rabbitmq

# Enable/disable communication
COMMUNICATION_ENABLED=true

# RabbitMQ Configuration (requires: pip install aio-pika)
RABBITMQ_HOST=rabbitmq
RABBITMQ_PORT=5672
RABBITMQ_USER=guest
RABBITMQ_PASSWORD=guest
RABBITMQ_EXCHANGE=scrape-events
RABBITMQ_QUEUE=  # Optional, defaults to job-{job_id}
```

## Complete Example

### Basic Usage

```python
from services import JobState, CommunicationFactory

async def run_job(job_id: str):
    # Create job state
    job_state = JobState(job_id, base_path="/app/shared")
    await job_state.initialize()

    # Create communication service (based on .env config)
    comm_service = CommunicationFactory.create(job_id)

    if comm_service:
        # Connect
        connected = await comm_service.connect()
        if connected:
            # Register observer for auto-broadcasting
            async def broadcast_state(state):
                await comm_service.send_state_update(state)

            job_state.add_observer(broadcast_state)

    try:
        # Update state (automatically broadcasts if observer is set)
        await job_state.set_status("running")
        await job_state.set_total_urls(100)

        # Do work...
        for i in range(100):
            await process_url(url)
            await job_state.increment_completed()  # Auto-broadcasts!

        await job_state.set_status("completed")

    except Exception as e:
        await job_state.set_error(str(e))

    finally:
        if comm_service:
            await comm_service.disconnect()
```

### Advanced Usage with Custom Events

```python
# Send custom event with additional data
if comm_service:
    await comm_service.send_event("url_completed", {
        "url": "https://example.com",
        "page_number": 5,
        "files_created": ["file1.md", "file2.json"],
        "state": (await job_state.get_snapshot()).to_dict()
    })

    # Or use convenience method
    await comm_service.send_url_completed(
        url="https://example.com",
        page_number=5,
        files_created=["file1.md", "file2.json"],
        state=await job_state.get_snapshot()
    )
```

## Migration Path

### Step 1: Update Imports (Backward Compatible)

The old imports still work:
```python
from services import JobStateManager
```

But you can also use new imports:
```python
from services import CommunicationFactory, JobState
```

### Step 2: Replace JobStateManager with JobState

1. Find all `JobStateManager` instantiations
2. Replace with `JobState`
3. Update method calls (API is mostly the same)

### Step 3: Use CommunicationFactory

1. Create services with `CommunicationFactory.create(job_id)`
2. Remove manual messaging configuration (now in .env)

### Step 4: Add Observer Pattern (Optional)

For automatic state broadcasting, register communication service as observer.

## RabbitMQ Setup

### Installation

```bash
pip install aio-pika
```

### Docker Compose

```yaml
services:
  rabbitmq:
    image: rabbitmq:3-management
    ports:
      - "5672:5672"
      - "15672:15672"  # Management UI
    environment:
      RABBITMQ_DEFAULT_USER: guest
      RABBITMQ_DEFAULT_PASS: guest
    volumes:
      - rabbitmq_data:/var/lib/rabbitmq

volumes:
  rabbitmq_data:
```

### Configuration

```bash
COMMUNICATION_METHOD=rabbitmq
RABBITMQ_HOST=rabbitmq
RABBITMQ_PORT=5672
RABBITMQ_USER=guest
RABBITMQ_PASSWORD=guest
```

## Benefits

1. **Modularity**: Easy to add new communication methods (WebSockets, Kafka, etc.)
2. **Scalability**: RabbitMQ provides queue-based reliability
3. **Maintainability**: Clean separation of concerns
4. **Flexibility**: Switch communication methods via .env
5. **Reliability**: No lost messages with RabbitMQ queues
6. **Backward Compatible**: Old code continues to work

## Testing

### Test RabbitMQ
```python
from services import CommunicationFactory
import asyncio

async def test():
    comm = CommunicationFactory.create("test-job-123")
    await comm.connect()
    await comm.send_event("test", {"message": "Hello RabbitMQ!"})
    await comm.disconnect()

asyncio.run(test())
```

## Troubleshooting

### Import Errors
- Ensure `aio-pika` is installed for RabbitMQ
- Check `COMMUNICATION_METHOD` in .env

### Connection Failures
- Verify service is running (RabbitMQ)
- Check host/port configuration
- Review logs for connection errors

### No Messages Received
- Check subscribers are connected
- Verify exchange/queue configuration (RabbitMQ)
- Ensure routing keys match (RabbitMQ uses `job.{job_id}.{event}`)

## Next Steps

1. Update `main.py` to use new architecture
2. Update `crawler_service.py` to use JobState observer pattern
3. Test with RabbitMQ
4. Remove legacy code after migration is complete
