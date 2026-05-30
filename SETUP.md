# Setup & Deploy Guide

This guide covers three paths:

- **[A] Docker Compose](#a-docker-compose-recommended)** — one command, everything in containers. ✅ Start here.
- **[B] Local Dev (no Docker)](#b-local-dev-no-docker)** — run each service on the host for faster iteration.
- **[C] Kubernetes (kind)](#c-kubernetes-kind)** — self-hosted k8s on your laptop using kind (free).

---

## Prerequisites

| Tool | Min version | Check |
|------|-------------|-------|
| Docker Desktop (or Docker Engine + Compose plugin) | 24+ | `docker --version` |
| Docker Compose v2 | 2.20+ | `docker compose version` |
| GNU Make | any | `make --version` |
| A Gemini API key (free tier) | — | [aistudio.google.com](https://aistudio.google.com) → Get API key |

> **Other LLM providers** (OpenAI, Anthropic, Ollama) are supported — see [Switching providers](#switching-providers).

---

## A. Docker Compose (recommended)

### 1 — Get the code

```bash
cd /path/to/Chatbot          # already done; this is your repo root
```

### 2 — Configure environment

```bash
cp .env.example .env
```

Open `.env` in any editor and set your Gemini key:

```
GEMINI_API_KEY=AIza...your-key-here...
```

That's the only required change. Every other value has a working default.

<details>
<summary>What the other variables mean</summary>

| Variable | Default | Purpose |
|----------|---------|---------|
| `PROVIDER` | `gemini` | Active LLM backend. One of `gemini`, `openai`, `anthropic`, `ollama` |
| `GEMINI_MODEL` | `gemini-1.5-flash` | Model name forwarded to Gemini |
| `POSTGRES_PASSWORD` | `chatbot` | Postgres password (only for local Docker) |
| `PII_REDACTION_ENABLED` | `true` | Toggle Presidio PII redaction in the worker |
| `CONTEXT_TURN_LIMIT` | `12` | How many recent messages to send to the LLM |
| `SDK_BATCH_SIZE` | `20` | How many inference events to batch before shipping |
| `SDK_FLUSH_INTERVAL_MS` | `500` | Max wait before flushing a partial batch |

</details>

### 3 — Start everything

```bash
make up
```

This is equivalent to:
```bash
docker compose -f infra/docker-compose.yml --env-file .env up --build
```

**First run takes 3–8 minutes** — Docker pulls base images and the worker installs spaCy + downloads the English NER model. Subsequent starts are under 30 seconds (cached layers).

You'll see logs from all six services interleaved. Watch for these ready signals:

```
postgres        | database system is ready to accept connections
redis           | Ready to accept connections tcp
ingestion-api   | Uvicorn running on http://0.0.0.0:8001
worker          | created consumer group workers on llm.events
worker          | worker worker-1 consuming llm.events
chat-api        | chat-api ready (provider=gemini)
web             | Listening on port 3000
```

> **Tip:** To run in the background instead, use `make up-d` — then `make logs` to follow logs.

### 4 — Verify all services are healthy

Open a second terminal (keep the compose logs running in the first) and run:

```bash
make health
```

Expected output:

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

If any service shows `FAIL`, check the [Troubleshooting](#troubleshooting) section.

### 5 — Open the app

| URL | What it is |
|-----|-----------|
| http://localhost:3000 | Chat UI |
| http://localhost:3000/conversations | Conversation list (cancel / resume) |
| http://localhost:3000/dashboard | Latency / throughput / errors |
| http://localhost:8000/docs | Chat API interactive docs (Swagger) |
| http://localhost:8001/docs | Ingestion API interactive docs |

### 6 — Stop

```bash
# Stop containers, keep Postgres data:
make down

# Full reset (wipes the Postgres volume too):
make down-v
```

---

## Switching providers

Edit `.env`, change `PROVIDER` and supply the matching key, then restart just chat-api:

```bash
# OpenAI
PROVIDER=openai
OPENAI_API_KEY=sk-...

# Anthropic
PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...

# Local Ollama (model must already be pulled in Ollama)
PROVIDER=ollama
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_MODEL=llama3.2
```

```bash
make restart SERVICE=chat-api
```

> The ingestion pipeline, worker, and frontend need no restart — only chat-api reads the provider setting.

---

## B. Local Dev (no Docker)

Use this when you want hot-reload on code changes without rebuilding images.

### Prerequisites

| Tool | Min version |
|------|-------------|
| Python | 3.11+ |
| Node.js | 20+ |
| Postgres | 15+ (running locally) |
| Redis | 7+ (running locally) |

### 1 — Start Postgres + Redis

If you have them installed locally:

```bash
# macOS with Homebrew
brew services start postgresql@16
brew services start redis
```

Or use Docker just for the data stores (no other services):

```bash
docker run -d --name pg  -p 5432:5432 -e POSTGRES_USER=chatbot -e POSTGRES_PASSWORD=chatbot -e POSTGRES_DB=chatbot postgres:16-alpine
docker run -d --name red -p 6379:6379 redis:7-alpine
```

### 2 — Initialise the schema

```bash
psql postgresql://chatbot:chatbot@localhost:5432/chatbot -f infra/postgres/init.sql
```

### 3 — Install the SDK (shared package)

```bash
make dev-sdk
# or: pip install -e packages/llm_logger
```

### 4 — Start each service in its own terminal

**Terminal 1 — Ingestion API:**

```bash
export GEMINI_API_KEY=AIza...    # needed by chat-api, not here, but handy to set once
make dev-ingestion
```

**Terminal 2 — Worker:**

```bash
make dev-worker
```

**Terminal 3 — Chat API:**

```bash
export GEMINI_API_KEY=AIza...
make dev-chat
```

**Terminal 4 — Web:**

```bash
make dev-web
```

All four support hot-reload (`--reload` for uvicorn, `next dev` for the frontend). Edit any Python or TypeScript file and the process picks up the change within ~1 second.

---

## C. Kubernetes (kind)

This creates a self-hosted k8s cluster on your laptop using [kind](https://kind.sigs.k8s.io/) (Kubernetes in Docker) — completely free.

### Prerequisites

```bash
# macOS
brew install kind kubectl

# Verify
kind --version
kubectl version --client
```

### 1 — Create the cluster

```bash
make k8s-cluster
```

This creates a single-node kind cluster named `chatbot-local` and sets your `kubectl` context to it automatically.

### 2 — Build and load images

```bash
make k8s-build-load
```

This builds all four app images locally and loads them into the kind cluster's internal registry (no external registry needed).

> This step takes 3–8 minutes on first run. Subsequent runs reuse Docker cache layers.

### 3 — Create the secret

```bash
cp infra/k8s/secret.example.yaml infra/k8s/secret.yaml
```

Open `infra/k8s/secret.yaml` and fill in your key(s):

```yaml
stringData:
  GEMINI_API_KEY: "AIza...your-key-here..."
  POSTGRES_PASSWORD: "chatbot"
```

Apply it:

```bash
make k8s-secret
```

> `secret.yaml` is in `.gitignore` — it will never be accidentally committed.

### 4 — Deploy

```bash
make k8s-deploy
```

This runs `kubectl apply -k infra/k8s`. Kustomize embeds `infra/postgres/init.sql` into a ConfigMap automatically.

### 5 — Watch pods come up

```bash
make k8s-status
# or watch continuously:
watch make k8s-status
```

Wait until all pods show `Running` and `READY 1/1`:

```
NAME                             READY   STATUS    RESTARTS
chat-api-6d7b9f4c5-abc12         1/1     Running   0
ingestion-api-7c8f5b6d9-def34    1/1     Running   0
worker-5b4c9d8e7-ghi56           1/1     Running   0
web-4a3b7c6d5-jkl78              1/1     Running   0
postgres-0                       1/1     Running   0
redis-8f9c4b5d6-mno90            1/1     Running   0
```

### 6 — Access the app

```bash
# Forward the web UI to localhost:3000
kubectl -n chatbot port-forward svc/web 3000:3000 &

# Forward chat-api to localhost:8000
kubectl -n chatbot port-forward svc/chat-api 8000:8000 &
```

Then open http://localhost:3000.

### 7 — Tear down

```bash
# Just delete deployments (keeps the cluster):
kubectl delete -k infra/k8s

# Full cluster removal:
make k8s-down
```

---

## Troubleshooting

### `make health` → FAIL on chat-api

1. Check the logs: `make logs-svc SERVICE=chat-api`
2. Common causes:
   - **`GEMINI_API_KEY` missing or invalid** — chat-api will crash on startup with `RuntimeError: GEMINI_API_KEY not set`. Copy `.env.example` again, fill in the key, then `make down && make up`.
   - **Postgres not ready yet** — SQLAlchemy throws `connection refused`. Wait 15s and retry.
   - **Port 8000 already in use** — kill whatever is on that port: `lsof -ti:8000 | xargs kill -9`

### `make health` → FAIL on ingestion-api

- Usually Redis not ready. Check: `make logs-svc SERVICE=redis`

### Worker starts then exits immediately

- Check: `make logs-svc SERVICE=worker`
- Likely cause: Postgres or Redis healthcheck is still pending. Docker Compose waits for `service_healthy` before starting worker, but if your Docker version is older the healthcheck may be flaky. Fix: `make down && make up`.

### `docker compose` not found / `make` not found

```bash
# macOS
brew install make

# Docker Compose v2 check (must be plugin, not standalone)
docker compose version    # ← with a space, not a hyphen
# If you have the old docker-compose binary, update Docker Desktop.
```

### First build is very slow

The worker image installs spaCy and downloads the `en_core_web_sm` model (~50 MB). This only happens on the very first build; subsequent builds use the layer cache. If it's timing out, check your internet connection or run `make build` with no timeout constraint.

### Port conflicts

All ports used:

| Port | Service |
|------|---------|
| 3000 | Next.js web |
| 8000 | chat-api |
| 8001 | ingestion-api |
| 5432 | Postgres |
| 6379 | Redis |

If any are in use, stop the conflicting process or change the host-side port in `infra/docker-compose.yml` (`"HOST:8000"` → e.g. `"8080:8000"`).

### Postgres volume has stale schema

If you previously ran with a different schema and Postgres is refusing to apply `init.sql`:

```bash
make down-v    # destroys the pgdata volume
make up        # re-creates everything from scratch
```

### Next.js build fails inside Docker

The web Dockerfile uses `output: "standalone"` in `next.config.mjs`. If you see errors about missing `server.js`, ensure Docker has at least **4 GB RAM** allocated (Docker Desktop → Settings → Resources).
