import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from hawki_crawler.common.job_schema import CrawlJob
from hawki_crawler.crawler.communication.producer_service import publish_crawl_job
from hawki_crawler.crawler.communication.rabbit_producer import RabbitMQProducer, RabbitProducerConfig


class FakeExchange:
    def __init__(self, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.last_publish = None

    async def publish(self, message, routing_key: str, mandatory: bool) -> None:
        if self.should_fail:
            raise RuntimeError("forced publish failure")
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


def _config() -> RabbitProducerConfig:
    return RabbitProducerConfig(
        host="rabbitmq",
        port=5672,
        user="guest",
        password="guest",
        vhost="/",
        heartbeat=30,
        connection_timeout=30,
        exchange="jobs",
        exchange_type="direct",
        main_routing_key="crawl",
        publisher_confirms=True,
        persistent_messages=True,
        mandatory_publish=True,
        job_schema_version="1",
        job_source="crawler",
        default_max_retries=3,
    )


@pytest.mark.asyncio
async def test_publish_success() -> None:
    exchange = FakeExchange()
    channel = FakeChannel(exchange)
    connection = FakeConnection(channel)
    fake_aio_pika = FakeAioPika(connection)
    producer = RabbitMQProducer(config=_config())
    producer._load_aio_pika = lambda: fake_aio_pika

    job = CrawlJob(
        job_id=uuid4(),
        schema_version="1",
        url="https://example.com",
        created_at=datetime.now(timezone.utc),
        trace_id="trace-1",
    )
    result = await producer.publish_job(job)

    assert result.success is True
    assert result.job_id == job.job_id
    assert result.routing_key == "crawl"
    assert connection.publisher_confirms is True
    assert channel.declared == {"name": "jobs", "type": "direct", "durable": True}
    assert exchange.last_publish is not None

    message_payload = json.loads(exchange.last_publish["message"].kwargs["body"].decode("utf-8"))
    assert message_payload["job_id"] == str(job.job_id)
    assert message_payload["url"] == "https://example.com"


@pytest.mark.asyncio
async def test_publish_failure_returns_explicit_failure() -> None:
    exchange = FakeExchange(should_fail=True)
    channel = FakeChannel(exchange)
    connection = FakeConnection(channel)
    fake_aio_pika = FakeAioPika(connection)
    producer = RabbitMQProducer(config=_config())
    producer._load_aio_pika = lambda: fake_aio_pika

    job = CrawlJob(
        job_id=uuid4(),
        schema_version="1",
        url="https://example.com/fail",
        created_at=datetime.now(timezone.utc),
    )
    result = await producer.publish_job(job)

    assert result.success is False
    assert result.job_id == job.job_id
    assert "forced publish failure" in (result.error or "")


def test_serialization_produces_json_safe_payload() -> None:
    producer = RabbitMQProducer(config=_config())
    job = CrawlJob(
        job_id=uuid4(),
        schema_version="1",
        url="https://example.com/serialize",
        created_at=datetime.now(timezone.utc),
        payload={"scheduled_for": datetime(2026, 1, 1, tzinfo=timezone.utc)},
    )

    serialized = producer._serialize_job(job)
    payload = json.loads(serialized.decode("utf-8"))

    assert payload["url"] == "https://example.com/serialize"
    assert isinstance(payload["payload"]["scheduled_for"], str)


def test_env_configuration_loading(monkeypatch) -> None:
    monkeypatch.setenv("RABBITMQ_HOST", "mq.internal")
    monkeypatch.setenv("RABBITMQ_PORT", "5673")
    monkeypatch.setenv("RABBITMQ_USER", "app")
    monkeypatch.setenv("RABBITMQ_PASSWORD", "secret")
    monkeypatch.setenv("RABBITMQ_VHOST", "/prod")
    monkeypatch.setenv("RABBITMQ_HEARTBEAT", "15")
    monkeypatch.setenv("RABBITMQ_CONNECTION_TIMEOUT", "20")
    monkeypatch.setenv("RABBITMQ_EXCHANGE", "crawl_jobs")
    monkeypatch.setenv("RABBITMQ_EXCHANGE_TYPE", "direct")
    monkeypatch.setenv("RABBITMQ_MAIN_ROUTING_KEY", "crawl.submit")
    monkeypatch.setenv("RABBITMQ_PUBLISHER_CONFIRMS", "false")
    monkeypatch.setenv("RABBITMQ_PERSISTENT_MESSAGES", "true")
    monkeypatch.setenv("RABBITMQ_MANDATORY_PUBLISH", "false")
    monkeypatch.setenv("JOB_SCHEMA_VERSION", "2")
    monkeypatch.setenv("JOB_SOURCE", "crawler-api")
    monkeypatch.setenv("JOB_DEFAULT_MAX_RETRIES", "5")

    cfg = RabbitProducerConfig.from_env()

    assert cfg.host == "mq.internal"
    assert cfg.port == 5673
    assert cfg.user == "app"
    assert cfg.vhost == "/prod"
    assert cfg.heartbeat == 15
    assert cfg.connection_timeout == 20
    assert cfg.exchange == "crawl_jobs"
    assert cfg.main_routing_key == "crawl.submit"
    assert cfg.publisher_confirms is False
    assert cfg.persistent_messages is True
    assert cfg.mandatory_publish is False
    assert cfg.job_schema_version == "2"
    assert cfg.job_source == "crawler-api"
    assert cfg.default_max_retries == 5


@pytest.mark.asyncio
async def test_publish_crawl_job_helper_applies_schema_metadata() -> None:
    exchange = FakeExchange()
    channel = FakeChannel(exchange)
    connection = FakeConnection(channel)
    fake_aio_pika = FakeAioPika(connection)
    cfg = _config()
    cfg = RabbitProducerConfig(
        **{**cfg.__dict__, "job_schema_version": "3", "job_source": "crawler-service", "default_max_retries": 7}
    )
    producer = RabbitMQProducer(config=cfg)
    producer._load_aio_pika = lambda: fake_aio_pika

    result = await publish_crawl_job(
        url="https://example.com/new",
        payload={"depth": 2},
        trace_id="trace-helper",
        producer=producer,
    )

    assert result.success is True
    assert result.job_id is not None
    assert UUID(str(result.job_id))
    published = json.loads(exchange.last_publish["message"].kwargs["body"].decode("utf-8"))
    assert published["schema_version"] == "3"
    assert published["source"] == "crawler-service"
    assert published["max_retries"] == 7
    assert published["trace_id"] == "trace-helper"
    assert published["payload"] == {"depth": 2}

