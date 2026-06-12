"""Temporal activities — the only place side effects happen (DB writes, the LLM call).

All activities are async (asyncpg + an awaited LLM call), so no sync activity executor is
needed on the worker. The decide activity is the sole LLM call site (Decision #3); the rules
engine it wraps is pure and lives in app.agent.decide.
"""
from __future__ import annotations

import asyncio
import json

from temporalio import activity

from ..agent.decide import decide
from ..agent.llm import classify_message
from ..db import db
from .shared import (
    KIND_FALLBACK,
    KIND_LLM,
    VIS_DEBUG,
    VIS_NORMAL,
    DecisionResult,
    LogEntry,
    RunContext,
)


@activity.defn
async def record_entries(run_id: str, entries: list[LogEntry]) -> None:
    """Append activity-log rows (events, wake decisions, actions, summaries) in order."""
    if not entries:
        return
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            for e in entries:
                await conn.execute(
                    """
                    INSERT INTO activity_log
                        (run_id, kind, action, trigger, visibility, message, payload)
                    VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
                    """,
                    run_id,
                    e.kind,
                    e.action,
                    e.trigger,
                    e.visibility,
                    e.message,
                    json.dumps(e.payload or {}),
                )


@activity.defn
async def update_run_status(
    run_id: str, status: str, completion_reason: str | None, completed: bool
) -> None:
    await db.execute(
        """
        UPDATE runs
           SET status = $2,
               completion_reason = COALESCE($3, completion_reason),
               updated_at = now(),
               completed_at = CASE WHEN $4 THEN now() ELSE completed_at END
         WHERE run_id = $1
        """,
        run_id,
        status,
        completion_reason,
        completed,
    )


@activity.defn
async def decide_activity(ctx: RunContext) -> DecisionResult:
    """Run the agent decision. For customer messages this is the one LLM call site, guarded by
    a hard fallback; the resulting classification only ever *feeds* the deterministic rules."""
    classification = None
    extra: list[LogEntry] = []

    if ctx.trigger == "event:customer_message_received" and ctx.event is not None:
        text = str(ctx.event.payload.get("text", ""))
        classification = await asyncio.to_thread(classify_message, text)
        source = classification.get("source")
        label = classification.get("label")
        if source == "llm":
            extra.append(
                LogEntry(
                    kind=KIND_LLM,
                    message=f"LLM classified customer message as '{label}'.",
                    visibility=VIS_NORMAL,
                    payload={"label": label, "source": "llm"},
                )
            )
        elif source == "fallback":
            extra.append(
                LogEntry(
                    kind=KIND_FALLBACK,
                    message=(
                        f"LLM unavailable ({classification.get('error', 'unknown')}); "
                        f"fell back to rules classification '{label}'."
                    ),
                    visibility=VIS_NORMAL,
                    payload=classification,
                )
            )
        # source == "rules": LLM disabled, nothing extra to log.

    decision = decide(ctx, classification)
    return DecisionResult(decision=decision, extra_logs=extra)
