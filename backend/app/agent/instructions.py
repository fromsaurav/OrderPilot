"""Deterministic interpretation of per-run extra instructions (PDF p.2).

Instructions are free text added after a run starts and become part of the run context.
We recognize a small set of patterns deterministically and turn them into a flags object the
policy consults. Unrecognized instructions are kept (and logged as context notes) so they are
visible in the activity log; when the LLM call site is enabled it may interpret them, but the
deterministic path never depends on that.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class InstructionFlags:
    escalate_delays: bool = False        # "escalate delays immediately"
    escalate_payment_issues: bool = False  # "escalate payment problems"
    escalate_always: bool = False        # "escalate everything"
    suppress_customer_update: bool = False  # "do not message the customer"
    suppress_escalation: bool = False    # "do not escalate / note only"
    aggressive_stale: bool = False       # "escalate if it goes stale"
    unrecognized: tuple[str, ...] = ()


def _has(text: str, *words: str) -> bool:
    return all(w in text for w in words)


def _negated(text: str) -> bool:
    return any(n in text for n in ("do not", "don't", "dont", "no ", "never", "avoid"))


def interpret(instructions: list[str]) -> InstructionFlags:
    flags = InstructionFlags()
    unrecognized: list[str] = []

    for raw in instructions:
        text = raw.lower().strip()
        recognized = False

        # Suppress customer messaging: "do not message/contact/email the customer"
        if _negated(text) and _has(text, "customer") or (
            _negated(text) and any(w in text for w in ("message", "contact", "email"))
        ):
            flags.suppress_customer_update = True
            recognized = True

        # Suppress escalation / note-only
        if (_negated(text) and "escalate" in text) or ("note only" in text) or (
            "only note" in text
        ):
            flags.suppress_escalation = True
            recognized = True

        # Escalation intents (positive, not negated)
        if "escalate" in text and not _negated(text):
            if "delay" in text:
                flags.escalate_delays = True
                recognized = True
            if any(w in text for w in ("payment", "billing", "charge")):
                flags.escalate_payment_issues = True
                recognized = True
            if any(w in text for w in ("everything", "all", "any event", "always")):
                flags.escalate_always = True
                recognized = True
            if any(w in text for w in ("stale", "stuck", "no progress", "idle")):
                flags.aggressive_stale = True
                recognized = True
            # bare "escalate immediately" with no object -> treat as delays+payment
            if not recognized:
                flags.escalate_delays = True
                flags.escalate_payment_issues = True
                recognized = True

        if not recognized:
            unrecognized.append(raw.strip())

    flags.unrecognized = tuple(unrecognized)
    return flags
