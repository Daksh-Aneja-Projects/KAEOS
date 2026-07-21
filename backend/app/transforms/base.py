"""
KAEOS L1/L2 — Transform Engine Base (KAEOS Data Fabric)
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)


@dataclass
class TransformRecord:
    """A record flowing through the transform pipeline."""
    id: str
    source_record_id: str
    data: dict
    text_content: str = ""
    metadata: dict = field(default_factory=dict)
    chunks: list[dict] = field(default_factory=list)
    pii_detections: list[dict] = field(default_factory=list)
    lineage: list[dict] = field(default_factory=list)


@dataclass
class TransformResult:
    """Result of processing a batch through a transform node."""
    records: list[TransformRecord]
    stats: dict = field(default_factory=dict)
    errors: list[dict] = field(default_factory=list)


class BaseTransformNode(ABC):
    """Abstract base class for all transform nodes in the DAG."""

    def __init__(self, node_id: str, config: dict):
        self.node_id = node_id
        self.config = config
        self.logger = logging.getLogger(f"transform.{self.__class__.__name__}")

    @abstractmethod
    async def process(self, records: list[TransformRecord]) -> TransformResult:
        """Process a batch of records. Returns transformed records + stats."""
        ...

    @abstractmethod
    def validate_config(self) -> list[str]:
        """Validate node configuration. Returns list of validation errors."""
        ...

    def add_lineage(self, record: TransformRecord, action: str):
        """Track lineage — append transform step to record history."""
        record.lineage.append({
            "node_id": self.node_id,
            "node_type": self.__class__.__name__,
            "action": action,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
