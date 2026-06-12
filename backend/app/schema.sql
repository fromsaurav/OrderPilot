-- App schema for OrderPilot. Applied idempotently at backend startup (Decision #8).
-- The same Postgres also backs Temporal (separate `temporal`/`temporal_visibility` DBs);
-- these app tables live in the `orderpilot` database.

CREATE TABLE IF NOT EXISTS runs (
    run_id            TEXT PRIMARY KEY,           -- == Temporal workflow id
    order_id          TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'running',  -- running | paused | completed | terminated
    completion_reason TEXT,
    wake_interval_s   INTEGER NOT NULL,
    max_run_age_s     INTEGER NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at      TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS activity_log (
    id          BIGSERIAL PRIMARY KEY,
    run_id      TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    kind        TEXT NOT NULL,        -- event | wake_decision | action | instruction | summary | llm | fallback | lifecycle
    action      TEXT,                 -- escalate_to_fulfillment_team | send_customer_update | add_internal_note (when kind=action)
    trigger     TEXT,                 -- workflow_start | event:<type> | timer | interrupt | terminate
    -- Decision #9 refinement: no-op timer wakes are 'debug'; UI filters them by default.
    visibility  TEXT NOT NULL DEFAULT 'normal',  -- normal | debug
    message     TEXT NOT NULL,
    payload     JSONB
);

CREATE INDEX IF NOT EXISTS idx_activity_run ON activity_log (run_id, id);
CREATE INDEX IF NOT EXISTS idx_activity_visibility ON activity_log (run_id, visibility, id);
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs (status, created_at DESC);
