"""The agent decision core: ``decide(context) -> Decision``.

This is the complete, self-sufficient deterministic policy (PDF p.1, "deterministic policy /
rules engine"). It is pure: no I/O, no clock, no randomness — given the same RunContext it
returns the same Decision. The optional LLM call site lives upstream in the decide *activity*
and only ever feeds a `classification` hint into this function; the rules below never depend
on it (Decision #3: rules-first, LLM-optional).

Policy baseline follows the LOCKED table in the brief (§4). Per-run extra instructions are
interpreted deterministically (agent.instructions) into flags consulted as overrides.
"""
from __future__ import annotations

from typing import Optional

from ..temporal.shared import (
    ACTION_CUSTOMER_UPDATE,
    ACTION_ESCALATE,
    ACTION_INTERNAL_NOTE,
    VIS_DEBUG,
    VIS_NORMAL,
    ActionSpec,
    Decision,
    RunContext,
    has_open_risk,
)
from .instructions import InstructionFlags, interpret

# Timer-wake escalation: how long an order may carry unresolved risk before the stale-order
# review escalates it. Lowered when an "escalate if stale" instruction is active.
STALE_THRESHOLD_SECONDS = 600
STALE_THRESHOLD_AGGRESSIVE_SECONDS = 120


class _Builder:
    """Collects actions while honoring instruction-driven suppression."""

    def __init__(self, flags: InstructionFlags) -> None:
        self.flags = flags
        self.actions: list[ActionSpec] = []
        self.updates: dict = {}

    def note(self, message: str, visibility: str = VIS_NORMAL) -> None:
        self.actions.append(ActionSpec(ACTION_INTERNAL_NOTE, message, visibility))

    def debug_note(self, message: str) -> None:
        """A heartbeat note (e.g. unchanged stale status) — hidden from the default view."""
        self.actions.append(ActionSpec(ACTION_INTERNAL_NOTE, message, VIS_DEBUG))

    def customer(self, message: str) -> None:
        if not self.flags.suppress_customer_update:
            self.actions.append(ActionSpec(ACTION_CUSTOMER_UPDATE, message))

    def escalate(self, message: str) -> None:
        if not self.flags.suppress_escalation:
            self.actions.append(ActionSpec(ACTION_ESCALATE, message))


def decide(ctx: RunContext, classification: Optional[dict] = None) -> Decision:
    flags = interpret(ctx.instructions)
    b = _Builder(flags)
    trigger = ctx.trigger

    if trigger == "workflow_start":
        b.note(f"Supervisor started for order {ctx.order_id}; awaiting events.")

    elif trigger == "timer":
        _timer_review(ctx, b)

    elif trigger == "interrupt":
        _interrupt_review(ctx, b)

    elif trigger.startswith("event:"):
        _on_event(ctx, b, classification)

    return Decision(actions=b.actions, state_updates=b.updates)


def _on_event(ctx: RunContext, b: _Builder, classification: Optional[dict]) -> None:
    et = ctx.event.type if ctx.event else ""
    state, counters = ctx.state, ctx.counters

    if et == "order_created":
        b.note("Order acknowledged; supervision started.")

    elif et == "payment_failed":
        b.customer("We noticed a payment issue on your order and are looking into it.")
        repeat = counters.get("payment_failures", 0) >= 2
        if b.flags.escalate_payment_issues or b.flags.escalate_always or repeat:
            reason = "repeat payment failure" if repeat else "payment failure (per instruction)"
            b.escalate(f"Escalating to fulfillment: {reason} on order {ctx.order_id}.")

    elif et == "shipment_delayed":
        # LOCKED baseline: shipment_delayed -> escalate + customer update.
        b.escalate(f"Shipment delayed on order {ctx.order_id} — fulfillment please advise.")
        b.customer("Apologies — your shipment is delayed. We're actively chasing it.")

    elif et == "refund_requested":
        b.customer("We've received your refund request and are processing it.")
        b.escalate(f"Refund requested on order {ctx.order_id} — please review.")

    elif et == "customer_message_received":
        label = (classification or {}).get("label")
        src = (classification or {}).get("source")
        suffix = f" (classified: {label}, via {src})" if label else ""
        b.note(f"Customer message received and logged{suffix}.")
        if label in {"complaint", "negative", "refund", "escalation"}:
            b.customer("Thanks for reaching out — we're reviewing your concern and will follow up.")
        if label in {"refund", "escalation"}:
            b.escalate(f"Customer message needs attention ({label}) on order {ctx.order_id}.")

    elif et in {"payment_confirmed", "shipment_created"}:
        # Only reached if an "escalate everything" instruction forced a wake on a routine event.
        b.note(f"Routine progress event '{et}' reviewed on demand (instruction-forced wake).")

    # delivered / cancelled never reach decide() — the workflow handles completion directly.


def _timer_review(ctx: RunContext, b: _Builder) -> None:
    """Scheduled wake (PDF p.1 trigger 3). Reviews state; produces a visible action only when
    something actually needs attention (Decision #9 refinement — otherwise the workflow logs a
    debug-level no-op and the agent goes back to sleep)."""
    state = ctx.state
    if not has_open_risk(state):
        return  # no actions -> workflow records a debug no-op wake

    open_flags = [k for k in ("payment_risk", "shipment_risk", "refund_risk") if state.get(k)]
    threshold = (
        STALE_THRESHOLD_AGGRESSIVE_SECONDS if b.flags.aggressive_stale else STALE_THRESHOLD_SECONDS
    )
    if (ctx.age_seconds >= threshold) and not state.get("stale_escalated"):
        # New decision: the order has aged past threshold with unresolved risk -> escalate once.
        b.escalate(
            f"Order {ctx.order_id} has unresolved issues and is aging "
            f"({int(ctx.age_seconds)}s) — escalating to fulfillment."
        )
        b.note(f"Stale-order check: escalated unresolved {', '.join(open_flags)}.")
        b.updates["stale_escalated"] = True
    else:
        # Heartbeat: open risk but nothing new to do (below threshold, or already escalated).
        # Debug visibility so repeated wakes don't bury the log (Decision #9 refinement).
        b.debug_note(
            f"Stale-order check (age {int(ctx.age_seconds)}s): unresolved "
            f"{', '.join(open_flags)}; no new action."
        )


def _interrupt_review(ctx: RunContext, b: _Builder) -> None:
    """Manual interrupt = force immediate agent wake. Always produces a visible status note,
    then re-evaluates open risks like a timer review would."""
    state = ctx.state
    summary = _state_summary(state)
    b.note(f"Manual interrupt — status check. {summary}")
    _timer_review(ctx, b)


def _state_summary(state: dict) -> str:
    parts = []
    if state.get("payment"):
        parts.append(f"payment={state['payment']}")
    if state.get("shipment"):
        parts.append(f"shipment={state['shipment']}")
    if state.get("refund_requested"):
        parts.append("refund=requested")
    return "Order state: " + (", ".join(parts) if parts else "no events yet") + "."
