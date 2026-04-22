"""RabbitMQ transport-focused producer for crawl jobs."""

from __future__ import annotations

import importlib
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError

from src.common.job_schema import CrawlJob


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, str(default)).strip().lower()
    return raw in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class RabbitProducerConfig:
    """Environment-backed RabbitMQ producer configuration."""

    host: str
    port: int
    user: str
    password: str
    vhost: str
    heartbeat: int
    connection_timeout: int
    exchange: str
    exchange_type: str
    main_routing_key: str
    publisher_confirms: bool
    persistent_messages: bool
    mandatory_publish: bool
    job_schema_version: str
    job_source: str
    default_max_retries: int

    @classmethod
    def from_env(cls) -> "RabbitProducerConfig":
        return cls(
            host=os.getenv("RABBITMQ_HOST", "localhost"),
            port=int(os.getenv("RABBITMQ_PORT", "5672")),
            user=os.getenv("RABBITMQ_USER", "guest"),
            password=os.getenv("RABBITMQ_PASSWORD", "guest"),
            vhost=os.getenv("RABBITMQ_VHOST", "/"),
            heartbeat=int(os.getenv("RABBITMQ_HEARTBEAT", "30")),
            connection_timeout=int(os.getenv("RABBITMQ_CONNECTION_TIMEOUT", "30")),
            exchange=os.getenv("RABBITMQ_EXCHANGE", "jobs"),
            exchange_type=os.getenv("RABBITMQ_EXCHANGE_TYPE", "direct"),
            main_routing_key=os.getenv("RABBITMQ_MAIN_ROUTING_KEY", "crawl"),
            publisher_confirms=_env_bool("RABBITMQ_PUBLISHER_CONFIRMS", True),
            persistent_messages=_env_bool("RABBITMQ_PERSISTENT_MESSAGES", True),
            mandatory_publish=_env_bool("RABBITMQ_MANDATORY_PUBLISH", True),
            job_schema_version=os.getenv("JOB_SCHEMA_VERSION", "1"),
            job_source=os.getenv("JOB_SOURCE", "crawler"),
            default_max_retries=int(os.getenv("JOB_DEFAULT_MAX_RETRIES", "3")),
        )


class PublishResult(BaseModel):
    """Result contract for a RabbitMQ publish attempt."""

    model_config = ConfigDict(extra="forbid")

    success: bool
    job_id: Optional[UUID]
    url: Optional[str]
    exchange: str
    routing_key: str
    mandatory: bool
    trace_id: Optional[str] = None
    error: Optional[str] = None
    broker_message_id: Optional[str] = None


class RabbitProducerError(RuntimeError):
    """Raised when producer setup fails before a publish attempt."""


class RabbitMQProducer:
    """Small async RabbitMQ producer with explicit validation and result reporting."""

    def __init__(
        self,
        config: Optional[RabbitProducerConfig] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.config = config or RabbitProducerConfig.from_env()
        self.logger = logger or logging.getLogger("rabbitmq_producer")
        self._aio_pika: Any = None
        self._connection: Any = None
        self._channel: Any = None
        self._exchange: Any = None

    def _load_aio_pika(self) -> Any:
        try:
            return importlib.import_module("aio_pika")
        except ImportError as exc:
            raise RabbitProducerError(
                "aio-pika is not installed. Install it with: pip install aio-pika"
            ) from exc

    def _log_structured(
        self,
        level: int,
        event: str,
        job_id: Optional[UUID],
        url: Optional[str],
        trace_id: Optional[str],
        **extra: Any,
    ) -> None:
        payload: dict[str, Any] = {
            "event": event,
            "job_id": str(job_id) if job_id else None,
            "url": url,
            "exchange": self.config.exchange,
            "routing_key": self.config.main_routing_key,
            "trace_id": trace_id,
        }
        payload.update(extra)
        self.logger.log(level, json.dumps(payload, default=str, sort_keys=True))

    async def connect(self) -> None:
        """Establish robust broker connection and declare exchange."""
        if self._connection and not getattr(self._connection, "is_closed", True):
            return

        self._aio_pika = self._load_aio_pika()
        self._connection = await self._aio_pika.connect_robust(
            host=self.config.host,
            port=self.config.port,
            login=self.config.user,
            password=self.config.password,
            virtualhost=self.config.vhost,
            heartbeat=self.config.heartbeat,
            timeout=self.config.connection_timeout,
        )
        self._channel = await self._connection.channel(
            publisher_confirms=self.config.publisher_confirms
        )
        self._exchange = await self._channel.declare_exchange(
            self.config.exchange,
            type=self.config.exchange_type,
            durable=True,
        )

    async def close(self) -> None:
        """Close producer resources gracefully."""
        if self._channel and not getattr(self._channel, "is_closed", True):
            await self._channel.close()
        if self._connection and not getattr(self._connection, "is_closed", True):
            await self._connection.close()

    async def __aenter__(self) -> "RabbitMQProducer":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    @staticmethod
    def _serialize_job(job: CrawlJob) -> bytes:
        return job.model_dump_json().encode("utf-8")

    async def publish_job(self, job: CrawlJob | dict[str, Any]) -> PublishResult:
        """
        Validate and publish a crawl job as a persistent JSON message.

        Failures return explicit failure state; no publish-level retries are performed.
        """
        raw_job: dict[str, Any]
        if isinstance(job, CrawlJob):
            raw_job = job.model_dump(mode="python")
        else:
            raw_job = job

        try:
            validated_job = CrawlJob.model_validate(raw_job)
        except ValidationError as exc:
            raw_job_id = raw_job.get("job_id") if isinstance(raw_job, dict) else None
            url = raw_job.get("url") if isinstance(raw_job, dict) else None
            trace_id = raw_job.get("trace_id") if isinstance(raw_job, dict) else None
            job_id = None
            if raw_job_id:
                try:
                    job_id = UUID(str(raw_job_id))
                except (TypeError, ValueError):
                    job_id = None
            self._log_structured(
                logging.ERROR,
                "publish_validation_failed",
                job_id=job_id,
                url=url,
                trace_id=trace_id,
                error=str(exc),
            )
            return PublishResult(
                success=False,
                job_id=job_id,
                url=url,
                exchange=self.config.exchange,
                routing_key=self.config.main_routing_key,
                mandatory=self.config.mandatory_publish,
                trace_id=trace_id,
                error=str(exc),
            )

        self._log_structured(
            logging.INFO,
            "publish_attempt",
            job_id=validated_job.job_id,
            url=validated_job.url,
            trace_id=validated_job.trace_id,
        )

        try:
            await self.connect()
            body = self._serialize_job(validated_job)

            delivery_mode = (
                self._aio_pika.DeliveryMode.PERSISTENT
                if self.config.persistent_messages
                else self._aio_pika.DeliveryMode.NOT_PERSISTENT
            )
            message = self._aio_pika.Message(
                body=body,
                delivery_mode=delivery_mode,
                content_type="application/json",
                content_encoding="utf-8",
                message_id=str(validated_job.job_id),
            )

            await self._exchange.publish(
                message,
                routing_key=self.config.main_routing_key,
                mandatory=self.config.mandatory_publish,
            )

            self._log_structured(
                logging.INFO,
                "publish_success",
                job_id=validated_job.job_id,
                url=validated_job.url,
                trace_id=validated_job.trace_id,
            )
            return PublishResult(
                success=True,
                job_id=validated_job.job_id,
                url=validated_job.url,
                exchange=self.config.exchange,
                routing_key=self.config.main_routing_key,
                mandatory=self.config.mandatory_publish,
                trace_id=validated_job.trace_id,
                broker_message_id=str(validated_job.job_id),
            )
        except Exception as exc:
            self._log_structured(
                logging.ERROR,
                "publish_failure",
                job_id=validated_job.job_id,
                url=validated_job.url,
                trace_id=validated_job.trace_id,
                error=str(exc),
            )
            return PublishResult(
                success=False,
                job_id=validated_job.job_id,
                url=validated_job.url,
                exchange=self.config.exchange,
                routing_key=self.config.main_routing_key,
                mandatory=self.config.mandatory_publish,
                trace_id=validated_job.trace_id,
                error=str(exc),
            )
