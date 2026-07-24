"""
Phase 1C regression guard — deployment artifacts must keep RLS effective.

Postgres exempts a table's OWNER from its row-level-security policies, so if the
app connects as the DB owner every tenant-isolation policy is installed yet
INERT. These tests assert that every Postgres compose file connects the backend
as the non-owner ``kaeos_app`` role and carries a separate owner URL for the
maintenance/migration path — the exact misconfiguration that shipped in the
original docker-compose.prod.yml.
"""
import os
import re

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO = os.path.dirname(_BACKEND)

_COMPOSE_FILES = [
    os.path.join(_BACKEND, "docker-compose.prod.yml"),
    os.path.join(_REPO, "docker-compose.staging.yml"),
    os.path.join(_REPO, "docker-compose.yml"),
]

# Roles that OWN the tables (creator of the schema). The app must never connect
# as one of these, or RLS is bypassed.
_OWNER_ROLES = {"kaeos", "kaeos_admin", "postgres"}


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


@pytest.mark.parametrize("path", _COMPOSE_FILES)
def test_backend_connects_as_non_owner(path):
    if not os.path.exists(path):
        pytest.skip(f"{path} not present")
    txt = _read(path)
    m = re.search(r"[^_]DATABASE_URL=postgresql\+asyncpg://([a-z_]+):", txt)
    if not m:
        pytest.skip("no Postgres DATABASE_URL in this compose file")
    role = m.group(1)
    assert role not in _OWNER_ROLES, (
        f"{os.path.basename(path)}: backend connects as owner role {role!r}; "
        f"Postgres exempts owners from RLS, so tenant isolation would be inert. "
        f"Connect as the non-owner 'kaeos_app' role."
    )
    assert role == "kaeos_app", f"expected kaeos_app, got {role!r}"
    assert "KAEOS_OWNER_DB_URL" in txt, "owner URL required for migrations/DDL/seeding"


def test_startprod_runs_migrations_and_owner_scoped():
    txt = _read(os.path.join(_BACKEND, "start-prod.sh"))
    assert "alembic upgrade head" in txt, "prod entrypoint must run migrations"
    assert "KAEOS_OWNER_DB_URL" in txt, "migrations must run under the owner URL"
