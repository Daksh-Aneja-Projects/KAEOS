"""Shared route enumeration for the authorization-coverage tests.

Why this exists
---------------
``test_default_deny`` and ``test_rbac_coverage`` lint EVERY route for an
authorization gate. Both used to walk ``app.routes`` directly and read
``route.dependant``, which silently assumed FastAPI keeps every included route
as a flat ``APIRoute`` on the application.

FastAPI >= 0.120 (with the Starlette 1.x line) no longer does: ``include_router``
now stores each sub-router as a single ``fastapi.routing._IncludedRouter`` entry
that resolves its children lazily at request time. Under that layout
``app.routes`` exposes only a handful of flat routes, so the naive walk finds
almost nothing — the coverage lint would pass vacuously while hundreds of
mutations went unchecked. That is a silent LOSS OF SECURITY COVERAGE, which is
exactly what these tests exist to prevent.

``iter_api_routes`` enumerates leaf routes on BOTH layouts:
  * flat ``APIRoute`` entries (classic layout, and app-level routes),
  * ``Mount``/router objects that expose ``.routes``,
  * ``_IncludedRouter`` entries, via the public-ish ``original_router`` (the
    APIRouter that was included) combined with ``include_context.prefix`` (the
    prefix it was mounted under) so the reported path is the real request path.

Router-level gates (``include_router(..., dependencies=[Depends(require_role(...))])``)
are carried on ``include_context.dependencies``, so they are returned alongside
the per-route dependant and must be considered when deciding "is this gated".
"""
from __future__ import annotations

from typing import Iterator, NamedTuple

from fastapi.routing import APIRoute


class RouteInfo(NamedTuple):
    """One leaf HTTP route, with everything needed to judge its auth gate."""

    path: str                 # full request path, including the include prefix
    methods: frozenset        # {"POST", ...}
    dependant: object | None  # FastAPI Dependant tree for the endpoint
    router_dependencies: tuple  # include_router(dependencies=[...]) entries
    endpoint: object | None   # the endpoint function (for source inspection)


def _is_included_router(route) -> bool:
    return type(route).__name__ == "_IncludedRouter"


def iter_api_routes(app) -> Iterator[RouteInfo]:
    """Yield every leaf HTTP route reachable from ``app``, on any FastAPI layout."""
    seen: set[int] = set()

    def walk(routes, prefix: str = "", inherited_deps: tuple = ()):
        for route in routes or ():
            if id(route) in seen:
                continue
            seen.add(id(route))

            if isinstance(route, APIRoute):
                yield RouteInfo(
                    path=prefix + route.path,
                    methods=frozenset(route.methods or ()),
                    dependant=getattr(route, "dependant", None),
                    router_dependencies=inherited_deps,
                    endpoint=getattr(route, "endpoint", None),
                )
                continue

            if _is_included_router(route):
                ctx = getattr(route, "include_context", None)
                sub_prefix = prefix + (getattr(ctx, "prefix", "") or "")
                sub_deps = inherited_deps + tuple(getattr(ctx, "dependencies", ()) or ())
                inner = getattr(route, "original_router", None)
                yield from walk(getattr(inner, "routes", ()), sub_prefix, sub_deps)
                continue

            # Mount / sub-application / anything else exposing .routes
            sub = getattr(route, "routes", None)
            if sub:
                sub_prefix = prefix + (getattr(route, "path", "") or "")
                yield from walk(sub, sub_prefix, inherited_deps)

    yield from walk(getattr(app, "routes", ()))


def mutating_routes(app, safe_methods=frozenset({"GET", "HEAD", "OPTIONS"})) -> list[RouteInfo]:
    """Every state-changing (non-safe-method) leaf route."""
    return [r for r in iter_api_routes(app) if r.methods - safe_methods]
