"""Own all asyncio child work and safe HTTP sessions before issuing a receipt."""

import asyncio
from contextvars import ContextVar, copy_context

current_scope = ContextVar("crawler_scope", default=None)


def install_task_tracking(loop):
    previous = loop.get_task_factory()
    if getattr(previous, "_crawler_tracking", False):
        return

    def factory(loop, coro, **kwargs):
        context = kwargs.get("context")
        if context is None:
            context = copy_context()
        scope = context.get(current_scope)
        if scope and scope.closed:
            coro.close()
            raise RuntimeError("Job task admission is closed")
        task = (
            previous(loop, coro, **kwargs)
            if previous
            else asyncio.Task(coro, loop=loop, **kwargs)
        )
        if scope:
            scope.tasks.add(task)
        return task

    factory._crawler_tracking = True
    loop.set_task_factory(factory)
    original_call_at = loop.call_at
    original_call_later = loop.call_later
    scheduling = False

    def schedule(method, when, callback, *args, context=None):
        nonlocal scheduling
        # asyncio and uvloop delegate between these methods differently.
        if scheduling:
            return method(when, callback, *args, context=context)
        context = context if context is not None else copy_context()
        scope = context.get(current_scope)
        if scope and scope.closed:
            raise RuntimeError("Job delayed-work admission is closed")

        def run():
            scope.handles.discard(handle)
            if not scope.closed:
                callback(*args)

        scheduling = True
        try:
            scheduled_callback = run if scope else callback
            scheduled_args = () if scope else args
            handle = method(when, scheduled_callback, *scheduled_args, context=context)
        finally:
            scheduling = False
        if scope:
            scope.handles.add(handle)
        return handle

    def call_at(when, callback, *args, context=None):
        return schedule(original_call_at, when, callback, *args, context=context)

    # uvloop's C implementation of call_later does not delegate to call_at.
    def call_later(delay, callback, *args, context=None):
        return schedule(original_call_later, delay, callback, *args, context=context)

    loop.call_at = call_at
    loop.call_later = call_later


class JobScope:
    def __init__(self, root, receipt_path=None):
        self.root = root
        self.receipt_path = receipt_path
        self.tasks = set()
        self.sessions = set()
        self.files = set()
        self.handles = set()
        self.closed = False
        self.stopping = False

    async def drain(self):
        self.stopping = True
        # Tasks created during cancellation cleanup are included in the next pass.
        while True:
            pending = [t for t in self.tasks if not t.done()]
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
                continue
            open_sessions = [session for session in self.sessions if not session.closed]
            if not open_sessions:
                break
            for session in open_sessions:
                await session.close()
                if not session.closed:
                    raise RuntimeError("HTTP session did not close")
        for stream in list(self.files):
            stream.close()
        for handle in self.handles:
            handle.cancel()
        self.handles.clear()
        self.closed = True
