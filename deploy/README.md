# Deploy

Production deployment via Docker Compose. Runs Caddy (TLS + reverse proxy) in front of two identical copies of the Virtual Agent service — `app-blue` and `app-green` — and swaps between them for zero-downtime deploys. There is no database, no migration step and no frontend build: the service is a single FastAPI process, its only client is the iOS app, and the wiki it answers from ships inside the image.

## First-time setup on a new VPS

1. Install Docker: https://docs.docker.com/engine/install/
2. Clone this repo to `/opt/virtualagent/app/` (owned by a dedicated `virtualagent` user, `chmod 700` on `/opt/virtualagent/`)
3. Copy `deploy/.env.example` to `/opt/virtualagent/.env`, fill in real values (`chmod 600`)
4. Edit `deploy/Caddyfile`: replace `agent.example.com` with your hostname and `ops@example.com` with the address Let's Encrypt should notify
5. Point the DNS A record for that hostname at the VPS public IP
6. `cd /opt/virtualagent/app/deploy && cp upstream.conf.example upstream.conf && docker compose --env-file /opt/virtualagent/.env up -d caddy app-blue`
7. Caddy auto-provisions a Let's Encrypt cert on first request
8. Copy `deploy/deploy.sh` to `/opt/virtualagent/deploy.sh` and schedule it (systemd timer or cron). From then on every commit to `main` is a blue/green swap; nobody runs `docker compose` by hand

## Files

- `docker-compose.yml` - Caddy + the two app colours
- `Dockerfile` - the service image: Python 3.11, `uv`-installed dependencies, the backend, and a copy of `virtualagent/resources/`
- `Caddyfile` - reverse-proxy config (TLS + hostname routing); imports `upstream.conf`
- `upstream.conf.example` - shape of the one-line file that names the live colour. The real `upstream.conf` is written by `deploy.sh` and is gitignored
- `deploy.sh` - blue/green deploy script. This copy is the source of truth; the live `/opt/virtualagent/deploy.sh` is mirrored by hand
- `.env.example` - secret template (committed); real `.env` lives outside the checkout and is gitignored

## Ports

- `80` / `443` (public) - Caddy

Nothing else is published. The app containers are reachable only from Caddy over the internal Docker network.

## Environment variables

The app container reads these from `/opt/virtualagent/.env` via docker-compose:

| Variable | Required | Purpose |
|---|---|---|
| `OPENROUTER_API_KEY` | **yes** | OpenRouter chat completions and the embeddings that index the wiki. The service refuses to start without it |
| `BRAVE_SEARCH_API_KEY` | optional | Brave Search key for the web fallback. When unset the agent answers from the wiki only and says it does not know otherwise |
| `CHAT_MODEL` | optional | OpenRouter chat model. Defaults to `anthropic/claude-sonnet-4.6`; set it to canary a new model on the inactive colour |
| `CORS_ORIGINS` | optional | Comma-separated browser origins allowed to call the API. The iOS app needs none; leave empty |

`WIKI_RESOURCES_DIR` is **not** set in `.env`. `docker-compose.yml` pins it to
`/app/virtualagent/resources`, the copy of the wiki that `Dockerfile` bakes into
the image, so the code and the knowledge it answers from always deploy together.

Minimal `.env` for a fresh deploy:

```
OPENROUTER_API_KEY=sk-or-...
BRAVE_SEARCH_API_KEY=...
```

## The wiki deploys like code

The agent's knowledge is every `.md` and `.txt` file under `virtualagent/resources/`
at the repo root. The image copies that folder in at build time and the service
indexes it at startup, so adding a document to the folder and merging to `main`
*is* a deploy: `deploy.sh` builds a new image on the inactive colour, waits for
its healthcheck (which only passes once the wiki is indexed), and flips Caddy.
There is no upload path, no sync job and no volume to keep in step.

## Secret hygiene

The real `.env` lives ONLY on the deploy host, in a directory owned by a non-factory user with mode 600. It is never committed, never shared via chat, and never readable by the Dark Factory workflow user.
