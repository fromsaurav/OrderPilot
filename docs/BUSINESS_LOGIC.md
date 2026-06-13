# Business Logic — How the Order Supervisor Works

## In one paragraph

It's an AI supervisor that babysits a **single e-commerce order** from creation to completion.
**One Temporal workflow per order.** The workflow mostly **sleeps** to save resources, waking only
when an **event** arrives (payment failed, shipment delayed, customer messaged) or on a **timer**.
When it wakes, a **decision engine** looks at what happened and the order's state and picks an
**action** — escalate to fulfillment, send a customer update, or log an internal note. A human can
inject events, add instructions mid-flight ("escalate immediately if delayed"), and
pause/resume/terminate it. The workflow only ends when the **system** says so (order
delivered/cancelled, max age hit, or manual kill) — never just because the agent feels done.
Everything in the **activity log** is the workflow narrating its own wake → decide → act → sleep
cycle.

> This doc explains the *what happens and why*, pointing at the exact functions. For the system
> diagram see [ARCHITECTURE.md](ARCHITECTURE.md); for design rationale see [DESIGN.md](DESIGN.md).

---

## The core loop: wake → decide → act → sleep

All of this lives in **[`backend/app/temporal/workflow.py`](../backend/app/temporal/workflow.py)**,
class `OrderSupervisorWorkflow`.

The loop never busy-spins. It blocks in:

```python
await workflow.wait_condition(self._work_pending, timeout=...)   # run()
```

It wakes for exactly one of: a signal arrived (event/instruction/pause/resume/interrupt), or the
`timeout` (the next scheduled wake) elapsed, or the run completed. Then it drains work, maybe
reasons, and goes back to sleep. `timeout` is the per-run **wake interval** (default 60s,
Decision #9); when paused it sleeps until the **max-age deadline** instead.

### The three inference triggers (where each enters the code)

| Trigger | Entry point | Notes |
|---|---|---|
| **Workflow start** | `run()` → `_reason_and_act("workflow_start")` | first decision: acknowledge the order |
| **Incoming event** | `inject_event` signal → queue → `_drain_events()` | a Temporal **signal**, not a poll |
| **Scheduled timer** | `wait_condition` times out → `_reason_and_act("timer")` | periodic state review |

---

## Step 1 — an event arrives and is folded into state

`inject_event` (a `@workflow.signal`) just appends the event to an in-memory queue. On the next
loop turn `_drain_events()` pulls each event and **folds it into the order's state** with
`reduce_event()` in **[`shared.py`](../backend/app/temporal/shared.py)**:

- `payment_failed` → `state.payment="failed"`, sets `payment_risk`, increments `payment_failures`
- `shipment_delayed` → `state.shipment="delayed"`, sets `shipment_risk`, increments `shipment_delays`
- `refund_requested` → sets `refund_requested` + `refund_risk`
- `customer_message_received` → stores `last_customer_message`
- `delivered` / `cancelled` → terminal (see completion)

State is held **in the workflow's memory** (authoritative across Temporal replays); Postgres is
the read model for the UI.

## Step 2 — pre-wake check: wake now or stay asleep?

Still in `_drain_events()`, before doing any real reasoning, the workflow runs the lightweight
`pre_wake_check(event_type, escalate_always)` (in `shared.py`):

- **Terminal events** → handled by the completion path.
- **Routine events** (`payment_confirmed`, `shipment_created`, the `ROUTINE_EVENTS` set) → **stay
  asleep**; it writes a *debug-level* "Stayed asleep…" line and defers to the next scheduled wake.
- **Everything else** (payment_failed, shipment_delayed, refund_requested, customer_message) →
  **wake now** and reason.
- An active "escalate everything" instruction forces every event to wake.

This is the visible *"stayed asleep"* decision the assignment asks for.

## Step 3 — the decision engine (the "agent")

When it decides to wake, `_reason_and_act(trigger, event)` builds a `RunContext` (order id,
trigger, current state, instructions, age, counters, the triggering event) and calls the
**`decide_activity`** in **[`activities.py`](../backend/app/temporal/activities.py)**.

Inside `decide_activity`:
1. **(Only for `customer_message_received`)** it calls the **single LLM call site**,
   `classify_message()` in **[`llm.py`](../backend/app/agent/llm.py)**, to label the message
   (complaint / refund / escalation / question / neutral). On **any** failure (no key, timeout,
   rate-limit, bad output) it falls back to the keyword `rules_classify()` and tags the result
   `source="fallback"`. With no key configured it's `source="rules"`. **The system runs fully
   without an LLM.**
2. It calls the pure rules engine **`decide(ctx, classification)`** in
   **[`decide.py`](../backend/app/agent/decide.py)**, which returns a `Decision` (a list of
   actions + state updates). `decide()` does no I/O — same input, same output.

### The policy (what decision each trigger produces)

| Trigger | Default action(s) | Instruction overrides |
|---|---|---|
| `workflow_start` | `add_internal_note` (order acknowledged) | — |
| `order_created` | `add_internal_note` | — |
| `payment_failed` | `send_customer_update` | + `escalate` on 2nd failure, or if "escalate payment…" instruction |
| `shipment_delayed` | `escalate_to_fulfillment_team` + `send_customer_update` | `send` suppressed by "do not message the customer" |
| `refund_requested` | `send_customer_update` + `escalate_to_fulfillment_team` | `send` suppressed likewise |
| `customer_message_received` | `add_internal_note` | + `send`/`escalate` if classified complaint/refund/escalation |
| `payment_confirmed`, `shipment_created` | (stay asleep) | only acted on if "escalate everything" forced a wake |
| **timer** | review state; **escalate once** if risk is unresolved past the stale threshold | else a *debug* heartbeat (`no new action`) |
| **interrupt** | always a visible status note, then a stale review | — |
| `delivered` / `cancelled` | system completes the run | — |

Instruction text is interpreted **deterministically** by `interpret()` in
**[`instructions.py`](../backend/app/agent/instructions.py)** into flags
(`escalate_delays`, `escalate_payment_issues`, `escalate_always`, `suppress_customer_update`,
`suppress_escalation`, `aggressive_stale`). Unrecognized text is still logged as context.

## Step 4 — act: write the action to the activity log

Back in `_reason_and_act`, each action in the `Decision` becomes an `activity_log` row via the
`record_entries` activity. **Actions don't call anything external** — "escalate" / "send update"
are just records, exactly as the assignment specifies. The three action types:

- `escalate_to_fulfillment_team` — flag an order issue to fulfillment
- `send_customer_update` — a status/apology to the customer
- `add_internal_note` — an internal observation

**Decision #9 refinement:** a timer wake with nothing new to do writes only a **debug** line, so
the default log view stays clean. Only genuine new decisions are `normal` visibility.

## Step 5 — sleep again

The loop returns to `wait_condition`. Nothing runs until the next event or scheduled wake.

## Completion is system-owned (never the agent's choice)

In `workflow.py` / `routes.py`, a run ends **only** via:
1. a **terminal event** (`delivered` / `cancelled`) → `_drain_events` flags completion,
2. **max run age** → the loop's deadline check,
3. **manual terminate** → the backend calls Temporal's terminate API (see below).

In all cases a **final summary** is written to the activity log (`_complete()` →
`_build_summary()`; for terminate, the backend writes it since the workflow is hard-stopped).

---

## How to interact with the app — and what to check

Two ways: the **Next.js UI** (buttons/forms) or the **API** directly
(**[`routes.py`](../backend/app/api/routes.py)**). The UI just calls these endpoints. Below,
`$API` is `http://localhost:8000` locally, or `http://<ec2-ip>:30080` in the cloud.

| You do | UI / API | What happens internally | What to check |
|---|---|---|---|
| **Start a run** | `POST /runs` `{order_id, wake_interval_s?, max_run_age_s?, instructions?}` | inserts a `runs` row + starts the workflow; first decision = acknowledge | run appears in `GET /runs` as `running`; log has "Supervisor started…" |
| **Inject an event** | `POST /runs/{id}/events` `{type, payload?}` | `inject_event` signal → reduce → pre-wake → maybe decide | risk events add action lines; routine events show only in `?include_debug=true` as "Stayed asleep" |
| **Add an instruction** | `POST /runs/{id}/instructions` `{text}` | `add_instruction` signal; future decisions consult `interpret()` | log shows "Instruction added: …"; behavior changes on the next matching event |
| **Pause / Resume** | `POST /runs/{id}/pause` \| `/resume` | signals; paused runs buffer events + skip timer reasoning | run status flips `paused`/`running`; log shows "Run paused/running" |
| **Interrupt** | `POST /runs/{id}/interrupt` | signal; forces an immediate wake + status note (even if paused) | log shows a "Manual interrupt — status check" note |
| **Terminate** | `POST /runs/{id}/terminate` `{reason}` | Temporal **terminate API** (not a signal); backend writes summary | status → `terminated`; final summary line present |
| **Inspect a run** | `GET /runs/{id}` | run row + live `get_status` query | shows current state/counters/paused |
| **Read the log** | `GET /runs/{id}/log` (`?include_debug=true`) | reads `activity_log` | default view = meaningful decisions; debug view = stay-asleep + timer heartbeats |

### Worked example (what you should see)

1. Start a run (`wake_interval_s: 5`).
2. Inject `payment_failed` → log gets **`send_customer_update`**.
3. Inject `payment_confirmed` → **nothing** in the default log; debug view shows *"Stayed asleep
   on routine 'payment_confirmed'"*.
4. Inject `shipment_delayed` → log gets **`escalate_to_fulfillment_team` + `send_customer_update`**.
5. Add instruction **"do not message the customer"**, inject `shipment_delayed` again → this time
   **only `escalate`** appears (customer update suppressed) — proves instructions change behavior.
6. Inject `customer_message_received` with text *"I want a refund"* → note + (rules classify
   "refund") → **`send_customer_update` + `escalate`**.
7. Wait through a couple of timer wakes → default log stays quiet; debug view shows stale-order
   heartbeats; if it ages past the threshold, **one** escalation appears.
8. Inject `delivered` → run flips to **`completed`** with a **final summary** line.

This exact sequence is automated and asserted in
**[`scripts/local_demo.sh`](../scripts/local_demo.sh)** (17 checks) — run it to confirm the whole
business flow end-to-end.
