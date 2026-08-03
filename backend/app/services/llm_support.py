"""
KAEOS L9 — LLM Router support primitives.

Class-independent helpers extracted from ``llm_router`` so the router module
stays focused on routing/completion logic:
  * Ollama reachability probes (cached, non-blocking).
  * The content-addressed embedding cache (a byte-identical memo of a pure
    ``(model, text) -> vector`` function).
  * The router's public exception hierarchy.

``llm_router`` re-exports every name here, so external imports such as
``from app.services.llm_router import BudgetExceededError`` keep working.
"""
from collections import OrderedDict as _OrderedDict
import hashlib
import math
import struct
import time

# ─── Ollama reachability probe (avoid repeated socket calls) ───
_OLLAMA_PROBE_CACHE: dict[str, tuple[float, bool]] = {}
_OLLAMA_PROBE_TTL = 30.0  # seconds


def _blocking_tcp_probe(host: str, port: int, timeout: float) -> bool:
    """Blocking TCP connect — kept because it is far more reliable than an
    asyncio open_connection on Windows, where the async path can spuriously
    time out on a localhost connect that a blocking connect completes."""
    import socket

    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        # Connection refused / DNS / timeout -> host is not reachable.
        return False


async def _ollama_reachable(base_url: str) -> bool:
    """Fast, cached TCP probe to check whether an Ollama server is reachable.

    Uses a blocking socket connect (reliable) offloaded to a worker thread via
    asyncio.to_thread, so the event loop is never blocked while still getting a
    trustworthy result. A generous timeout accommodates a slow localhost stack.
    """
    import asyncio

    now = time.time()
    cached = _OLLAMA_PROBE_CACHE.get(base_url)
    if cached and (now - cached[0]) < _OLLAMA_PROBE_TTL:
        return cached[1]

    host, port = "localhost", 11434
    try:
        stripped = base_url.split("://", 1)[-1]
        hostport = stripped.split("/", 1)[0]
        if ":" in hostport:
            host, port_str = hostport.rsplit(":", 1)
            port = int(port_str)
        else:
            host = hostport
    except Exception:
        # A malformed OLLAMA_BASE_URL falls back to the localhost:11434
        # defaults initialized above; the reachability probe below then
        # reports honestly whether anything is actually there.
        pass

    try:
        reachable = await asyncio.to_thread(_blocking_tcp_probe, host, port, 1.5)
    except Exception:
        # Best-effort reachability: any probe failure means "assume unreachable"
        # and fall back to the cloud/fake router downstream.
        reachable = False

    _OLLAMA_PROBE_CACHE[base_url] = (now, reachable)
    return reachable


# ─── Embedding cache ───
# An embedding is a PURE function of (model, text): the same text under the same
# model always yields the same vector, so caching returns a byte-identical result
# while eliminating a repeat provider call. Content-only (no tenant data), so
# cross-tenant reuse of identical text is safe. Bounded LRU.
_EMBED_CACHE: "_OrderedDict[str, list]" = _OrderedDict()
_EMBED_CACHE_MAX = 8192
_EMBED_CACHE_STATS = {"hits": 0, "misses": 0}


def _embed_key(model: str, text: str) -> str:
    # Non-security cache key (embedding memoization), not a digest of secrets —
    # usedforsecurity=False documents intent and clears the bandit B324 gate.
    return hashlib.sha1(  # nosec B324
        f"{model}\x00{text}".encode("utf-8", "replace"), usedforsecurity=False
    ).hexdigest()


def _embed_cache_get(key: str):
    v = _EMBED_CACHE.get(key)
    if v is not None:
        _EMBED_CACHE.move_to_end(key)
        _EMBED_CACHE_STATS["hits"] += 1
    return v


def _embed_cache_put(key: str, vec: list) -> None:
    _EMBED_CACHE[key] = vec
    _EMBED_CACHE.move_to_end(key)
    while len(_EMBED_CACHE) > _EMBED_CACHE_MAX:
        _EMBED_CACHE.popitem(last=False)


# Known embedding dimensions by model id (fallback: 1536).
_EMBEDDING_DIMS = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
    "embed-english-v3.0": 1024,
    "ollama/nomic-embed-text:latest": 768,
    "nomic-embed-text": 768,
}


def embedding_dim(model: str) -> int:
    return _EMBEDDING_DIMS.get(model, 1536)


def pseudo_embedding(text: str, dim: int) -> list[float]:
    """Deterministic, unit-normalized pseudo-embedding seeded from a hash."""
    seed = hashlib.sha256((text or "").encode("utf-8")).digest()
    vals: list[float] = []
    counter = 0
    while len(vals) < dim:
        block = hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
        for i in range(0, len(block), 4):
            if len(vals) >= dim:
                break
            u = struct.unpack(">I", block[i:i + 4])[0] / 0xFFFFFFFF
            vals.append(u * 2.0 - 1.0)  # map to [-1, 1]
        counter += 1
    norm = math.sqrt(sum(v * v for v in vals)) or 1.0
    return [v / norm for v in vals]


# ─── Router exception hierarchy ───
class BudgetExceededError(RuntimeError):
    """Raised when a tenant's token/cost budget hard limit blocks an LLM call."""


class NoLLMProviderError(RuntimeError):
    """Raised when no LLM provider is reachable and simulated output is not
    permitted. Governance gates MUST treat this as fail-closed (deny / route to
    human) rather than rubber-stamping a decision on a fabricated response."""


class PIIScrubError(RuntimeError):
    """Raised when PII scrubbing fails under a data-residency / strict-egress
    policy. The cloud LLM call MUST be blocked rather than send unscrubbed PII."""
