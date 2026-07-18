"""KAEOS — Authentication & API Key Middleware (L17 Security Fabric)"""
import logging

logger = logging.getLogger(__name__)
from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from datetime import datetime, timezone
from typing import Optional
import hashlib
import uuid


import os
import json

KEYS_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "api_keys.json")

def load_keys():
    if os.path.exists(KEYS_FILE):
        try:
            with open(KEYS_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load API keys: {e}")
    return {}

def save_keys(keys):
    os.makedirs(os.path.dirname(KEYS_FILE), exist_ok=True)
    try:
        with open(KEYS_FILE, "w") as f:
            json.dump(keys, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save API keys: {e}")

# Persistent API key store
# Format: { hashed_key: { tenant_id, role, name, created_at, rate_limit } }
_API_KEYS = load_keys()

security = HTTPBearer(auto_error=False)


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def generate_api_key(tenant_id: str, name: str, role: str = "operator") -> dict:
    """Generate a new API key for a tenant."""
    raw_key = f"kt_{uuid.uuid4().hex}"
    hashed = hash_key(raw_key)
    _API_KEYS[hashed] = {
        "tenant_id": tenant_id,
        "name": name,
        "role": role,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "rate_limit": 1000,  # requests/hour
        "active": True,
    }
    save_keys(_API_KEYS)
    return {"api_key": raw_key, "key_id": hashed[:12], "tenant_id": tenant_id, "role": role}


def revoke_api_key(key_id_prefix: str) -> bool:
    """Revoke an API key by its prefix."""
    for hashed, meta in _API_KEYS.items():
        if hashed.startswith(key_id_prefix):
            meta["active"] = False
            save_keys(_API_KEYS)
            return True
    return False


async def get_current_tenant(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict:
    """
    Extracts tenant context from API key.
    In dev mode (no keys registered), returns a default tenant.
    """
    # Dev mode bypass — respect DEV_MODE flag
    from app.core.config import get_settings
    settings = get_settings()
    if settings.DEV_MODE:
        return {
            "tenant_id": "tenant_acme",
            "role": "admin",
            "name": "dev_mode",
            "authenticated": False,
        }

    if not credentials:
        raise HTTPException(401, "Missing API key. Use Authorization: Bearer kt_...")

    hashed = hash_key(credentials.credentials)
    key_meta = _API_KEYS.get(hashed)

    if not key_meta:
        raise HTTPException(401, "Invalid API key")
    if not key_meta.get("active", True):
        raise HTTPException(403, "API key has been revoked")

    return {
        "tenant_id": key_meta["tenant_id"],
        "role": key_meta["role"],
        "name": key_meta["name"],
        "authenticated": True,
    }


def initialize_dev_mode():
    """Seed a default dev key if no keys exist and in DEV_MODE."""
    from app.core.config import get_settings
    if get_settings().DEV_MODE and not _API_KEYS:
        dev_key = generate_api_key("tenant_acme", "dev_default", "admin")
        logger.info(f"[AUTH] Dev API Key generated: {dev_key['api_key'][:8]}... (truncated)")
