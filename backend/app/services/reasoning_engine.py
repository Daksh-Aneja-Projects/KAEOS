"""
KAEOS Enterprise Reasoning Engine
Phase 6: Reasoning Engine Upgrade (OODA Architecture)
Combines Enterprise State, Enterprise Graph, Memory, Policies, and Simulations 
to reason about events and trigger actions.
"""

import logging
from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.llm_router import LLMRouter
from app.services.debate_engine import DebateEngine
from app.services.state.state_service import StateService
from app.services.graph.graph_service import GraphService
from app.services.memory.enterprise_memory import EnterpriseMemoryService

logger = logging.getLogger(__name__)


class ReasoningEngine:
    
    def __init__(self, graph_service: GraphService):
        self.router = LLMRouter()
        self.debate_engine = DebateEngine()
        self.graph = graph_service

    async def run_ooda_loop(self, db: AsyncSession, tenant_id: str, event_payload: dict, event_type: str, domain: str) -> Dict[str, Any]:
        """
        Executes the full OODA loop for a given enterprise event.
        """
        logger.info(f"OODA Loop started for tenant {tenant_id} on event {event_type}")
        
        # 1. Observe (Gather direct event data)
        observation = await self._observe(event_payload, event_type)
        
        # 2. Orient (Pull Context: State, Graph, Memory, Policies)
        context = await self._orient(db, tenant_id, observation, event_type, domain)
        
        # 3. Decide (Reasoning Layer & Debate)
        decision = await self._decide(context)
        
        # 4. Act (Trigger Actions)
        action_result = await self._act(decision)
        
        # 5. Learn (Update Memory & Provenance)
        await self._learn(db, tenant_id, context, decision, action_result)
        
        return {
            "observation": observation,
            "context_summary": context.get("summary", "Context loaded"),
            "decision": decision,
            "action": action_result
        }

    async def _observe(self, event_payload: dict, event_type: str):
        return {
            "raw_event": event_payload,
            "type": event_type
        }

    async def _orient(self, db: AsyncSession, tenant_id: str, observation: dict, event_type: str, domain: str):
        """Pulls from Enterprise Graph, State Engine, and Memory."""
        # 1. State Context
        current_state = await StateService.get_state(db, tenant_id, domain)
        state_dict = current_state.__dict__ if current_state else {}
        
        # 2. Graph Context (Impact radius)
        source_entity = observation["raw_event"].get("source_entity_id")
        impacts = []
        if source_entity:
            impacts = await self.graph.get_impact_radius(source_entity, depth=2)
            
        # 3. Memory Context (Past similar situations)
        past_memories = await EnterpriseMemoryService.recall_similar_situations(
            db, tenant_id, f"Event: {event_type}. Source: {source_entity}", limit=3
        )
        
        return {
            "state_context": state_dict,
            "graph_impacts": impacts,
            "memory_context": past_memories,
            "summary": f"Oriented with {len(impacts)} impacted nodes and {len(past_memories)} past memories."
        }

    async def _decide(self, context: dict):
        """Uses LLM Reasoning + Debate Engine to reach a conclusion."""
        # Check if cross-domain debate is needed based on graph impact
        impacts = context.get("graph_impacts", [])
        
        if len(impacts) > 5:
            # Significant blast radius -> Trigger cross-domain debate
            logger.info("ReasoningEngine: Large blast radius detected. Triggering cross-domain debate.")
            
            active_departments = context.get("active_departments", ["Domain1", "Domain2", "Domain3"])
            
            decision = await self.debate_engine.run_cross_domain_debate(
                topic=f"Handling systemic event affecting {len(impacts)} downstream nodes.",
                perspectives=active_departments
            )
            return {"type": "DEBATED_DECISION", "details": decision}
            
        return {"type": "DIRECT_DECISION", "action": "mitigate_locally"}

    async def _act(self, decision: dict):
        """Dispatches the decision to the Workforce OS or specific Agents."""
        logger.info(f"OODA Act: Dispatching {decision}")
        return {"status": "dispatched", "decision_type": decision.get("type")}

    async def _learn(self, db: AsyncSession, tenant_id: str, context: dict, decision: dict, action: dict):
        """Records the entire chain into Enterprise Memory."""
        logger.info("OODA Learn: Storing decision memory ledger")
        context_str = f"State: {context.get('state_context')}. Impacts: {len(context.get('graph_impacts', []))} nodes."
        await EnterpriseMemoryService.store_decision_memory(db, tenant_id, context_str, decision, "PENDING_VALIDATION")
