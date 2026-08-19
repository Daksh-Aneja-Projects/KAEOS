"""Dump the full HTTP surface so a refactor can be proven behaviour-preserving.

Walks app.main's route table AND the generated OpenAPI document, emitting a
deterministic JSON snapshot.

Three uses:

    # write/refresh the committed baseline (do this when the API changes on purpose)
    python -m scripts.openapi_surface_snapshot scripts/openapi_surface.baseline.json

    # gate: fail if the live surface drifts from the committed baseline
    python -m scripts.openapi_surface_snapshot --check scripts/openapi_surface.baseline.json

    # ad-hoc before/after a refactor (write two files, `diff` them)
    python -m scripts.openapi_surface_snapshot /tmp/before.json

The snapshot deliberately excludes anything env/version-dependent (no info block,
no APP_VERSION), so only a real change to the route set / signatures / OpenAPI
operations moves it.
"""
import json
import os
import sys
sys.path.insert(0, os.path.abspath("."))
os.environ.setdefault("DEV_MODE", "true")

_DEFAULT_BASELINE = os.path.join(os.path.dirname(__file__), "openapi_surface.baseline.json")


def build_surface() -> dict:
    """The public HTTP contract, taken from the generated OpenAPI document.

    We deliberately do NOT walk ``app.routes`` for the per-route table: FastAPI
    0.140 registers ``include_router`` as lazy ``_IncludedRouter`` proxies, so a
    top-level ``app.routes`` walk sees only a handful of routes while
    ``app.openapi()`` still resolves every operation. The OpenAPI document is
    both complete on that version and the actual client-facing contract, so it is
    the right thing to gate on. Prose (summary/description) is excluded on
    purpose - a docstring edit is not a surface change and must not fail the gate.
    """
    from app.main import app

    spec = app.openapi()
    paths = {}
    for p, ops in spec.get("paths", {}).items():
        for m, op in ops.items():
            if not isinstance(op, dict):     # path-level "parameters"/$ref, not an operation
                continue
            paths[f"{m.upper()} {p}"] = {
                "operationId": op.get("operationId"),
                "tags": op.get("tags"),
                "parameters": [(x.get("name"), x.get("in"), x.get("required")) for x in op.get("parameters", [])],
                "requestBody": json.dumps(op.get("requestBody"), sort_keys=True),
                "responses": {k: json.dumps(v, sort_keys=True) for k, v in sorted(op.get("responses", {}).items())},
            }

    return {
        # the method+path SET is the surface; the per-op detail carries params,
        # request/response schemas and status codes; components carries the
        # pydantic model schemas the operations $ref into.
        "operations": sorted(paths.keys()),
        "openapi_paths": dict(sorted(paths.items())),
        "components": json.dumps(spec.get("components"), sort_keys=True),
    }


def _canonical(surface: dict) -> str:
    return json.dumps(surface, indent=1, sort_keys=True, default=str)


def main() -> int:
    args = sys.argv[1:]
    if args and args[0] == "--check":
        baseline_path = args[1] if len(args) > 1 else _DEFAULT_BASELINE
        current = _canonical(build_surface())
        with open(baseline_path, encoding="utf-8") as f:
            baseline = _canonical(json.load(f))
        if current == baseline:
            n = len(json.loads(current)["operations"])
            print(f"[openapi] OK — HTTP surface matches baseline ({n} operations).")
            return 0
        import difflib
        diff = list(difflib.unified_diff(
            baseline.splitlines(), current.splitlines(),
            "baseline", "current", lineterm=""))
        print(f"[openapi] FAIL — the HTTP surface drifted from the committed baseline "
              f"({sum(1 for d in diff if d[:1] in '+-' and d[:2] not in ('+++', '---'))} changed lines):")
        print("\n".join(diff[:200]))
        if len(diff) > 200:
            print(f"          … {len(diff) - 200} more diff lines")
        print(f"[openapi] If this change is intentional, refresh the baseline:\n"
              f"          python -m scripts.openapi_surface_snapshot {baseline_path}")
        return 1

    # write/refresh mode
    path = args[0] if args else _DEFAULT_BASELINE
    surface = build_surface()
    with open(path, "w", encoding="utf-8") as f:
        f.write(_canonical(surface))
    print(f"{len(surface['operations'])} openapi operations -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
