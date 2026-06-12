"""Temporal client factory (shared by the API process and the worker).

Retries the initial connect: in docker-compose / k8s the Temporal frontend may still be coming
up when the backend or worker starts.
"""
from __future__ import annotations

import asyncio
import logging

from temporalio.client import Client

from ..config import get_settings

log = logging.getLogger("orderpilot.temporal")


async def get_client(max_attempts: int = 30, delay_s: float = 2.0) -> Client:
    s = get_settings()
    last: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await Client.connect(s.temporal_address, namespace=s.temporal_namespace)
        except Exception as exc:  # noqa: BLE001 — retry any connect failure during startup
            last = exc
            log.warning("Temporal connect attempt %d/%d failed: %s", attempt, max_attempts, exc)
            await asyncio.sleep(delay_s)
    raise RuntimeError(f"could not connect to Temporal at {s.temporal_address}") from last
