# Deploy

Production deployment via Docker Compose. Runs Caddy (TLS + reverse proxy) in front of two identical copies of the Virtual Agent service — `app-blue` and `app-green` — and swaps between them for zero-downtime deploys. There is no database, no migration step and no frontend build: the service is a single FastAPI process, its only client is the iOS app, and the wiki it answers from is a folder on the host that the service watches.

## First-time setup on a new VPS

1. Install Docker: https://docs.docker.com/engine/install/
2. Clone this repo to `/opt/virtualagent/app/` (owned by a dedicated `virtualagent` user, `chmod 700` on `/opt/virtualagent/`)
3. Copy `deploy/.env.example` to `/opt/virtualagent/.env`, fill in real values (`chmod 600`). `VIRTUALAGENT_HOST` is the public hostname and `LETSENCRYPT_EMAIL` the contact; the Caddyfile reads both from the environment and compose refuses to start Caddy without them
4. Point the DNS A record for that hostname at the VPS public IP
5. Create the wiki folder and put at least one document in it. `WIKI_DIR` must name a folder that **exists on this host and is readable by uid 1000**: compose is now told not to invent it (`create_host_path: false`), and a colour that indexes zero documents never becomes healthy. Both of those are deliberate — a mistyped path used to mount an empty directory and go live answering every client from the web
6. `cd /opt/virtualagent/app/deploy && docker compose --env-file /opt/virtualagent/.env config >/dev/null` renders the stack and fails loudly, naming the variable, if `VIRTUALAGENT_HOST`, `LETSENCRYPT_EMAIL` or `OPENROUTER_API_KEY` is still unset
7. `cp upstream.conf.example upstream.conf && docker compose --env-file /opt/virtualagent/.env up -d caddy app-blue`
8. Caddy auto-provisions a Let's Encrypt cert on first request
9. Install the deploy wrapper and the timer:
   ```bash
   cp /opt/virtualagent/app/deploy/host-wrapper.sh /opt/virtualagent/deploy.sh
   chmod 755 /opt/virtualagent/deploy.sh
   cp /opt/virtualagent/app/deploy/virtualagent-deploy.service \
      /opt/virtualagent/app/deploy/virtualagent-deploy.timer \
      /opt/virtualagent/app/deploy/virtualagent-deploy-alert@.service \
      /etc/systemd/system/
   systemctl daemon-reload
   systemctl enable --now virtualagent-deploy.timer
   ```
   `/opt/virtualagent/deploy.sh` is a **wrapper**, not a copy of the deploy script: it locates the checkout and runs `deploy/deploy.sh` from inside it. That is the one file mirrored by hand, and it holds no deploy logic, so it has nothing to go stale. From then on every commit to `main` is a blue/green swap (unless a hold is in place, below); nobody runs `docker compose` by hand

A host that already runs an older layout (a different root than `/opt/virtualagent/`) does not need to move: `deploy.sh` derives the checkout and the env file from its own location (`<root>/deploy.sh`, `<root>/app`, `<root>/.env`, and `<root>/app/deploy/deploy.sh` resolves the same root); the log and lock default to `/var/log/virtualagent-deploy.log` and `/var/run/virtualagent-deploy.lock`. Each can be overridden with `VIRTUALAGENT_ROOT`, `VIRTUALAGENT_REPO`, `VIRTUALAGENT_ENV`, `VIRTUALAGENT_LOG`, `VIRTUALAGENT_LOCK` (absolute paths).

## Commands

All four are the same script. On a host with the wrapper installed, run them as `/opt/virtualagent/deploy.sh <command>`.

| Command | What it does |
|---|---|
| `deploy.sh` | What the timer runs. Fetch, decide whether the commit on `origin/main` is the one already serving, pull, build the inactive colour, wait for its healthcheck, read its `/api/health`, flip Caddy, prove the service answers through the public hostname, stop the old colour |
| `deploy.sh flip` | Send traffic to the colour that is already built and healthy. The second half of a held deploy |
| `deploy.sh rollback` | Start the stopped colour and route back to it. Uses `docker compose start`, never `up`, so the old container keeps the image it was built from |
| `deploy.sh status` | Print the live colour, its indexed document count, the commit last deployed successfully, whether a hold is in place, and the state of every container. Safe at any time |

## Holding a deploy (the canary path)

`touch /opt/virtualagent/.hold` (or set `VIRTUALAGENT_NO_FLIP=1` in the service unit). With a hold in place the timer still pulls, still builds the new commit on the inactive colour and still checks it — it just does not send traffic to it. The log says which commit is waiting. Look at it from the host:

```bash
docker exec virtualagent-app-green curl -s localhost:8000/api/health
```

Then either promote it — `rm /opt/virtualagent/.hold && /opt/virtualagent/deploy.sh flip` — or leave the hold in place and let the next commit replace the candidate. This is also how a model canary is run: set `CHAT_MODEL` in `.env`, hold, and the new model serves only the colour nothing is routed to until you flip.

A hold does not stop the world: a wiki document dropped in `WIKI_DIR` is still picked up within seconds by whichever colour is live, because the wiki is not deployed by this script.

## When a deploy fails

- The run exits non-zero and systemd marks `virtualagent-deploy.service` failed, so `systemctl --failed` shows it. If `/opt/virtualagent/alert.sh` exists (yours to write; it is host-specific and usually holds a credential, so it is not in git) the failure also runs it with the last 50 journal lines on stdin. `VIRTUALAGENT_ALERT_CMD` in the service unit is a second, simpler channel
- The checkout is put **back** on the commit that was serving. This matters: a failed run used to leave `HEAD` advanced, so every later tick said "no changes" and production sat on the old code indefinitely with a green timer. The script now also records the last commit it truly deployed in `/opt/virtualagent/.deployed-sha` and uses that, not `HEAD`, to decide whether there is work to do
- If the failure happened during the Caddy swap, the upstream file is rewritten to the colour that is actually serving and Caddy is reloaded again, so the file and the proxy cannot disagree. They disagreeing is what made the *next* run rebuild over the live colour
- The old colour is never stopped until the new one has answered a real request through the public hostname

To roll back by hand: `/opt/virtualagent/deploy.sh rollback`. Do not use `docker compose up -d app-blue` for this — `up` recreates the container from the image the compose file names *now*, which destroys the thing you are rolling back to. Each deploy builds `virtualagent-app:<short sha>` and the script keeps the newest five, so the previous image is on disk; `docker images --filter=reference='virtualagent-app:*'` lists them.

## Migrating a host that already runs the stack

Do these **before** the commit that introduces `VIRTUALAGENT_HOST` reaches `main`, in this order. The timer will otherwise pull a Caddyfile that reads the hostname from an environment the running container does not have, and an old mirrored `deploy.sh` would read the resulting `docker compose config` failure as "blue/green not yet configured" and exit 0 with nothing deployed.

1. Add `VIRTUALAGENT_HOST` and `LETSENCRYPT_EMAIL` to the host `.env` (the values that used to be edited into the Caddyfile). Remove the DynaChat variables if they are still there; nothing reads them
2. Replace the hand-mirrored `/opt/virtualagent/deploy.sh` with `deploy/host-wrapper.sh` and install the systemd units (step 9 above). Until you do, the script warns on every run that the host copy differs from the one in the checkout
3. Make sure `WIKI_DIR` names a folder that exists on the host and contains at least one `.md` or `.txt` file. A missing folder is now a container that refuses to start rather than an empty wiki that goes live
4. If the Caddyfile in the host checkout was edited by hand (the old runbook said to), discard that edit so the pull can fast-forward: `git -C /opt/virtualagent/app checkout -- deploy/Caddyfile`
5. Merge. On its first run the new script renders the stack against `.env`, recreates the Caddy container once so it has the two variables (a few seconds of downtime, that one time), then does the normal blue/green swap

If step 1 is missed, the script says so in its log on every run and pulls nothing; once the variables are in, the next run deploys.

## Files

- `docker-compose.yml` - Caddy + the two app colours
- `Dockerfile` - the service image: Python 3.11, `uv`-installed dependencies, the backend, and a copy of `virtualagent/resources/`
- `../.dockerignore` - what is kept out of the build context. It lives at the **repository root**, not here, because that is the build context (`build.context: ..`) and Docker reads only `<context>/.dockerignore`
- `Caddyfile` - reverse-proxy config (TLS + hostname routing); the hostname and contact come from `.env`, and it imports `upstream.conf`
- `upstream.conf.example` - shape of the one-line file that names the live colour. The real `upstream.conf` is written by `deploy.sh` and is gitignored
- `deploy.sh` - the blue/green deploy script, and the only place that decides anything. Run from the checkout by the wrapper
- `host-wrapper.sh` - the one file copied to the host, as `/opt/virtualagent/deploy.sh`. Locates the checkout, execs the script above
- `virtualagent-deploy.service` / `.timer` / `virtualagent-deploy-alert@.service` - the systemd units, committed so the cadence, the user and the failure handling are reviewable and a new host is reproducible
- `.env.example` - secret template (committed); real `.env` lives outside the checkout and is gitignored

## Building the image before the host does

Nothing in the gate builds this image today, so the production host is the first machine to try. Until that is automated, run this on any machine with Docker after touching `deploy/Dockerfile`, `app/backend/pyproject.toml` or `app/backend/uv.lock`:

```bash
docker build -f deploy/Dockerfile -t virtualagent-app:smoke .
```

from the repository root — that path is the build context, and building from anywhere else is not the same build. The two things it catches are the two that have bitten: a `uv` pin that cannot read the lockfile (`uv sync --frozen` fails), and a context that is not being filtered (watch the "transferring context" size; it should be a few megabytes, not hundreds).

## Ports

- `80` / `443` (public) - Caddy

Nothing else is published. The app containers are reachable only from Caddy over the internal Docker network.

## Environment variables

The containers read these from `/opt/virtualagent/.env` via docker-compose. The first two go to the Caddy container, the rest to the app containers:

| Variable | Required | Purpose |
|---|---|---|
| `VIRTUALAGENT_HOST` | **yes** | The public hostname Caddy serves and provisions a certificate for. Read by the Caddy container, not the app; `deploy.sh` also reads it out of the env file for the post-flip smoke test |
| `LETSENCRYPT_EMAIL` | **yes** | The contact Let's Encrypt notifies about the certificate. Read by the Caddy container |
| `OPENROUTER_API_KEY` | **yes** | OpenRouter chat completions and the embeddings that index the wiki. The service refuses to start without it |
| `WEB_SEARCH_PROVIDER` | optional | `perplexity` (default: Sonar through OpenRouter, no second key), `brave`, or `none` |
| `BRAVE_SEARCH_API_KEY` | optional | Brave Search key; setting it selects Brave as the web fallback |
| `CHAT_MODEL` | optional | OpenRouter chat model. Defaults to `anthropic/claude-sonnet-4.6`; set it with a hold in place to canary a new model on the colour nothing is routed to |
| `CORS_ORIGINS` | optional | Comma-separated browser origins allowed to call the API. The iOS app needs none; leave empty |
| `WIKI_DIR` | optional | The live wiki: a folder on this host, mounted read-only into both colours. **It must exist**; compose will not create it. Default: the checkout's `virtualagent/resources` |

`WIKI_RESOURCES_DIR` is **not** set in `.env`. `docker-compose.yml` pins it to
`/app/virtualagent/resources` inside the container and mounts `WIKI_DIR` there.

The deploy script's own settings are not in `.env` — it never sources that file, it only passes it to compose. They are environment variables on the systemd unit: `VIRTUALAGENT_ALERT_CMD`, `VIRTUALAGENT_NO_FLIP`, `VIRTUALAGENT_KEEP_IMAGES`, plus the path overrides listed above.

Minimal `.env` for a fresh deploy:

```
VIRTUALAGENT_HOST=agent.example.com
LETSENCRYPT_EMAIL=ops@example.com
OPENROUTER_API_KEY=sk-or-...
WIKI_DIR=/opt/virtualagent/wiki
```

Changing `VIRTUALAGENT_HOST` or `LETSENCRYPT_EMAIL` later means recreating the Caddy container (`docker compose --env-file /opt/virtualagent/.env up -d caddy`); a `caddy reload` re-reads the Caddyfile but not the container's environment.

## The wiki is a folder on the host

The agent's knowledge is every `.md` and `.txt` file in `WIKI_DIR` (default: the
checkout's `virtualagent/resources/`). The image carries a copy of the repository's
folder so a container has knowledge with no mount at all; in production both colours
mount the host folder read-only over that copy, and the service watches it: a document
added, changed or removed is re-indexed within `WIKI_POLL_SECONDS` (10) and answered
from on the next question. Nothing is built, nothing is flipped, and a bad rebuild
keeps the previous index.

To add knowledge on the host, write the file there, or convert one:

```bash
uv run --project tools/wiki python tools/wiki/ingest.py brochure.pdf --out /opt/virtualagent/wiki
```

The format is described in `virtualagent/resources/README.md`. `/api/health` shows
`wiki_documents` and `wiki_indexed_at`, so a dropped file is easy to confirm — and so
does `deploy.sh status`. A colour that indexes **nothing** never reports healthy and is
never flipped live: the whole product is "answer from the wiki first", and a wiki of
zero documents would answer everything from the web instead.

## Secret hygiene

The real `.env` lives ONLY on the deploy host, in a directory owned by a non-factory user with mode 600. It is never committed, never shared via chat, and never readable by the Dark Factory workflow user. The deploy script reads exactly one value out of it (`VIRTUALAGENT_HOST`, for the smoke test) and never logs the rest.
