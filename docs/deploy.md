# Deploying

[简体中文](deploy.zh-CN.md)

How to run lingo-agent on a small Linux server, behind HTTPS, with backups. The main path uses the prebuilt images published on Docker Hub for each release; building from source works the same way with `make up`. The last part, [continuous deployment](#optional-continuous-deployment-to-your-own-server), is optional: it lets a tag pushed to your fork of the repository deploy itself to your server. Why it works this way is in [ADR 0063](decisions/0063-deployment.md).

Everything below uses `lingo.example.com` for the domain and `/opt/lingo-agent` for the checkout; replace them with yours.

## What you need

- A Linux server (amd64; the images are not built for arm64 yet) with Docker and Compose v2, `git`, `make` and `openssl`.
- **Memory.** The three containers are capped at 512 MB (Postgres), 768 MB (backend) and 384 MB (frontend). Measured on a 2-core server with about 1.6 GB of RAM: around 210–230 MB for the backend, 65–115 MB for the frontend and 75–80 MB for Postgres once running. The one-time example sentence import needs about 800 MB more for a few minutes. On a server with 2 GB or less, add swap first (2 GB is enough):

  ```bash
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
  sudo mkswap /swapfile && sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
  ```

- A domain whose DNS points at the server, ports 80 and 443 open, and a reverse proxy for HTTPS. This guide uses nginx and certbot; any proxy works if it does what the [template below](#5-https-with-nginx) does.
- Model API keys are **not** part of the deployment: each user enters their own in the app's Settings, stored encrypted.

Don't build the images on a server this small: building the frontend needs more memory than it has. Use the prebuilt images, or build somewhere else and push to a registry.

## First install

### 1. Get the release

Check out the release you are going to run. The compose file and `config/` come from the checkout, so they must match the images:

```bash
umask 022   # see below
sudo mkdir -p /opt/lingo-agent && sudo chown "$USER" /opt/lingo-agent
git clone --branch v0.3.0 https://github.com/YangD1/lingo-agent.git /opt/lingo-agent
cd /opt/lingo-agent
make env    # creates .env (mode 600) with a fresh encryption key and JWT secret
```

`umask 022` matters on servers whose default umask is `077`: the Postgres container runs as a different user and reads `docker/postgres/init/` from the checkout when it creates the database. If it can't, the first start leaves a half-initialised database (see [Troubleshooting](#troubleshooting)).

### 2. Production settings in `.env`

Change these lines (the comments in `.env` explain each one):

```bash
APP_ENV=prod
PROVIDERS_CONFIG=config/providers.prod.yaml
# Only read when the database is first created: set it before the first start.
POSTGRES_PASSWORD=<output of: openssl rand -hex 24>
# Only the reverse proxy on this machine may reach the frontend.
FRONTEND_HOST_BIND=127.0.0.1
# Prebuilt images; IMAGE_TAG is the release you checked out, without the "v".
BACKEND_IMAGE=youngdeezh/lingo-agent-backend
FRONTEND_IMAGE=youngdeezh/lingo-agent-frontend
IMAGE_TAG=0.3.0
```

Leave `PROVIDER_ALLOW_PRIVATE_NETWORKS=false` on any server other people use: it stops tenants from pointing a model connection at your internal network. The containers ignore `DATABASE_URL` in `.env` (their database address is fixed in `docker-compose.yml`), so you don't need to change it.

`APP_ENV=prod` refuses a `JWT_SECRET` shorter than 32 bytes (`make env` generates 32) and only sends the login cookie over HTTPS, so logging in over plain `http://` stops working on purpose.

**Back up `.env` now**, somewhere other than this server. `CREDENTIALS_ENCRYPTION_KEYS` in it encrypts the model API keys stored in the database; database backups are useless for those keys without it (see [Backups](#backups)).

### 3. Start

```bash
docker compose pull
docker compose up -d --no-build --wait
docker compose ps      # postgres, backend and frontend: running (healthy)
curl -sI http://127.0.0.1:3000 | head -n 1
```

The backend applies database migrations every time it starts. To build from source instead of pulling, leave the image lines at their defaults and run `make up`.

### 4. Import the word data (once)

The vocabulary pages, the placement test and the flashcards need three open datasets in the database. On a server, download them on the host and import them with one-off containers. Use `docker compose run --rm`, not `exec`: a separate container has its own memory cap and doesn't push the running backend over its 768 MB.

```bash
mkdir -p data/tatoeba data/simplewiktionary

# ECDICT word list (MIT), pinned to one commit; check the file before importing.
curl -fL -o data/ecdict.csv \
  https://raw.githubusercontent.com/skywind3000/ECDICT/bc015ed2e24a7abef49fc6dbbb7fe32c1dadaf8b/ecdict.csv
echo "1a6947e04785db63613a92e14903cdae7954f7e84860b10e68e5c7cbb3f9c3cf  data/ecdict.csv" | sha256sum -c

# Tatoeba example sentences (CC BY 2.0 FR), updated weekly.
for f in eng/eng_sentences.tsv.bz2 cmn/cmn_sentences.tsv.bz2 cmn/cmn-eng_links.tsv.bz2; do
  curl -fL -o "data/tatoeba/${f#*/}" "https://downloads.tatoeba.org/exports/per_language/$f"
done

# Simple English Wiktionary senses (CC BY-SA).
curl -fL -o data/simplewiktionary/simplewiktionary-latest-pages-articles.xml.bz2 \
  https://dumps.wikimedia.org/simplewiktionary/latest/simplewiktionary-latest-pages-articles.xml.bz2

run() { docker compose run --rm --no-deps -T -v "$PWD/data:/data:ro" backend python -m "$@"; }
run app.services.vocab.import_ecdict --csv /data/ecdict.csv     # ~15 s, ~38,000 words
run app.services.vocab.import_tatoeba --dir /data/tatoeba       # ~3 min, ~800 MB
run app.services.vocab.import_simplewiktionary \
  --file /data/simplewiktionary/simplewiktionary-latest-pages-articles.xml.bz2   # ~10 s
```

Run them in this order (the other two attach to the words from ECDICT). Each one can be run again safely, for example to pick up a newer Tatoeba export. `data/` is never committed and can be deleted afterwards.

### 5. HTTPS with nginx

Create `/etc/nginx/sites-available/lingo.example.com` (on distributions without `sites-available`, put it in `/etc/nginx/conf.d/lingo.example.com.conf`):

```nginx
# lingo-agent: nginx terminates HTTPS and forwards to the frontend on 127.0.0.1:3000.
map $http_upgrade $lingo_connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 80;
    listen [::]:80;
    server_name lingo.example.com;

    # Largest attachment is a 20 MB document.
    client_max_body_size 25m;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Host              $host;
        # Overwrite, don't append: per-IP rate limits read X-Forwarded-For (ADR 0035).
        proxy_set_header X-Forwarded-For   $remote_addr;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        # Realtime voice calls are WebSockets.
        proxy_set_header Upgrade           $http_upgrade;
        proxy_set_header Connection        $lingo_connection_upgrade;
        # Chat replies stream (SSE); pass bytes through as they arrive.
        proxy_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    access_log /var/log/nginx/lingo.access.log;
    error_log  /var/log/nginx/lingo.error.log;
}
```

Then enable it and get a certificate; certbot adds the `listen 443 ssl` lines and the HTTP → HTTPS redirect, and renews the certificate on its own:

```bash
sudo ln -s /etc/nginx/sites-available/lingo.example.com /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d lingo.example.com
```

What each part is for, if you use another proxy:

| Setting | Without it |
|---|---|
| `X-Forwarded-For $remote_addr` (overwrite) | Next passes the browser's own header on, so anyone can fake their IP and dodge the per-IP limits on login and sign-up. Caddy's `reverse_proxy` overwrites it by default. |
| `FRONTEND_HOST_BIND=127.0.0.1` | The frontend is also reachable directly on port 3000, around the proxy, with the same problem. |
| `Upgrade` / `Connection` | Realtime voice calls fail to connect. |
| `proxy_buffering off`, long timeouts | Chat replies arrive all at once instead of streaming, and long replies or calls get cut off. |
| `client_max_body_size` | Attachments over 1 MB fail with 413. |

Open `https://lingo.example.com`, create the first account and add a model connection under Settings. Check that `http://` redirects to `https://`, and that ports 3000, 8000 and 5433 are not reachable from outside (`ss -tlnp` on the server shows them on `127.0.0.1` only).

## Backups

`deploy/backup.sh [label]` (or `make backup`) dumps the database to `backups/<UTC time>_<label>.dump` with `pg_dump -Fc`, checks the dump can be read back and keeps the newest 14 (`LINGO_BACKUP_KEEP`). A daily backup with cron (`crontab -e`, as a user in the `docker` group):

```cron
30 4 * * * cd /opt/lingo-agent && deploy/backup.sh daily >/dev/null
```

Backups on the same disk don't survive losing the server: copy `backups/` somewhere else regularly (`rsync`, object storage, …).

**Back up `.env` separately.** The dump holds model API keys encrypted with `CREDENTIALS_ENCRYPTION_KEYS`. A database restored without the same keys works, but every stored API key is unreadable and users have to enter them again. `JWT_SECRET` matters less: without it everyone is simply logged out. Don't store `.env` next to the dumps: whoever has both has the API keys.

**Restore** with `make restore FILE=backups/<name>.dump` (or `deploy/restore.sh <file>`). It asks first, backs up the current database (`before_restore`), stops the backend and frontend, restores in one transaction (a failed restore leaves the database as it was) and starts them again. The running version must match the dump's schema: see [rolling back](#rolling-back).

## Upgrading

Read the release notes for anything that needs doing by hand, then:

```bash
cd /opt/lingo-agent
deploy/backup.sh before_0.3.1
git fetch --tags && git checkout v0.3.1
sed -i 's/^IMAGE_TAG=.*/IMAGE_TAG=0.3.1/' .env
docker compose pull
docker compose up -d --no-build --wait
```

The backend migrates the database when it starts. If `.env.example` gained new settings, the defaults apply; compare with `diff .env.example .env` to see them. Building from source: `git checkout` the new tag and `make up`.

### Rolling back

Whether you can simply go back depends on whether the new version changed the database schema. Before upgrading, note what each version expects:

```bash
docker compose run --rm --no-deps -T --entrypoint alembic backend heads
```

Run it again after the upgrade. If the output is the same, go back by checking out the old tag, setting `IMAGE_TAG` back and running the same `pull` and `up`. If it changed, the old version may not run on the new schema: check out the old tag, set `IMAGE_TAG` back, `docker compose pull`, then restore the backup taken before the upgrade:

```bash
make restore FILE=backups/<time>_before_0.3.1.dump
```

`restore.sh` starts the backend and frontend again from the old images once the database matches them. Anything written between the upgrade and the restore is lost.

## Optional: continuous deployment to your own server

[`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml) is how the project deploys its own server, and you can use it from a fork. Pushing a `v*` tag runs CI on that commit, builds the backend and frontend images once and pushes them to each registry that is configured; if a server is configured, it then connects over SSH and tells the server to switch to that commit. Each part only runs when its settings exist, so a fork without any just runs CI.

Running the workflow by hand from an older tag rolls back: its images are still in the registry, so it skips CI and building and goes straight to the deploy (about a minute).

### How a deploy works

The server pulls everything from a **private registry**: the two app images, plus a small *release image* holding that commit's compose file, `config/`, Postgres init scripts and `deploy/` scripts. The SSH key can run one command only, `deploy <40-hex commit>`, enforced on the server by [`deploy/deploy-entry`](../deploy/deploy-entry); it can't upload files or open a shell. So a leaked key can at worst redeploy something CI already built.

On the server, `deploy/deploy.sh`:

1. pulls the images (nothing changes if this fails);
2. compares the schema the new and current backend images expect (`alembic heads`);
3. backs up the database (`backups/<time>_before_<commit>.dump`);
4. starts the new version and waits for every health check;
5. on success, points `current` at the new release and removes old releases beyond the newest five;
6. on failure: **if the schema didn't change**, starts the previous version again; **if it did**, leaves the new version in place (the old code may not run on the new schema), marks the run failed and prints the `restore.sh` command for the backup from step 3.

The output in the Actions log is steps and outcomes only, because a public repository's logs are public. Full details are in `logs/` on the server, and every deploy is a line in `deployed.log`.

Layout on the server (`LINGO_ROOT`, here `/srv/lingo-agent`):

```
releases/<commit>/   one release: compose file, config/, deploy/, .env -> ../../shared/.env
current -> releases/<commit>
shared/.env          the only copy of the settings and secrets
shared/postgres-init a fixed copy of docker/postgres/init
backups/  logs/  bin/deploy-entry  deployed.log
```

Releases are directories rather than one checkout so that switching back is just starting another directory. The compose project name is fixed (`lingo-agent`), so the database volume stays the same whichever directory starts it, including an earlier checkout deploy.

### Server setup (once)

1. **Registry.** Any registry the server can pull from and GitHub can push to. Create `backend`, `frontend`, `release` and `pgvector` repositories under one namespace (private ones are fine; the workflow also copies the pinned pgvector image there, for servers that can't reach Docker Hub).
2. **Deploy user.** Membership of the `docker` group amounts to root on the machine, which is why the key is locked to one command:

   ```bash
   sudo useradd --create-home --groups docker --shell /bin/bash deploy
   sudo passwd -l deploy
   sudo install -d -o deploy -g deploy /srv/lingo-agent/{shared,releases,bin}
   sudo install -d -o deploy -g deploy -m 700 /srv/lingo-agent/{backups,logs}
   ```

3. **Settings.** Put your `.env` (or a fresh one from `make env` with the production values above) at `/srv/lingo-agent/shared/.env`, mode 600, owned by `deploy`, and add:

   ```bash
   BACKEND_IMAGE=<registry>/<namespace>/backend
   FRONTEND_IMAGE=<registry>/<namespace>/frontend
   RELEASE_IMAGE=<registry>/<namespace>/release
   POSTGRES_IMAGE=<registry>/<namespace>/pgvector:pg16
   POSTGRES_INIT_DIR=/srv/lingo-agent/shared/postgres-init
   ```

   `IMAGE_TAG` isn't needed: each release sets it to its commit. Copy `docker/postgres/init/` to `shared/postgres-init/` (readable by others: `chmod -R go+rX`).
4. **Entry point and key.** Install the entry point (each successful deploy replaces it with the new release's copy) and a key that can only run it:

   ```bash
   sudo install -o deploy -g deploy -m 755 deploy/deploy-entry /srv/lingo-agent/bin/
   ssh-keygen -t ed25519 -N '' -C lingo-deploy -f ./lingo-deploy   # on your own machine
   ```

   Add one line to `~deploy/.ssh/authorized_keys` (directory 700, file 600):

   ```
   restrict,command="/srv/lingo-agent/bin/deploy-entry" ssh-ed25519 AAAA... lingo-deploy
   ```

   Check that `ssh -i lingo-deploy deploy@<server> ls` is refused, then keep the private key only in the GitHub secret below.
5. **Registry login** as the deploy user, so it can pull: `sudo -iu deploy docker login <registry>`.
6. **Daily backups.** [`deploy/systemd/`](../deploy/systemd) has a service and timer (04:30 every day, as `deploy`):

   ```bash
   sudo cp deploy/systemd/lingo-backup.* /etc/systemd/system/
   sudo systemctl daemon-reload && sudo systemctl enable --now lingo-backup.timer
   ```

   It runs `current/deploy/backup.sh`, so it starts working after the first deploy.

### GitHub settings

Create an environment named `production` (Settings → Environments), allow only tags matching `v*` to deploy to it, and put everything there:

| Kind | Name | Value |
|---|---|---|
| variable | `ACR_REGISTRY` | registry host GitHub pushes to (the name is historical; any registry works) |
| variable | `ACR_NAMESPACE` | namespace holding the four repositories |
| secret | `ACR_USERNAME`, `ACR_PASSWORD` | registry login with push access |
| variable | `DEPLOY_USER` | `deploy` |
| secret | `DEPLOY_HOST`, `DEPLOY_PORT` | server address and SSH port |
| secret | `DEPLOY_SSH_KEY` | the private key from step 4 |
| secret | `DEPLOY_KNOWN_HOSTS` | the server's host key line, e.g. from `ssh-keyscan -p <port> <host>`; check its fingerprint against the server's |
| variable | `DOCKERHUB_NAMESPACE` | optional: also publish public images there |
| secret | `DOCKERHUB_TOKEN` | Docker Hub access token with write access (with `DOCKERHUB_NAMESPACE`) |

`DEPLOY_USER` is a variable on purpose: Actions replaces every occurrence of a secret's value in the logs with `***`, and a secret "deploy" would blank out that word everywhere. With the server address and port as secrets, the public logs don't show where the server is.

Then push a tag:

```bash
git tag v0.3.0 && git push origin v0.3.0
```

The first run takes about 25 minutes (CI about 13, images about 8, the deploy about 2); with the build cache warm, images take about a minute. The server's first deploy has no previous release to fall back on. To move an existing checkout deploy over, stop it (`docker compose down` in the old directory, which keeps the database volume) just before the first run.

### Without GitHub

If Actions is unavailable, do by hand what the workflow does: build and push `backend`, `frontend` and `release` (`docker build -f deploy/release.Dockerfile .` from the repo root) tagged with the full commit hash, then, as an administrator on the server:

```bash
sudo -u deploy /srv/lingo-agent/bin/deploy-entry deploy <40-hex commit>
```

`deploy/rehearse.sh` runs the whole server side (first deploy, upgrade, automatic rollback, a failed migration and its restore) against local images; CI runs it on every push.

## Troubleshooting

- **Postgres keeps restarting or the backend can't log in to it after the first start.** Usually the init scripts weren't readable (`umask 077` when cloning): `chmod -R go+rX docker/postgres/init`. Postgres only runs them when it creates the database, so on a **new, empty** install also remove the half-created volume (`docker compose down -v`; this deletes the database). The same applies to changing `POSTGRES_PASSWORD` after the first start: it has no effect on an existing database.
- **Can't log in; the login request succeeds but you stay logged out.** `APP_ENV=prod` sends the cookie over HTTPS only. Open the site through the proxy with `https://`.
- **Everyone hits "too many attempts" together, or the limits never trigger.** The proxy isn't overwriting `X-Forwarded-For`, or the frontend is reachable on port 3000 directly.
- **Replies appear all at once.** Response buffering is on in the proxy (`proxy_buffering off`).
- **`docker compose pull` times out.** Some networks can't reach Docker Hub. Use a registry mirror configured in Docker, or the continuous deployment setup above, which mirrors the images to a registry the server can reach.
- **The example sentence import is killed.** It needs about 800 MB; add swap and run it with `docker compose run`, not `exec`.
- **Something else.** `docker compose ps` for health, `docker compose logs --tail 200 backend` for errors.
