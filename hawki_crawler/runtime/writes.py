"""One write fence shared by artifact, progress, sitemap and logging paths.

File operations are synchronous inside short critical sections: cancellation
cannot abandon executor-thread writes after the owning task has terminated.
"""

import builtins
import fcntl
import json
from contextlib import contextmanager
from pathlib import Path

from .scope import current_scope


class AdmissionClosed(RuntimeError):
    pass


def assert_writable(path=None):
    scope = current_scope.get()
    if scope and scope.closed:
        raise AdmissionClosed("Job scope has drained")
    if path is None:
        path = scope.root if scope else None
    if path is None:
        return
    path = Path(path).absolute()
    if scope and not path.resolve().is_relative_to(Path(scope.root).resolve()):
        raise AdmissionClosed("Artifact write escapes the current job root")
    if scope and scope.receipt_path:
        return _check_receipt(scope.receipt_path, path)
    resolved = path.resolve()
    for root in (path, *path.parents, resolved, *resolved.parents):
        directory = root / ".crawler-runtime"
        if not directory.is_dir():
            continue
        for record in directory.glob("*.json"):
            state = json.loads(record.read_text())
            if path.is_relative_to(
                Path(state["output_directory"])
            ) or resolved.is_relative_to(Path(state["output_directory"])):
                return _check_receipt(record, path)
        raise AdmissionClosed("Job has no durable writer admission")


def _check_receipt(record, path):
    state = json.loads(record.read_text())
    root = Path(state["output_directory"])
    if root.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise AdmissionClosed("Artifact path escapes its job root")
    if state["writer_admission_closed"] or state["sealed"]:
        raise AdmissionClosed("Job is permanently sealed")
    return record.with_suffix(".writers.lock")


@contextmanager
def writer_lease(path):
    lock_path = assert_writable(path)
    if lock_path is None:
        yield
        return
    with lock_path.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_SH)
        assert_writable(path)
        yield


@contextmanager
def open_sync(path, mode="r", **kwargs):
    with writer_lease(path):
        with builtins.open(path, mode, **kwargs) as stream:
            yield stream


class AsyncFile:
    def __init__(self, path, mode="r", **kwargs):
        self.path, self.mode, self.kwargs = path, mode, kwargs
        self.scope = current_scope.get()

    async def __aenter__(self):
        self.lease = (
            writer_lease(self.path) if any(m in self.mode for m in "wax+") else None
        )
        if self.lease:
            self.lease.__enter__()
        try:
            self.stream = builtins.open(self.path, self.mode, **self.kwargs)
        except BaseException:
            if self.lease:
                self.lease.__exit__(None, None, None)
            raise
        if self.scope:
            self.scope.files.add(self)
        return self

    async def write(self, data):
        assert_writable(self.path)
        return self.stream.write(data)

    async def read(self, *args):
        return self.stream.read(*args)

    def close(self):
        try:
            self.stream.close()
        finally:
            if self.scope:
                self.scope.files.discard(self)
            if self.lease:
                self.lease.__exit__(None, None, None)
                self.lease = None

    async def __aexit__(self, *args):
        self.close()


def mkdir(path, **kwargs):
    with writer_lease(path):
        Path(path).mkdir(**kwargs)


def unlink(path):
    with writer_lease(path):
        Path(path).unlink()
