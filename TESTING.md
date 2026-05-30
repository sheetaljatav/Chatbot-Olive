# Testing Guide

A step-by-step end-to-end test plan. Follow the sections in order: each builds on the previous one.

**Assumption:** Docker Compose is running (`make up` or `make up-d`). All services are healthy (`make health` returns `200`/`"ok"` everywhere).

---

## 1. Smoke test — health endpoints

Run this before anything else. Everything green = infra is wired correctly.

```bash
make health
```

**Expected output:**

```
── chat-api ──────────────────────────
{
    "status": "ok",
    "provider": "gemini"
}
── ingestion-api ─────────────────────
{
    "status": "ok"
}
── web ───────────────────────────────
HTTP 200
```

Or verify each individually with curl:

```bash
curl -s http://localhost:8000/health | python3 -m json.tool
curl -s http://localhost:8001/health | python3 -m json.tool
curl -s -o /dev/null -w "%{http_code}" http://localhost:3000
```

---

## 2. First chat — verify the full pipeline in one shot

This single test exercises every component end-to-end.

### Step 1 — Open the UI

Go to http://localhost:3000. You should see an empty chat input with a **Send** button.

### Step 2 — Send a message

Type:
```
Hello! What is 2 + 2?
```

Press Enter or click **Send**.

**What you should see:**
- Your message appears in a dark bubble on the right.
- An assistant bubble appears on the left and text streams in character-by-character.
- Streaming finishes with the correct answer.

### Step 3 — Verify it landed in Postgres

Open a second terminal:

```bash
make db-counts
```

**Expected:**

```
   t          | count
--------------+-------
 conversations|     1
 messages     |     2   ← user message + assistant message
 inference_logs|    1
```

### Step 4 — Inspect the inference log

```bash
make db-logs
```

**Expected columns with real values:**

| Column | What to check |
|--------|---------------|
| `provider` | `gemini` (or your configured provider) |
| `model` | `gemini-1.5-flash` |
| `status` | `success` |
| `latency_ms` | a positive integer (e.g. 1200) |
| `input` | truncated text of your message |
| `output` | truncated start of the assistant response |

### Step 5 — Verify Redis processed the event

```bash
make redis-stream
```

The stream length should be **0** (the worker consumed and ACKed the event). If it's `1`, wait 2 seconds and retry — the worker may still be processing.

```bash
make redis-pending
```

Should return **empty** (no pending/un-ACKed entries).

---

## 3. Multi-turn conversation

Tests that context window is maintained across turns.

1. In the same chat window from §2, send a follow-up that requires memory:
   ```
   What did I just ask you about?
   ```

2. The assistant should reference your previous question (`2 + 2`). If it says "I don't know what you asked", context is broken — check `CONTEXT_TURN_LIMIT` in `.env`.

3. Send two more messages and verify the conversation remains coherent.

```bash
# Check message count grows correctly:
make db-counts
# messages row should now be 6 (3 pairs)
```

---

## 4. Streaming — Stop button

Tests that cancellation closes the upstream LLM stream and records the event correctly.

1. Type a prompt that produces a long response, e.g.:
   ```
   Write a 500-word essay about the history of the internet.
   ```

2. Click **Stop** within the first 2–3 seconds of streaming.

**What you should see in the UI:**
- Streaming stops mid-sentence.
- The partial text is kept in the conversation bubble.
- A `[cancelled]` marker appears at the end.

**Verify in the database:**

```bash
make db-logs
```

The most recent row should have `status = cancelled`.

---

## 5. Conversation list and resume

Tests the `/conversations` page and resume flow.

### List

1. Go to http://localhost:3000/conversations.
2. You should see the conversations from §2–4, each with a title (auto-generated from the first message), message count, and a status badge.

### Cancel a conversation

1. Click the red **Cancel** button next to an `active` conversation.
2. The status badge should immediately update to `cancelled` (client-side update, no page reload).
3. Verify in the DB:
   ```bash
   make db-counts
   # then check status in psql:
   make psql
   ```
   Inside psql:
   ```sql
   SELECT id, title, status FROM conversations ORDER BY updated_at DESC LIMIT 5;
   \q
   ```
   The conversation's `status` should be `cancelled`.

### Resume

1. Click any conversation title on the list page.
2. You are taken to `/conversations/<id>` with the full history loaded.
3. Send another message — the conversation continues from where it left off, with the correct context.

---

## 6. API endpoint tests (curl)

Use these to test the API directly, independent of the UI.

### 6a — Create a conversation

```bash
curl -s -X POST http://localhost:8000/conversations \
  -H "Content-Type: application/json" \
  -d '{"title": "curl test"}' | python3 -m json.tool
```

Save the `id` field from the response (call it `$CID`):

```bash
CID="<paste-uuid-here>"
```

### 6b — Send a chat message (streaming)

```bash
curl -s -N \
  -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d "{\"conversation_id\": \"$CID\", \"message\": \"Name three planets\"}"
```

You should see a stream of `data: {...}` lines:

```
data: {"type": "start", "conversation_id": "...", ...}
data: {"type": "delta", "text": "Here"}
data: {"type": "delta", "text": " are"}
...
data: {"type": "done", "message_id": "...", "usage": {...}}
```

### 6c — Retrieve conversation with messages

```bash
curl -s http://localhost:8000/conversations/$CID | python3 -m json.tool
```

Expected: the conversation object with a `messages` array containing the user + assistant messages.

### 6d — List all conversations

```bash
curl -s http://localhost:8000/conversations | python3 -m json.tool
```

### 6e — Cancel a conversation via API

```bash
curl -s -X PUT http://localhost:8000/conversations/$CID/cancel | python3 -m json.tool
```

Expected:
```json
{"ok": true, "active_streams_signalled": 0}
```

### 6f — Metrics endpoints

```bash
# Summary (last 60 minutes, default)
curl -s "http://localhost:8000/metrics/summary" | python3 -m json.tool

# Time series (last 30 minutes)
curl -s "http://localhost:8000/metrics/timeseries?window=30" | python3 -m json.tool

# Per-model breakdown
curl -s "http://localhost:8000/metrics/by_model" | python3 -m json.tool
```

**Expected fields in summary:**

```json
{
  "total": 5,
  "success": 4,
  "errors": 0,
  "cancelled": 1,
  "tokens": 1234,
  "p50": 980,
  "p95": 1800,
  "p99": 2200,
  "error_rate": 0.0
}
```

### 6g — Send a log directly to the ingestion API

Bypasses chat-api entirely — tests the ingestion path in isolation.

```bash
curl -s -X POST http://localhost:8001/v1/logs \
  -H "Content-Type: application/json" \
  -d '{
    "events": [{
      "request_id": "00000000-0000-0000-0000-000000000001",
      "provider": "test",
      "model": "test-model",
      "status": "success",
      "started_at": "2025-01-01T00:00:00Z",
      "ended_at":   "2025-01-01T00:00:01Z",
      "prompt_tokens": 10,
      "completion_tokens": 20,
      "input_preview": "hello",
      "output_preview": "world"
    }]
  }' | python3 -m json.tool
```

Expected: `{"accepted": 1, "rejected": 0}`

Wait 2 seconds, then verify it landed:

```bash
make db-logs
# The test-model row should appear at the top.
```

---

## 7. PII redaction

Tests that Presidio strips sensitive data from inference log previews.

### Step 1 — Send a message containing PII

```bash
curl -s -N \
  -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "My email is john.doe@example.com and my phone is 555-867-5309. What should I have for lunch?"}'
```

Wait for the stream to finish.

### Step 2 — Check the inference log preview

```bash
make db-logs
```

The `input` column of the most recent row should show something like:
```
My email is <EMAIL_ADDRESS> and my phone is <PHONE_NUMBER>. What sh…
```

The actual PII values should be gone. The `messages.content` column retains the original (needed for context replay) — this is intentional and noted as a future improvement in `README.md`.

To see the full preview in psql:

```bash
make psql
```

```sql
SELECT input_preview, output_preview
FROM inference_logs
ORDER BY created_at DESC
LIMIT 1;
\q
```

---

## 8. Dashboard

1. Open http://localhost:3000/dashboard.
2. After §2–7 you should have enough data for the panels to render. You should see:
   - **Requests** stat card: a positive number.
   - **p95 latency** stat card: a positive millisecond count.
   - **Requests per minute** line chart: at least one data point.
   - **Per-model breakdown** table: at least one row (your provider/model).

3. The dashboard auto-refreshes every 5 seconds. Send another message in a new tab and watch the counts increment.

---

## 9. Multi-provider switch

Tests that swapping providers requires only an env change and a single service restart.

### Step 1 — Check current provider

```bash
curl -s http://localhost:8000/health | python3 -m json.tool
# "provider": "gemini"
```

### Step 2 — Switch to Ollama (local, free, no key needed)

> Skip this step if you don't have Ollama installed. The same process works for `openai` or `anthropic` with their respective keys.

First, ensure Ollama is running with a model pulled:
```bash
ollama pull llama3.2
ollama serve   # if not already running
```

Edit `.env`:
```
PROVIDER=ollama
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_MODEL=llama3.2
```

Restart only chat-api:
```bash
make restart SERVICE=chat-api
```

### Step 3 — Verify the switch

```bash
curl -s http://localhost:8000/health | python3 -m json.tool
# "provider": "ollama"
```

Send a chat message via the UI or curl. It should work the same way.

```bash
make db-logs
# Most recent row should have provider = "ollama"
```

Switch back when done:
```bash
# restore .env to PROVIDER=gemini, then:
make restart SERVICE=chat-api
```

---

## 10. Worker resilience — backlog drain

Tests that events queued while the worker is down are processed when it comes back up.

### Step 1 — Stop the worker

```bash
docker compose -f infra/docker-compose.yml stop worker
```

### Step 2 — Send a few messages via the UI

Send 3–4 messages. The chat UI should still work normally (the SDK ships to ingestion-api asynchronously; user-facing latency is unaffected).

### Step 3 — Check the stream backlog

```bash
make redis-stream
# Stream length should be > 0 (events waiting to be consumed)
```

### Step 4 — Restart the worker

```bash
docker compose -f infra/docker-compose.yml start worker
```

### Step 5 — Verify the backlog drains

```bash
# Wait 5 seconds, then:
make redis-stream
# Stream length should return to 0

make db-counts
# inference_logs count should have increased
```

---

## 11. Concurrent-cancel signal test

Tests that `PUT /conversations/:id/cancel` interrupts an active stream.

### Step 1 — Start a long stream

In the UI, send:
```
Write a 1000-word poem about the ocean.
```

Do not press Stop yet. Copy the conversation ID from the URL bar: `/conversations/<CID>`.

### Step 2 — Cancel from a second terminal while it streams

```bash
curl -s -X PUT http://localhost:8000/conversations/<CID>/cancel | python3 -m json.tool
```

Expected response:
```json
{"ok": true, "active_streams_signalled": 1}
```

**What you should see in the UI:** the stream stops mid-line. The conversation badge on the list page should change to `cancelled`.

---

## 12. Database inspection reference

Useful psql queries you can run at any time with `make psql`:

```sql
-- All conversations and their status
SELECT id, title, status, updated_at
FROM conversations
ORDER BY updated_at DESC;

-- Messages in a specific conversation (replace the UUID)
SELECT sequence, role, left(content, 80) AS preview, created_at
FROM messages
WHERE conversation_id = '<paste-uuid>'
ORDER BY sequence;

-- Inference logs with latency + token summary
SELECT provider, model, status,
       latency_ms, ttfb_ms,
       prompt_tokens, completion_tokens,
       left(input_preview, 60) AS input
FROM inference_logs
ORDER BY created_at DESC
LIMIT 20;

-- Average latency per provider/model
SELECT provider, model,
       COUNT(*) AS calls,
       ROUND(AVG(latency_ms)) AS avg_ms,
       ROUND(percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)) AS p95_ms
FROM inference_logs
WHERE status = 'success'
GROUP BY provider, model
ORDER BY calls DESC;

-- Error breakdown
SELECT error_code, COUNT(*) AS n
FROM inference_logs
WHERE status = 'error'
GROUP BY error_code
ORDER BY n DESC;

-- Check PII redaction: look for raw emails/phones in previews
SELECT id, input_preview, output_preview
FROM inference_logs
WHERE input_preview LIKE '%@%'
   OR input_preview LIKE '%555%'
ORDER BY created_at DESC
LIMIT 5;
-- Should return 0 rows if redaction is working.
```

---

## 13. Redis inspection reference

```bash
# Open redis-cli:
make redis-cli

# Inside redis-cli:
XLEN llm.events                         # total events in stream
XLEN llm.events.dlq                     # dead-letter queue length (should be 0)
XRANGE llm.events - + COUNT 5           # peek first 5 events
XREVRANGE llm.events + - COUNT 3        # peek last 3 events
XPENDING llm.events workers - + 10      # pending (un-ACKed) per consumer
XINFO GROUPS llm.events                 # consumer group stats
XINFO CONSUMERS llm.events workers      # per-worker delivery counts
```

---

## 14. API reference quick-sheet

All chat-api endpoints at a glance:

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Service + provider liveness |
| `POST` | `/chat` | Stream a chat turn (SSE) |
| `GET` | `/conversations` | List all conversations |
| `POST` | `/conversations` | Create a blank conversation |
| `GET` | `/conversations/{id}` | Get conversation + messages |
| `PUT` | `/conversations/{id}/cancel` | Cancel a conversation |
| `GET` | `/metrics/summary?window=60` | Headline stats |
| `GET` | `/metrics/timeseries?window=60` | Per-minute time series |
| `GET` | `/metrics/by_model?window=60` | Per provider/model breakdown |

Interactive Swagger docs: http://localhost:8000/docs

Ingestion API:

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Redis liveness |
| `POST` | `/v1/logs` | Accept batch of inference events |

Interactive Swagger docs: http://localhost:8001/docs

---

## 15. Pass / Fail checklist

Use this as a final sign-off before submission:

- [ ] `make health` → all three return `ok` / `200`
- [ ] First chat message streams in the UI and appears in `inference_logs`
- [ ] Multi-turn: follow-up message references previous context
- [ ] Stop button halts streaming; `inference_logs.status = 'cancelled'`
- [ ] Conversations list shows all conversations with correct status
- [ ] Resuming a conversation loads history and continues
- [ ] Cancel button on list page sets `status = 'cancelled'` in DB
- [ ] `PUT /conversations/:id/cancel` signals an active stream (`active_streams_signalled: 1`)
- [ ] PII test: email/phone in prompt → redacted in `input_preview`
- [ ] Dashboard at `/dashboard` renders all four panels with real data
- [ ] Metrics `/summary` returns non-zero `total` and positive `p95`
- [ ] Worker kill + restart → backlog in Redis drains to 0 after restart
- [ ] Direct POST to `/v1/logs` → row appears in `inference_logs`
