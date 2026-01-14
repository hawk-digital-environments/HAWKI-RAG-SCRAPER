"""
Example: Using the New Communication Architecture
==================================================

This example demonstrates how to use the refactored communication layer
with JobState and CommunicationFactory.

Key features:
1. JobState with observer pattern for auto-sync
2. CommunicationFactory for flexible communication method selection
3. Unified data packets based on JobState structure
4. Clean separation of concerns
"""

import asyncio
import os
from services import JobState, CommunicationFactory, StorageManager


async def example_basic_usage():
    """
    Basic example: Using JobState and CommunicationFactory
    """
    print("=== Basic Usage Example ===\n")

    job_id = "example-job-001"

    # 1. Create JobState
    job_state = JobState(job_id, base_path="/tmp/test_jobs")
    await job_state.initialize()
    print(f"✓ JobState initialized for job: {job_id}")

    # 2. Create communication service using factory
    # (automatically selects RabbitMQ or None based on .env)
    comm_service = CommunicationFactory.create(job_id)

    if comm_service:
        # 3. Connect to communication service
        connected = await comm_service.connect()
        if connected:
            print(f"✓ Connected to communication service")
        else:
            print("⚠ Communication service connection failed (continuing anyway)")
    else:
        print("ℹ No communication service configured")

    try:
        # 4. Update job state (persists to disk automatically)
        await job_state.set_status("running")
        await job_state.set_total_urls(10)
        print(f"✓ Job status set to 'running'")

        # 5. Send initial state update
        if comm_service:
            await comm_service.send_state_update(await job_state.get_snapshot())
            print(f"✓ Initial state broadcasted")

        # 6. Simulate processing URLs
        for i in range(1, 11):
            url = f"https://example.com/page-{i}"
            await job_state.set_current_url(url)

            # Simulate work
            await asyncio.sleep(0.1)

            # Update state
            await job_state.increment_completed()

            # Send state update
            if comm_service:
                await comm_service.send_state_update(await job_state.get_snapshot())

            print(f"  • Processed: {url} ({i}/10)")

        # 7. Mark job as completed
        await job_state.set_status("completed")
        if comm_service:
            await comm_service.send_state_update(await job_state.get_snapshot())

        print(f"\n✓ Job completed successfully")

        # 8. Show final state
        final_state = await job_state.get_dict()
        print(f"\nFinal State:")
        print(f"  Status: {final_state['status']}")
        print(f"  Total URLs: {final_state['total_urls']}")
        print(f"  Completed: {final_state['completed_urls']}")
        print(f"  Failed: {final_state['failed_urls']}")

    except Exception as e:
        print(f"\n✗ Error: {e}")
        await job_state.set_error(str(e))
        if comm_service:
            await comm_service.send_state_update(await job_state.get_snapshot())

    finally:
        # 9. Cleanup
        if comm_service:
            await comm_service.disconnect()
            print(f"\n✓ Communication service disconnected")


async def example_observer_pattern():
    """
    Advanced example: Using observer pattern for automatic broadcasting
    """
    print("\n\n=== Observer Pattern Example ===\n")

    job_id = "example-job-002"

    # 1. Create JobState
    job_state = JobState(job_id, base_path="/tmp/test_jobs")
    await job_state.initialize()

    # 2. Create communication service
    comm_service = CommunicationFactory.create(job_id)

    if comm_service:
        connected = await comm_service.connect()
        if connected:
            print(f"✓ Connected to communication service")

            # 3. Register observer for automatic broadcasting
            async def auto_broadcast(state):
                """This function is called automatically when state changes"""
                await comm_service.send_state_update(state)
                print(f"  → Auto-broadcasted state update (status={state.status}, completed={state.completed_urls})")

            job_state.add_observer(auto_broadcast)
            print(f"✓ Observer registered - state changes will auto-broadcast\n")
        else:
            print("⚠ Communication service connection failed\n")
    else:
        print("ℹ No communication service configured\n")

    try:
        # 4. Update state - automatically broadcasts via observer!
        print("Updating state (watch for auto-broadcast):")
        await job_state.set_status("running")
        await job_state.set_total_urls(5)

        for i in range(1, 6):
            url = f"https://example.com/page-{i}"
            await job_state.set_current_url(url)
            await asyncio.sleep(0.1)
            await job_state.increment_completed()
            print(f"  • Processed: {url}")

        await job_state.set_status("completed")
        print(f"\n✓ Job completed")

    finally:
        if comm_service:
            await comm_service.disconnect()
            print(f"✓ Disconnected")


async def example_custom_events():
    """
    Example: Sending custom events with additional data
    """
    print("\n\n=== Custom Events Example ===\n")

    job_id = "example-job-003"

    job_state = JobState(job_id, base_path="/tmp/test_jobs")
    await job_state.initialize()

    comm_service = CommunicationFactory.create(job_id)

    if comm_service:
        connected = await comm_service.connect()
        if connected:
            print(f"✓ Connected to communication service\n")

            # Send custom events with additional context
            await comm_service.send_event("sitemap_detected", {
                "sitemap_url": "https://example.com/sitemap.xml",
                "total_urls": 150
            })
            print(f"✓ Sent 'sitemap_detected' event")

            await comm_service.send_event("urls_discovered", {
                "urls_count": 150,
                "total_to_crawl": 150
            })
            print(f"✓ Sent 'urls_discovered' event")

            # Send URL completion with full state
            await job_state.set_status("running")
            await job_state.increment_completed()

            await comm_service.send_url_completed(
                url="https://example.com/page-1",
                page_number=1,
                files_created=["content.md", "data.json", "images/img1.jpg"],
                state=await job_state.get_snapshot()
            )
            print(f"✓ Sent 'url_completed' event with state")

            # Send job summary
            await comm_service.send_job_summary({
                "job_id": job_id,
                "status": "completed",
                "timing": {
                    "started_at": "2025-12-03T10:00:00Z",
                    "completed_at": "2025-12-03T10:05:00Z",
                    "duration_seconds": 300
                },
                "urls": {
                    "total": 150,
                    "completed": 148,
                    "failed": 2,
                    "success_rate": 98.67
                }
            })
            print(f"✓ Sent 'job_summary' event")

            await comm_service.disconnect()
            print(f"\n✓ All custom events sent successfully")
        else:
            print("⚠ Could not connect to communication service")
    else:
        print("ℹ No communication service configured")


async def example_error_handling():
    """
    Example: Proper error handling
    """
    print("\n\n=== Error Handling Example ===\n")

    job_id = "example-job-004"

    job_state = JobState(job_id, base_path="/tmp/test_jobs")
    await job_state.initialize()

    comm_service = CommunicationFactory.create(job_id)

    if comm_service:
        connected = await comm_service.connect()
        if connected:
            print(f"✓ Connected\n")
        else:
            print("⚠ Connection failed, but continuing...\n")

    try:
        await job_state.set_status("running")
        await job_state.set_total_urls(5)

        # Simulate an error on the 3rd URL
        for i in range(1, 6):
            url = f"https://example.com/page-{i}"
            await job_state.set_current_url(url)

            if i == 3:
                # Simulate error
                error_msg = "Connection timeout while fetching page"
                print(f"  ✗ Error on {url}: {error_msg}")
                await job_state.increment_failed()

                # Send state update with error context
                if comm_service:
                    await comm_service.send_event("url_failed", {
                        "url": url,
                        "error": error_msg,
                        "state": (await job_state.get_snapshot()).to_dict()
                    })
            else:
                print(f"  ✓ Processed {url}")
                await job_state.increment_completed()

            if comm_service:
                await comm_service.send_state_update(await job_state.get_snapshot())

        # Complete with partial success
        await job_state.set_status("completed")
        print(f"\n✓ Job completed with {await job_state.completed_urls} successes and {await job_state.failed_urls} failures")

    except Exception as e:
        print(f"\n✗ Fatal error: {e}")
        await job_state.set_error(str(e))
        if comm_service:
            await comm_service.send_state_update(await job_state.get_snapshot())

    finally:
        if comm_service:
            await comm_service.disconnect()


async def main():
    """Run all examples"""
    print("=" * 60)
    print("NEW COMMUNICATION ARCHITECTURE EXAMPLES")
    print("=" * 60)

    # Check configuration
    comm_method = os.getenv("COMMUNICATION_METHOD", "none")
    comm_enabled = os.getenv("COMMUNICATION_ENABLED", "true").lower() == "true"

    print(f"\nConfiguration:")
    print(f"  COMMUNICATION_METHOD: {comm_method}")
    print(f"  COMMUNICATION_ENABLED: {comm_enabled}")

    if comm_method == "rabbitmq":
        rabbitmq_host = os.getenv("RABBITMQ_HOST")
        print(f"  RABBITMQ_HOST: {rabbitmq_host}")

    print("\n" + "=" * 60 + "\n")

    # Run examples
    await example_basic_usage()
    await example_observer_pattern()
    await example_custom_events()
    await example_error_handling()

    print("\n" + "=" * 60)
    print("ALL EXAMPLES COMPLETED")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
