#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-https://voiceconnect-api-271365674375.us-central1.run.app}"
TEST_EMAIL="${TEST_EMAIL:-test-$(date +%s)@example.com}"
TEST_PASSWORD="${TEST_PASSWORD:-TestPassword123}"
TEST_NAME="${TEST_NAME:-Test Client}"
TEST_WEBSITE="${TEST_WEBSITE:-https://example.com}"
TEST_AREA_CODE="${TEST_AREA_CODE:-512}"

ADMIN_EMAIL="${ADMIN_EMAIL:-}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-}"

if ! command -v curl >/dev/null 2>&1; then
  echo "ERROR: curl is required." >&2
  exit 127
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: jq is required. Install with: brew install jq" >&2
  exit 127
fi

hr() { printf '\n%s\n' "------------------------------------------------------------"; }
ok() { printf 'PASS: %s\n' "$1"; }
fail() { printf 'FAIL: %s\n' "$1"; exit 1; }

call_json() {
  local method="$1"
  local path="$2"
  local token="${3:-}"
  local body="${4:-}"

  local tmp
  tmp="$(mktemp)"
  local code

  if [[ -n "$token" ]]; then
    if [[ -n "$body" ]]; then
      code="$(curl -sS -o "$tmp" -w '%{http_code}' -X "$method" "${BASE_URL}${path}" \
        -H "Authorization: Bearer $token" \
        -H "Content-Type: application/json" \
        -d "$body")"
    else
      code="$(curl -sS -o "$tmp" -w '%{http_code}' -X "$method" "${BASE_URL}${path}" \
        -H "Authorization: Bearer $token")"
    fi
  else
    if [[ -n "$body" ]]; then
      code="$(curl -sS -o "$tmp" -w '%{http_code}' -X "$method" "${BASE_URL}${path}" \
        -H "Content-Type: application/json" \
        -d "$body")"
    else
      code="$(curl -sS -o "$tmp" -w '%{http_code}' -X "$method" "${BASE_URL}${path}")"
    fi
  fi

  printf '%s\n' "$code"
  cat "$tmp"
  rm -f "$tmp"
}

do_request() {
  local method="$1"
  local path="$2"
  local token="${3:-}"
  local body="${4:-}"
  local raw

  raw="$(call_json "$method" "$path" "$token" "$body")"
  HTTP_CODE="$(printf '%s\n' "$raw" | head -n 1)"
  HTTP_BODY="$(printf '%s\n' "$raw" | tail -n +2)"
}

expect_http() {
  local expected="$1"
  local got="$2"
  local label="$3"
  if [[ "$got" != "$expected" ]]; then
    fail "$label (expected HTTP $expected, got $got)"
  fi
  ok "$label"
}

hr
echo "VoiceConnect curl test"
echo "Base URL: $BASE_URL"

# 0) Health
hr
echo "[0] GET /health"
do_request GET "/health"
expect_http 200 "$HTTP_CODE" "Health endpoint"
echo "$HTTP_BODY" | jq . >/dev/null
ok "Health response is JSON"

# 1) Signup a test client
hr
echo "[1] POST /auth/signup"
signup_payload="$(jq -nc \
  --arg name "$TEST_NAME" \
  --arg website "$TEST_WEBSITE" \
  --arg email "$TEST_EMAIL" \
  --arg password "$TEST_PASSWORD" \
  --arg area_code "$TEST_AREA_CODE" \
  '{name:$name, website_url:$website, email:$email, password:$password, area_code:$area_code}')"

do_request POST "/auth/signup" "" "$signup_payload"
expect_http 201 "$HTTP_CODE" "Signup"

echo "$HTTP_BODY" | jq . >/dev/null
ok "Signup response is JSON"

CLIENT_TOKEN="$(echo "$HTTP_BODY" | jq -r '.access_token // empty')"
CLIENT_ID="$(echo "$HTTP_BODY" | jq -r '.client_id // empty')"

[[ -n "$CLIENT_TOKEN" ]] || fail "Signup did not return access_token"
[[ -n "$CLIENT_ID" ]] || fail "Signup did not return client_id"
ok "Received client token and client ID"

# 2) Verify client profile includes plan/usage/email method
hr
echo "[2] GET /me/profile"
do_request GET "/me/profile" "$CLIENT_TOKEN"
expect_http 200 "$HTTP_CODE" "Client profile"

echo "$HTTP_BODY" | jq . >/dev/null

plan_key="$(echo "$HTTP_BODY" | jq -r '.plan.key // empty')"
monthly_minutes="$(echo "$HTTP_BODY" | jq -r '.usage.monthly_minutes // empty')"
email_send_method="$(echo "$HTTP_BODY" | jq -r '.email_send_method // empty')"

[[ "$plan_key" == "starter" ]] || fail "Expected default plan starter, got '$plan_key'"
[[ -n "$monthly_minutes" ]] || fail "usage.monthly_minutes missing"
[[ -n "$email_send_method" ]] || fail "email_send_method missing"
ok "Profile includes plan, usage, and email_send_method"

# 3) Send mock post-call webhook with valid schema
hr
echo "[3] POST /elevenlabs/post-call"
CONVERSATION_ID="conv_$(date +%s)"
CALL_SID="CA$(date +%s)"

post_call_payload="$(jq -nc \
  --arg conv "$CONVERSATION_ID" \
  --arg call_sid "$CALL_SID" \
  --arg client_id "$CLIENT_ID" \
  '{
    type: "post_call_transcription",
    event_timestamp: (now | floor),
    data: {
      conversation_id: $conv,
      status: "completed",
      agent_id: "test-agent",
      metadata: { body: { From: "+15125550199", To: "+15125550000", CallSid: $call_sid, CallDuration: 300 } },
      conversation_initiation_client_data: { dynamic_variables: { client_id: $client_id, call_sid: $call_sid, called_number: "+15125550000", caller_id: "+15125550199" } },
      analysis: {
        transcript_summary: "Test call summary",
        data_collection_results: {
          phone_number: { value: "+15125550199" },
          branch: { value: "JOB_SEEKER" },
          email_address: { value: "caller@example.com" }
        }
      },
      transcript: [
        { role: "user", message: "Hello", time_in_call_seconds: 10 },
        { role: "agent", message: "Hi", time_in_call_seconds: 20 }
      ]
    }
  }')"

do_request POST "/elevenlabs/post-call" "" "$post_call_payload"
expect_http 200 "$HTTP_CODE" "Post-call webhook"
echo "$HTTP_BODY" | jq . >/dev/null
ok "Post-call response is JSON"

# 4) Verify usage updated
hr
echo "[4] GET /me/profile after post-call"
do_request GET "/me/profile" "$CLIENT_TOKEN"
expect_http 200 "$HTTP_CODE" "Client profile after post-call"

monthly_minutes_2="$(echo "$HTTP_BODY" | jq -r '.usage.monthly_minutes // 0')"
call_count_2="$(echo "$HTTP_BODY" | jq -r '.usage.call_count // 0')"

awk "BEGIN {exit !($monthly_minutes_2 > 0)}" || fail "monthly_minutes did not increase"
awk "BEGIN {exit !($call_count_2 >= 1)}" || fail "call_count did not increase"
ok "Usage updated after post-call"

# 5) Optional admin checks
hr
echo "[5] Optional admin checks (/api/clients and /api/clients/{id}/calls)"
if [[ -n "$ADMIN_EMAIL" && -n "$ADMIN_PASSWORD" ]]; then
  admin_login_payload="$(jq -nc --arg email "$ADMIN_EMAIL" --arg password "$ADMIN_PASSWORD" '{email:$email, password:$password}')"
  do_request POST "/auth/login" "" "$admin_login_payload"
  expect_http 200 "$HTTP_CODE" "Admin login"

  ADMIN_TOKEN="$(echo "$HTTP_BODY" | jq -r '.access_token // empty')"
  [[ -n "$ADMIN_TOKEN" ]] || fail "Admin login did not return token"

  do_request GET "/api/clients" "$ADMIN_TOKEN"
  expect_http 200 "$HTTP_CODE" "Admin list clients"

  echo "$HTTP_BODY" | jq . >/dev/null
  ok "Admin clients response is JSON"

  do_request GET "/api/clients/${CLIENT_ID}/calls" "$ADMIN_TOKEN"
  expect_http 200 "$HTTP_CODE" "Admin client calls"
  calls_len="$(echo "$HTTP_BODY" | jq 'length')"
  awk "BEGIN {exit !($calls_len >= 1)}" || fail "Expected at least 1 call in admin calls endpoint"
  ok "Admin calls endpoint returned data"
else
  echo "Skipping admin checks. Set ADMIN_EMAIL and ADMIN_PASSWORD to enable."
fi

hr
echo "All requested curl tests passed."
echo "Test account: $TEST_EMAIL"
echo "Client ID: $CLIENT_ID"
