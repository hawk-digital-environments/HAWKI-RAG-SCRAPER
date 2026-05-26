import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from hawki_crawler.common.pipeline_events import FileDiscoveredEvent
from hawki_crawler.crawler.communication.pipeline_event_producer import (
    RabbitMQEventProducer,
    RabbitMQEventProducerConfig,
)


class FakeExchange:
    def __init__(self, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.last_publish = None

    async def publish(self, message, routing_key: str, mandatory: bool) -> None:
        if self.should_fail:
            raise RuntimeError("forced pipeline publish failure")
        self.last_publish = {
            "message": message,
            "routing_key": routing_key,
            "mandatory": mandatory,
        }


class FakeChannel:
    def __init__(self, exchange: FakeExchange) -> None:
        self.exchange = exchange
        self.is_closed = False
        self.declared = None

    async def declare_exchange(self, name: str, type: str, durable: bool):
        self.declared = {"name": name, "type": type, "durable": durable}
        return self.exchange

    async def close(self) -> None:
        self.is_closed = True


class FakeConnection:
    def __init__(self, channel: FakeChannel) -> None:
        self._channel = channel
        self.is_closed = False
        self.publisher_confirms = None

    async def channel(self, publisher_confirms: bool):
        self.publisher_confirms = publisher_confirms
        return self._channel

    async def close(self) -> None:
        self.is_closed = True


class FakeDeliveryMode:
    PERSISTENT = 2
    NOT_PERSISTENT = 1


class FakeMessage:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs


class FakeAioPika:
    DeliveryMode = FakeDeliveryMode
    Message = FakeMessage

    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self.connect_kwargs = None

    async def connect_robust(self, **kwargs):
        self.connect_kwargs = kwargs
        return self.connection


def _config() -> RabbitMQEventProducerConfig:
    return RabbitMQEventProducerConfig(
        host="rabbitmq",
        port=5672,
        user="guest",
        password="guest",
        vhost="/",
        heartbeat=30,
        connection_timeout=30,
        events_exchange="pipeline.events",
        events_exchange_type="direct",
        file_discovered_routing_key="scrape.file.discovered",
        publisher_confirms=True,
        persistent_messages=True,
        mandatory_publish=True,
    )


def _event() -> FileDiscoveredEvent:
    return FileDiscoveredEvent(
        event_id=uuid4(),
        job_id=uuid4(),
        schema_version="1",
        event_type="scrape.file.discovered",
        source="scraper",
        url="https://example.com/files/sample.pdf",
        page_url="https://example.com/page",
        local_path="/app/shared/sample/files/sample.pdf",
        relative_path="files/sample.pdf",
        filename="sample.pdf",
        extension="pdf",
        content_type="application/pdf",
        file_size_bytes=123,
        checksum_sha256="abc123",
        discovered_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_pipeline_publish_success() -> None:
    exchange = FakeExchange()
    channel = FakeChannel(exchange)
    connection = FakeConnection(channel)
    fake_aio_pika = FakeAioPika(connection)
    producer = RabbitMQEventProducer(config=_config())
    producer._load_aio_pika = lambda: fake_aio_pika

    result = await producer.publish_file_discovered(_event())

    assert result.success is True
    assert result.routing_key == "scrape.file.discovered"
    assert connection.publisher_confirms is True
    assert channel.declared == {"name": "pipeline.events", "type": "direct", "durable": True}
    payload = json.loads(exchange.last_publish["message"].kwargs["body"].decode("utf-8"))
    assert payload["event_type"] == "scrape.file.discovered"
    assert payload["filename"] == "sample.pdf"


@pytest.mark.asyncio
async def test_pipeline_publish_failure_returns_explicit_failure() -> None:
    exchange = FakeExchange(should_fail=True)
    channel = FakeChannel(exchange)
    connection = FakeConnection(channel)
    fake_aio_pika = FakeAioPika(connection)
    producer = RabbitMQEventProducer(config=_config())
    producer._load_aio_pika = lambda: fake_aio_pika

    result = await producer.publish_file_discovered(_event())

    assert result.success is False
    assert "forced pipeline publish failure" in (result.error or "")


def test_pipeline_producer_env_configuration_loading(monkeypatch) -> None:
    monkeypatch.setenv("RABBITMQ_HOST", "mq.internal")
    monkeypatch.setenv("RABBITMQ_PORT", "5673")
    monkeypatch.setenv("RABBITMQ_USER", "app")
    monkeypatch.setenv("RABBITMQ_PASSWORD", "secret")
    monkeypatch.setenv("RABBITMQ_VHOST", "/prod")
    monkeypatch.setenv("RABBITMQ_HEARTBEAT", "15")
    monkeypatch.setenv("RABBITMQ_CONNECTION_TIMEOUT", "20")
    monkeypatch.setenv("RABBITMQ_EVENTS_EXCHANGE", "pipeline.events")
    monkeypatch.setenv("RABBITMQ_EVENTS_EXCHANGE_TYPE", "direct")
    monkeypatch.setenv("RABBITMQ_FILE_DISCOVERED_ROUTING_KEY", "scrape.file.discovered")
    monkeypatch.setenv("RABBITMQ_PUBLISHER_CONFIRMS", "false")
    monkeypatch.setenv("RABBITMQ_PERSISTENT_MESSAGES", "true")
    monkeypatch.setenv("RABBITMQ_MANDATORY_PUBLISH", "false")

    cfg = RabbitMQEventProducerConfig.from_env()

    assert cfg.host == "mq.internal"
    assert cfg.port == 5673
    assert cfg.user == "app"
    assert cfg.vhost == "/prod"
    assert cfg.heartbeat == 15
    assert cfg.connection_timeout == 20
    assert cfg.events_exchange == "pipeline.events"
    assert cfg.events_exchange_type == "direct"
    assert cfg.file_discovered_routing_key == "scrape.file.discovered"
    assert cfg.publisher_confirms is False
    assert cfg.persistent_messages is True
    assert cfg.mandatory_publish is False
