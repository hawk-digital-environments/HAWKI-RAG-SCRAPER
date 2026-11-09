"""Durable runtime receipts. Tombstones live outside the artifact directory."""

import fcntl
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

TERMINAL = {"completed", "failed", "cancelled"}
JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,190}$")


def now():
    return datetime.now(timezone.utc).isoformat()


def validate_job_id(job_id):
    if not JOB_ID.fullmatch(job_id):
        raise ValueError("Invalid job_id")
    return job_id


def atomic_json(path, body):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(body, stream, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


class RuntimeStore:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.directory = self.root / ".crawler-runtime"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.owner = (self.directory / "owner.lock").open("a+")
        try:
            fcntl.flock(self.owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.owner.close()
            raise RuntimeError(
                "DATA_PATH already has a crawler runtime owner"
            ) from None
        # Legacy artifact state is evidence of existence, never of drainage.
        for path in self.root.iterdir():
            if (
                path.is_dir()
                and JOB_ID.fullmatch(path.name)
                and (path / "job_state.json").is_file()
                and not self.path(path.name).exists()
            ):
                self.save(
                    dict(
                        job_id=path.name,
                        external_job_id=path.name,
                        status="unknown",
                        state="unknown",
                        message="Legacy job has no drainage receipt",
                        created_at=None,
                        started_at=None,
                        finished_at=None,
                        completed_at=None,
                        cancel_requested=False,
                        terminal=False,
                        sealed=False,
                        sealed_at=None,
                        quiescent=False,
                        writer_admission_closed=False,
                        output_directory=str(path),
                        metadata={},
                        fingerprint=None,
                    )
                )
        # A dead process is not evidence that all its external work drained.
        for record in self.records():
            if not record["sealed"]:
                record.update(
                    status="unknown",
                    state="unknown",
                    terminal=False,
                    message="Previous runtime did not prove drainage; reconciliation required",
                )
                self.save(record)

    def close(self):
        self.owner.close()

    def path(self, job_id):
        return self.directory / (validate_job_id(job_id) + ".json")

    def get(self, job_id):
        path = self.path(job_id)
        return json.loads(path.read_text()) if path.exists() else None

    def records(self):
        return [
            json.loads(p.read_text()) for p in sorted(self.directory.glob("*.json"))
        ]

    def save(self, record):
        atomic_json(self.path(record["job_id"]), record)

    def artifact_root(self, config):
        if config.output_dir == "output":
            return self.root / config.job_id
        supplied = Path(config.output_dir)
        if ".." in supplied.parts:
            raise ValueError("output_dir cannot contain parent traversal")
        if supplied.is_absolute() and not supplied.is_relative_to(self.root):
            for prefix in ("/shared", "/app/shared", "/var/www/html/shared"):
                if supplied.is_relative_to(prefix):
                    supplied = self.root / supplied.relative_to(prefix)
                    break
            else:
                raise ValueError("output_dir must be inside shared DATA_PATH")
        root = (self.root / supplied / config.job_id).resolve()
        if not root.is_relative_to(self.root) or root.is_relative_to(self.directory):
            raise ValueError("output_dir escapes the artifact area")
        return root

    def admit(self, config, limit):
        job_id = validate_job_id(config.job_id)
        payload = config.model_dump(mode="json")
        fingerprint = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()
        existing = self.get(job_id)
        if existing:
            if existing.get("fingerprint") != fingerprint:
                raise ValueError("job_id already belongs to a different request")
            return existing, False
        artifact_root = self.artifact_root(config)
        if artifact_root.exists():
            raise ValueError(
                "Existing legacy artifacts require reconciliation; use a new job_id"
            )
        for other in self.records():
            previous_root = Path(other["output_directory"])
            if artifact_root.is_relative_to(
                previous_root
            ) or previous_root.is_relative_to(artifact_root):
                raise ValueError(
                    "Artifact roots cannot overlap another permanent job identity"
                )
        if sum(not r["sealed"] for r in self.records()) >= limit:
            raise OverflowError("MAX_CONCURRENT_TASKS capacity exhausted")
        record = dict(
            job_id=job_id,
            external_job_id=job_id,
            status="pending",
            state="pending",
            message="Crawl job submitted",
            created_at=now(),
            started_at=None,
            finished_at=None,
            completed_at=None,
            cancel_requested=False,
            terminal=False,
            sealed=False,
            sealed_at=None,
            quiescent=False,
            writer_admission_closed=False,
            pages_crawled=0,
            total_pages=config.max_pages,
            output_directory=str(artifact_root),
            fingerprint=fingerprint,
            metadata={
                key: payload.get(key)
                for key in (
                    "source_id",
                    "source_url",
                    "generation",
                    "url_ingestion_operation_id",
                    "metadata",
                )
            },
        )
        self.save(record)
        return record, True

    def update(self, job_id, **values):
        record = self.get(job_id)
        if not record:
            raise KeyError(job_id)
        if record["sealed"]:
            raise ValueError("Job is permanently sealed")
        if record["cancel_requested"] and values.get("status") in {
            "pending",
            "running",
            "paused",
        }:
            raise ValueError("Cancellation cannot move backwards")
        record.update(values)
        if "status" in values:
            record["state"] = record["status"]
            record["terminal"] = record["status"] in TERMINAL
        self.save(record)
        return record

    def retire(self, job_id):
        record = self.get(job_id)
        if not record or not record["sealed"]:
            raise ValueError("Only sealed jobs may be retired")
        record.setdefault("retired_at", now())
        self.save(record)

    def seal(self, job_id, **values):
        record = self.get(job_id)
        if record["sealed"]:
            return record
        # Caller must have drained its scope before this irreversible operation.
        if values.get("status", record["status"]) not in TERMINAL:
            raise ValueError("Only a drained terminal job can be sealed")
        with self.path(job_id).with_suffix(".writers.lock").open("a+") as lock:
            # Never block the event loop behind an unconfirmed external writer.
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return self.update(
                job_id,
                **values,
                sealed=True,
                sealed_at=now(),
                quiescent=True,
                writer_admission_closed=True,
            )
