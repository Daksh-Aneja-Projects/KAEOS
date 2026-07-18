"""AEOS P1 — External Intelligence Layer
Turns AEOS from reactive to anticipatory. Ingests external signals
(regulatory, vendor, market) and correlates them with the Company Brain.
"""
import json
import logging

logger = logging.getLogger(__name__)


class ExternalIntelligenceEngine:
    """P1 — Anticipatory Intelligence from external sources.
    
    Signal Types:
    - REGULATORY: GDPR, FLSA, EU AI Act, local labor law changes
    - VENDOR: HRIS/ERP vendor release notes, API deprecations
    - MARKET: Industry benchmarks, peer data
    - THREAT: Cybersecurity advisories for connected SaaS
    - ECONOMIC: CPI, labor market indices
    """

    SIGNAL_TYPES = ["REGULATORY", "VENDOR", "MARKET", "THREAT", "ECONOMIC"]

    async def ingest_signal(
        self, signal_type: str, source: str, title: str,
        content: str, severity: str = "MEDIUM",
        tenant_id: str = "default", metadata: dict = None
    ) -> dict:
        """Ingest an external signal into the knowledge graph."""
        from app.core.database import AsyncSessionLocal
        from app.models.agent_factory import ActivityFeedEvent, ActivityEventType, ActivitySeverity
        import uuid

        signal_id = str(uuid.uuid4())

        async with AsyncSessionLocal() as db:
            # Log to activity feed
            event = ActivityFeedEvent(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                event_type=ActivityEventType.EXTERNAL_SIGNAL,
                title=f"[{signal_type}] {title}",
                description=content[:500],
                severity=ActivitySeverity.WARNING if severity == "HIGH" else ActivitySeverity.INFO,
                source_type="external_intelligence",
                source_id=signal_id,
                requires_action=severity == "HIGH",
                event_metadata={"signal_type": signal_type, "source": source, **(metadata or {})},
            )
            db.add(event)
            await db.commit()

        logger.info(f"P1 External signal ingested: [{signal_type}] {title}")
        return {"signal_id": signal_id, "status": "INGESTED", "signal_type": signal_type}

    async def correlate_with_brain(
        self, signal_content: str, tenant_id: str = "default"
    ) -> dict:
        """Cross-signal correlation — maps external signals to internal KB entities."""
        from app.services.llm_router import LLMRouter

        llm = LLMRouter()
        prompt = (
            f"You are the AEOS Cross-Signal Correlation Engine.\n"
            f"An external signal was received:\n{signal_content[:1000]}\n\n"
            f"Identify which internal enterprise domains, rules, or workflows this signal impacts.\n"
            f"Output JSON: {{\"impacted_domains\": [\"...\"], \"risk_level\": \"HIGH|MEDIUM|LOW\", "
            f"\"recommended_actions\": [\"...\"], \"urgency_hours\": int}}"
        )

        try:
            res = await llm.complete(prompt=prompt, model_tier="reasoning")
            content = res if isinstance(res, str) else res.get("content", "{}")
            return {"correlation": json.loads(content), "status": "CORRELATED"}
        except Exception as e:
            logger.error(f"P1 correlation failed: {e}")
            return {"correlation": None, "status": "FAILED", "error": str(e)}

    async def generate_proactive_alert(
        self, signal_type: str, content: str, tenant_id: str = "default"
    ) -> dict:
        """P1 — Generate proactive alerts before issues manifest internally."""
        correlation = await self.correlate_with_brain(content, tenant_id)
        risk = (correlation.get("correlation") or {}).get("risk_level", "LOW")

        if risk in ("HIGH", "MEDIUM"):
            from app.services.activity_feed import ActivityFeedService
            from app.models.agent_factory import ActivityEventType, ActivitySeverity

            feed = ActivityFeedService()
            await feed.emit(
                event_type=ActivityEventType.PROACTIVE_ALERT,
                title=f"Proactive Alert: {signal_type} signal requires attention",
                description=json.dumps(correlation.get("correlation", {}).get("recommended_actions", [])),
                tenant_id=tenant_id,
                severity=ActivitySeverity.ACTION_REQUIRED if risk == "HIGH" else ActivitySeverity.WARNING,
                source_type="external_intelligence",
                requires_action=risk == "HIGH",
                metadata=correlation.get("correlation"),
            )

        return {"alert_generated": risk in ("HIGH", "MEDIUM"), "risk_level": risk, "correlation": correlation}
