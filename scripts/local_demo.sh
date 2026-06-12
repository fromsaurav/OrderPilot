#!/usr/bin/env bash
# Local end-to-end smoke test for the rules-only application (no LLM key required).
# Brings up the docker-compose stack if needed, drives the API through the full feature set,
# and asserts the agent behaved correctly. Exits non-zero on any failed assertion.
#
#   ./scripts/local_demo.sh
#
set -euo pipefail

API="${API:-http://localhost:8000}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_DIR="$ROOT/backend"
PASS=0; FAIL=0

say()  { printf "\n\033[1;36m== %s\033[0m\n" "$*"; }
ok()   { printf "  \033[32m✓\033[0m %s\n" "$*"; PASS=$((PASS+1)); }
bad()  { printf "  \033[31m✗ %s\033[0m\n" "$*"; FAIL=$((FAIL+1)); }
need() { command -v "$1" >/dev/null 2>&1 || { echo "missing dependency: $1"; exit 2; }; }

need curl; need jq

j() { curl -s "$API$1"; }                                   # GET
p() { local body="${2:-}"; [ -z "$body" ] && body='{}'      # POST (avoids ${2:-{}} brace clash)
      curl -s -X POST "$API$1" -H 'content-type: application/json' -d "$body"; }

# ----- ensure stack is up -----
if [ "$(curl -s -o /dev/null -w '%{http_code}' "$API/healthz" || true)" != "200" ]; then
  say "Backend not up — starting docker-compose stack"
  (cd "$COMPOSE_DIR" && docker compose up -d --build)
fi
say "Waiting for backend health"
for i in $(seq 1 40); do
  [ "$(curl -s -o /dev/null -w '%{http_code}' "$API/healthz" || true)" = "200" ] && { ok "backend healthy"; break; }
  sleep 2
  [ "$i" = "40" ] && { bad "backend never became healthy"; exit 1; }
done

# ----- scenario -----
say "Start a run (wake=5s)"
RID=$(p /runs '{"order_id":"SMOKE","wake_interval_s":5,"max_run_age_s":3600}' | jq -r .run_id)
[ -n "$RID" ] && [ "$RID" != "null" ] && ok "started $RID" || { bad "start failed"; exit 1; }

inject() { p "/runs/$RID/events" "$1" >/dev/null; }

say "Inject events: routine ones must stay asleep, risk ones must act"
inject '{"type":"order_created"}'
inject '{"type":"payment_confirmed"}'      # routine -> stay asleep
inject '{"type":"shipment_created"}'       # routine -> stay asleep
inject '{"type":"shipment_delayed"}'       # risk -> escalate + customer update
inject '{"type":"customer_message_received","payload":{"text":"I demand a refund"}}'
sleep 2

LOG=$(j "/runs/$RID/log")
DBG=$(j "/runs/$RID/log?include_debug=true")

has_action()  { echo "$LOG" | jq -e --arg a "$1" '.entries[] | select(.action==$a)' >/dev/null; }
count_kind()  { echo "$DBG" | jq --arg k "$1" '[.entries[] | select(.kind==$k)] | length'; }

has_action escalate_to_fulfillment_team && ok "shipment_delayed escalated" || bad "no escalation"
has_action send_customer_update          && ok "customer update sent"       || bad "no customer update"

# routine events stayed asleep -> two debug wake_decision entries, and NOT in the normal view
STAYED=$(echo "$DBG" | jq '[.entries[] | select(.kind=="wake_decision" and (.message|test("Stayed asleep")))] | length')
[ "$STAYED" -ge 2 ] && ok "routine events stayed asleep ($STAYED)" || bad "routine events did not stay asleep ($STAYED)"
NORMAL_WAKE=$(echo "$LOG" | jq '[.entries[] | select(.kind=="wake_decision")] | length')
[ "$NORMAL_WAKE" = "0" ] && ok "no wake_decision noise in default view" || bad "wake noise leaked into default view"

# refund classification (rules path, no LLM key) -> escalation present for the customer message
echo "$LOG" | jq -e '.entries[] | select(.trigger=="event:customer_message_received" and .action=="escalate_to_fulfillment_team")' >/dev/null \
  && ok "refund message routed to escalation (rules classifier)" || bad "refund message not escalated"

say "Instruction override: suppress customer messaging"
p "/runs/$RID/instructions" '{"text":"do not message the customer"}' >/dev/null
sleep 1
BEFORE=$(j "/runs/$RID/log" | jq '[.entries[] | select(.action=="send_customer_update")] | length')
inject '{"type":"shipment_delayed"}'   # would normally send a customer update
sleep 2
AFTER=$(j "/runs/$RID/log" | jq '[.entries[] | select(.action=="send_customer_update")] | length')
NEWESC=$(j "/runs/$RID/log" | jq '[.entries[] | select(.action=="escalate_to_fulfillment_team")] | length')
[ "$AFTER" = "$BEFORE" ] && ok "customer update suppressed by instruction" || bad "instruction did not suppress customer update ($BEFORE -> $AFTER)"
[ "$NEWESC" -ge 2 ] && ok "escalation still fired under suppression" || bad "escalation missing"

say "Timer heartbeats are debug-only (Decision #9)"
sleep 6
HB=$(j "/runs/$RID/log?include_debug=true" | jq '[.entries[] | select(.visibility=="debug" and .kind=="action")] | length')
NHB=$(j "/runs/$RID/log" | jq '[.entries[] | select(.message|test("no new action"))] | length')
[ "$HB" -ge 1 ] && ok "stale heartbeats recorded at debug ($HB)" || bad "no debug heartbeats found"
[ "$NHB" = "0" ] && ok "heartbeats absent from default view" || bad "heartbeats leaked into default view"

say "Lifecycle: pause / resume / interrupt"
p "/runs/$RID/pause"     >/dev/null && ok "paused"
p "/runs/$RID/resume"    >/dev/null && ok "resumed"
p "/runs/$RID/interrupt" >/dev/null && ok "interrupted"
sleep 2

say "System-owned completion via terminal event"
inject '{"type":"delivered"}'
sleep 2
ST=$(j "/runs/$RID" | jq -r .run.status)
SUM=$(j "/runs/$RID/log" | jq -r '.entries[] | select(.kind=="summary") | .message')
[ "$ST" = "completed" ] && ok "run completed (system-owned)" || bad "run not completed (status=$ST)"
[ -n "$SUM" ] && ok "final summary written: ${SUM:0:60}..." || bad "no final summary"

say "Manual terminate path"
RID2=$(p /runs '{"order_id":"SMOKE-KILL","wake_interval_s":60,"max_run_age_s":3600}' | jq -r .run_id)
inject2() { p "/runs/$RID2/events" "$1" >/dev/null; }
inject2 '{"type":"payment_failed"}'; sleep 1
p "/runs/$RID2/terminate" '{"reason":"smoke test"}' >/dev/null
sleep 1
ST2=$(j "/runs/$RID2" | jq -r .run.status)
[ "$ST2" = "terminated" ] && ok "run terminated" || bad "terminate failed (status=$ST2)"

# ----- summary -----
printf "\n\033[1m%d passed, %d failed\033[0m\n" "$PASS" "$FAIL"
[ "$FAIL" = "0" ] || exit 1
echo "Local demo smoke test PASSED."
