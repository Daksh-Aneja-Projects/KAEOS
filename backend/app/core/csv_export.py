"""Small helper to render a list of dict rows as a downloadable CSV response.

Used by the audit/compliance export endpoints (Actions Ledger, Provenance
Ledger, Compliance frameworks) so operators can pull evidence for auditors
without screen-scraping the UI.
"""
import csv
import io
from typing import Any, Sequence

from starlette.responses import Response


def csv_response(rows: Sequence[dict], filename: str, columns: list[str] | None = None) -> Response:
    """Serialize ``rows`` to a text/csv download.

    ``columns`` fixes the header order; when omitted it is the union of keys in
    first-seen order. Values that are dict/list are JSON-ish stringified so the
    cell stays single-valued. An empty result still returns a valid header row.
    """
    if columns is None:
        columns = []
        seen = set()
        for r in rows:
            for k in r.keys():
                if k not in seen:
                    seen.add(k)
                    columns.append(k)

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow({c: _cell(r.get(c)) for c in columns})

    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _cell(v: Any) -> Any:
    if isinstance(v, (dict, list)):
        import json
        return json.dumps(v, separators=(",", ":"), default=str)
    return "" if v is None else v
