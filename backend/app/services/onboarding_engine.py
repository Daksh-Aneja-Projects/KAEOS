"""
KAEOS S1 N4 — Tenant Onboarding Engine
State machine managing cold-start sequence, KG bootstrap, schema mapping.
"""
import logging
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.infrastructure import (
    TenantOnboarding, OnboardingStage, SchemaMapping
)

logger = logging.getLogger(__name__)


class OnboardingEngineService:
    """
    N4 — Tenant Onboarding Engine
    Manages the full cold-start onboarding sequence from connector configuration
    to fully-operational AEOS agent activation.
    """

    STAGE_ORDER = [
        OnboardingStage.INITIATED,
        OnboardingStage.CONNECTORS_CONFIGURED,
        OnboardingStage.SCHEMA_MAPPED,
        OnboardingStage.PII_CLASSIFIED,
        OnboardingStage.FULL_CRAWL_RUNNING,
        OnboardingStage.KG_POPULATED,
        OnboardingStage.CONFIDENCE_ASSIGNED,
        OnboardingStage.AGENTS_ACTIVATED,
        OnboardingStage.ELICITATION_STARTED,
        OnboardingStage.FULLY_ONBOARDED
    ]

    @staticmethod
    async def initiate_onboarding(
        db: AsyncSession,
        tenant_id: str,
        tenant_name: str,
        industry_vertical: str = None
    ) -> dict:
        """Start the onboarding process for a new tenant."""
        # Check if already exists
        result = await db.execute(
            select(TenantOnboarding).where(TenantOnboarding.tenant_id == tenant_id)
        )
        existing = result.scalar_one_or_none()
        if existing:
            return OnboardingEngineService._to_dict(existing)

        onboarding = TenantOnboarding(
            tenant_id=tenant_id,
            tenant_name=tenant_name,
            industry_vertical=industry_vertical,
            stages_completed=[{
                "stage": OnboardingStage.INITIATED.value,
                "completed_at": datetime.now(timezone.utc).isoformat()
            }]
        )
        db.add(onboarding)
        await db.commit()
        await db.refresh(onboarding)
        # Register the new tenant in the platform registry (source of truth).
        from app.services.tenant_registry import ensure_tenant
        await ensure_tenant(db, tenant_id, name=tenant_name)
        logger.info(f"[N4] Onboarding initiated for tenant {tenant_id} ({tenant_name})")
        return OnboardingEngineService._to_dict(onboarding)

    @staticmethod
    async def advance_stage(
        db: AsyncSession,
        tenant_id: str,
        metrics: dict = None
    ) -> dict:
        """Advance the onboarding to the next stage."""
        result = await db.execute(
            select(TenantOnboarding).where(TenantOnboarding.tenant_id == tenant_id)
        )
        onboarding = result.scalar_one_or_none()
        if not onboarding:
            return {"error": "onboarding_not_found"}

        stages = OnboardingEngineService.STAGE_ORDER
        current_idx = stages.index(onboarding.current_stage)

        if current_idx >= len(stages) - 1:
            return {"error": "already_fully_onboarded", **OnboardingEngineService._to_dict(onboarding)}

        next_stage = stages[current_idx + 1]
        onboarding.current_stage = next_stage
        onboarding.stage_progress_pct = round(((current_idx + 1) / (len(stages) - 1)) * 100, 1)

        completed = onboarding.stages_completed or []
        completed.append({
            "stage": next_stage.value,
            "completed_at": datetime.now(timezone.utc).isoformat()
        })
        onboarding.stages_completed = completed

        # Update metrics if provided
        if metrics:
            for key in ["connectors_configured", "entities_discovered", "mappings_confirmed",
                         "pii_fields_detected", "rules_extracted", "kg_nodes_created"]:
                if key in metrics:
                    setattr(onboarding, key, metrics[key])

        if next_stage == OnboardingStage.FULLY_ONBOARDED:
            onboarding.completed_at = datetime.now(timezone.utc)

        await db.commit()
        logger.info(f"[N4] Tenant {tenant_id} advanced to stage {next_stage.value}")
        return OnboardingEngineService._to_dict(onboarding)

    @staticmethod
    async def get_onboarding_status(
        db: AsyncSession,
        tenant_id: str
    ) -> Optional[dict]:
        """Get current onboarding status for a tenant."""
        result = await db.execute(
            select(TenantOnboarding).where(TenantOnboarding.tenant_id == tenant_id)
        )
        onboarding = result.scalar_one_or_none()
        if not onboarding:
            return None
        return OnboardingEngineService._to_dict(onboarding)

    @staticmethod
    async def list_all_onboardings(db: AsyncSession) -> list:
        """Every tenant's onboarding record — PLATFORM-ADMIN ONLY.

        Deliberately unfiltered. Callers must have proven admin authorization
        (see app.core.admin) before reaching this; a tenant-scoped caller wants
        list_onboardings_for_tenant() instead.
        """
        result = await db.execute(
            select(TenantOnboarding).order_by(TenantOnboarding.initiated_at.desc())
        )
        return [OnboardingEngineService._to_dict(o) for o in result.scalars().all()]

    @staticmethod
    async def list_onboardings_for_tenant(db: AsyncSession, tenant_id: str) -> list:
        """One tenant's own onboarding record(s) — the ordinary, safe path."""
        result = await db.execute(
            select(TenantOnboarding)
            .where(TenantOnboarding.tenant_id == tenant_id)
            .order_by(TenantOnboarding.initiated_at.desc())
        )
        return [OnboardingEngineService._to_dict(o) for o in result.scalars().all()]

    # ── Schema Mapping (AI-First) ─────────────────────────────────────────

    @staticmethod
    async def propose_mappings(
        db: AsyncSession,
        tenant_id: str,
        connector_id: str,
        source_fields: list
    ) -> list:
        """
        AI-propose schema mappings for a connector's source fields.
        Uses field name similarity, data type matching, and cross-tenant patterns.
        """

        def _field_overlap_score(a: str, b: str) -> float:
            """Deterministic confidence based on character n-gram overlap between field names."""
            a_chars = set(a[i:i+2] for i in range(len(a) - 1)) or {a}
            b_chars = set(b[i:i+2] for i in range(len(b) - 1)) or {b}
            if not a_chars or not b_chars:
                return 0.60
            overlap = len(a_chars & b_chars) / len(a_chars | b_chars)
            # Scale: 0.60 base + up to 0.25 from overlap
            return round(0.60 + overlap * 0.25, 3)


        # Target entities in Knowledge Graph
        target_entities = {
            "Employee": ["employee_id", "display_name", "email", "role", "department", "hire_date", "status"],
            "OrgUnit": ["unit_id", "name", "parent_id", "manager_id", "headcount"],
            "Role": ["role_id", "title", "level", "department", "competencies"],
            "Policy": ["policy_id", "title", "content", "effective_date", "category"],
            "Contract": ["contract_id", "type", "start_date", "end_date", "value"],
            "Asset": ["asset_id", "name", "type", "status", "assigned_to"]
        }

        # PII categories
        pii_fields = {
            "ssn": "SSN", "social_security": "SSN", "salary": "COMPENSATION",
            "compensation": "COMPENSATION", "birth": "DOB", "dob": "DOB",
            "phone": "PHONE", "email": "EMAIL", "address": "ADDRESS",
            "health": "HEALTH_DATA", "medical": "HEALTH_DATA", "bank": "FINANCIAL",
            "account_number": "FINANCIAL", "name": "NAME", "first_name": "NAME",
            "last_name": "NAME"
        }

        mappings = []
        for field_info in source_fields:
            source_field = field_info.get("field_name", "")
            source_object = field_info.get("object_type", "Unknown")
            source_type = field_info.get("data_type", "string")

            # Simple heuristic-based mapping (would be ML-powered in prod)
            best_match = None
            best_confidence = 0.0
            field_lower = source_field.lower()

            for entity, fields in target_entities.items():
                for target_field in fields:
                    # Exact match
                    if field_lower == target_field:
                        best_match = (entity, target_field)
                        best_confidence = 0.95
                        break
                    # Partial match — score via deterministic n-gram overlap
                    elif target_field in field_lower or field_lower in target_field:
                        score = _field_overlap_score(field_lower, target_field)
                        if score > best_confidence:
                            best_match = (entity, target_field)
                            best_confidence = score
                if best_match and best_confidence > 0.9:
                    break

            if not best_match:
                best_match = ("Employee", source_field)
                # Fixed baseline for unrecognised fields — reproducible, not random
                best_confidence = 0.35

            # PII check
            is_pii = False
            pii_category = None
            for pii_key, pii_cat in pii_fields.items():
                if pii_key in field_lower:
                    is_pii = True
                    pii_category = pii_cat
                    break

            # Confidence tier
            if best_confidence >= 0.85:
                conf_tier = "GREEN"
            elif best_confidence >= 0.60:
                conf_tier = "AMBER"
            else:
                conf_tier = "RED"

            mapping = SchemaMapping(
                tenant_id=tenant_id,
                connector_id=connector_id,
                source_field=source_field,
                source_object=source_object,
                source_type=source_type,
                target_entity=best_match[0],
                target_field=best_match[1],
                ai_confidence=round(best_confidence, 3),
                confidence_tier=conf_tier,
                is_pii=is_pii,
                pii_category=pii_category,
                sensitivity_tier="CONFIDENTIAL" if is_pii else "INTERNAL"
            )
            db.add(mapping)
            mappings.append(mapping)

        await db.commit()

        return [{
            "id": m.id,
            "source_field": m.source_field,
            "source_object": m.source_object,
            "source_type": m.source_type,
            "target_entity": m.target_entity,
            "target_field": m.target_field,
            "ai_confidence": m.ai_confidence,
            "confidence_tier": m.confidence_tier,
            "is_pii": m.is_pii,
            "pii_category": m.pii_category,
            "sensitivity_tier": m.sensitivity_tier,
            "admin_confirmed": m.admin_confirmed
        } for m in mappings]

    @staticmethod
    async def confirm_mapping(
        db: AsyncSession,
        mapping_id: str,
        confirmed_by: str,
        target_entity: str = None,
        target_field: str = None
    ) -> dict:
        """Admin confirms or corrects a schema mapping."""
        result = await db.execute(
            select(SchemaMapping).where(SchemaMapping.id == mapping_id)
        )
        mapping = result.scalar_one_or_none()
        if not mapping:
            return {"error": "mapping_not_found"}

        mapping.admin_confirmed = True
        mapping.confirmed_by = confirmed_by
        mapping.confirmed_at = datetime.now(timezone.utc)
        if target_entity:
            mapping.target_entity = target_entity
            mapping.mapping_source = "MANUAL"
        if target_field:
            mapping.target_field = target_field
            mapping.mapping_source = "MANUAL"

        await db.commit()
        return {
            "id": mapping.id,
            "source_field": mapping.source_field,
            "target_entity": mapping.target_entity,
            "target_field": mapping.target_field,
            "admin_confirmed": True,
            "confirmed_by": confirmed_by
        }

    @staticmethod
    async def get_mappings(
        db: AsyncSession,
        tenant_id: str,
        connector_id: str = None,
        confirmed_only: bool = False
    ) -> list:
        """Get schema mappings for a tenant."""
        query = select(SchemaMapping).where(SchemaMapping.tenant_id == tenant_id)
        if connector_id:
            query = query.where(SchemaMapping.connector_id == connector_id)
        if confirmed_only:
            query = query.where(SchemaMapping.admin_confirmed == True)
        query = query.order_by(SchemaMapping.ai_confidence.desc())

        result = await db.execute(query)
        mappings = result.scalars().all()
        return [{
            "id": m.id,
            "source_field": m.source_field,
            "source_object": m.source_object,
            "source_type": m.source_type,
            "target_entity": m.target_entity,
            "target_field": m.target_field,
            "ai_confidence": m.ai_confidence,
            "confidence_tier": m.confidence_tier,
            "mapping_source": m.mapping_source,
            "is_pii": m.is_pii,
            "pii_category": m.pii_category,
            "sensitivity_tier": m.sensitivity_tier,
            "admin_confirmed": m.admin_confirmed,
            "confirmed_by": m.confirmed_by,
            "confirmed_at": str(m.confirmed_at) if m.confirmed_at else None
        } for m in mappings]

    @staticmethod
    def _to_dict(o: TenantOnboarding) -> dict:
        stages = OnboardingEngineService.STAGE_ORDER
        current_idx = stages.index(o.current_stage) if o.current_stage in stages else 0
        return {
            "id": o.id,
            "tenant_id": o.tenant_id,
            "tenant_name": o.tenant_name,
            "industry_vertical": o.industry_vertical,
            "current_stage": o.current_stage.value,
            "stage_progress_pct": o.stage_progress_pct,
            "stages_completed": o.stages_completed,
            "current_stage_index": current_idx,
            "total_stages": len(stages),
            "connectors_configured": o.connectors_configured,
            "entities_discovered": o.entities_discovered,
            "mappings_confirmed": o.mappings_confirmed,
            "pii_fields_detected": o.pii_fields_detected,
            "rules_extracted": o.rules_extracted,
            "kg_nodes_created": o.kg_nodes_created,
            "model_pack_requested": o.model_pack_requested,
            "model_pack_delivered": o.model_pack_delivered,
            "initiated_at": str(o.initiated_at) if o.initiated_at else None,
            "completed_at": str(o.completed_at) if o.completed_at else None,
            "estimated_completion_hours": o.estimated_completion_hours
        }
