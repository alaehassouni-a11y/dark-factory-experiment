# syntax=docker/dockerfile:1.7
#
# Virtual Agent single-container image.
#   One stage: python runtime that serves the FastAPI service. There is no
#   frontend to build — the only client is the iOS app, which talks to /api.
#
# Build context is the repo root (see deploy/docker-compose.yml → build.context: ..).
# The filter on that context is the repo-root `.dockerignore`: Docker reads only
# `<context>/.dockerignore`, so an ignore file sitting next to this Dockerfile
# would never be applied. It lived here until 2026-09 and never filtered a byte.

FROM python:3.11-slim AS runtime

# The uv binary, pinned. The pin has to be a uv that can READ app/backend/uv.lock:
# that file is `version = 1 / revision = 3`, a lock format only uv 0.7+ parses,
# and it is written by the uv the repo develops with (0.12.9). A pin older than
# the lock makes `uv sync --frozen` below fail the build — on the production
# host, which is the only machine that builds this image today. Bump this tag in
# the same commit as any uv upgrade that rewrites the lock.
COPY --from=ghcr.io/astral-sh/uv:0.12.9 /uv /usr/local/bin/uv

# Minimal runtime deps. curl is what the post-flip smoke test and in-container
# debugging use; the healthcheck below uses python's urllib, no extra package.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Non-root user.
RUN groupadd --system --gid 1000 app \
 && useradd --system --uid 1000 --gid app --home /app app

WORKDIR /app

# The dependency environment is built OUTSIDE the source tree, at /opt/venv, on
# purpose: `COPY app/backend/` further down copies a whole directory, and on a
# machine where someone has run `uv sync` in app/backend that directory contains
# a `.venv` built for the host's OS. Copied over a venv living at
# backend/.venv it would silently replace the Linux one built here, and the
# container would start against a Windows or macOS interpreter path. A venv at
# /opt/venv cannot be reached by any COPY of the source tree.
#
# UV_LINK_MODE=copy because the cache below is a BuildKit cache mount — a
# different filesystem, where uv's default hardlinking cannot work.
# UV_COMPILE_BYTECODE trades a little build time for a faster first request,
# which matters against the healthcheck's 30s start_period.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

# Install Python deps first (separate layer for cache). The cache mount keeps
# the downloaded wheels across builds, so a source-only change rebuilds in
# seconds even though the layer itself is invalidated by a lock change.
COPY app/backend/pyproject.toml app/backend/uv.lock ./backend/
RUN --mount=type=cache,target=/root/.cache/uv \
    cd backend && uv sync --frozen --no-dev

# Copy backend source.
COPY --chown=app:app app/backend/ ./backend/

# Belt and braces over the .dockerignore at the context root. The ignore file is
# the real filter, but it is one file away from the build and nothing in CI
# proves it was applied; this line makes the image correct even when it was not.
# A host virtual environment, the service's tests and the tool caches have no
# business in production, and the first of them used to be able to shadow the
# environment this image runs on.
RUN rm -rf backend/.venv backend/venv backend/tests \
           backend/.pytest_cache backend/.mypy_cache backend/.ruff_cache \
 && find backend -type d -name '__pycache__' -prune -exec rm -rf {} +

# The image carries a copy of the repository's virtualagent/resources/ so the
# container has knowledge with no mount at all — a bare `docker run` of this
# image answers from the repo's wiki, and that is what the default is for.
# In production it is NOT the wiki that gets used: docker-compose.yml mounts the
# host's WIKI_DIR read-only over this same path in both colours, and the service
# watches that folder (WIKI_POLL_SECONDS), so a document dropped there is
# answered from within seconds with no build, no new image and no Caddy flip.
COPY --chown=app:app virtualagent/resources/ ./virtualagent/resources/

RUN chown -R app:app /app

USER app

# Container serves the FastAPI /api routes only; there is nothing static.
# WIKI_RESOURCES_DIR points at the path above — the image's own copy when
# nothing is mounted, the host's live wiki when compose mounts one over it.
# docker-compose.yml pins the same value so the two cannot drift.
ENV WIKI_RESOURCES_DIR=/app/virtualagent/resources \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# Healthcheck hits /api/health AND READS IT. A 200 alone is not enough: a wiki
# root that does not exist, or one this uid cannot read, indexes zero documents,
# logs one warning and still serves `status: ok` — a colour that answers every
# client from the web, which inverts the product's first rule, behind a green
# check that deploy.sh would happily flip live. Requiring wiki_documents >= 1
# holds production to the same standard harness/e2e.py holds the gate to.
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=5 \
    CMD python -c "import json,urllib.request,sys; h=json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)); sys.exit(0 if h.get('wiki_documents', 0) >= 1 else 1)" || exit 1

# Start the built environment's uvicorn directly, not `uv run`. `uv run`
# re-resolves the project at every container start: it wants the lock, the
# pyproject and possibly the network, inside the 30s start_period, and when it
# is unhappy the symptom is a healthcheck timeout rather than an error anyone
# reads. The environment was built at image build time; running it is all that
# is left to do. `--app-dir /app` is what puts `backend.main:app` on sys.path.
#
# `--proxy-headers --forwarded-allow-ips="*"` tells Starlette to rewrite
# `request.client.host` from the left-most `X-Forwarded-For` value. Safe here
# because the app container does NOT publish a host port in compose (only
# Caddy reaches uvicorn, on the internal Docker network). If anyone ever adds
# `ports: - "8000:8000"` to this service, the forwarded address becomes
# spoofable and any accounting keyed on the client address can be bypassed.
CMD ["/opt/venv/bin/uvicorn", "backend.main:app", "--app-dir", "/app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
