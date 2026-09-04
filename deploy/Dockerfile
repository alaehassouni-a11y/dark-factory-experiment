# syntax=docker/dockerfile:1.7
#
# Virtual Agent single-container image.
#   One stage: python runtime that serves the FastAPI service. There is no
#   frontend to build — the only client is the iOS app, which talks to /api.
#
# Build context is the repo root (see deploy/docker-compose.yml → build.context: ..).

FROM python:3.11-slim AS runtime

# Pull in the uv binary (pinned).
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

# Minimal runtime deps. curl isn't strictly required (healthcheck uses urllib)
# but is useful for in-container debugging.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Non-root user.
RUN groupadd --system --gid 1000 app \
 && useradd --system --uid 1000 --gid app --home /app app

WORKDIR /app

# Install Python deps first (separate layer for cache).
COPY --chown=app:app app/backend/pyproject.toml app/backend/uv.lock ./backend/
RUN cd backend && uv sync --frozen --no-dev

# Copy backend source.
COPY --chown=app:app app/backend/ ./backend/

# The wiki ships inside the image. The service indexes this folder at startup
# and answers from it before it ever touches the web, so a document added to
# virtualagent/resources/ and merged to main deploys exactly like code: new
# image, new colour, Caddy flip. No volume, no sync job.
COPY --chown=app:app virtualagent/resources/ ./virtualagent/resources/

RUN chown -R app:app /app

USER app

# Container serves the FastAPI /api routes only; there is nothing static.
# WIKI_RESOURCES_DIR points at the copy baked in above (docker-compose.yml
# pins the same value so the two can't drift).
ENV WIKI_RESOURCES_DIR=/app/virtualagent/resources \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# Healthcheck hits /api/health. The wiki index is built during app startup and
# a wiki that fails to index is a startup failure, so a 200 here means the
# process is up AND the agent has its knowledge — not just that uvicorn bound
# the port.
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).status == 200 else 1)" || exit 1

# Run from /app so the `backend.main:app` module path resolves.
#
# `--proxy-headers --forwarded-allow-ips="*"` tells Starlette to rewrite
# `request.client.host` from the left-most `X-Forwarded-For` value. Safe here
# because the app container does NOT publish a host port in compose (only
# Caddy reaches uvicorn, on the internal Docker network). If anyone ever adds
# `ports: - "8000:8000"` to this service, the forwarded address becomes
# spoofable and any accounting keyed on the client address can be bypassed.
CMD ["uv", "--project", "backend", "run", "uvicorn", "backend.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
