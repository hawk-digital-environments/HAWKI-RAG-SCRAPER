"""Service helpers for publishing crawl jobs through RabbitMQ."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from src.common.job_schema import CrawlJob

from .rabbit_producer import PublishResult, RabbitMQProducer, RabbitProducerConfig


def build_crawl_job(
    url: str,
    payload: Optional[dict[str, Any]] = None,
    trace_id: Optional[str] = None,
    config: Optional[RabbitProducerConfig] = None,
) -> CrawlJob:
    """Create a validated crawl job using shared schema defaults."""
    cfg = config or RabbitProducerConfig.from_env()
    return CrawlJob(
        job_id=uuid4(),
        schema_version=cfg.job_schema_version,
        url=url,
        source=cfg.job_source,
        created_at=datetime.now(timezone.utc),
        retry_count=0,
        max_retries=cfg.default_max_retries,
        trace_id=trace_id,
        payload=payload,
    )


async def publish_crawl_job(
    url: str,
    payload: Optional[dict[str, Any]] = None,
    trace_id: Optional[str] = None,
    producer: Optional[RabbitMQProducer] = None,
) -> PublishResult:
    """
    Build and publish a CrawlJob via RabbitMQ.

    This helper keeps producer logic transport-focused by separating job construction
    from connection and broker-specific publish mechanics.
    """
    managed_producer = producer or RabbitMQProducer()
    should_close = producer is None
    job = build_crawl_job(url=url, payload=payload, trace_id=trace_id, config=managed_producer.config)

    try:
        return await managed_producer.publish_job(job)
    finally:
        if should_close:
            await managed_producer.close()

