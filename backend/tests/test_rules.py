"""Pure unit tests for the deterministic rules engine (no Temporal / DB needed).

Run: ``python -m pytest backend/tests/test_rules.py`` or ``python backend/tests/test_rules.py``.
Validates the LOCKED policy table, instruction overrides, pre-wake check, and event reduction.
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.agent.decide import decide  # noqa: E402
from app.agent.instructions import interpret  # noqa: E402
from app.temporal.shared import (  # noqa: E402
    ACTION_CUSTOMER_UPDATE,
    ACTION_ESCALATE,
    ACTION_INTERNAL_NOTE,
    Event,
    RunContext,
    pre_wake_check,
    reduce_event,
)


def ctx(trigger, state=None, instructions=None, counters=None, age=0.0, event=None):
    return RunContext(
        run_id="r1", order_id="o1", trigger=trigger, state=state or {},
        instructions=instructions or [], age_seconds=age, counters=counters or {}, event=event,
    )


def actions(decision):
    return [(a.type) for a in decision.actions]


def test_workflow_start_notes():
    d = decide(ctx("workflow_start"))
    assert actions(d) == [ACTION_INTERNAL_NOTE]


def test_payment_failed_default_customer_update():
    d = decide(ctx("event:payment_failed", state={"payment": "failed"},
                   counters={"payment_failures": 1}, event=Event("payment_failed")))
    assert actions(d) == [ACTION_CUSTOMER_UPDATE]


def test_payment_failed_second_escalates():
    d = decide(ctx("event:payment_failed", state={"payment": "failed"},
                   counters={"payment_failures": 2}, event=Event("payment_failed")))
    assert ACTION_ESCALATE in actions(d) and ACTION_CUSTOMER_UPDATE in actions(d)


def test_payment_failed_escalates_with_instruction():
    d = decide(ctx("event:payment_failed", counters={"payment_failures": 1},
                   instructions=["please escalate payment problems immediately"],
                   event=Event("payment_failed")))
    assert ACTION_ESCALATE in actions(d)


def test_shipment_delayed_escalate_and_customer():
    d = decide(ctx("event:shipment_delayed", event=Event("shipment_delayed")))
    assert set(actions(d)) == {ACTION_ESCALATE, ACTION_CUSTOMER_UPDATE}


def test_do_not_message_suppresses_customer_update():
    d = decide(ctx("event:shipment_delayed", instructions=["do not message the customer"],
                   event=Event("shipment_delayed")))
    assert ACTION_CUSTOMER_UPDATE not in actions(d)
    assert ACTION_ESCALATE in actions(d)


def test_refund_requested():
    d = decide(ctx("event:refund_requested", event=Event("refund_requested")))
    assert set(actions(d)) == {ACTION_ESCALATE, ACTION_CUSTOMER_UPDATE}


def test_customer_message_rules_note_only():
    d = decide(ctx("event:customer_message_received", event=Event("customer_message_received")),
               classification={"label": "neutral", "source": "rules"})
    assert actions(d) == [ACTION_INTERNAL_NOTE]


def test_customer_message_complaint_adds_customer_update():
    d = decide(ctx("event:customer_message_received", event=Event("customer_message_received")),
               classification={"label": "complaint", "source": "llm"})
    assert ACTION_CUSTOMER_UPDATE in actions(d)


def test_customer_message_refund_escalates():
    d = decide(ctx("event:customer_message_received", event=Event("customer_message_received")),
               classification={"label": "refund", "source": "fallback"})
    assert ACTION_ESCALATE in actions(d)


def test_timer_noop_when_no_risk():
    d = decide(ctx("timer", state={"payment": "confirmed"}))
    assert actions(d) == []


def test_timer_notes_open_risk():
    d = decide(ctx("timer", state={"shipment_risk": True}, age=10))
    assert ACTION_INTERNAL_NOTE in actions(d)


def test_timer_escalates_when_stale():
    d = decide(ctx("timer", state={"shipment_risk": True}, age=10_000))
    assert ACTION_ESCALATE in actions(d)
    assert d.state_updates.get("stale_escalated") is True


def test_pre_wake_routine_stays_asleep():
    assert pre_wake_check("payment_confirmed", escalate_always=False) is False
    assert pre_wake_check("shipment_created", escalate_always=False) is False


def test_pre_wake_risk_wakes():
    assert pre_wake_check("payment_failed", escalate_always=False) is True
    assert pre_wake_check("shipment_delayed", escalate_always=False) is True


def test_pre_wake_escalate_always_forces_wake():
    assert pre_wake_check("payment_confirmed", escalate_always=True) is True


def test_interpret_recognizes_escalate_delays():
    f = interpret(["if shipment is delayed, escalate immediately"])
    assert f.escalate_delays is True


def test_interpret_suppress_customer():
    f = interpret(["do not contact the customer"])
    assert f.suppress_customer_update is True


def test_reduce_event_counts_failures():
    state, counters = {}, {}
    reduce_event(state, counters, Event("payment_failed"))
    reduce_event(state, counters, Event("payment_failed"))
    assert counters["payment_failures"] == 2 and state["payment_risk"] is True


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for fn in fns:
        try:
            fn()
            passed += 1
        except Exception:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
