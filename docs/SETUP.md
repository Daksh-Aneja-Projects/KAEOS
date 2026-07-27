# Setup, Development & Deployment

Back to the [README](../README.md). Related: [Testing](TESTING.md) |
[Deployment runbook](DEPLOYMENT.md) | [Security model](SECURITY_MODEL.md)

## Prerequisites

- Python 3.12 (what CI, the Dockerfile, and the lint target all use; earlier
  versions are not tested)
- Node.js 20 for the frontend
- Docker 24+ and Docker Compose v2
- An LLM API key (Anthropic Claude **or** OpenAI) - **or** [Ollama](https://ollama.ai) for fully local inference
- 8GB RAM minimum (16GB recommended). For local inference, the default model
  `qwen2.5-coder:7b` targets a GPU with 6GB VRAM; CPU-only inference works but is slow.

## 1. Clone and configure

```bash
git clone https://github.com/Daksh-Aneja-Projects/KAEOS.git
cd KAEOS
cp .env.example .env
```

Open `.env` and set at minimum:

Pick one of two modes:

```env
# Mode A: local/dev (zero external services, auth + tenant isolation OFF).
# Uses SQLite + in-memory cache; simplest way to try KAEOS locally.
# BOTH lines are required: DEV_MODE disables auth, so ENVIRONMENT must be
# explicitly set to a known-local value (development, dev, local, test,
# testing, ci) or the app refuses to boot.
DEV_MODE=true
ENVIRONMENT=development

# Mode B: production-like (Postgres + RLS, auth ON).
# Leave DEV_MODE unset (or false). DEV_MODE=true is REFUSED unless ENVIRONMENT
# is explicitly one of the known-local values above - an unset ENVIRONMENT or
# anything else (staging, production, typos) fails closed, so it can never
# leak into a real deploy.

SECRET_KEY=<generate with: python -c "import secrets; print(secrets.token_urlsafe(32))">
ADMIN_SECRET=<a second unique secret - guards the admin endpoints>
ANTHROPIC_API_KEY=sk-ant-...   # or OPENAI_API_KEY=sk-...
# For fully-local inference (no cloud keys needed):
# OLLAMA_BASE_URL=http://localhost:11434

# Your first admin login - provisioned automatically on startup.
# There is NO default public login; pick your own here.
ADMIN_EMAIL=admin@yourco.com
ADMIN_PASSWORD=<a strong password - this is how you sign in>
```

> **First login.** After the stack is up, sign in at the frontend with the
> `ADMIN_EMAIL` / `ADMIN_PASSWORD` you set above. Leaving `ADMIN_PASSWORD` empty
> (outside `DEV_MODE`) means no admin is seeded - a deliberate choice so a public
> deployment never ships with known credentials.

> Outside `DEV_MODE=true` the backend **refuses to boot** until both `SECRET_KEY`
> and `ADMIN_SECRET` are set to real values - a default secret is a security
> incident waiting to happen, so it fails fast instead.

> **Zero-dependency dev stack.** KAEOS runs with **no external services** for local
> development: set `DEV_MODE=true` in `.env` and it uses SQLite (relational + vector +
> graph via the polystore) and an in-memory cache/pub-sub. When no LLM provider key is
> configured the system routes to Ollama (if running) or returns deterministic simulated
> responses. In production, provide a PostgreSQL `DATABASE_URL` (**`pgvector/pgvector:pg16`
> image** - plain Postgres lacks the `vector` type), Redis, and optionally Neo4j - the
> polystore selects those backends automatically.
>
> **Hard guard:** `DEV_MODE=true` disables auth and tenant isolation, so the backend
> **refuses to boot** unless `ENVIRONMENT` is explicitly set to a known-local value
> (`development`, `dev`, `local`, `test`, `testing`, `ci`). Unset or anything else
> - including `staging`, `production`, and typos - fails closed.

## 2. Start all services

```bash
docker compose up --build
```

| Service | URL |
|---------|-----|
| Frontend (containerized, Nginx) | http://localhost:5174 |
| Frontend (local dev, `npm run dev`) | http://localhost:5173 |
| Backend API | http://localhost:8001 |
| API Docs (Swagger) | http://localhost:8001/docs |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3000 |

## 3. Login

Sign in with the admin account you configured in `.env` - the `ADMIN_EMAIL` /
`ADMIN_PASSWORD` you set in step 1. It's provisioned automatically on first
startup. There is **no** default/shared login: if `ADMIN_PASSWORD` is empty
(outside `DEV_MODE`), no admin is seeded, by design.

## 4. Seed demo data (usually automatic)

The stack **auto-seeds on startup** (`SEED_DEMO_DATA=true`, the default), so after step 2 the
7 departments are already populated. Set `SEED_DEMO_DATA=false` if you want an empty tenant that
reflects only genuinely ingested data.

To (re)run the seeder manually, run it **inside the backend container** so it targets the same
database the app uses (running it on your host hits a different DB, e.g. a local SQLite file):

```bash
docker compose exec backend python -m scripts.seed_master
```

This seeds all 7 departments - HR, Finance, Legal, Sales, Support, Operations, **Engineering & IT Ops** -
plus the Agent Factory, external-intelligence signals, and infrastructure (model registry, prompts,
cost governor). Takes ~30 seconds. It is idempotent: re-running tops up anything added since your
tenant was first seeded (new connectors, new departments) without duplicating existing rows.

## 5. Deploy your first AI Department

1. Navigate to **Workforce** in the sidebar
2. Click **Deploy Department**
3. Select **Human Resources** domain pack
4. Connect your data sources (or use the built-in demo data)
5. Click **Deploy** - the 11-state FSM provisions your AI department automatically

## Environment variables

See [`.env.example`](../.env.example) for the complete reference with descriptions.

**Minimum required variables** (outside `DEV_MODE` the app refuses to boot without
`SECRET_KEY`, `ADMIN_SECRET`, and - to get a login - `ADMIN_EMAIL`/`ADMIN_PASSWORD`):

| Variable | Description |
|----------|-------------|
| `SECRET_KEY` | JWT signing key (generate with `secrets.token_urlsafe(32)`) |
| `ADMIN_SECRET` | Second unique secret guarding the admin endpoints (required outside `DEV_MODE`) |
| `ADMIN_EMAIL` | Email for the first admin account, provisioned on startup |
| `ADMIN_PASSWORD` | Password for the first admin account; if empty outside `DEV_MODE`, no admin is seeded |
| `DATABASE_URL` | SQLAlchemy async DB URL (default: `sqlite+aiosqlite:///./kaeos.db`) |
| `REDIS_URL` | Redis connection URL (optional in dev mode) |
| `ANTHROPIC_API_KEY` | Anthropic Claude API key (or use `OPENAI_API_KEY`) |
| `OLLAMA_BASE_URL` | Ollama base URL for local inference (default: `http://localhost:11434`) |

## Development

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate       # Windows
# source .venv/bin/activate  # Linux/Mac
pip install -r requirements.txt

# Apply DB migrations
alembic upgrade head

# Start dev server (port 8001)
python -m uvicorn app.main:app --port 8001 --reload

# Seed all demo data (from backend/)
python -m scripts.seed_master
```

### Frontend

```bash
cd frontend
npm install
npm run dev
# -> http://localhost:5173
```

### Database migrations

```bash
cd backend

# Create a new migration after changing models
alembic revision --autogenerate -m "describe your change"

# Apply pending migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1
```

### Local Ollama (for fully-local LLM inference)

```bash
# Install Ollama: https://ollama.ai
ollama pull qwen2.5-coder:7b # Default for all text tiers - strict JSON, fits a 6GB GPU
ollama pull phi4-mini        # Optional: the "weak model" for BYOK ceiling demos
ollama pull nomic-embed-text # Embeddings for RAG

# The LLM router auto-detects Ollama at http://localhost:11434
```

## Deployment

### Production with Docker Compose

```bash
# Build and start all services
docker compose up --build -d

# Run migrations - as the OWNER role. The app connects as kaeos_app (non-owner)
# so RLS applies to it; that role deliberately cannot run DDL. Alembic follows
# DATABASE_URL, so point it at the owner for this one command:
docker compose exec backend sh -c 'DATABASE_URL="$KAEOS_OWNER_DB_URL" alembic upgrade head'

# Seed demo data (seeding also runs on the owner connection automatically)
docker compose exec backend python -m scripts.seed_master
```

> **Fresh database bootstrap order:** the backend's startup `init_db()` creates the full
> schema (and the pgvector extension) on first boot; `alembic upgrade head` then installs
> the RLS policies and the `kaeos_app` role. The migration chain is state-aware, so this
> works on both fresh and existing databases. After any deploy, prove isolation:
> `python scripts/verify_rls.py`.

### Health check

```bash
curl http://localhost:8001/health
# {
#   "status": "ok",
#   "app": "KAEOS",
#   "backends": {
#     "vector_store": {"backend": "pgvector", "available": true},
#     "graph_store":  {"backend": "neo4j",    "available": true},
#     "cache_bus":    {"backend": "redis",    "available": true}
#   }
# }
```

On the dev stack (no external services): backends report `sqlite` / `sqlite` / `memory`.

### Monitoring

- **Prometheus** metrics at `http://localhost:9090`
- **Grafana** at `http://localhost:3000` (dev default password only - set `GRAFANA_ADMIN_PASSWORD`
  before exposing it). Point it at the Prometheus data source to chart API latency, HITL queue
  depth, and skill execution metrics.

See the full [deployment runbook](DEPLOYMENT.md) for production hardening steps.
