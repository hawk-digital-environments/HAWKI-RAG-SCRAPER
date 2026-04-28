"""RabbitMQ producer for pipeline events."""

from __future__ import annotations

import importlib
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError

from src.common.pipeline_events import FileDiscoveredEvent


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, str(default)).strip().lower()
    return raw in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class RabbitMQEventProducerConfig:
    """Environment-backed RabbitMQ producer configuration for pipeline events."""

    host: str
    port: int
    user: str
    password: str
    vhost: str
    heartbeat: int
    connection_timeout: int
    events_exchange: str
    events_exchange_type: str
    file_discovered_routing_key: str
    publisher_confirms: bool
    persistent_messages: bool
    mandatory_publish: bool

    @classmethod
    def from_env(cls) -> "RabbitMQEventProducerConfig":
        return cls(
            host=os.getenv("RABBITMQ_HOST", "localhost"),
            port=int(os.getenv("RABBITMQ_PORT", "5672")),
            user=os.getenv("RABBITMQ_USER", "guest"),
            password=os.getenv("RABBITMQ_PASSWORD", "guest"),
            vhost=os.getenv("RABBITMQ_VHOST", "/"),
            heartbeat=int(os.getenv("RABBITMQ_HEARTBEAT", "30")),
            connection_timeout=int(os.getenv("RABBITMQ_CONNECTION_TIMEOUT", "30")),
            events_exchange=os.getenv("RABBITMQ_EVENTS_EXCHANGE", "pipeline.events"),
            events_exchange_type=os.getenv("RABBITMQ_EVENTS_EXCHANGE_TYPE", "direct"),
            file_discovered_routing_key=os.getenv(
                "RABBITMQ_FILE_DISCOVERED_ROUTING_KEY", "scrape.file.discovered"
            ),
            publisher_confirms=_env_bool("RABBITMQ_PUBLISHER_CONFIRMS", True),
            persistent_messages=_env_bool("RABBITMQ_PERSISTENT_MESSAGES", True),
            mandatory_publish=_env_bool("RABBITMQ_MANDATORY_PUBLISH", True),
        )


class PipelinePublishResult(BaseModel):
    """Explicit publish result for pipeline event publishing."""

    model_config = ConfigDict(extra="forbid")

    success: bool
    event_id: Optional[UUID]
    job_id: Optional[UUID]
    event_type: str
    exchange: str
    routing_key: str
    mandatory: bool
    url: Optional[str] = None
    local_path: Optional[str] = None
    error: Optional[str] = None


class RabbitMQEventProducerError(RuntimeError):
    """Raised when producer setup fails before publish attempts."""


class RabbitMQEventProducer:
    """Async RabbitMQ producer for `FileDiscoveredEvent` events."""

    def __init__(
        self,
        config: Optional[RabbitMQEventProducerConfig] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.config = config or RabbitMQEventProducerConfig.from_env()
        self.logger = logger or logging.getLogger("rabbitmq_pipeline_producer")
        self._aio_pika: Any = None
        self._connection: Any = None
        self._channel: Any = None
        self._exchange: Any = None

    def _load_aio_pika(self) -> Any:
        try:
            return importlib.import_module("aio_pika")
        except ImportError as exc:
            raise RabbitMQEventProducerError(
                "aio-pika is not installed. Install it with: pip install aio-pika"
            ) from exc

    def _log_structured(
        self,
        level: int,
        event_name: str,
        event_id: Optional[UUID],
        job_id: Optional[UUID],
        url: Optional[str],
        local_path: Optional[str],
        trace_id: Optional[str] = None,
        **extra: Any,
    ) -> None:
        payload: dict[str, Any] = {
            "event": event_name,
            "event_id": str(event_id) if event_id else None,
            "job_id": str(job_id) if job_id else None,
            "url": url,
            "local_path": local_path,
            "exchange": self.config.events_exchange,
            "routing_key": self.config.file_discovered_routing_key,
            "trace_id": trace_id,
        }
        payload.update(extra)
        self.logger.log(level, json.dumps(payload, default=str, sort_keys=True))

    async def connect(self) -> None:
        """Connect robustly and declare the durable events exchange."""
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
            self.config.events_exchange,
            type=self.config.events_exchange_type,
            durable=True,
        )

    async def close(self) -> None:
        """Close channel and connection gracefully."""
        if self._channel and not getattr(self._channel, "is_closed", True):
            await self._channel.close()
        if self._connection and not getattr(self._connection, "is_closed", True):
            await self._connection.close()

    async def __aenter__(self) -> "RabbitMQEventProducer":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    @staticmethod
    def _serialize_event(event: FileDiscoveredEvent) -> bytes:
        return event.model_dump_json().encode("utf-8")

    async def publish_file_discovered(
        self, event: FileDiscoveredEvent | dict[str, Any]
    ) -> PipelinePublishResult:
        """Validate and publish a `scrape.file.discovered` event."""
        raw_event: dict[str, Any]
        if isinstance(event, FileDiscoveredEvent):
            raw_event = event.model_dump(mode="python")
        else:
            raw_event = event

        try:
            validated = FileDiscoveredEvent.model_validate(raw_event)
        except ValidationError as exc:
            raw_event_id = raw_event.get("event_id") if isinstance(raw_event, dict) else None
            raw_job_id = raw_event.get("job_id") if isinstance(raw_event, dict) else None
            event_id = None
            job_id = None
            try:
                if raw_event_id:
                    event_id = UUID(str(raw_event_id))
            except (TypeError, ValueError):
                event_id = None
            try:
                if raw_job_id:
                    job_id = UUID(str(raw_job_id))
            except (TypeError, ValueError):
                job_id = None
            url = raw_event.get("url") if isinstance(raw_event, dict) else None
            local_path = raw_event.get("local_path") if isinstance(raw_event, dict) else None
            trace_id = raw_event.get("trace_id") if isinstance(raw_event, dict) else None
            self._log_structured(
                logging.ERROR,
                "pipeline_publish_validation_failed",
                event_id=event_id,
                job_id=job_id,
                url=url,
                local_path=local_path,
                trace_id=trace_id,
                error=str(exc),
            )
            return PipelinePublishResult(
                success=False,
                event_id=event_id,
                job_id=job_id,
                event_type="scrape.file.discovered",
                exchange=self.config.events_exchange,
                routing_key=self.config.file_discovered_routing_key,
                mandatory=self.config.mandatory_publish,
                url=url,
                local_path=local_path,
                error=str(exc),
            )

        self._log_structured(
            logging.INFO,
            "pipeline_publish_attempt",
            event_id=validated.event_id,
            job_id=validated.job_id,
            url=validated.url,
            local_path=validated.local_path,
            trace_id=validated.trace_id,
        )

        try:
            await self.connect()
            body = self._serialize_event(validated)
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
                message_id=str(validated.event_id),
                type=validated.event_type,
            )
            await self._exchange.publish(
                message,
                routing_key=self.config.file_discovered_routing_key,
                mandatory=self.config.mandatory_publish,
            )
            self._log_structured(
                logging.INFO,
                "pipeline_publish_success",
                event_id=validated.event_id,
                job_id=validated.job_id,
                url=validated.url,
                local_path=validated.local_path,
                trace_id=validated.trace_id,
            )
            return PipelinePublishResult(
                success=True,
                event_id=validated.event_id,
                job_id=validated.job_id,
                event_type=validated.event_type,
                exchange=self.config.events_exchange,
                routing_key=self.config.file_discovered_routing_key,
                mandatory=self.config.mandatory_publish,
                url=validated.url,
                local_path=validated.local_path,
            )
        except Exception as exc:  # pragma: no cover - integration failure path
            self._log_structured(
                logging.ERROR,
                "pipeline_publish_failure",
                event_id=validated.event_id,
                job_id=validated.job_id,
                url=validated.url,
                local_path=validated.local_path,
                trace_id=validated.trace_id,
                error=str(exc),
            )
            return PipelinePublishResult(
                success=False,
                event_id=validated.event_id,
                job_id=validated.job_id,
                event_type=validated.event_type,
                exchange=self.config.events_exchange,
                routing_key=self.config.file_discovered_routing_key,
                mandatory=self.config.mandatory_publish,
                url=validated.url,
                local_path=validated.local_path,
                error=str(exc),
            )
