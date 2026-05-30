# --- builder ---
FROM node:20-alpine AS builder
WORKDIR /app
COPY apps/web/package.json apps/web/package-lock.json* ./
RUN npm install --legacy-peer-deps --no-audit --no-fund

COPY apps/web/ ./

# NEXT_PUBLIC_* must be present at build time (Next.js inlines them into the
# client bundle). Defaults to localhost for local dev; production passes "/api"
# (same-origin, proxied by Caddy) so no public URL needs to be known at build.
ARG NEXT_PUBLIC_CHAT_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_CHAT_API_URL=$NEXT_PUBLIC_CHAT_API_URL
RUN npm run build

# --- runner ---
FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production

# Next.js "standalone" output bundles only what's needed.
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

EXPOSE 3000
CMD ["node", "server.js"]
