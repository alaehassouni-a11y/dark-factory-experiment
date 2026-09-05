# Deploy

Production deployment via Docker Compose. Runs Caddy (TLS + reverse proxy) in front of two identical copies of the Virtual Agent service — `app-blue` and `app-green` — and swaps between them for zero-downtime deploys. There is no database, no migration step and no frontend build: the service is a single FastAPI process, its only client is the iOS app, and the wiki it answers from ships inside the image.

## First-time setup on a new VPS

1. Install Docker: https://docs.docker.com/engine/install/
2. Clone this repo to `/opt/virtualagent/app/` (owned by a dedicated `virtualagent` user, `chmod 700` on `/opt/virtualagent/`)
3. Copy `deploy/.env.example` to `/opt/virtualagent/.env`, fill in real values (`chmod 600`). `VIRTUALAGENT_HOST` is the public hostname and `LETSENCRYPT_EMAIL` the contact; the Caddyfile reads both from the environment and compose refuses to start Caddy without them
4. Point the DNS A record for that hostname at the VPS public IP
5. `cd /opt/virtualagent/app/deploy && docker compose --env-file /opt/virtualagent/.env config >/dev/null` renders the stack and fails loudly, naming the variable, if `VIRTUALAGENT_HOST`, `LETSENCRYPT_EMAIL` or `OPENROUTER_API_KEY` is still unset
6. `cp upstream.conf.example upstream.conf && docker compose --env-file /opt/virtualagent/.env up -d caddy app-blue`
7. Caddy auto-provisions a Let's Encrypt cert on first request
8. Copy `deploy/deploy.sh` to `/opt/virtualagent/deploy.sh` and schedule it (systemd timer or cron). From then on every commit to `main` is a blue/green swap; nobody runs `docker compose` by hand

A host that already runs an older layout (a different root than `/opt/virtualagent/`) does not need to move: `deploy.sh` derives the checkout and the env file from its own location (`<root>/deploy.sh`, `<root>/app`, `<root>/.env`); the log and lock default to `/var/log/virtualagent-deploy.log` and `/var/run/virtualagent-deploy.lock`. Each can be overridden with `VIRTUALAGENT_ROOT`, `VIRTUALAGENT_REPO`, `VIRTUALAGENT_ENV`, `VIRTUALAGENT_LOG`, `VIRTUALAGENT_LOCK` (absolute paths). Mirror the script, keep the root. On the first run after this change the script recreates the Caddy container once, so it picks up the two new variables; expect a few seconds of downtime that one time

## Migrating a host that already runs the stack

Do these **before** the commit that introduces `VIRTUALAGENT_HOST` reaches `main`, in this order. The timer will otherwise pull a Caddyfile that reads the hostname from an environment the running container does not have, and the old mirrored `deploy.sh` would read the resulting `docker compose config` failure as "blue/green not yet configured" and exit 0 with nothing deployed.

1. Add `VIRTUALAGENT_HOST` and `LETSENCRYPT_EMAIL` to the host `.env` (the values that used to be edited into the Caddyfile). Remove the DynaChat variables if they are still there; nothing reads them
2. Mirror the new `deploy/deploy.sh` over the host copy the timer runs
3. If the Caddyfile in the host checkout was edited by hand (the old runbook said to), discard that edit so the pull can fast-forward: `git -C /opt/virtualagent/app checkout -- deploy/Caddyfile`
4. Merge. On its first run the new script renders the stack against `.env`, recreates the Caddy container once so it has the two variables (a few seconds of downtime, that one time), then does the normal blue/green swap

If step 1 is missed, the script says so in its log on every run and pulls nothing; once the variables are in, the next run deploys.

## Files

- `docker-compose.yml` - Caddy + the two app colours
- `Dockerfile` - the service image: Python 3.11, `uv`-installed dependencies, the backend, and a copy of `virtualagent/resources/`
- `Caddyfile` - reverse-proxy config (TLS + hostname routing); the hostname and contact come from `.env`, and it imports `upstream.conf`
- `upstream.conf.example` - shape of the one-line file that names the live colour. The real `upstream.conf` is written by `deploy.sh` and is gitignored
- `deploy.sh` - blue/green deploy script. This copy is the source of truth; the live `/opt/virtualagent/deploy.sh` is mirrored by hand. It fails loudly when the checkout, the env file, or a required variable is missing, rather than exiting 0 with nothing deployed
- `.env.example` - secret template (committed); real `.env` lives outside the checkout and is gitignored

## Ports

- `80` / `443` (public) - Caddy

Nothing else is published. The app containers are reachable only from Caddy over the internal Docker network.

## Environment variables

The containers read these from `/opt/virtualagent/.env` via docker-compose. The first two go to the Caddy container, the rest to the app containers:

| Variable | Required | Purpose |
|---|---|---|
| `VIRTUALAGENT_HOST` | **yes** | The public hostname Caddy serves and provisions a certificate for. Read by the Caddy container, not the app |
| `LETSENCRYPT_EMAIL` | **yes** | The contact Let's Encrypt notifies about the certificate. Read by the Caddy container |
| `OPENROUTER_API_KEY` | **yes** | OpenRouter chat completions and the embeddings that index the wiki. The service refuses to start without it |
| `BRAVE_SEARCH_API_KEY` | optional | Brave Search key for the web fallback. When unset the agent answers from the wiki only and says it does not know otherwise |
| `CHAT_MODEL` | optional | OpenRouter chat model. Defaults to `anthropic/claude-sonnet-4.6`; set it to canary a new model on the inactive colour |
| `CORS_ORIGINS` | optional | Comma-separated browser origins allowed to call the API. The iOS app needs none; leave empty |

`WIKI_RESOURCES_DIR` is **not** set in `.env`. `docker-compose.yml` pins it to
`/app/virtualagent/resources`, the copy of the wiki that `Dockerfile` bakes into
the image, so the code and the knowledge it answers from always deploy together.

Minimal `.env` for a fresh deploy:

```
VIRTUALAGENT_HOST=agent.example.com
LETSENCRYPT_EMAIL=ops@example.com
OPENROUTER_API_KEY=sk-or-...
BRAVE_SEARCH_API_KEY=...
```

Changing `VIRTUALAGENT_HOST` or `LETSENCRYPT_EMAIL` later means recreating the Caddy container (`docker compose --env-file /opt/virtualagent/.env up -d caddy`); a `caddy reload` re-reads the Caddyfile but not the container's environment.

## The wiki deploys like code

The agent's knowledge is every `.md` and `.txt` file under `virtualagent/resources/`
at the repo root. The image copies that folder in at build time and the service
indexes it at startup, so adding a document to the folder and merging to `main`
*is* a deploy: `deploy.sh` builds a new image on the inactive colour, waits for
its healthcheck (which only passes once the wiki is indexed), and flips Caddy.
There is no upload path, no sync job and no volume to keep in step.

## Secret hygiene

The real `.env` lives ONLY on the deploy host, in a directory owned by a non-factory user with mode 600. It is never committed, never shared via chat, and never readable by the Dark Factory workflow user.
