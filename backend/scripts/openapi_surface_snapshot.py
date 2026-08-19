"""Dump the full HTTP surface so a refactor can be proven behaviour-preserving.

Walks app.main's route table AND the generated OpenAPI document, emitting a
deterministic JSON snapshot. Run before and after; `diff` must be empty.
"""
import json
import os
import sys
sys.path.insert(0, os.path.abspath("."))
os.environ.setdefault("DEV_MODE", "true")

from fastapi.routing import APIRoute
from app.main import app

routes = []
for r in app.routes:
    if not isinstance(r, APIRoute):
        continue
    routes.append({
        "path": r.path,
        "methods": sorted(r.methods),
        "name": r.name,
        "operation_id": r.operation_id,
        "unique_id": r.unique_id,
        "status_code": r.status_code,
        "response_model": getattr(r.response_model, "__name__", str(r.response_model)),
        "response_class": r.response_class.__class__.__name__ if not isinstance(r.response_class, type) else r.response_class.__name__,
        "tags": list(r.tags),
        "summary": r.summary,
        "description": r.description,
        "deprecated": r.deprecated,
        "include_in_schema": r.include_in_schema,
        "dependencies": len(r.dependencies),
        "dependant_params": sorted(
            (p.name, str(p.field_info.__class__.__name__)) for p in
            (r.dependant.path_params + r.dependant.query_params + r.dependant.header_params + r.dependant.cookie_params)
        ),
        "body_field": getattr(r.body_field, "name", None) if r.body_field else None,
        "responses": {str(k): sorted(v) for k, v in sorted(r.responses.items())},
    })

spec = app.openapi()
paths = {}
for p, ops in spec.get("paths", {}).items():
    for m, op in ops.items():
        paths[f"{m.upper()} {p}"] = {
            "operationId": op.get("operationId"),
            "summary": op.get("summary"),
            "description": op.get("description"),
            "tags": op.get("tags"),
            "parameters": [(x.get("name"), x.get("in"), x.get("required")) for x in op.get("parameters", [])],
            "requestBody": json.dumps(op.get("requestBody"), sort_keys=True),
            "responses": {k: json.dumps(v, sort_keys=True) for k, v in sorted(op.get("responses", {}).items())},
        }

out = {
    "route_order": [f"{','.join(r['methods'])} {r['path']}" for r in routes],
    "routes": sorted(routes, key=lambda r: (r["path"], r["methods"])),
    "openapi_paths": dict(sorted(paths.items())),
    "components": json.dumps(spec.get("components"), sort_keys=True),
}
with open(sys.argv[1], "w", encoding="utf-8") as f:
    json.dump(out, f, indent=1, sort_keys=True, default=str)
print(f"{len(routes)} routes, {len(paths)} openapi operations -> {sys.argv[1]}")
