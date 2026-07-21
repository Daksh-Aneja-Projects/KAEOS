"""
KAEOS — Transform Node Registry & DAG Nodes (KAEOS Data Fabric)
Includes: FieldMapper, Deduplicator, Normalizer, Filter, MetadataInjector
"""
from app.transforms.base import BaseTransformNode, TransformRecord, TransformResult
from datetime import datetime, timezone
import hashlib
import json
import re
import logging

logger = logging.getLogger(__name__)


class FieldMapperNode(BaseTransformNode):
    """Map source fields to target schema."""

    def validate_config(self) -> list[str]:
        if not self.config.get("mappings") and not self.config.get("auto_detect"):
            return ["Either 'mappings' or 'auto_detect' must be provided"]
        return []

    async def process(self, records: list[TransformRecord]) -> TransformResult:
        mappings = self.config.get("mappings", {})
        drop_unmapped = self.config.get("drop_unmapped", False)
        auto_detect = self.config.get("auto_detect", False)
        processed = []

        for record in records:
            new_data = {}
            if auto_detect and not mappings:
                for key, value in record.data.items():
                    new_data[key.lower().replace(" ", "_").replace("-", "_")] = value
            else:
                for target, source_config in mappings.items():
                    source_field = source_config if isinstance(source_config, str) else source_config.get("source", "")
                    transform = None if isinstance(source_config, str) else source_config.get("transform")
                    value = record.data.get(source_field)
                    if value is not None and transform:
                        value = self._apply_transform(value, transform)
                    if value is not None:
                        new_data[target] = value
                if not drop_unmapped:
                    for key, value in record.data.items():
                        if key not in new_data:
                            new_data[key] = value

            record.data = new_data
            self.add_lineage(record, f"field_mapped:{len(mappings)}_fields")
            processed.append(record)

        return TransformResult(records=processed, stats={"total_records": len(records), "mapped_fields": len(mappings)})

    @staticmethod
    def _apply_transform(value, transform: str):
        if transform == "lowercase": return str(value).lower()
        elif transform == "uppercase": return str(value).upper()
        elif transform == "strip": return str(value).strip()
        elif transform == "to_string": return str(value)
        elif transform == "to_int":
            try: return int(value)
            except (ValueError, TypeError): return None
        return value


class DeduplicatorNode(BaseTransformNode):
    """Remove duplicate records."""

    def validate_config(self) -> list[str]:
        if not self.config.get("key_fields") and self.config.get("strategy") != "hash":
            return ["key_fields required for exact dedup strategy"]
        return []

    async def process(self, records: list[TransformRecord]) -> TransformResult:
        key_fields = self.config.get("key_fields", [])
        strategy = self.config.get("strategy", "exact")
        seen = set()
        unique_records = []
        duplicates = 0

        for record in records:
            if strategy == "hash":
                key = hashlib.sha256(json.dumps(record.data, sort_keys=True, default=str).encode()).hexdigest()
            else:
                key = "|".join(str(record.data.get(f, "")) for f in key_fields)

            if key not in seen:
                seen.add(key)
                self.add_lineage(record, "dedup:kept")
                unique_records.append(record)
            else:
                duplicates += 1

        return TransformResult(records=unique_records, stats={"total": len(records), "unique": len(unique_records), "duplicates": duplicates})


class NormalizerNode(BaseTransformNode):
    """Standardize data formats."""

    def validate_config(self) -> list[str]:
        return []

    async def process(self, records: list[TransformRecord]) -> TransformResult:
        rules = self.config.get("rules", [])
        normalized = 0
        for record in records:
            for rule in rules:
                field_name = rule.get("field")
                norm_type = rule.get("type")
                if field_name not in record.data or record.data[field_name] is None:
                    continue
                value = record.data[field_name]
                if norm_type == "email": record.data[field_name] = str(value).lower().strip(); normalized += 1
                elif norm_type == "phone": record.data[field_name] = re.sub(r"[^\d+]", "", str(value)); normalized += 1
                elif norm_type == "lowercase": record.data[field_name] = str(value).lower(); normalized += 1
            self.add_lineage(record, f"normalized:{normalized}_fields")

        return TransformResult(records=records, stats={"total": len(records), "normalized_fields": normalized})


class FilterNode(BaseTransformNode):
    """Drop records matching filter criteria."""

    def validate_config(self) -> list[str]:
        if not self.config.get("conditions"):
            return ["At least one filter condition required"]
        return []

    async def process(self, records: list[TransformRecord]) -> TransformResult:
        conditions = self.config.get("conditions", [])
        mode = self.config.get("mode", "exclude")
        filtered, dropped = [], 0

        for record in records:
            matches = self._evaluate(record.data, conditions)
            if (mode == "exclude" and not matches) or (mode == "include" and matches):
                filtered.append(record)
                self.add_lineage(record, "filter:kept")
            else:
                dropped += 1

        return TransformResult(records=filtered, stats={"total": len(records), "kept": len(filtered), "dropped": dropped})

    @staticmethod
    def _evaluate(data: dict, conditions: list[dict]) -> bool:
        for c in conditions:
            actual = data.get(c.get("field", ""))
            expected = c.get("value")
            op = c.get("operator", "eq")
            if op == "eq" and actual != expected: return False
            elif op == "neq" and actual == expected: return False
            elif op == "contains" and expected not in str(actual): return False
            elif op == "exists" and actual is None: return False
            elif op == "gt" and (actual is None or actual <= expected): return False
            elif op == "lt" and (actual is None or actual >= expected): return False
        return True


class MetadataInjectorNode(BaseTransformNode):
    """Attach metadata to records/chunks."""

    def validate_config(self) -> list[str]:
        return []

    async def process(self, records: list[TransformRecord]) -> TransformResult:
        inject = self.config.get("inject", {})
        for record in records:
            record.metadata.update(inject)
            if self.config.get("include_timestamp", True):
                record.metadata["processed_at"] = datetime.now(timezone.utc).isoformat()
            for chunk in record.chunks:
                chunk["metadata"] = {**chunk.get("metadata", {}), **record.metadata}
            self.add_lineage(record, "metadata_injected")

        return TransformResult(records=records, stats={"total": len(records), "keys_injected": len(inject)})


# ── Registry ──
NODE_REGISTRY: dict[str, type[BaseTransformNode]] = {
    "field_mapper": FieldMapperNode,
    "deduplicator": DeduplicatorNode,
    "normalizer": NormalizerNode,
    "filter": FilterNode,
    "metadata_injector": MetadataInjectorNode,
}


def get_node_class(node_type: str) -> type[BaseTransformNode]:
    if node_type == "chunker":
        from app.transforms.chunker import ChunkerNode
        return ChunkerNode
    elif node_type == "pii_scrubber":
        from app.transforms.pii_scrubber import PIIScrubberNode
        return PIIScrubberNode
    elif node_type in NODE_REGISTRY:
        return NODE_REGISTRY[node_type]
    raise ValueError(f"Unknown transform node: {node_type}")
