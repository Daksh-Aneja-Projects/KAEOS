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
        v = json.dumps(v, separators=(",", ":"), default=str)
    if v is None:
        return ""
    # CSV/formula-injection neutralization: a tenant-controlled value that starts
    # with a formula trigger (=,+,-,@,tab,CR) would execute in Excel/LibreOffice
    # when an admin opens an exported evidence file. Prefix a single quote so the
    # cell is treated as text, never a formula.
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v
