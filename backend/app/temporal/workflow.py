"""OrderSupervisorWorkflow — one workflow per order.

Three inference triggers (PDF p.1): workflow start, incoming event (signal), scheduled timer
wake. The workflow never busy-loops: it sleeps in ``wait_condition`` until a signal arrives or
the next scheduled wake elapses, reasons via the decide activity, acts, updates state, sleeps
again. Completion is system-owned (PDF p.2): a terminal event, max run age, or backend-issued
terminate — never the agent's own choice.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from ..agent.instructions import interpret
    from .activities import decide_activity, record_entries, update_run_status

from .shared import (
    KIND_ACTION,
    KIND_EVENT,
    KIND_INSTRUCTION,
    KIND_LIFECYCLE,
    KIND_SUMMARY,
    KIND_WAKE,
    TERMINAL_EVENTS,
    VIS_DEBUG,
    VIS_NORMAL,
    Event,
    LogEntry,
    RunContext,
    StartParams,
    pre_wake_check,
    reduce_event,
)

_ACT_TIMEOUT = timedelta(seconds=20)
_DB_TIMEOUT = timedelta(seconds=10)


@workflow.defn
class OrderSupervisorWorkflow:
    def __init__(self) -> None:
        self._params: StartParams | None = None
        self._state: dict = {}
        self._counters: dict = {}
        self._instructions: list[str] = []
        self._pending_events: list[Event] = []
        self._unlogged_instructions: list[str] = []
        self._status_changes: list[tuple[str, str | None, bool]] = []
        self._paused = False
        self._interrupt = False
        self._completed = False
        self._completion_reason: str | None = None

    # ------------------------------------------------------------------ run loop
    @workflow.run
    async def run(self, params: StartParams) -> dict:
        self._params = params
        self._instructions = list(params.instructions)
        self._start = workflow.now()
        deadline = self._start + timedelta(seconds=params.max_run_age_s)
        wake_interval = timedelta(seconds=params.wake_interval_s)
        next_wake = self._start + wake_interval

        # Trigger 1: workflow start.
        await self._reason_and_act("workflow_start")

        reason = "max_run_age"
        while not self._completed:
            await self._flush_pending_logs()

            now = workflow.now()
            if now >= deadline:
                reason = "max_run_age"
                break

            # Paused runs do not timer-wake; they only wake on signals or the age deadline.
            target = deadline if self._paused else min(next_wake, deadline)
            timeout = max((target - now).total_seconds(), 0.0)
            try:
                await workflow.wait_condition(self._work_pending, timeout=timeout)
            except asyncio.TimeoutError:
                pass

            if self._completed:
                break

            await self._flush_pending_logs()

            # Drain events first. Terminal events complete the run even when paused.
            if await self._drain_events():
                reason = self._completion_reason or reason
                break

            # Interrupt forces an immediate wake even while paused (deliberate force-wake).
            if self._interrupt:
                self._interrupt = False
                await self._reason_and_act("interrupt")
                continue
            if self._paused:
                continue

            now = workflow.now()
            if now >= next_wake:
                await self._reason_and_act("timer")  # Trigger 3: scheduled wake.
                while next_wake <= now:
                    next_wake += wake_interval

        await self._complete(reason)
        return {"run_id": params.run_id, "completion_reason": reason}

    def _work_pending(self) -> bool:
        return bool(
            self._pending_events
            or self._completed
            or self._interrupt
            or self._unlogged_instructions
            or self._status_changes
        )

    # ------------------------------------------------------------------ signals
    @workflow.signal
    def inject_event(self, event: Event) -> None:  # Trigger 2: incoming event.
        self._pending_events.append(event)

    @workflow.signal
    def add_instruction(self, text: str) -> None:
        self._instructions.append(text)
        self._unlogged_instructions.append(text)

    @workflow.signal
    def pause(self) -> None:
        if not self._paused:
            self._paused = True
            self._status_changes.append(("paused", None, False))

    @workflow.signal
    def resume(self) -> None:
        if self._paused:
            self._paused = False
            self._status_changes.append(("running", None, False))

    @workflow.signal
    def interrupt(self) -> None:
        self._interrupt = True

    @workflow.query
    def get_status(self) -> dict:
        return {
            "order_id": self._params.order_id if self._params else None,
            "state": self._state,
            "counters": self._counters,
            "instructions": self._instructions,
            "paused": self._paused,
            "completed": self._completed,
            "completion_reason": self._completion_reason,
        }

    # ------------------------------------------------------------------ helpers
    async def _drain_events(self) -> bool:
        """Apply and act on buffered events. Returns True if a terminal event completed the run."""
        while self._pending_events:
            ev = self._pending_events.pop(0)
            reduce_event(self._state, self._counters, ev)
            await self._record(
                [LogEntry(kind=KIND_EVENT, message=f"Event received: {ev.type}",
                          trigger=f"event:{ev.type}", payload=ev.payload)]
            )
            if ev.type in TERMINAL_EVENTS:
                self._completed = True
                self._completion_reason = f"terminal:{ev.type}"
                return True
            if self._paused:
                await self._record(
                    [LogEntry(kind=KIND_WAKE, visibility=VIS_DEBUG, trigger=f"event:{ev.type}",
                              message=f"Paused — buffered '{ev.type}', deferring action until resume.")]
                )
                continue
            # Pre-wake check (PDF p.2): wake-now vs stay-asleep.
            flags = interpret(self._instructions)
            if pre_wake_check(ev.type, flags.escalate_always):
                await self._reason_and_act(f"event:{ev.type}", event=ev)
            else:
                await self._record(
                    [LogEntry(kind=KIND_WAKE, visibility=VIS_DEBUG, trigger=f"event:{ev.type}",
                              message=f"Stayed asleep on routine '{ev.type}'; deferring to next scheduled wake.")]
                )
            if self._completed:
                return True
        return False

    async def _reason_and_act(self, trigger: str, event: Event | None = None) -> None:
        self._counters["wake_count"] = self._counters.get("wake_count", 0) + 1
        age = (workflow.now() - self._start).total_seconds()
        ctx = RunContext(
            run_id=self._params.run_id,
            order_id=self._params.order_id,
            trigger=trigger,
            state=dict(self._state),
            instructions=list(self._instructions),
            age_seconds=age,
            counters=dict(self._counters),
            event=event,
        )
        result = await workflow.execute_activity(
            decide_activity, ctx, start_to_close_timeout=_ACT_TIMEOUT
        )
        self._state.update(result.decision.state_updates)

        entries = list(result.extra_logs)
        if result.decision.actions:
            for a in result.decision.actions:
                entries.append(
                    LogEntry(kind=KIND_ACTION, action=a.type, message=a.message,
                             trigger=trigger, visibility=a.visibility)
                )
        elif trigger == "timer":
            # Decision #9: a no-op scheduled wake is recorded at debug visibility only.
            entries.append(
                LogEntry(kind=KIND_WAKE, visibility=VIS_DEBUG, trigger="timer",
                         message="Timer wake: no open issues; back to sleep.")
            )
        if entries:
            await self._record(entries)

    async def _flush_pending_logs(self) -> None:
        if self._unlogged_instructions:
            entries = [
                LogEntry(kind=KIND_INSTRUCTION, message=f"Instruction added: {t}",
                         payload={"instruction": t})
                for t in self._unlogged_instructions
            ]
            self._unlogged_instructions = []
            await self._record(entries)
        if self._status_changes:
            changes = self._status_changes
            self._status_changes = []
            for status, creason, completed in changes:
                await workflow.execute_activity(
                    update_run_status,
                    args=[self._params.run_id, status, creason, completed],
                    start_to_close_timeout=_DB_TIMEOUT,
                )
                await self._record(
                    [LogEntry(kind=KIND_LIFECYCLE, message=f"Run {status}.")]
                )

    async def _complete(self, reason: str) -> None:
        age = int((workflow.now() - self._start).total_seconds())
        await self._record(
            [LogEntry(kind=KIND_SUMMARY, trigger=reason, message=self._build_summary(reason, age))]
        )
        await workflow.execute_activity(
            update_run_status,
            args=[self._params.run_id, "completed", reason, True],
            start_to_close_timeout=_DB_TIMEOUT,
        )

    async def _record(self, entries: list[LogEntry]) -> None:
        await workflow.execute_activity(
            record_entries, args=[self._params.run_id, entries], start_to_close_timeout=_DB_TIMEOUT
        )

    def _build_summary(self, reason: str, age: int) -> str:
        s, c = self._state, self._counters
        facts = []
        if s.get("payment"):
            facts.append(f"payment {s['payment']}")
        if s.get("shipment"):
            facts.append(f"shipment {s['shipment']}")
        if s.get("delivered"):
            facts.append("delivered")
        if s.get("cancelled"):
            facts.append("cancelled")
        if s.get("refund_requested"):
            facts.append("refund requested")
        state_str = ("Final state: " + ", ".join(facts) + ".") if facts else "No order events recorded."
        return (
            f"Order {self._params.order_id} supervision complete ({reason}). {state_str} "
            f"Wakes: {c.get('wake_count', 0)}, payment failures: {c.get('payment_failures', 0)}, "
            f"shipment delays: {c.get('shipment_delays', 0)}. Run age: {age}s."
        )
