# deploy

Everything needed to run STREM as containers.

- `docker/docker-compose.yml` — Postgres, Redis and the five services (gateway on
  port 8000). Build contexts are `../../services/*`.
- `docker/postgres/init/` — creates one database per service on first boot.
- `.env.example` — safe local defaults; copy to `.env` and add `OPENAI_API_KEY`.
- `scripts/migrate-stack.py` — runs every service's Alembic migrations.
- `scripts/seed-demo.py` — demo athlete `race-demo@strem.app` / `NeverSettle123!`
  with a race, training, check-ins and a checkpoint plan for race-day mode.
- `scripts/delete-local-account.py` — remove one local account to test sign-up again.
- `scripts/smoke-health.py` — checks every service's `/health`.

## Production (#21)

The API runs on one server (Oracle Cloud Always Free, or a ~€4/month Hetzner VPS)
with Docker Compose; the web app runs on Vercel. Every green CI run on `main`
deploys itself through `.github/workflows/deploy.yml`.

- `docker/docker-compose.prod.yml` — overlay on the same compose file: GHCR images
  (tag = commit SHA), no public ports except Caddy, required secrets.
- `docker/Caddyfile` — HTTPS for `API_DOMAIN` (automatic certificates) → gateway.
- `.env.prod.example` — what the server's `/srv/strem/.env` holds.
- `scripts/server-setup.sh` — run once on a fresh Ubuntu server: Docker, firewall,
  `/srv/strem/.env` with generated secrets, nightly backup.
- `scripts/backup-db.sh` — nightly `pg_dumpall` into `/srv/strem/backups`, 7 days kept.
- `../apps/mobile/vercel.json` — the Vercel build of the web app.

One-time setup:

1. **DNS:** `api.strem.<domain>` A record → server IP; `strem.<domain>` → Vercel.
2. **Server:** run `server-setup.sh`, then fill `API_DOMAIN`, `WEB_ORIGIN`,
   `OPENAI_API_KEY` and Strava in `/srv/strem/.env`.
3. **GitHub** (repo → Settings → Secrets and variables → Actions): variable
   `DEPLOY_HOST` (server IP), optional `DEPLOY_USER` (default `ubuntu`); secret
   `DEPLOY_SSH_KEY` (private key whose public half is in the server's
   `~/.ssh/authorized_keys`). The deploy job runs only once `DEPLOY_HOST` exists.
4. **Vercel:** import the repo with root directory `apps/mobile`; set
   `EXPO_PUBLIC_API_URL=https://api.strem.<domain>/v1`; add the `strem.<domain>` domain.

Each deploy: build ARM images → pull on the server → `alembic upgrade head` for
auth, user, training and ai → `up -d --wait` → `https://API_DOMAIN/health`.
Roll back: Actions → Deploy → Run workflow with an older commit SHA.

See "Run it yourself" in the root `README.md` for the commands and every setting.
