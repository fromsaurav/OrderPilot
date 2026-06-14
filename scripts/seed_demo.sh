#!/usr/bin/env bash
# Seed baseline runs so the UI isn't empty when opened. Targets the cloud API by default
# (terraform output), or pass a base URL: ./scripts/seed_demo.sh http://1.2.3.4:30080
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API="${1:-${API:-$(terraform -chdir="$ROOT/terraform" output -raw api_nodeport_url 2>/dev/null || echo http://localhost:8000)}}"
echo "Seeding against $API"

post() { curl -s -X POST "$API$1" -H 'content-type: application/json' -d "${2:-{}}"; }
start() { post /runs "{\"order_id\":\"$1\",\"wake_interval_s\":${2:-30},\"max_run_age_s\":86400}" | jq -r .run_id; }
ev()    { post "/runs/$1/events" "{\"type\":\"$2\"${3:+,\"payload\":$3}}" >/dev/null; }

# 1. A healthy order progressing then delivered (completed + final summary).
R1=$(start ORD-DELIVERED 30); ev "$R1" order_created; ev "$R1" payment_confirmed; ev "$R1" shipment_created; sleep 1; ev "$R1" delivered

# 2. A delayed shipment -> escalation + customer update (running).
R2=$(start ORD-DELAYED 30); ev "$R2" order_created; ev "$R2" payment_confirmed; sleep 1; ev "$R2" shipment_delayed

# 3. A refund + customer message (running, shows actions + classification).
R3=$(start ORD-REFUND 30); ev "$R3" order_created; ev "$R3" refund_requested
ev "$R3" customer_message_received '{"text":"This is unacceptable, I want a refund now"}'

# 4. A payment failure then paused (shows paused lifecycle state).
R4=$(start ORD-PAUSED 30); ev "$R4" order_created; ev "$R4" payment_failed; sleep 1
post "/runs/$R4/pause" >/dev/null

# 5. A run started with an instruction that changes behavior (escalate delays immediately).
R5=$(post /runs '{"order_id":"ORD-INSTRUCT","wake_interval_s":30,"max_run_age_s":86400,"instructions":["escalate delays immediately"]}' | jq -r .run_id)
ev "$R5" order_created; sleep 1; ev "$R5" shipment_delayed

sleep 2
echo "Seeded runs:"
curl -s "$API/runs" | jq -r '.runs[] | "  \(.status)\t\(.order_id)\t\(.run_id)"' | column -t -s $'\t'
