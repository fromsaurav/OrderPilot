"""Cross-boundary types and domain constants.

This module is imported by BOTH the workflow (which runs in Temporal's deterministic
sandbox) and activities/API code. It must stay free of I/O and non-deterministic imports —
stdlib only. All types crossing the workflow<->activity boundary are plain dataclasses of
JSON-serializable primitives (no datetime; ages are passed as floats).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

TASK_QUEUE = "order-supervisor"

# --- Events (PDF p.2). `cancelled` is terminal-only per DESIGN.md note. ---
EVENT_TYPES = [
    "order_created",
    "payment_confirmed",
    "payment_failed",
    "shipment_created",
    "shipment_delayed",
    "delivered",
    "refund_requested",
    "customer_message_received",
    "cancelled",
]
TERMINAL_EVENTS = {"delivered", "cancelled"}

# Routine progress events: pre-wake check stays asleep and defers to next scheduled wake.
ROUTINE_EVENTS = {"payment_confirmed", "shipment_created"}

# --- Actions (PDF p.2): each writes an activity-log record, nothing external. ---
ACTION_ESCALATE = "escalate_to_fulfillment_team"
ACTION_CUSTOMER_UPDATE = "send_customer_update"
ACTION_INTERNAL_NOTE = "add_internal_note"
ACTIONS = {ACTION_ESCALATE, ACTION_CUSTOMER_UPDATE, ACTION_INTERNAL_NOTE}

# --- Activity-log kinds / visibility ---
KIND_EVENT = "event"
KIND_WAKE = "wake_decision"
KIND_ACTION = "action"
KIND_INSTRUCTION = "instruction"
KIND_SUMMARY = "summary"
KIND_LLM = "llm"
KIND_FALLBACK = "fallback"
KIND_LIFECYCLE = "lifecycle"

VIS_NORMAL = "normal"
VIS_DEBUG = "debug"  # no-op wakes etc.; UI hides by default (Decision #9 refinement)


@dataclass
class Event:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class ActionSpec:
    type: str           # one of ACTIONS
    message: str
    # Decision #9 refinement: repeated heartbeat-style notes (e.g. an unchanged stale-order
    # status on every timer wake) are emitted at debug visibility so the default UI view shows
    # only genuine new decisions. Defaults to normal.
    visibility: str = VIS_NORMAL


@dataclass
class LogEntry:
    kind: str
    message: str
    action: Optional[str] = None
    trigger: Optional[str] = None
    visibility: str = VIS_NORMAL
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunContext:
    """Everything the agent's decide() needs. Passed into the decide activity."""
    run_id: str
    order_id: str
    trigger: str                       # workflow_start | event:<type> | timer | interrupt
    state: dict[str, Any]              # accumulated order facts
    instructions: list[str]
    age_seconds: float
    counters: dict[str, int]          # payment_failures, shipment_delays, wake_count, ...
    event: Optional[Event] = None     # the triggering event, when trigger startswith "event:"


@dataclass
class Decision:
    """Returned by decide(). Pure data — workflow applies it deterministically."""
    actions: list[ActionSpec] = field(default_factory=list)
    state_updates: dict[str, Any] = field(default_factory=dict)
    note: Optional[str] = None         # optional reasoning note (logged at debug for no-ops)


@dataclass
class DecisionResult:
    """What the decide activity returns: the decision plus any extra log lines the activity
    produced out-of-band (e.g. the LLM-used / fallback notes from the single LLM call site).
    The workflow records extra_logs alongside the action entries so all logging stays in one
    place (the workflow)."""
    decision: Decision
    extra_logs: list[LogEntry] = field(default_factory=list)


@dataclass
class StartParams:
    run_id: str
    order_id: str
    wake_interval_s: int
    max_run_age_s: int
    instructions: list[str] = field(default_factory=list)


def reduce_event(state: dict[str, Any], counters: dict[str, int], event: Event) -> None:
    """Deterministically fold an event into accumulated order state + counters.

    Pure, stdlib-only, side-effect-free except mutating the passed dicts — safe to call
    inside the workflow sandbox so in-memory state stays authoritative across replays.
    """
    t = event.type
    if t == "order_created":
        state["order_created"] = True
    elif t == "payment_confirmed":
        state["payment"] = "confirmed"
        state.pop("payment_risk", None)
    elif t == "payment_failed":
        state["payment"] = "failed"
        state["payment_risk"] = True
        counters["payment_failures"] = counters.get("payment_failures", 0) + 1
    elif t == "shipment_created":
        state["shipment"] = "created"
    elif t == "shipment_delayed":
        state["shipment"] = "delayed"
        state["shipment_risk"] = True
        counters["shipment_delays"] = counters.get("shipment_delays", 0) + 1
    elif t == "refund_requested":
        state["refund_requested"] = True
        state["refund_risk"] = True
    elif t == "customer_message_received":
        state["last_customer_message"] = str(event.payload.get("text", "")).strip()
        counters["customer_messages"] = counters.get("customer_messages", 0) + 1
    elif t == "delivered":
        state["delivered"] = True
    elif t == "cancelled":
        state["cancelled"] = True


def has_open_risk(state: dict[str, Any]) -> bool:
    """Any unresolved risk flag the timer-wake review cares about."""
    return bool(
        state.get("payment_risk") or state.get("shipment_risk") or state.get("refund_risk")
    )


def pre_wake_check(event_type: str, escalate_always: bool) -> bool:
    """Lightweight wake-now vs stay-asleep decision (PDF p.2), run in the workflow.

    Terminal events are handled by the completion path (always). Routine progress events
    stay asleep and defer reasoning to the next scheduled wake — this is the visible
    "stayed asleep" decision. Risk/interaction events wake immediately. An active
    "escalate everything" instruction forces every event to wake.
    """
    if event_type in TERMINAL_EVENTS:
        return True
    if escalate_always:
        return True
    return event_type not in ROUTINE_EVENTS
