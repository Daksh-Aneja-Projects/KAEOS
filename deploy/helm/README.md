# KAEOS Helm chart

Deploys the KAEOS backend API + frontend SPA to Kubernetes (>=1.25). Managed
Postgres (with the `pgvector` extension) and Redis are expected out of cluster -
a hand-rolled StatefulSet is not a production datastore.

## What's in the box

| Object | Purpose |
|--------|---------|
| Deployment (backend) | gunicorn/uvicorn API, 2 replicas, HPA to 8 on 70% CPU |
| Deployment (frontend) | nginx-served static SPA |
| Job (Helm hook) | `alembic upgrade head` as the **owner** role, pre-install/pre-upgrade, so app pods never race on DDL |
| Service x2 | ClusterIP for backend + frontend |
| Ingress | `/api`, `/ws`, `/health` to backend; `/` to frontend (opt-in) |
| HPA | backend CPU autoscaling |
| Secret | DB URLs, `SECRET_KEY`, admin bootstrap (or bring your own via `secrets.existingSecret`) |

Liveness + readiness both hit `/health`, which returns **503** when the primary
datastore is unreachable, so a broken pod is pulled from the Service.

## Quick start

```bash
helm upgrade --install kaeos deploy/helm/kaeos \
  --namespace kaeos --create-namespace \
  --set externalDatabase.appUrl="postgresql+asyncpg://kaeos_app:...@host:5432/kaeos" \
  --set externalDatabase.ownerUrl="postgresql+asyncpg://kaeos:...@host:5432/kaeos" \
  --set externalRedis.url="redis://host:6379/0" \
  --set secrets.SECRET_KEY="$(openssl rand -hex 32)" \
  --set secrets.ADMIN_SECRET="$(openssl rand -hex 24)" \
  --set image.repository=ghcr.io/you/kaeos
```

`appUrl` must use the **non-owner** DB role (so Postgres RLS applies); `ownerUrl`
uses the owner role (migrations + seeders bypass RLS by design). In production
prefer `secrets.existingSecret` fed by a secrets manager / External Secrets over
inline values.

Render locally without a cluster: `helm template kaeos deploy/helm/kaeos`.
