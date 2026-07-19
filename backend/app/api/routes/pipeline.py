"""KAEOS — Pipeline API (L0 Data Fabric + Extract-OS ETL Engine)"""
from app.core.tenant import get_tenant_id
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional

from app.services.pipeline_service import PipelineService
from app.services.llm_router import LLMRouter

router = APIRouter(prefix="/pipeline", tags=["Pipeline — L0 ETL Engine"])


class PipelineRunRequest(BaseModel):
    connector_slug: str
    connector_config: dict
    connector_credentials: dict = {}
    dag_config: Optional[dict] = None
    destination_type: str = "local_file"
    destination_config: Optional[dict] = None


@router.post("/run")
async def run_pipeline(body: PipelineRunRequest, tenant_id: str = Depends(get_tenant_id)):
    """Execute a full Extract → Transform → Load pipeline (tenant-scoped)."""
    result = await PipelineService.run_pipeline(
        tenant_id=tenant_id,
        connector_config=body.connector_config,
        connector_credentials=body.connector_credentials,
        connector_slug=body.connector_slug,
        dag_config=body.dag_config,
        destination_type=body.destination_type,
        destination_config=body.destination_config,
    )
    return result


@router.get("/connectors/available")
async def list_available_connectors():
    """List connectors with real implementations."""
    return {
        "connectors": [
            {"slug": "csv", "name": "CSV / File Upload", "category": "custom", "auth_type": "none", "status": "AVAILABLE"},
            {"slug": "rest_api", "name": "REST API", "category": "custom", "auth_type": "api_key", "status": "AVAILABLE"},
        ]
    }


@router.get("/transforms/available")
async def list_available_transforms():
    """List available transform nodes for DAG construction."""
    return {
        "nodes": [
            {"type": "chunker", "name": "Text Chunker", "description": "Split text into AI-ready chunks (4 strategies)"},
            {"type": "pii_scrubber", "name": "PII Scrubber", "description": "Detect & handle PII via Presidio (mask/redact/flag/halt)"},
            {"type": "field_mapper", "name": "Field Mapper", "description": "Map source fields to target schema"},
            {"type": "deduplicator", "name": "Deduplicator", "description": "Remove duplicate records (exact or hash)"},
            {"type": "normalizer", "name": "Normalizer", "description": "Standardize data formats (email, phone, dates)"},
            {"type": "filter", "name": "Filter", "description": "Drop or keep records matching conditions"},
            {"type": "metadata_injector", "name": "Metadata Injector", "description": "Attach custom metadata to records"},
        ]
    }


@router.get("/llm/providers")
async def list_llm_providers():
    """List supported LLM providers (BYOK)."""
    return {
        "providers": LLMRouter.list_supported_providers(),
        "embedding_models": LLMRouter.list_embedding_models(),
    }
