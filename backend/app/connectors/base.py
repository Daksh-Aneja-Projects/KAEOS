"""
KAEOS L0 — Connector Framework (merged from Extract-OS)

Every connector implements the Connector interface:
- authenticate / health_check
- fetch_schema — discover source data structure
- fetch_delta — incremental sync (changed records only)
- fetch_full — full historical sync
"""
from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import logging

logger = logging.getLogger(__name__)


@dataclass
class SyncCursor:
    """Resumption point for incremental sync — connector-specific."""
    type: str  # "timestamp" | "offset" | "id_range" | "page_token"
    value: Any
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class SourceRecord:
    """A single record extracted from a source connector."""
    id: str
    source_table: str
    data: dict
    raw_hash: str = ""
    ingested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.raw_hash:
            self.raw_hash = hashlib.sha256(
                json.dumps(self.data, sort_keys=True, default=str).encode()
            ).hexdigest()


@dataclass
class RecordBatch:
    """A batch of records from a connector sync."""
    records: list[SourceRecord]
    cursor: Optional[SyncCursor] = None
    has_more: bool = False
    total_count: Optional[int] = None


@dataclass
class SourceSchema:
    """Schema definition discovered from a source connector."""
    tables: list[dict]
    raw: Optional[dict] = None


class BaseConnector(ABC):
    """
    Abstract base class for all KAEOS connectors.
    Every connector must implement these methods.
    """

    def __init__(self, config: dict, credentials: dict):
        self.config = config
        self.credentials = credentials
        self.logger = logging.getLogger(f"connector.{self.__class__.__name__}")

    @abstractmethod
    async def authenticate(self) -> bool:
        """Validate credentials and establish connection."""
        ...

    @abstractmethod
    async def health_check(self) -> dict:
        """Check connector health. Returns {"status": "healthy|unhealthy", "message": "..."}"""
        ...

    @abstractmethod
    async def fetch_schema(self) -> SourceSchema:
        """Discover and return the source data schema."""
        ...

    @abstractmethod
    async def fetch_delta(self, cursor: Optional[SyncCursor] = None) -> RecordBatch:
        """Fetch only records changed since the given cursor."""
        ...

    @abstractmethod
    async def fetch_full(self) -> AsyncIterator[RecordBatch]:
        """Full sync — yields batches of all records."""
        ...

    def generate_record_id(self, source_table: str, primary_key: str) -> str:
        """Deterministic record ID: SHA-256(connector_type + source_table + primary_key)."""
        raw = f"{self.__class__.__name__}:{source_table}:{primary_key}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]
