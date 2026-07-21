"""
KAEOS L0 — CSV Connector (KAEOS Data Fabric)
Supports CSV, TSV, and structured text files.
"""
import csv
import os
from typing import AsyncIterator, Optional
from app.connectors.base import (
    BaseConnector, SourceRecord, RecordBatch, SyncCursor, SourceSchema,
)
import logging

logger = logging.getLogger(__name__)


class CSVConnector(BaseConnector):
    """
    CSV/TSV file connector — ingests data from local or remote CSV files.

    Config:
        file_path: str — path to CSV file or directory of CSVs
        delimiter: str — field delimiter (default: ",")
        encoding: str — file encoding (default: "utf-8")
        has_header: bool — first row is header (default: True)
        batch_size: int — records per batch (default: 1000)
        text_fields: list[str] — fields to concatenate as text_content
    """

    async def authenticate(self) -> bool:
        file_path = self.config.get("file_path", "")
        if not file_path:
            return False
        return os.path.exists(file_path)

    async def health_check(self) -> dict:
        file_path = self.config.get("file_path", "")
        if os.path.exists(file_path):
            size = os.path.getsize(file_path) if os.path.isfile(file_path) else 0
            return {"status": "healthy", "message": f"File accessible, size: {size} bytes"}
        return {"status": "unhealthy", "message": f"File not found: {file_path}"}

    async def fetch_schema(self) -> SourceSchema:
        file_path = self.config.get("file_path", "")
        delimiter = self.config.get("delimiter", ",")
        encoding = self.config.get("encoding", "utf-8")

        tables = []
        files = self._get_files(file_path)

        for fp in files:
            with open(fp, "r", encoding=encoding) as f:
                reader = csv.DictReader(f, delimiter=delimiter)
                fields = [{"name": col, "type": "string"} for col in (reader.fieldnames or [])]
                tables.append({"name": os.path.basename(fp), "fields": fields})

        return SourceSchema(tables=tables)

    async def fetch_delta(self, cursor: Optional[SyncCursor] = None) -> RecordBatch:
        file_path = self.config.get("file_path", "")
        delimiter = self.config.get("delimiter", ",")
        encoding = self.config.get("encoding", "utf-8")
        batch_size = self.config.get("batch_size", 1000)

        start_offset = int(cursor.value) if cursor else 0
        records = []

        with open(file_path, "r", encoding=encoding) as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            for i, row in enumerate(reader):
                if i < start_offset:
                    continue
                if len(records) >= batch_size:
                    return RecordBatch(
                        records=records,
                        cursor=SyncCursor(type="offset", value=i),
                        has_more=True,
                    )
                records.append(SourceRecord(
                    id=self.generate_record_id(os.path.basename(file_path), str(i)),
                    source_table=os.path.basename(file_path),
                    data=dict(row),
                ))

        return RecordBatch(
            records=records,
            cursor=SyncCursor(type="offset", value=start_offset + len(records)),
            has_more=False,
        )

    async def fetch_full(self) -> AsyncIterator[RecordBatch]:
        cursor = None
        while True:
            batch = await self.fetch_delta(cursor)
            yield batch
            if not batch.has_more:
                break
            cursor = batch.cursor

    def _get_files(self, path: str) -> list[str]:
        if os.path.isfile(path):
            return [path]
        elif os.path.isdir(path):
            return [os.path.join(path, f) for f in os.listdir(path) if f.endswith((".csv", ".tsv", ".txt"))]
        return []
