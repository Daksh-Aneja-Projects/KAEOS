from typing import Dict, Any

class DecayManager:
    """L7 - Freshness, Decay & Temporal Knowledge Management"""
    
    EVENT_INVALIDATION_MAP = {
        "org_chart_change": {"action": "CONFIDENCE_DECAY_50%"},
        "pricing_sheet_updated": {"action": "CONFIDENCE_RESET_TO_INFERRED"},
        "employee_departure": {"action": "FLAG_FOR_REVALIDATION"},
    }
    
    async def handle_trigger_event(self, event_type: str, context: Dict[str, Any]):
        """Event-Triggered Invalidation."""
        if event_type in self.EVENT_INVALIDATION_MAP:
            action = self.EVENT_INVALIDATION_MAP[event_type]["action"]
            # Apply decay action to affected rules
            return {"status": "DECAY_APPLIED", "action": action}
        return {"status": "IGNORED"}
        
    async def run_decay_scheduler(self):
        """Runs hourly to apply exponential decay to rule confidence."""
        from app.core.database import AsyncSessionLocal
        from app.models.domain import Rule, DecayEvent, ConfidenceTier
        from sqlalchemy import select
        from datetime import datetime, timezone
        import logging

        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Rule).where(Rule.confidence_scalar > 0.0))
            rules = result.scalars().all()
            
            now = datetime.now(timezone.utc)
            decay_count = 0
            for r in rules:
                if not r.validated_at:
                    continue
                days_since = (now - r.validated_at).days
                if days_since > 0 and r.half_life_days > 0:
                    old_conf = r.confidence_scalar
                    new_conf = old_conf * (0.5 ** (days_since / r.half_life_days))
                    
                    if old_conf - new_conf > 0.01:  # Only update if meaningful decay
                        if new_conf < 0.2 and old_conf >= 0.2:
                            r.confidence_tier = ConfidenceTier.SPECULATIVE
                        
                        event = DecayEvent(
                            tenant_id=r.tenant_id,
                            rule_id=r.id,
                            event_type="SCHEDULED_DECAY",
                            confidence_before=old_conf,
                            confidence_after=new_conf,
                            half_life_days=r.half_life_days,
                            days_since_validation=days_since,
                            action_taken="DECAY_APPLIED"
                        )
                        db.add(event)
                        r.confidence_scalar = new_conf
                        r.last_decay_at = now
                        decay_count += 1
                        
                        # Emit activity event for significant decays
                        if old_conf >= 0.6 and new_conf < 0.6:
                            from app.services.activity_feed import ActivityFeedService
                            from app.models.agent_factory import ActivityEventType, ActivitySeverity
                            feed = ActivityFeedService()
                            await feed.emit(
                                event_type=ActivityEventType.DECAY_ALERT,
                                title="Rule confidence decayed below 60%",
                                description=f"Rule '{r.statement[:80]}...' dropped from {old_conf:.0%} to {new_conf:.0%}. {days_since} days since validation.",
                                tenant_id=r.tenant_id,
                                severity=ActivitySeverity.ACTION_REQUIRED,
                                source_type="rule", source_id=r.id,
                                requires_action=True,
                                metadata={"confidence_before": old_conf, "confidence_after": new_conf, "days_since_validation": days_since},
                            )
            await db.commit()
            logging.getLogger(__name__).info(f"Temporal Decay applied to {decay_count} rules.")

class FeedbackEngine:
    """L10 - Closed-Loop Feedback & Active Learning Engine"""
    
    async def process_agent_outcome(self, execution_data: Dict[str, Any]) -> Dict[str, Any]:
        """Processes agent outcomes to adjust confidence and trigger learning."""
        status = execution_data.get("status")
        execution_data.get("rule_id")
        
        if status == "SUCCESS_CLEAN":
            # Increase confidence
            return {"confidence_delta": 0.05, "action": "UPDATE_KB"}
        elif status == "HUMAN_OVERRIDDEN":
            # Significant confidence drop, trigger elicitation
            return {"confidence_delta": -0.30, "action": "TRIGGER_ELICITATION"}
            
        return {"action": "NONE"}
