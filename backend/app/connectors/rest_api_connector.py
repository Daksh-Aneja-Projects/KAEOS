"""
KAEOS L0 — Universal REST API Connector (KAEOS Data Fabric)
"""
import httpx
from typing import AsyncIterator, Optional
from app.connectors.base import (
    BaseConnector, SourceRecord, RecordBatch, SyncCursor, SourceSchema,
)
import logging

logger = logging.getLogger(__name__)


class RESTAPIConnector(BaseConnector):
    """
    Universal REST API connector — connect to any HTTP API.
    Config: base_url, endpoint, method, headers, params, data_path,
            pagination_type, auth_type, batch_size
    """

    async def authenticate(self) -> bool:
        base_url = self.config.get("base_url", "")
        if not base_url:
            return False
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(base_url, headers=self._build_headers())
                return resp.status_code < 500
        except Exception as e:
            logger.warning(f"REST connector auth failed for {base_url}: {e}")
            return False

    async def health_check(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(self.config.get("base_url", ""), headers=self._build_headers())
                return {"status": "healthy" if resp.status_code < 400 else "unhealthy", "message": f"Status {resp.status_code}"}
        except Exception as e:
            return {"status": "unhealthy", "message": str(e)}

    async def fetch_schema(self) -> SourceSchema:
        batch = await self.fetch_delta()
        if batch.records:
            fields = [{"name": k, "type": type(v).__name__} for k, v in batch.records[0].data.items()]
            return SourceSchema(tables=[{"name": self.config.get("endpoint", "records"), "fields": fields}])
        return SourceSchema(tables=[])

    async def fetch_delta(self, cursor: Optional[SyncCursor] = None) -> RecordBatch:
        base_url = self.config.get("base_url", "")
        endpoint = self.config.get("endpoint", "")
        params = dict(self.config.get("params", {}))
        batch_size = self.config.get("batch_size", 100)
        pagination_type = self.config.get("pagination_type", "none")

        if cursor and pagination_type == "offset":
            params["offset"] = cursor.value
            params["limit"] = batch_size
        elif cursor and pagination_type == "page":
            params["page"] = cursor.value
            params["per_page"] = batch_size

        url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}" if endpoint else base_url

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(url, headers=self._build_headers(), params=params)
            resp.raise_for_status()
            data = resp.json()
            items = self._extract_data(data, self.config.get("data_path", ""))
            if not isinstance(items, list):
                items = [items] if items else []

            records = [
                SourceRecord(
                    id=self.generate_record_id(endpoint or "records", str(item.get("id", i))),
                    source_table=endpoint or "records",
                    data=item,
                )
                for i, item in enumerate(items)
            ]

            has_more = False
            next_cursor = None
            if pagination_type != "none" and len(items) >= batch_size:
                has_more = True
                if pagination_type == "offset":
                    next_cursor = SyncCursor(type="offset", value=int(cursor.value if cursor else 0) + batch_size)
                elif pagination_type == "page":
                    next_cursor = SyncCursor(type="page", value=int(cursor.value if cursor else 1) + 1)

            return RecordBatch(records=records, cursor=next_cursor, has_more=has_more)

    async def fetch_full(self) -> AsyncIterator[RecordBatch]:
        cursor = None
        while True:
            batch = await self.fetch_delta(cursor)
            yield batch
            if not batch.has_more:
                break
            cursor = batch.cursor

    def _build_headers(self) -> dict:
        headers = dict(self.config.get("headers", {}))
        auth_type = self.config.get("auth_type", "none")
        if auth_type == "bearer":
            headers["Authorization"] = f"Bearer {self.credentials.get('token', '')}"
        elif auth_type == "api_key":
            headers[self.config.get("api_key_header", "X-API-Key")] = self.credentials.get("api_key", "")
        headers.setdefault("Content-Type", "application/json")
        return headers

    @staticmethod
    def _extract_data(response, path: str):
        if not path:
            return response
        current = response
        for part in path.split("."):
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
        return current
