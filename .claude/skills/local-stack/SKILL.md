---
name: local-stack
description: Use for running the dev or full local stack: dev.sh, local_up.sh, local_down.sh, compose services, memory limits; not for deploys.
---

# Local stack

- **Dev services only** (postgres 5433, redis 6380, S3, vault, hydra, mailpit): `docker compose -f materials/docker-compose.dev.yaml up -d --wait postgres redis s3 s3-init vault vault-init mailpit`. Tests and `scripts/check_migrations.sh` need these. Stop with `down` (add `-v` to wipe).
- **One backend process on the host**: `scripts/dev.sh <all|api|bot|worker|scheduler|migrate|seed-demo|...>`; it starts the compose services and creates `materials/dev-keys/jwt-bearer.pem` if missing.
- **Whole stack** (backend and web images, all services, Hydra clients, demo data): `scripts/local_up.sh [--no-build] [--no-seed]`; stop with `scripts/local_down.sh [--wipe]` (`--wipe` deletes database, Redis, files, Vault data). Settings go in `.env.local`.
- **Memory** (Docker VM 8 GB): one heavy job at a time. Never run `local_up.sh --full-build` while tests run; build web apps one by one; do not run the full suite and a stack build together.
- Docker failing with "read-only file system" or exit 255 after a restart means the Docker VM is broken: restart Docker Desktop, then `up -d --wait`.
- Secrets stay in git-ignored files (`materials/dev-keys/secrets.env`, `.env.local`); never print them. `dev.env` keeps the AI mode `fake`.
- **Admission stack on the host**: `scripts/admission_local.sh` starts the compose services, migrates, bootstraps Hydra once, then runs api (8000), worker, bot and the `iht-web` dev servers id (3001), admission (3009), admin (3004), share (3006, basePath `/ai`); logs in `.local-logs/`; Ctrl-C stops all. AI is real when `IHSP_OPENROUTER__API_KEY` is in `materials/dev-keys/secrets.env` (`AI_MODE=fake` forces fake). Each app's `public/env.js` points at `localhost:8000` and the other ports (admission: `OAUTH_CLIENT_ID=admission`, `APP_NAME=admission`). The guest viewer is `http://localhost:3006/ai/admission-guest/#gst_…`. `apps/landing` also uses port 3009: do not run it together.
