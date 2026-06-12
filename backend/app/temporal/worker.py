"""Temporal worker process: hosts the workflow and activities on the task queue.

Run with: ``python -m app.temporal.worker``. Scaled by the HPA in-cluster (Phase 4).
"""
from __future__ import annotations

import asyncio
import logging

from temporalio.worker import Worker

from ..config import get_settings
from ..db import db
from . import activities as act
from .client import get_client
from .workflow import OrderSupervisorWorkflow

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("orderpilot.worker")


async def main() -> None:
    s = get_settings()
    await db.connect()
    await db.init_schema()
    client = await get_client()
    worker = Worker(
        client,
        task_queue=s.task_queue,
        workflows=[OrderSupervisorWorkflow],
        activities=[act.decide_activity, act.record_entries, act.update_run_status],
    )
    log.info("Worker started on task queue '%s' (temporal=%s)", s.task_queue, s.temporal_address)
    try:
        await worker.run()
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
