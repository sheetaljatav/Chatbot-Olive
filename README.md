# Lightweight LLM Inference Logging & Ingestion

A small, end-to-end system around an LLM chatbot:

- **Chatbot UI** (Next.js) with streaming, conversation list, resume, and a stop button.
- **`llm_logger` SDK** — a Python wrapper that captures inference metadata and ships it to an ingestion endpoint without blocking the user-facing request.
- **Ingestion API + Worker** — receives log batches, publishes them to a Redis Stream, redacts PII, and writes to PostgreSQL.
- **Dashboard** for latency / throughput / errors.
- **Docker Compose** for one-command local setup; **Kubernetes** manifests for self-hosted deploys.

```
┌─────────┐  POST /chat (SSE)   ┌──────────┐
│ Next.js │ ──────────────────▶ │ chat-api │ ─── Gemini / OpenAI / Anthropic / Ollama
│   UI    │ ◀───────  stream  ─ │          │
└─────────┘                     └────┬─────┘
                                     │ llm_logger SDK
                                     │ batched POST
                                     ▼
                              ┌──────────────┐  XADD   ┌──────────────────┐
                              │ ingestion-api│ ──────▶ │ Redis Stream     │
                              └──────────────┘         │  llm.events      │
                                                       └────────┬─────────┘
                                                                ▼
                                                       ┌──────────────┐
                                                       │   worker     │  PII redact
                                                       │ (consumer    │  → upsert
                                                       │   group)     │
                                                       └────┬─────────┘
                                                            ▼
                                                       ┌──────────────┐
                                                       │ PostgreSQL   │
                                                       └──────────────┘
```

---

## Setup

### 1. Prerequisites
- Docker (24+) with Docker Compose v2.
- A Gemini API key (free tier works fine). OpenAI / Anthropic / local Ollama are optional drop-ins.

### 2. Configure
```bash
cp .env.example .env
# edit .env and set GEMINI_API_KEY=...
```

### 3. Run
```bash
docker compose --env-file .env -f infra/docker-compose.yml up --build
```
That starts six containers — `postgres`, `redis`, `ingestion-api`, `worker`, `chat-api`, `web` — with healthchecks gating dependent services.

| Service        | URL                                  |
| -------------- | ------------------------------------ |
| Chat UI        | http://localhost:3000                |
| Dashboard      | http://localhost:3000/dashboard      |
| Conversations  | http://localhost:3000/conversations  |
| Chat API       | http://localhost:8000/health         |
| Ingestion API  | http://localhost:8001/health         |
| Postgres       | localhost:5432 (chatbot / chatbot)   |

### 4. Switching providers
Set `PROVIDER` in `.env` to one of `gemini | openai | anthropic | ollama`, supply the corresponding API key (or `OLLAMA_BASE_URL`), and restart `chat-api`.

### 5. Kubernetes (self-hosted, free, via kind)
```bash
kind create cluster
# build + load images into kind
docker build -f apps/chat-api/Dockerfile      -t chatbot/chat-api:latest      .
docker build -f apps/ingestion-api/Dockerfile -t chatbot/ingestion-api:latest .
docker build -f apps/worker/Dockerfile        -t chatbot/worker:latest        .
docker build -f apps/web/Dockerfile           -t chatbot/web:latest           .
for img in chat-api ingestion-api worker web; do kind load docker-image chatbot/$img:latest; done

# install nginx ingress, then:
cp infra/k8s/secret.example.yaml infra/k8s/secret.yaml   # fill in keys
kubectl apply -f infra/k8s/secret.yaml

# init.sql lives outside infra/k8s (it is shared with docker-compose), so the
# configMapGenerator references a parent path. Render with the load restrictor
# relaxed and pipe to apply — plain `kubectl apply -k` cannot relax it.
kubectl kustomize --load-restrictor LoadRestrictionsNone infra/k8s | kubectl apply -f -
```

---

## Architecture overview

Four moving parts:

1. **`chat-api`** runs the chat. For every user turn it persists the user message, calls the provider via the SDK, streams chunks back over SSE, and on completion persists the assistant message. Cancellation flows two ways: client disconnect (detected via `request.is_disconnected()`) and an explicit `PUT /conversations/:id/cancel` (signalled via an in-memory event registry).
2. **`llm_logger`** is the SDK the chat uses. The `observe()` async context manager captures start/end timestamps, TTFB, token usage, status, and previews; events are enqueued into a bounded buffer and shipped asynchronously by a single background task. Logging failures never break the chat.
3. **`ingestion-api`** is a thin façade: validate the payload, `XADD` it to a Redis Stream, return 202. No DB write on the hot path.
4. **`worker`** runs a Redis Streams consumer group. For each entry: parse → PII-redact previews via Presidio → upsert into Postgres. Failed entries are retried (per Redis pending-entry counters) and after N attempts moved to a DLQ stream.

### Why these choices

- **Async, fire-and-forget logging.** The chat hot path never waits on logging; the SDK's enqueue is non-blocking and bounded.
- **Redis Streams between API and DB.** Absorbs bursts; gives us consumer groups (horizontal scaling) and a built-in pending list (retries) without standing up Kafka.
- **Workers do PII + DB.** Keeps the public-facing API tiny and stateless. Adding more workers is just adding pods.
- **One Postgres for chat + logs.** Simpler ops, joins between messages and logs come for free. Partition `inference_logs` by month once volume justifies it.
- **Custom dashboard, not Grafana.** Same UX as the rest of the app; one fewer container. Aggregation runs as SQL in `chat-api` and is cached for 5s on the client. Grafana would be a drop-in replacement (Postgres data source) at higher scale.

---

## Schema design

Three tables — `conversations`, `messages`, `inference_logs`. Normalized just enough; flexibility lives in a single `JSONB` column.

```
conversations (id, title, status, created_at, updated_at)
messages       (id, conversation_id, role, content, sequence, created_at)
inference_logs (id, request_id UNIQUE, conversation_id, message_id,
                provider, model, status, error_code, error_message,
                started_at, ended_at, latency_ms (GENERATED), ttfb_ms,
                prompt_tokens, completion_tokens, total_tokens,
                input_preview, output_preview, metadata JSONB)
```

Key decisions:

- **Messages are first-class.** They drive UI replay *and* the model's context window. Inference logs are a parallel observability stream that joins via `message_id` but has its own lifecycle (deleting logs doesn't break chat).
- **`request_id UNIQUE` on `inference_logs`** — the SDK generates this, so retries from the SDK or the worker are idempotent.
- **`latency_ms` is a generated column** — always consistent with the timestamps. `ttfb_ms` is captured separately because for streaming responses it's the more useful number.
- **`JSONB metadata`** — provider-specific extras (`finish_reason`, `temperature`, safety ratings, etc.) without schema-migration churn. Queryable via JSON operators when needed.
- **Triggers** keep `conversations.updated_at` fresh on new messages, so the list view ordering "just works."

---

## Tradeoffs

| Decision | Win | Cost |
| --- | --- | --- |
| Redis Streams over Kafka | Tiny operational footprint; one container, consumer groups, DLQ pattern out of the box | Less throughput headroom than Kafka; single-node Redis is the SPOF (mitigated by Sentinel/Cluster) |
| Single Postgres for chat + logs | Simpler ops, joins are free | At scale, logs will dominate writes; partition or split into a separate logging DB |
| Custom dashboard in Next.js | Cohesive UX, fewer services | No multi-tenant cuts, no alerting — Grafana would replace this in prod |
| Fire-and-forget SDK with bounded buffer | Zero user-facing latency cost for logging | On overflow, oldest events drop. Acceptable for observability; not for billing-grade auditing |
| Storing `input_preview` / `output_preview` (truncated) | Tiny rows, faster scans, less PII surface | Full prompt/response not in logs; live in `messages` table (post-redaction) |
| Postgres-native `pg_partman` / time partitioning not used | Faster to ship | Once `inference_logs` exceeds tens of millions of rows, dashboard queries slow; partition then |
| `text()` SQL instead of full ORM | Greppable, no migration tooling required for a 3-table schema | Less type safety; SQLAlchemy Core/ORM gives more compile-time help at the cost of indirection |

---

## What I'd improve with more time

- **Partitioning** `inference_logs` by `created_at` month + a retention policy.
- **OpenTelemetry**: spans on the SDK side that propagate trace context end-to-end, exported to a self-hosted Tempo / Jaeger.
- **Multi-tenant auth** (currently no users; conversations are global). Add API keys + per-tenant rate limits at the ingestion layer.
- **Token cost estimation** in `metadata` using a pricing table per (provider, model).
- **Grafana + Prometheus** for the on-call view, alongside the in-app dashboard for product use.
- **PII redaction profile per environment** — currently global. In real use you'd want stricter rules in prod and looser in dev.
- **Idempotent client retries from the chat UI** if a stream drops mid-response.
- **Production-grade Redis** (Sentinel or managed) and read replicas for Postgres for the dashboard reads.

See [ARCHITECTURE.md](./ARCHITECTURE.md) for the deeper notes on ingestion flow, logging strategy, scaling, and failure handling.
