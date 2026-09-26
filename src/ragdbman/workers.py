# SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
# SPDX-License-Identifier: Apache-2.0

"""Off-loop work with cancellation that never leaves an unowned writer behind."""

import asyncio
import threading


async def _drain(task):
    # Repeated cancellation must not release a collection lock while a worker
    # still owns its database transaction or temporary converter directory.
    while not task.done():
        try:
            await asyncio.shield(task)
        except BaseException:
            if task.done():
                break
    try:
        task.result()
    except BaseException:
        pass


async def run_sync(function, *args, on_cancel=None):
    """Run blocking work in a thread; wait for its cleanup before cancelling."""
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        if on_cancel:
            on_cancel()
        await _drain(task)
        raise


async def run_async(function, *args):
    """Run a self-contained converter coroutine on a worker-owned event loop.

    Only use this for work with no shared async clients/locks. Cancellation is
    forwarded to the worker loop so subprocess cleanup still runs. The caller
    waits until that cleanup finishes, including any thread work in the worker.
    """
    state_lock = threading.Lock()
    state = {"cancelled": False, "loop": None, "task": None}

    async def invoke():
        with state_lock:
            state["loop"] = asyncio.get_running_loop()
            state["task"] = asyncio.current_task()
            if state["cancelled"]:
                state["task"].cancel()
        try:
            return await function(*args)
        finally:
            with state_lock:
                state["loop"] = None
                state["task"] = None

    def worker():
        return asyncio.run(invoke())

    def cancel():
        with state_lock:
            state["cancelled"] = True
            loop, task = state["loop"], state["task"]
            if loop is not None and not loop.is_closed():
                loop.call_soon_threadsafe(task.cancel)

    return await run_sync(worker, on_cancel=cancel)
