"""JobRunner (LLD B10.7, AI-ADR-1): a background task per summary, in this process; the state lives in the database.

The registry holds strong references to running tasks so they are not garbage-collected mid-flight. On shutdown the
lifespan cancels them; each catches CancelledError and makes one best-effort ``failed JOB_ABORTED`` write.
"""
from __future__ import annotations

import asyncio
import logging

from app.orchestrator.orchestrator import JobContext, SummaryOrchestrator

log = logging.getLogger("ai.jobs")


class JobRunner:
    def __init__(self, orchestrator: SummaryOrchestrator, deadline_s: float) -> None:
        self._orch, self._deadline = orchestrator, deadline_s
        self._tasks: set[asyncio.Task[None]] = set()

    def start(self, job: JobContext) -> asyncio.Task[None]:
        job.deadline_s = self._deadline
        task = asyncio.create_task(self._orch.run(job), name=f"summary-{job.summary_id}")
        self._tasks.add(task)
        task.add_done_callback(self._done)
        return task

    def _done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and (exc := task.exception()) is not None:
            log.error("job.crashed", extra={"error_type": type(exc).__name__})

    @property
    def running(self) -> int:
        return len(self._tasks)

    async def wait_idle(self) -> None:
        """Test helper: waits until every job has finished."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def shutdown(self, grace_s: float = 6.0) -> None:
        tasks = list(self._tasks)
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=grace_s)
