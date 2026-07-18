"""
KAEOS — Destination Adapters (merged from Extract-OS)
Output targets for pipeline data: Local File, Webhook
"""
from abc import ABC, abstractmethod
from typing import Optional
from dataclasses import dataclass, field
import json
import os
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)


@dataclass
class WriteResult:
    records_written: int = 0
    records_failed: int = 0
    errors: list[dict] = field(default_factory=list)


class BaseDestination(ABC):
    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    async def connect(self) -> bool: ...

    @abstractmethod
    async def write(self, records: list[dict], metadata: Optional[dict] = None) -> WriteResult: ...

    @abstractmethod
    async def delete(self, ids: list[str]) -> int: ...

    @abstractmethod
    async def health_check(self) -> dict: ...


class LocalFileDestination(BaseDestination):
    """Write pipeline output to local JSONL files."""

    OUTPUT_BASE = "./data/output"

    def _resolve_output_dir(self) -> str:
        """Confine output inside OUTPUT_BASE.

        `output_dir` comes straight from the (authenticated) API request, so an
        absolute path or `..` segment would let a tenant write anywhere the
        process can. Relative paths are joined under the base; escapes are
        rejected, not silently rewritten.
        """
        base = os.path.abspath(self.OUTPUT_BASE)
        requested = str(self.config.get("output_dir") or "")
        if not requested:
            return base
        if os.path.isabs(requested):
            raise ValueError("output_dir must be a relative path (it is resolved under the pipeline output directory)")
        candidate = os.path.abspath(os.path.join(base, requested))
        if candidate != base and not candidate.startswith(base + os.sep):
            raise ValueError("output_dir may not escape the pipeline output directory")
        return candidate

    async def connect(self) -> bool:
        os.makedirs(self._resolve_output_dir(), exist_ok=True)
        return True

    async def write(self, records: list[dict], metadata: Optional[dict] = None) -> WriteResult:
        output_dir = self._resolve_output_dir()
        fmt = self.config.get("format", "jsonl")
        pipeline_id = (metadata or {}).get("pipeline_id", "unknown")
        run_id = (metadata or {}).get("run_id", "unknown")

        os.makedirs(output_dir, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(output_dir, f"{pipeline_id}_{run_id}_{timestamp}.{fmt}")

        written, errors = 0, []
        try:
            if fmt == "jsonl":
                with open(filepath, "w", encoding="utf-8") as f:
                    for record in records:
                        f.write(json.dumps(record, default=str) + "\n")
                        written += 1
            elif fmt == "json":
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(records, f, indent=2, default=str)
                    written = len(records)
        except Exception as e:
            errors.append({"error": str(e)})

        return WriteResult(records_written=written, errors=errors)

    async def delete(self, ids: list[str]) -> int:
        return 0

    async def health_check(self) -> dict:
        try:
            os.makedirs(self._resolve_output_dir(), exist_ok=True)
            return {"status": "healthy"}
        except Exception as e:
            return {"status": "unhealthy", "message": str(e)}


class WebhookDestination(BaseDestination):
    """Push pipeline output to a webhook URL via HTTP POST."""

    async def connect(self) -> bool:
        return bool(self.config.get("url"))

    async def write(self, records: list[dict], metadata: Optional[dict] = None) -> WriteResult:
        import httpx
        url = self.config.get("url", "")
        headers = self.config.get("headers", {"Content-Type": "application/json"})
        batch_size = self.config.get("batch_size", 100)
        written, errors = 0, []

        async with httpx.AsyncClient(timeout=30) as client:
            for i in range(0, len(records), batch_size):
                batch = records[i:i + batch_size]
                try:
                    resp = await client.post(url, json={"data": batch, "metadata": metadata or {}}, headers=headers)
                    resp.raise_for_status()
                    written += len(batch)
                except Exception as e:
                    errors.append({"batch": i, "error": str(e)})

        return WriteResult(records_written=written, errors=errors)

    async def delete(self, ids: list[str]) -> int:
        return 0

    async def health_check(self) -> dict:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(self.config.get("url", ""))
                return {"status": "healthy" if resp.status_code < 500 else "unhealthy"}
        except Exception as e:
            return {"status": "unhealthy", "message": str(e)}


DESTINATION_REGISTRY = {"local_file": LocalFileDestination, "webhook": WebhookDestination}


def get_destination(dest_type: str, config: dict) -> BaseDestination:
    cls = DESTINATION_REGISTRY.get(dest_type)
    if not cls:
        raise ValueError(f"Unknown destination type: {dest_type}")
    return cls(config)
