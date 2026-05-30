# Architecture Notes

## Ingestion flow

```
chat-api (during a chat turn)
  │
  │   llm_logger.observe(...) context:
  │     ├─ records started_at (UTC) + perf_counter()
  │     ├─ yields handle for caller to fill in input/output/usage/metadata
  │     ├─ on first streamed chunk: mark_first_token() → captures ttfb
  │     ├─ on exit: builds InferenceEvent (status = success | error | cancelled)
  │     └─ shipper.enqueue(event)  ← O(1), non-blocking
  │
  ▼
shipper background task (one per chat-api process)
  ├─ awaits batch_size events  OR  flush_interval_ms timeout
  ├─ POST /v1/logs with the batch (JSON, pydantic-typed)
  ├─ retries 5xx with exp backoff
  └─ on persistent failure, re-queues events at the front of the buffer
                                             ▼
                              ingestion-api (FastAPI)
                                ├─ Pydantic validates IngestRequest
                                ├─ pipelines XADD per event into Redis Stream
                                │  llm.events with approximate maxlen=100k
                                └─ returns 202 Accepted
                                             ▼
                                worker (Redis consumer group "workers")
                                  ├─ XREADGROUP > with block=5s, count=32
                                  ├─ for each entry:
                                  │   ├─ parse via Pydantic (drop to DLQ if invalid)
                                  │   ├─ PII-redact previews via Presidio
                                  │   ├─ upsert into inference_logs (on
                                  │   │   request_id conflict → update)
                                  │   └─ XACK
                                  ├─ on exception:
                                  │   ├─ retries via Redis pending-entries
                                  │   └─ after max_retries → XADD to DLQ + XACK
                                  └─ XAUTOCLAIM with min_idle=30s reclaims
                                     orphaned entries from crashed workers
```

The hot path the user feels is **just** the LLM call. Everything else — logging, redaction, DB writes — happens off the request thread.

## Logging strategy

- **What's captured per call:** `request_id` (idempotency), `provider`, `model`, `status`, `error_code/message`, `started_at`, `ended_at`, `ttfb_ms`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `input_preview` (truncated, ≤500 chars), `output_preview` (truncated), `metadata` (free-form JSON for `finish_reason`, etc.), `conversation_id`, `message_id`.
- **Where time is measured:** `started_at` is wall-clock (UTC) on entering `observe()`; `ended_at` on exit. `ttfb_ms` is the delta between `started_perf` and the first `mark_first_token()` call — the metric that actually matters for streaming UX.
- **Idempotency:** the SDK generates `request_id` once per `observe()`; the DB `UNIQUE (request_id)` plus `ON CONFLICT UPDATE` means duplicates from any retry layer (SDK shipper, Redis re-delivery, worker retry) converge to a single row.
- **Backpressure:** SDK buffer is bounded; on overflow, oldest entries drop (the chat is still served — observability gaps are tolerable; user-visible failures are not). A `dropped` counter is incremented for visibility.
- **Failure isolation:** every step in the SDK swallows internal exceptions and logs them. The chat path can never raise because of a logging bug.

## Scaling considerations

- **chat-api** is stateless except for the in-memory cancellation registry. Behind a load balancer the registry doesn't span pods, but cancel-from-other-pod is a fringe case — the simpler fix when it matters is replacing the in-process registry with a Redis pub/sub channel keyed by conversation id.
- **ingestion-api** is stateless and trivially horizontal. Throughput is limited by Redis `XADD` (~100k ops/s on a single node).
- **worker** scales by adding pods; the consumer group divides entries automatically. Each worker should keep `WORKER_BATCH_COUNT` modest so that a single bad batch can't stall many entries.
- **Postgres** is the only stateful piece that needs care.
  - Hot writes: `inference_logs`. Time-partition by month (`pg_partman`) once row counts pass ~10M.
  - Hot reads: dashboard aggregations. Move them to a read replica and add covering indices on `(created_at)` for the time-series query and `(provider, model, created_at)` for per-model breakdowns.
- **Redis** is a SPOF at single-node. For production use either Redis Sentinel or a managed Redis with persistence enabled.

## Failure handling assumptions

| Failure | Behavior | Loss? |
| --- | --- | --- |
| Provider 5xx / timeout | `observe()` catches, logs `status=error` with `error_code=ExceptionClass` and `error_message`. SDK still ships the event. | None (the failure is recorded). |
| User cancels mid-stream | Frontend `AbortController` closes the SSE; chat-api detects via `is_disconnected()`; partial assistant content is persisted; `inference_logs.status='cancelled'`. | Only the un-streamed remainder. |
| `PUT /conversations/:id/cancel` from elsewhere | `CancellationRegistry` signals all active streams for that conversation; same path as above. | Same. |
| Ingestion API down | SDK shipper retries with backoff. After `max_retries`, the batch is re-queued at the buffer head. If down for long enough that the bounded buffer overflows, oldest events drop. | Observability gap (oldest first). Chat still works. |
| Redis down | Ingestion API returns 5xx; SDK retries. Workers' `XREADGROUP` errors are caught with a 1s sleep. | None if Redis comes back before SDK buffer overflows. |
| Worker crashes mid-event | Entry stays in Redis "pending" list (un-XACK'd). On any worker's next poll, `XAUTOCLAIM` (min_idle=30s) reclaims it. | None. |
| Worker fails repeatedly on the same entry | After `WORKER_MAX_RETRIES` deliveries (tracked by Redis `times_delivered`), the entry is XADD'd to `llm.events.dlq` with the reason and acked off the main stream. | The event is parked for offline inspection rather than blocking the stream. |
| Postgres down | Worker's upsert raises; the entry is not acked and Redis will re-deliver. Backlog accumulates in the stream until Postgres recovers. | None (events stay queued). |
| SDK process crash before flush | Up to `buffer_max` events lost. Acceptable tradeoff for non-blocking observability; for billing-grade auditing, swap in a disk-backed queue. | Last few events. |

## PII redaction

- Applied in the **worker**, not the SDK. Two reasons: (a) keep the SDK light (no spaCy / Presidio dependency for every chat-api process); (b) the worker has the central place to enforce a policy.
- Redacts `input_preview`, `output_preview` on the inference event. The `messages.content` column is **not** currently redacted on insert because it's needed verbatim for context replay; a stricter mode would store a redacted shadow column for analytics. (Listed as an improvement in the README.)
- Detects `EMAIL_ADDRESS, PHONE_NUMBER, CREDIT_CARD, US_SSN, IP_ADDRESS` by default; configurable via `PII_ENTITIES`.

## Streaming

- Chat-api emits SSE with one JSON object per `data:` line. Frontend parses with a small generator (`lib/stream.ts`) that handles partial chunks across reads.
- The provider abstraction (`packages/llm_logger/llm_logger/providers/base.py`) normalizes every backend to an async iterator of `LLMStreamChunk`. Final chunk carries usage + finish_reason so we can record both even when the provider sends them out-of-band.
- Nginx ingress in k8s sets `proxy-buffering: off` so SSE bytes reach the browser immediately.

## What this isn't

- An auth system. Conversations are global. Anyone with the URL sees the list.
- A multi-tenant billing pipeline.
- A production observability stack (no Prometheus, no Sentry). The dashboard is for the assignment's "latency + throughput + errors" requirement and is fine for a small deploy.
