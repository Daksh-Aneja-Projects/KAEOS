"""KAEOS Polystore — Blob/object deletion for GDPR erasure.

The relational erasure (``privacy_erasure``) tombstones PII rows and nulls the DB
pointer to a stored file, but the FILE itself lives outside the database. This
module deletes that file so a subject's resume/document does not survive erasure
in the blob layer.

Backends, chosen by the path/URI scheme:
  * local filesystem path  — ``os.remove`` (the dev/default deployment stores
    resumes as local files; the recruiting agent reads them with ``open()``).
  * ``s3://bucket/key``     — best-effort via boto3 IF installed and credentialed.
  * ``gs://bucket/key``     — best-effort via google-cloud-storage IF installed.

Best-effort by design: a storage outage or a missing SDK must never abort the DB
erasure that already committed. Every call returns an auditable per-path result
so the caller can record exactly what was and was not removed.
"""
from __future__ import annotations

import logging
import os
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# A tombstone value written by the erasure step is not a real path — never try to
# delete it (and never treat it as a filesystem traversal).
_SENTINELS = {"[ERASED]", "[REDACTED:INJECTION]", ""}


def _result(path: str, deleted: bool, backend: str, error: str | None = None) -> dict:
    r = {"path": path, "deleted": deleted, "backend": backend}
    if error:
        r["error"] = error
    return r


async def delete_blob(path: str | None) -> dict:
    """Delete a single blob by local path or object-store URI. Best-effort.

    Returns ``{path, deleted: bool, backend, error?}``. ``deleted`` is False (not
    an exception) for a missing file, an unconfigured backend, or any error, so a
    caller can safely aggregate results across many subjects.
    """
    if not path or path in _SENTINELS:
        return _result(path or "", False, "none", "empty or tombstoned path")

    scheme = (urlparse(path).scheme or "").lower()
    # A Windows drive letter ("C:\\resume.pdf") parses as a single-char scheme —
    # that is a local path, not an object-store URI. Real schemes are longer.
    if len(scheme) <= 1:
        scheme = ""

    if scheme in ("s3",):
        return await _delete_s3(path)
    if scheme in ("gs", "gcs"):
        return await _delete_gcs(path)
    if scheme in ("", "file"):
        return _delete_local(path[7:] if scheme == "file" else path)

    return _result(path, False, scheme, f"unsupported blob scheme '{scheme}'")


def _delete_local(path: str) -> dict:
    try:
        if not os.path.isfile(path):
            return _result(path, False, "local", "file not found")
        os.remove(path)
        return _result(path, True, "local")
    except OSError as e:
        logger.warning("[BlobStore] local delete failed for %s: %s", path, e)
        return _result(path, False, "local", str(e))


async def _delete_s3(uri: str) -> dict:
    try:
        import boto3  # optional dependency
    except ImportError:
        return _result(uri, False, "s3", "boto3 not installed")
    try:
        parsed = urlparse(uri)
        bucket, key = parsed.netloc, parsed.path.lstrip("/")
        import asyncio
        client = boto3.client("s3")
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: client.delete_object(Bucket=bucket, Key=key)
        )
        return _result(uri, True, "s3")
    except Exception as e:  # credentials / network / permissions
        logger.warning("[BlobStore] s3 delete failed for %s: %s", uri, e)
        return _result(uri, False, "s3", str(e))


async def _delete_gcs(uri: str) -> dict:
    try:
        from google.cloud import storage  # optional dependency
    except ImportError:
        return _result(uri, False, "gcs", "google-cloud-storage not installed")
    try:
        parsed = urlparse(uri)
        bucket_name, blob_name = parsed.netloc, parsed.path.lstrip("/")
        import asyncio

        def _do():
            client = storage.Client()
            client.bucket(bucket_name).blob(blob_name).delete()

        await asyncio.get_running_loop().run_in_executor(None, _do)
        return _result(uri, True, "gcs")
    except Exception as e:
        logger.warning("[BlobStore] gcs delete failed for %s: %s", uri, e)
        return _result(uri, False, "gcs", str(e))


async def delete_blobs(paths: list[str | None]) -> dict:
    """Delete many blobs; return ``{attempted, deleted, results}``.

    Deduplicates and skips empties/tombstones. Never raises — aggregates the
    per-path outcomes so erasure can log a complete, honest receipt.
    """
    seen: set[str] = set()
    results: list[dict] = []
    for p in paths:
        if not p or p in _SENTINELS or p in seen:
            continue
        seen.add(p)
        results.append(await delete_blob(p))
    deleted = sum(1 for r in results if r.get("deleted"))
    return {"attempted": len(results), "deleted": deleted, "results": results}
