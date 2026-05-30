# Deploying for a free public demo link

This deploys the **entire stack** (web, chat-api, ingestion-api, worker, Postgres,
Redis) to a single Linux VM using your existing Docker Compose setup, fronted by
[Caddy](https://caddyserver.com/) for automatic HTTPS. It reuses everything that
already works locally — no re-architecture.

> **Why a VM and not Render/Railway?** This is a 6-service app. Render's free
> tier doesn't run background workers (the event `worker` would need a paid
> plan), Railway's free credit is one-time, and 1 GB free micro-VMs OOM on the
> Presidio/spaCy worker. A free VM with enough RAM runs the whole compose stack
> as-is.

---

## 1. Get a free VM

**[Oracle Cloud "Always Free"](https://www.oracle.com/cloud/free/)** is the
recommended free option — an Ampere ARM VM with up to 4 vCPU / 24 GB RAM, free
forever. (Account signup needs a card for identity verification but Always Free
resources are never charged.)

Any VM works (DigitalOcean, Hetzner, EC2, a home server…). Recommended minimum:
**2 vCPU / 4 GB RAM**, Ubuntu 22.04+.

In the VM's firewall / security list, **open inbound TCP 80 and 443**.

## 2. Get a free HTTPS hostname

Caddy needs a domain to issue a free Let's Encrypt certificate. If you don't own
one, use a free dynamic-DNS subdomain:

- Create a free subdomain at **[DuckDNS](https://www.duckdns.org/)** (e.g.
  `mychatbot.duckdns.org`) and point it at your VM's public IP.

## 3. Install Docker on the VM

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker   # run docker without sudo
```

## 4. Clone and configure

```bash
git clone <your-repo-url> chatbot && cd chatbot
cp .env.example .env
```

Edit `.env` and set at minimum:

```bash
PROVIDER=gemini
GEMINI_API_KEY=<your-key>
GEMINI_MODEL=gemini-2.5-flash

# Public hostname from step 2 (no protocol):
DOMAIN=mychatbot.duckdns.org
```

> The internal service URLs (`DATABASE_URL`, `REDIS_URL`, `INGESTION_URL`,
> `CHAT_API_URL`) already point at the compose service names and need no change.
> The browser talks to chat-api at the same origin via `/api`, so no public API
> URL has to be configured.

## 5. Deploy (one command)

```bash
docker compose -f infra/docker-compose.yml -f infra/docker-compose.prod.yml \
  --env-file .env up -d --build
```

This builds the images, bakes `NEXT_PUBLIC_CHAT_API_URL=/api` into the web
bundle, starts all services, and brings up Caddy. The Postgres schema bootstraps
automatically from `infra/postgres/init.sql` on first start (same as local).

Caddy obtains a TLS certificate within ~30 seconds of the first HTTPS request.

> Requires Docker Compose **v2.24+** (for the `!reset` directive that hides
> internal ports). Check with `docker compose version`.

## 6. Verify

```bash
curl -s https://$DOMAIN/api/health      # {"status":"ok","provider":"gemini"}
curl -s -o /dev/null -w '%{http_code}\n' https://$DOMAIN   # 200
```

Then open **`https://mychatbot.duckdns.org`** — that's your shareable demo link.

## 7. Updating

```bash
git pull
docker compose -f infra/docker-compose.yml -f infra/docker-compose.prod.yml \
  --env-file .env up -d --build
```

## Teardown

```bash
docker compose -f infra/docker-compose.yml -f infra/docker-compose.prod.yml down
# add -v to also remove the Postgres + Caddy volumes
```

---

## Architecture on the VM

```
                 Internet (HTTPS :443)
                        │
                   ┌────▼────┐
                   │  Caddy  │  auto-TLS, single origin
                   └──┬───┬──┘
            /api/*    │   │   /*
        ┌─────────────┘   └──────────────┐
        ▼                                 ▼
   ┌──────────┐                      ┌─────────┐
   │ chat-api │                      │   web   │
   └────┬─────┘                      └─────────┘
        │ (internal docker network)
   ┌────┴───────────┬───────────────┐
   ▼                ▼               ▼
┌────────┐   ┌──────────────┐   ┌───────┐
│postgres│   │ingestion-api │   │ redis │
└────────┘   └──────┬───────┘   └───┬───┘
                    │  XADD          │ consumer group
                    └────────►───────┴────► ┌────────┐
                                            │ worker │ → postgres
                                            └────────┘
```

Only Caddy is exposed publicly; every other service stays on the internal Docker
network.
