#!/usr/bin/env bash
# Drive Temporal worker CPU up to trigger the HPA, then stop so it scales back down.
# Creates many runs and floods them with events for a while; the worker must process all the
# resulting workflow tasks + activities, which raises its CPU past the HPA target.
#
#   watch in one terminal:   KUBECONFIG=./kubeconfig kubectl -n orderpilot get hpa -w
#   run this in another:     ./scripts/load_test.sh
#
# Tunables: RUNS (default 60), DURATION seconds of load (default 150), API base.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API="${API:-$(terraform -chdir="$ROOT/terraform" output -raw api_nodeport_url 2>/dev/null || echo http://localhost:8000)}"
RUNS="${RUNS:-60}"
DURATION="${DURATION:-150}"
EVENTS=(payment_failed shipment_delayed refund_requested customer_message_received payment_confirmed shipment_created)

echo "Target API: $API"
echo "Creating $RUNS load runs..."
ids=()
for i in $(seq 1 "$RUNS"); do
  id=$(curl -s -X POST "$API/runs" -H 'content-type: application/json' \
        -d "{\"order_id\":\"LOAD-$i\",\"wake_interval_s\":5,\"max_run_age_s\":3600}" | jq -r .run_id)
  [ -n "$id" ] && [ "$id" != "null" ] && ids+=("$id")
done
echo "  created ${#ids[@]} runs"

echo "Flooding events for ${DURATION}s  (watch: kubectl -n orderpilot get hpa -w)"
end=$((SECONDS + DURATION))
batches=0
while [ "$SECONDS" -lt "$end" ]; do
  for id in "${ids[@]}"; do
    t=${EVENTS[$RANDOM % ${#EVENTS[@]}]}
    curl -s -X POST "$API/runs/$id/events" -H 'content-type: application/json' -d "{\"type\":\"$t\"}" >/dev/null &
  done
  wait
  batches=$((batches + 1))
  printf "\r  sent %d batches (~%d events)   " "$batches" "$((batches * ${#ids[@]}))"
done

echo
echo "Load stopped. Worker CPU will fall; the HPA scales replicas back down within ~1-2 min."
echo "Terminating load runs..."
for id in "${ids[@]}"; do
  curl -s -X POST "$API/runs/$id/terminate" -H 'content-type: application/json' -d '{"reason":"load test done"}' >/dev/null &
done
wait
echo "done."
