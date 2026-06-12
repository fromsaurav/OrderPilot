"""FastAPI routes: start/list/inspect runs, inject events, add instructions, lifecycle controls.

The API owns two side-effect surfaces: the app DB (runs + activity_log reads, run-row creation)
and the Temporal client (start workflow, send signals, terminate). Per DESIGN.md, lifecycle
pause/resume/interrupt/add-instruction are Temporal *signals*; terminate is the Temporal
terminate API (not a signal).
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from temporalio.client import Client
from temporalio.service import RPCError

from ..config import get_settings
from ..db import db
from ..temporal.shared import EVENT_TYPES, KIND_SUMMARY, VIS_NORMAL, Event, StartParams
from ..temporal.workflow import OrderSupervisorWorkflow

router = APIRouter()


# ------------------------------------------------------------------ request models
class StartRunBody(BaseModel):
    order_id: str = Field(..., min_length=1)
    wake_interval_s: Optional[int] = Field(default=None, ge=5)
    max_run_age_s: Optional[int] = Field(default=None, ge=10)
    instructions: list[str] = Field(default_factory=list)


class EventBody(BaseModel):
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)


class InstructionBody(BaseModel):
    text: str = Field(..., min_length=1)


class TerminateBody(BaseModel):
    reason: str = "manual termination"


# ------------------------------------------------------------------ helpers
def _client(request: Request) -> Client:
    return request.app.state.temporal


def _handle(request: Request, run_id: str):
    return _client(request).get_workflow_handle(run_id)


async def _require_run(run_id: str) -> dict:
    row = await db.fetchrow("SELECT * FROM runs WHERE run_id = $1", run_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"run {run_id} not found")
    return dict(row)


# ------------------------------------------------------------------ meta
@router.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@router.get("/events/types")
async def event_types() -> dict:
    return {"event_types": EVENT_TYPES}


# ------------------------------------------------------------------ runs
@router.post("/runs", status_code=201)
async def start_run(body: StartRunBody, request: Request) -> dict:
    s = get_settings()
    wake = body.wake_interval_s or s.default_wake_interval_seconds
    max_age = body.max_run_age_s or s.default_max_run_age_seconds
    run_id = f"order-{body.order_id}-{uuid.uuid4().hex[:8]}"

    await db.execute(
        """
        INSERT INTO runs (run_id, order_id, status, wake_interval_s, max_run_age_s)
        VALUES ($1, $2, 'running', $3, $4)
        """,
        run_id, body.order_id, wake, max_age,
    )
    await _client(request).start_workflow(
        OrderSupervisorWorkflow.run,
        StartParams(
            run_id=run_id, order_id=body.order_id,
            wake_interval_s=wake, max_run_age_s=max_age, instructions=body.instructions,
        ),
        id=run_id,
        task_queue=s.task_queue,
    )
    return await _require_run(run_id)


@router.get("/runs")
async def list_runs(status: Optional[str] = None, limit: int = 100) -> dict:
    if status:
        rows = await db.fetch(
            "SELECT * FROM runs WHERE status = $1 ORDER BY created_at DESC LIMIT $2", status, limit
        )
    else:
        rows = await db.fetch("SELECT * FROM runs ORDER BY created_at DESC LIMIT $1", limit)
    return {"runs": [dict(r) for r in rows]}


@router.get("/runs/{run_id}")
async def get_run(run_id: str, request: Request) -> dict:
    run = await _require_run(run_id)
    live: Optional[dict] = None
    try:
        live = await _handle(request, run_id).query(OrderSupervisorWorkflow.get_status)
    except RPCError:
        live = None  # workflow gone (completed/terminated) — DB row is the source of truth
    return {"run": run, "live": live}


@router.get("/runs/{run_id}/log")
async def get_log(run_id: str, include_debug: bool = False, limit: int = 500) -> dict:
    await _require_run(run_id)
    if include_debug:
        rows = await db.fetch(
            "SELECT * FROM activity_log WHERE run_id = $1 ORDER BY id ASC LIMIT $2", run_id, limit
        )
    else:
        rows = await db.fetch(
            "SELECT * FROM activity_log WHERE run_id = $1 AND visibility = $2 "
            "ORDER BY id ASC LIMIT $3",
            run_id, VIS_NORMAL, limit,
        )
    return {"entries": [dict(r) for r in rows]}


# ------------------------------------------------------------------ events + instructions
@router.post("/runs/{run_id}/events")
async def inject_event(run_id: str, body: EventBody, request: Request) -> dict:
    await _require_run(run_id)
    if body.type not in EVENT_TYPES:
        raise HTTPException(status_code=422, detail=f"unknown event type '{body.type}'")
    try:
        await _handle(request, run_id).signal(
            OrderSupervisorWorkflow.inject_event, Event(type=body.type, payload=body.payload)
        )
    except RPCError as e:
        raise HTTPException(status_code=409, detail=f"run not signalable: {e}") from e
    return {"ok": True, "injected": body.type}


@router.post("/runs/{run_id}/instructions")
async def add_instruction(run_id: str, body: InstructionBody, request: Request) -> dict:
    await _require_run(run_id)
    try:
        await _handle(request, run_id).signal(OrderSupervisorWorkflow.add_instruction, body.text)
    except RPCError as e:
        raise HTTPException(status_code=409, detail=f"run not signalable: {e}") from e
    return {"ok": True}


# ------------------------------------------------------------------ lifecycle
async def _signal_lifecycle(request: Request, run_id: str, signal) -> dict:
    await _require_run(run_id)
    try:
        await _handle(request, run_id).signal(signal)
    except RPCError as e:
        raise HTTPException(status_code=409, detail=f"run not signalable: {e}") from e
    return {"ok": True}


@router.post("/runs/{run_id}/pause")
async def pause(run_id: str, request: Request) -> dict:
    return await _signal_lifecycle(request, run_id, OrderSupervisorWorkflow.pause)


@router.post("/runs/{run_id}/resume")
async def resume(run_id: str, request: Request) -> dict:
    return await _signal_lifecycle(request, run_id, OrderSupervisorWorkflow.resume)


@router.post("/runs/{run_id}/interrupt")
async def interrupt(run_id: str, request: Request) -> dict:
    return await _signal_lifecycle(request, run_id, OrderSupervisorWorkflow.interrupt)


@router.post("/runs/{run_id}/terminate")
async def terminate(run_id: str, body: TerminateBody, request: Request) -> dict:
    """System-owned completion via the Temporal terminate API (NOT a signal — a sleeping or
    paused workflow may never process one). The workflow is hard-stopped, so the backend writes
    the final summary + flips the run row to 'terminated' itself."""
    run = await _require_run(run_id)
    handle = _handle(request, run_id)

    # Best-effort snapshot of live state for the summary before we stop the workflow.
    live: Optional[dict] = None
    try:
        live = await handle.query(OrderSupervisorWorkflow.get_status)
    except RPCError:
        live = None
    try:
        await handle.terminate(reason=body.reason)
    except RPCError as e:
        raise HTTPException(status_code=409, detail=f"cannot terminate: {e}") from e

    summary = _terminate_summary(run, live, body.reason)
    await db.execute(
        """
        INSERT INTO activity_log (run_id, kind, trigger, visibility, message, payload)
        VALUES ($1, $2, 'terminate', $3, $4, '{}'::jsonb)
        """,
        run_id, KIND_SUMMARY, VIS_NORMAL, summary,
    )
    await db.execute(
        """
        UPDATE runs SET status='terminated', completion_reason=$2,
               updated_at=now(), completed_at=now()
         WHERE run_id=$1
        """,
        run_id, f"terminated: {body.reason}",
    )
    return {"ok": True, "status": "terminated"}


def _terminate_summary(run: dict, live: Optional[dict], reason: str) -> str:
    facts = ""
    if live and live.get("state"):
        s = live["state"]
        bits = [f"{k}={v}" for k, v in s.items() if not str(k).endswith("_risk")]
        if bits:
            facts = " Final state: " + ", ".join(bits) + "."
    return f"Order {run['order_id']} terminated by operator ({reason}).{facts}"
