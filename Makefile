# Convenience wrapper around docker compose and kubectl.
# All commands run from the repo root.
# Usage: make <target>  [SERVICE=name]

COMPOSE  = docker compose -f infra/docker-compose.yml --env-file .env
KUBECTL  = kubectl -n chatbot
CLUSTER  = chatbot-local

# ── Docker Compose ─────────────────────────────────────────────────────────────

.PHONY: up
up:                          ## Build images and start all services (foreground)
	$(COMPOSE) up --build

.PHONY: up-d
up-d:                        ## Build images and start all services (background)
	$(COMPOSE) up --build -d

.PHONY: down
down:                        ## Stop and remove containers (keeps volumes)
	$(COMPOSE) down

.PHONY: down-v
down-v:                      ## Stop containers AND delete Postgres volume (full reset)
	$(COMPOSE) down -v

.PHONY: ps
ps:                          ## Show container status
	$(COMPOSE) ps

.PHONY: logs
logs:                        ## Tail all service logs
	$(COMPOSE) logs -f

.PHONY: logs-svc
logs-svc:                    ## Tail a single service: make logs-svc SERVICE=worker
	$(COMPOSE) logs -f $(SERVICE)

.PHONY: restart
restart:                     ## Restart one service: make restart SERVICE=chat-api
	$(COMPOSE) restart $(SERVICE)

.PHONY: build
build:                       ## Rebuild images without starting
	$(COMPOSE) build

# ── Quick health check ─────────────────────────────────────────────────────────

.PHONY: health
health:                      ## Ping all three HTTP health endpoints
	@echo "── chat-api ──────────────────────────"
	@curl -sf http://localhost:8000/health | python3 -m json.tool || echo "FAIL"
	@echo "── ingestion-api ─────────────────────"
	@curl -sf http://localhost:8001/health | python3 -m json.tool || echo "FAIL"
	@echo "── web ───────────────────────────────"
	@curl -sf -o /dev/null -w "HTTP %{http_code}\n" http://localhost:3000 || echo "FAIL"

# ── Database ───────────────────────────────────────────────────────────────────

.PHONY: psql
psql:                        ## Open an interactive psql shell inside the container
	$(COMPOSE) exec postgres psql -U chatbot -d chatbot

.PHONY: db-counts
db-counts:                   ## Show row counts for the three main tables
	$(COMPOSE) exec postgres psql -U chatbot -d chatbot -c \
	  "SELECT 'conversations' t, COUNT(*) FROM conversations \
	   UNION ALL SELECT 'messages', COUNT(*) FROM messages \
	   UNION ALL SELECT 'inference_logs', COUNT(*) FROM inference_logs;"

.PHONY: db-logs
db-logs:                     ## Show the 10 most recent inference log rows
	$(COMPOSE) exec postgres psql -U chatbot -d chatbot -c \
	  "SELECT request_id, provider, model, status, latency_ms, \
	          left(input_preview,40) AS input, left(output_preview,40) AS output \
	   FROM inference_logs ORDER BY created_at DESC LIMIT 10;"

# ── Redis ──────────────────────────────────────────────────────────────────────

.PHONY: redis-cli
redis-cli:                   ## Open an interactive redis-cli shell
	$(COMPOSE) exec redis redis-cli

.PHONY: redis-stream
redis-stream:                ## Show stream length and last 3 entries
	@echo "── stream length ─────────────────────"
	$(COMPOSE) exec redis redis-cli XLEN llm.events
	@echo "── last 3 entries ────────────────────"
	$(COMPOSE) exec redis redis-cli XREVRANGE llm.events + - COUNT 3

.PHONY: redis-pending
redis-pending:               ## Show pending (un-ACKed) entry count
	$(COMPOSE) exec redis redis-cli XPENDING llm.events workers - + 10

.PHONY: redis-dlq
redis-dlq:                   ## Show entries in the dead-letter queue
	$(COMPOSE) exec redis redis-cli XRANGE llm.events.dlq - + COUNT 20

# ── Kubernetes (kind) ──────────────────────────────────────────────────────────

.PHONY: k8s-cluster
k8s-cluster:                 ## Create a local kind cluster
	kind create cluster --name $(CLUSTER)

.PHONY: k8s-build-load
k8s-build-load:              ## Build all images and load them into kind
	docker build -f apps/chat-api/Dockerfile      -t chatbot/chat-api:latest      .
	docker build -f apps/ingestion-api/Dockerfile -t chatbot/ingestion-api:latest .
	docker build -f apps/worker/Dockerfile        -t chatbot/worker:latest        .
	docker build -f apps/web/Dockerfile           -t chatbot/web:latest           .
	kind load docker-image chatbot/chat-api:latest      --name $(CLUSTER)
	kind load docker-image chatbot/ingestion-api:latest --name $(CLUSTER)
	kind load docker-image chatbot/worker:latest        --name $(CLUSTER)
	kind load docker-image chatbot/web:latest           --name $(CLUSTER)

.PHONY: k8s-secret
k8s-secret:                  ## Apply the secret (copy secret.example.yaml → secret.yaml first)
	$(KUBECTL) apply -f infra/k8s/secret.yaml

.PHONY: k8s-deploy
k8s-deploy:                  ## Deploy all manifests via kustomize
	kubectl apply -k infra/k8s

.PHONY: k8s-status
k8s-status:                  ## Show pod status in the chatbot namespace
	$(KUBECTL) get pods

.PHONY: k8s-logs
k8s-logs:                    ## Tail logs for a pod label: make k8s-logs SERVICE=worker
	$(KUBECTL) logs -l app=$(SERVICE) -f --tail=100

.PHONY: k8s-down
k8s-down:                    ## Delete the kind cluster entirely
	kind delete cluster --name $(CLUSTER)

# ── Local dev (no Docker) ──────────────────────────────────────────────────────

.PHONY: dev-sdk
dev-sdk:                     ## Install llm_logger in editable mode
	pip install -e packages/llm_logger

.PHONY: dev-ingestion
dev-ingestion:               ## Run ingestion-api locally (needs Redis on :6379)
	cd apps/ingestion-api && pip install -r requirements.txt && \
	  REDIS_URL=redis://localhost:6379/0 uvicorn app.main:app --port 8001 --reload

.PHONY: dev-worker
dev-worker:                  ## Run worker locally (needs Redis + Postgres)
	cd apps/worker && pip install -r requirements.txt && \
	  REDIS_URL=redis://localhost:6379/0 \
	  DATABASE_URL=postgresql+asyncpg://chatbot:chatbot@localhost:5432/chatbot \
	  python -m app.consumer

.PHONY: dev-chat
dev-chat:                    ## Run chat-api locally (needs Postgres + ingestion-api)
	cd apps/chat-api && pip install -r requirements.txt && \
	  DATABASE_URL=postgresql+asyncpg://chatbot:chatbot@localhost:5432/chatbot \
	  INGESTION_URL=http://localhost:8001 \
	  PROVIDER=gemini \
	  uvicorn app.main:app --port 8000 --reload

.PHONY: dev-web
dev-web:                     ## Run Next.js dev server (needs chat-api on :8000)
	cd apps/web && npm install && \
	  NEXT_PUBLIC_CHAT_API_URL=http://localhost:8000 npm run dev

# ── Help ───────────────────────────────────────────────────────────────────────

.PHONY: help
help:                        ## List all targets with descriptions
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
