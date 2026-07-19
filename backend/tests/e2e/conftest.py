"""
KAEOS E2E Test Suite — Shared Fixtures & Configuration
Uses real Ollama (qwen2.5-coder:7b) for LLM-powered tests. No simulation.

Compatible with pytest-asyncio 0.23+ (loop_scope="session")
"""
import pytest
import os
import sys
import httpx
import socket
import logging
from urllib.parse import urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

logger = logging.getLogger("e2e")

BASE_URL = os.environ.get("KAEOS_TEST_URL", "http://localhost:8001/api/v1")
# Roots for the endpoints that live OUTSIDE /api/v1 (admin, /ws). DERIVED from
# BASE_URL - never hardcode a port in a test. A hardcoded localhost:8001 hits
# whatever happens to hold that port (a stale container, another service), so a
# test can "fail" against a backend that isn't even the one under test.
BACKEND_ROOT = BASE_URL.rsplit("/api/v1", 1)[0]
WS_ROOT = BACKEND_ROOT.replace("https://", "wss://").replace("http://", "ws://")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:7b")
# Multi-step gated agents make 3+ sequential LLM calls — local Ollama needs headroom
TIMEOUT = float(os.environ.get("KAEOS_TEST_TIMEOUT", "300"))


def admin_secret() -> str:
    """Resolve ADMIN_SECRET the way the backend does (env, then backend/.env).

    Platform actions (provisioning a tenant, enumerating every tenant's
    onboarding) are gated on this; tenant JWTs deliberately do not authorize them.
    """
    secret = os.environ.get("ADMIN_SECRET", "")
    if secret:
        return secret
    env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("ADMIN_SECRET="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def _env_from_dotenv(key: str) -> str:
    """Read a single KEY from process env, then backend/.env (same as backend)."""
    val = os.environ.get(key, "")
    if val:
        return val
    env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith(f"{key}="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def admin_email() -> str:
    """The configured root-admin login email (ADMIN_EMAIL), default admin@kaeos.ai."""
    return (_env_from_dotenv("ADMIN_EMAIL") or "admin@kaeos.ai").lower()


def admin_password() -> str:
    """The configured root-admin password (ADMIN_PASSWORD). Empty if unset."""
    return _env_from_dotenv("ADMIN_PASSWORD")


def ollama_reachable() -> bool:
    try:
        with socket.create_connection(("localhost", 11434), timeout=2):
            return True
    except Exception:
        return False


def backend_reachable() -> bool:
    """Is the backend the tests actually target up?

    Derived from BASE_URL, never hardcoded: with a fixed ("localhost", 8001)
    this probed a DIFFERENT server than the tests hit whenever KAEOS_TEST_URL
    pointed elsewhere - so the suite would happily run against one backend
    while its skip-guard reported on another. That mismatch produced a full
    suite of bogus 401 failures once already.
    """
    parsed = urlparse(BASE_URL)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((parsed.hostname or "localhost", port), timeout=2):
            return True
    except Exception:
        return False


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def base_url():
    return BASE_URL


@pytest.fixture(scope="session")
def has_ollama():
    reachable = ollama_reachable()
    if not reachable:
        logger.warning("Ollama not reachable — LLM-dependent tests will be skipped")
    return reachable


@pytest.fixture
async def client():
    """
    Per-test async HTTP client — avoids event loop conflicts.
    Skips the whole test file if backend is not running.
    """
    if not backend_reachable():
        pytest.skip(f"KAEOS backend not running at {BASE_URL}")

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as c:
        yield c


# ── Assertion Helpers ─────────────────────────────────────────────────────────

def skip_if_llm_outage(r):
    """
    Skip ONLY when a 500 is a genuine LLM outage (timeout / Ollama down).
    A bare 500 is a product bug and must fail the test — blanket skip-on-500
    previously masked real AttributeErrors in three domain agents.
    """
    if r.status_code == 500 and any(
        m in r.text.lower() for m in ("timeout", "timed out", "ollama", "connection")
    ):
        pytest.skip(f"LLM outage: {r.text[:120]}")



async def assert_non_empty_list(client: httpx.AsyncClient, path: str, key: str = None):
    r = await client.get(path)
    assert r.status_code == 200, f"GET {path} → {r.status_code}: {r.text[:200]}"
    data = r.json()
    items = data[key] if key else data
    assert isinstance(items, list), f"Expected list at {path}, got {type(items)}"
    assert len(items) > 0, f"Expected non-empty list at {path}"
    return data


async def assert_object(client: httpx.AsyncClient, path: str, required_keys: list):
    r = await client.get(path)
    assert r.status_code == 200, f"GET {path} → {r.status_code}: {r.text[:200]}"
    data = r.json()
    assert isinstance(data, dict), f"Expected dict at {path}, got {type(data)}"
    for key in required_keys:
        assert key in data, f"Missing key '{key}' in {path}. Keys: {list(data.keys())}"
    return data


async def assert_dashboard(client: httpx.AsyncClient, path: str):
    r = await client.get(path)
    assert r.status_code == 200, f"GET {path} → {r.status_code}: {r.text[:200]}"
    data = r.json()
    assert isinstance(data, dict), f"Expected dict at {path}, got {type(data)}"
    assert len(data) >= 1, f"Dashboard at {path} appears empty: {list(data.keys())}"
    return data


async def assert_agent_action(client: httpx.AsyncClient, path: str, method: str = "POST", body: dict = None):
    if method == "POST":
        r = await client.post(path, json=body or {})
    else:
        r = await client.get(path)
    assert r.status_code == 200, f"{method} {path} → {r.status_code}: {r.text[:300]}"
    return r.json()
