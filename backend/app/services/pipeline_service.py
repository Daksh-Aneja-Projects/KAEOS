"""
KAEOS L0 — Pipeline Service (KAEOS Data Fabric)
Orchestrates: Extract → Transform (DAG) → Load → Signal Ingestion
This is the HARVEST mode engine for the epistemic OS.
"""
from datetime import datetime, timezone
from app.connectors.base import SourceRecord
from app.transforms.base import TransformRecord
from app.transforms import get_node_class
from app.destinations import get_destination
import logging
import uuid

logger = logging.getLogger(__name__)


class PipelineService:
    """
    Core pipeline orchestration — KAEOS Data Fabric ETL engine.
    Drives the L0 Data Fabric Connector Mesh.
    """

    @staticmethod
    async def run_pipeline(
        tenant_id: str,
        connector_config: dict,
        connector_credentials: dict,
        connector_slug: str,
        dag_config: dict | None = None,
        destination_type: str = "local_file",
        destination_config: dict | None = None,
    ) -> dict:
        """
        Execute a full Extract → Transform → Load pipeline for ONE tenant.

        `tenant_id` is REQUIRED and has no default: this is the one path that
        pulls EXTERNAL data into the platform, so every ingested/loaded record
        must be attributable to its tenant. We also bind the tenant into the
        ambient context so any DB session opened downstream is RLS-scoped even
        when the pipeline is driven outside an HTTP request (e.g. a worker).
        """
        if not tenant_id:
            raise ValueError("run_pipeline requires a tenant_id (external data ingestion must be tenant-scoped)")
        from app.core.context import current_tenant_id
        current_tenant_id.set(tenant_id)

        run_id = str(uuid.uuid4())
        log_entries = []

        def log(msg: str, level: str = "info"):
            log_entries.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": level,
                "message": msg,
            })
            logger.info(msg) if level == "info" else logger.warning(msg)

        try:
            log(f"Pipeline run {run_id} started")

            # ── STEP 1: EXTRACT ──
            log("Step 1: Extracting from source connector...")
            from app.connectors import get_connector_class
            ConnectorClass = get_connector_class(connector_slug)
            connector = ConnectorClass(config=connector_config, credentials=connector_credentials)

            if not await connector.authenticate():
                raise ValueError("Connector authentication failed")

            all_records: list[SourceRecord] = []
            cursor = None
            while True:
                batch = await connector.fetch_delta(cursor)
                all_records.extend(batch.records)
                if not batch.has_more:
                    break
                cursor = batch.cursor

            log(f"Extracted {len(all_records)} records")

            if not all_records:
                log("No records extracted", "warning")
                return {
                    "run_id": run_id, "status": "SUCCESS",
                    "records_read": 0, "records_written": 0,
                    "log": log_entries,
                }

            # ── STEP 2: TRANSFORM ──
            log("Step 2: Running transform DAG...")
            transform_records = [
                TransformRecord(
                    id=sr.id, source_record_id=sr.id,
                    data=sr.data,
                    # Stamp tenant_id onto every record's metadata at the source
                    # so it survives the transform DAG and lands on the output.
                    metadata={**(sr.metadata or {}), "tenant_id": tenant_id},
                )
                for sr in all_records
            ]

            dag = dag_config or {}
            nodes = dag.get("nodes", [])
            edges = dag.get("edges", [])

            if nodes:
                sorted_nodes = PipelineService._topological_sort(nodes, edges)
                for node_config in sorted_nodes:
                    node_type = node_config.get("type")
                    node_id = node_config.get("id")
                    config = node_config.get("config", {})

                    log(f"  Executing transform: {node_type} ({node_id})")
                    NodeClass = get_node_class(node_type)
                    node = NodeClass(node_id=node_id, config=config)
                    result = await node.process(transform_records)
                    transform_records = result.records
                    log(f"  Node complete — stats: {result.stats}")
            else:
                # Auto text extraction for records with no DAG
                for r in transform_records:
                    text_parts = [f"{k}: {v}" for k, v in r.data.items() if isinstance(v, str) and len(v) > 10]
                    r.text_content = "\n".join(text_parts)

            total_chunks = sum(len(r.chunks) for r in transform_records)
            total_pii = sum(len(r.pii_detections) for r in transform_records)
            log(f"Transform complete — {len(transform_records)} records, {total_chunks} chunks, {total_pii} PII detections")

            # ── STEP 3: LOAD ──
            log("Step 3: Loading to destination...")
            dest = get_destination(destination_type, destination_config or {})
            await dest.connect()

            output_records = []
            for record in transform_records:
                if record.chunks:
                    for ch in record.chunks:
                        # Chunks are dicts/objects produced by transforms — ensure
                        # each carries the tenant so nothing untenanted is loaded.
                        if isinstance(ch, dict):
                            ch.setdefault("tenant_id", tenant_id)
                            meta = ch.get("metadata")
                            if isinstance(meta, dict):
                                meta.setdefault("tenant_id", tenant_id)
                        output_records.append(ch)
                else:
                    output_records.append({
                        "record_id": record.id,
                        "tenant_id": tenant_id,
                        "data": record.data,
                        "text_content": record.text_content,
                        "metadata": {**(record.metadata or {}), "tenant_id": tenant_id},
                    })

            write_result = await dest.write(
                output_records, metadata={"run_id": run_id, "tenant_id": tenant_id}
            )
            log(f"Loaded {write_result.records_written} records to {destination_type}")

            return {
                "run_id": run_id,
                "status": "SUCCESS",
                "records_read": len(all_records),
                "records_written": write_result.records_written,
                "records_failed": write_result.records_failed,
                "chunks_produced": total_chunks,
                "pii_detections": total_pii,
                "log": log_entries,
            }

        except Exception as e:
            log(f"Pipeline failed: {e}", "error")
            return {
                "run_id": run_id,
                "status": "FAILED",
                "error": str(e),
                "log": log_entries,
            }

    @staticmethod
    def _topological_sort(nodes: list[dict], edges: list[dict]) -> list[dict]:
        node_map = {n["id"]: n for n in nodes}
        in_degree = {n["id"]: 0 for n in nodes}
        adj = {n["id"]: [] for n in nodes}

        for edge in edges:
            src, tgt = edge.get("source"), edge.get("target")
            if src in adj and tgt in in_degree:
                adj[src].append(tgt)
                in_degree[tgt] += 1

        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        sorted_ids = []

        while queue:
            nid = queue.pop(0)
            sorted_ids.append(nid)
            for neighbor in adj.get(nid, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        return [node_map[nid] for nid in sorted_ids if nid in node_map]
