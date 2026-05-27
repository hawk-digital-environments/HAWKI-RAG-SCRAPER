"""Centralized logging configuration utilities."""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_KNOWN_CONTEXT_KEYS = {
    "job_id",
    "trace_id",
    "event",
    "url",
    "local_path",
    "exchange",
    "routing_key",
    "status",
    "stage",
}

_RESERVED_LOG_RECORD_KEYS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys())


def parse_log_level(value: str, default: int = logging.INFO) -> int:
    """Parse string log levels from environment values safely."""
    normalized = (value or "").strip().upper()
    if not normalized:
        return default
    if normalized in logging._nameToLevel:  # type: ignore[attr-defined]
        level = logging._nameToLevel[normalized]  # type: ignore[attr-defined]
        return level if isinstance(level, int) else default
    return default


class ContextFilter(logging.Filter):
    """Attach a compact context suffix to plain text logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        context_parts: list[str] = []
        for key in sorted(_KNOWN_CONTEXT_KEYS):
            value = getattr(record, key, None)
            if value not in (None, ""):
                context_parts.append(f"{key}={value}")
        record.context = f" [{' '.join(context_parts)}]" if context_parts else ""
        return True


class JsonFormatter(logging.Formatter):
    """Structured JSON formatter for container-friendly logs."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in _KNOWN_CONTEXT_KEYS:
            value = getattr(record, key, None)
            if value not in (None, ""):
                payload[key] = value

        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _RESERVED_LOG_RECORD_KEYS and key not in _KNOWN_CONTEXT_KEYS
        }
        if extras:
            payload["extra"] = extras

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=True)


class JobContextFilter(logging.Filter):
    """Ensure job file log records always carry the current job id."""

    def __init__(self, job_id: str) -> None:
        super().__init__()
        self.job_id = job_id

    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "job_id", None):
            record.job_id = self.job_id
        return True


def configure_job_file_logger(job_id: str, log_path: Path) -> logging.LoggerAdapter:
    """Attach the per-job crawler log file handler once and return its adapter."""
    logger = logging.getLogger(f"crawler.{job_id}")
    handler_name = f"job_error_file_{job_id}"
    for handler in logger.handlers:
        if getattr(handler, "name", "") == handler_name:
            return logging.LoggerAdapter(logger, {"job_id": job_id})

    handler = logging.FileHandler(log_path)
    handler.name = handler_name
    handler.setLevel(parse_log_level(os.getenv("JOB_LOG_FILE_LEVEL", "INFO"), logging.INFO))
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s [job_id=%(job_id)s]"
        )
    )
    handler.addFilter(JobContextFilter(job_id))
    logger.addHandler(handler)
    logger.propagate = True
    return logging.LoggerAdapter(logger, {"job_id": job_id})


def configure_logging() -> None:
    """Configure root logging once using environment variables."""
    level = parse_log_level(os.getenv("LOG_LEVEL", "INFO"))
    format_mode = os.getenv("LOG_FORMAT", "text").strip().lower()

    handler = logging.StreamHandler(sys.stdout)
    if format_mode == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.addFilter(ContextFilter())
        handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s%(context)s")
        )

    logging.basicConfig(level=level, handlers=[handler], force=True)
    logging.getLogger().setLevel(level)
