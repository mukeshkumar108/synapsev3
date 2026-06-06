#!/usr/bin/env bash
set -euo pipefail

if [ "${1:-}" = "" ]; then
  echo "usage: $0 <base_url> [user_id] [day] [now_iso]"
  exit 1
fi

BASE_URL="${1%/}"
USER_ID="${2:-smoke-user}"
DAY="${3:-$(date +%F)}"
NOW_ISO="${4:-$(date -u +"%Y-%m-%dT%H:%M:%SZ")}"

echo "== health =="
curl -fsS "$BASE_URL/health"
echo

echo "== v3 health =="
curl -fsS "$BASE_URL/v3/health"
echo

echo "== schedule =="
curl -fsS "$BASE_URL/v3/ops/schedule/today?user_id=$USER_ID&day=$DAY"
echo

echo "== due tasks =="
curl -fsS "$BASE_URL/v3/ops/tasks/due?user_id=$USER_ID&now=$NOW_ISO"
echo

echo "== pending reminders =="
curl -fsS "$BASE_URL/v3/ops/reminders/pending?user_id=$USER_ID"
echo

echo "== active habits =="
curl -fsS "$BASE_URL/v3/ops/habits/active?user_id=$USER_ID"
echo

echo "== habit status =="
curl -fsS "$BASE_URL/v3/ops/habits/status?user_id=$USER_ID&day=$DAY"
echo

echo "== open threads =="
curl -fsS "$BASE_URL/v3/ops/threads/open?user_id=$USER_ID"
echo
