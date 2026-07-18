"""KAEOS — Skills Compiler (Upgraded for AEOS Agent Factory)
Compiles AgentBlueprints into SKILL.md agent contracts and deploys agents.
"""
import logging
import yaml
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.agent_factory import (
    AgentBlueprint, BlueprintStatus, DeployedAgent, AgentType, AgentStatus,
    ActivityFeedEvent, ActivityEventType, ActivitySeverity,
)
from app.models.domain import Skill, ProvenanceLedger
from app.services.provenance import ProvenanceEngine

logger = logging.getLogger(__name__)


class SkillsCompiler:
    """L8 — Compiles blueprints/rules into executable SKILL.md agent contracts."""

    def __init__(self):
        self.provenance = ProvenanceEngine()

    async def compile_from_blueprint(self, blueprint_id: str, tenant_id: str) -> dict:
        """Compile an approved AgentBlueprint into a Skill and persist it.
        
        Converts DAG nodes → steps, decision gates → exceptions,
        data sources → mcp_tool_bindings, checkpoints → guardrails.
        """
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(AgentBlueprint).where(
                    AgentBlueprint.id == blueprint_id,
                    AgentBlueprint.tenant_id == tenant_id,
                )
            )
            blueprint = result.scalar_one_or_none()
            if not blueprint:
                raise ValueError(f"Blueprint {blueprint_id} not found")
            if blueprint.status not in (BlueprintStatus.APPROVED, BlueprintStatus.BLUEPRINT_READY):
                raise ValueError(f"Blueprint must be APPROVED to compile (current: {blueprint.status})")

            dag = blueprint.blueprint_graph or {"nodes": [], "edges": []}
            nodes = dag.get("nodes", [])
            edges = dag.get("edges", [])

            # Convert DAG → SKILL.md structure
            from app.schemas.skills import validate_steps
            steps = validate_steps(self._nodes_to_steps(nodes, edges))
            exceptions = self._extract_exceptions(nodes, edges)
            mcp_tools = self._extract_mcp_tools(nodes, blueprint.mcp_tools_required or [])
            guardrails = blueprint.guardrails or {"pre_execution": [], "post_execution": []}
            triggers = self._derive_triggers(blueprint)

            # Calculate chain confidence (weakest link)
            chain_confidence = blueprint.confidence_floor or 0.5
            tier = self._confidence_to_tier(chain_confidence)

            # Generate skill_id
            skill_id = blueprint.name.lower().replace(" ", "_").replace(":", "")[:50]
            skill_id = f"{skill_id}_{blueprint.id[:6]}"

            skill = Skill(
                skill_id=skill_id,
                tenant_id=tenant_id,
                department=blueprint.department or "general",
                domain=blueprint.domain or "general",
                version="1.0",
                status="ACTIVE",
                confidence=chain_confidence,
                confidence_tier=tier,
                confidence_vector={"source_breadth": 0.5, "source_authority": 0.5, "temporal_freshness": 1.0, "outcome_validation": 0.5, "explicit_validation": 0.0},
                triggers=triggers,
                steps=steps,
                exceptions=exceptions,
                guardrails=guardrails,
                mcp_tool_bindings=mcp_tools,
                compliance_tags=blueprint.compliance_tags or [],
                provenance={"source": "blueprint", "blueprint_id": blueprint.id},
            )

            session.add(skill)

            # Update blueprint status
            blueprint.status = BlueprintStatus.COMPILED
            
            # Create provenance entry
            import hashlib
            chain_data = f"SKILL_COMPILED:{skill_id}:{blueprint.id}:{datetime.now(timezone.utc).isoformat()}"
            chain_hash = hashlib.sha256(chain_data.encode()).hexdigest()

            provenance = ProvenanceLedger(
                tenant_id=tenant_id,
                event_type="SKILL_COMPILED_FROM_BLUEPRINT",
                actor_hash="system:compiler",
                actor_role="system",
                confidence_at=chain_confidence,
                reasoning=f"Compiled from blueprint '{blueprint.name}' with {len(steps)} steps",
                chain_hash=chain_hash,
            )
            session.add(provenance)

            await session.commit()
            await session.refresh(skill)

            logger.info(f"[Compiler] Compiled blueprint '{blueprint.name}' → skill '{skill_id}' ({len(steps)} steps)")

            return {
                "skill_id": skill.id,
                "skill_name": skill_id,
                "steps_count": len(steps),
                "confidence": chain_confidence,
                "compliance_tags": blueprint.compliance_tags,
                "mcp_tools": mcp_tools,
                "blueprint_id": blueprint.id,
            }

    async def deploy_agent(self, blueprint_id: str, tenant_id: str, trigger_config: Optional[dict] = None) -> dict:
        """Deploy an agent from a compiled blueprint."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(AgentBlueprint).where(AgentBlueprint.id == blueprint_id, AgentBlueprint.tenant_id == tenant_id)
            )
            blueprint = result.scalar_one_or_none()
            if not blueprint:
                raise ValueError(f"Blueprint {blueprint_id} not found")

            # Find compiled skill
            skill_result = await session.execute(
                select(Skill).where(Skill.tenant_id == tenant_id, Skill.provenance["blueprint_id"].as_string() == blueprint_id)
            )
            skill = skill_result.scalar_one_or_none()

            agent = DeployedAgent(
                tenant_id=tenant_id,
                blueprint_id=blueprint_id,
                agent_name=blueprint.name,
                agent_type=AgentType.PERSISTENT,
                status=AgentStatus.RUNNING,
                compiled_skill_id=skill.id if skill else None,
                trigger_config=trigger_config or {"type": "manual", "config": {}},
            )
            session.add(agent)

            blueprint.status = BlueprintStatus.DEPLOYED
            blueprint.deployed_at = datetime.now(timezone.utc)

            # Emit activity event
            event = ActivityFeedEvent(
                tenant_id=tenant_id,
                event_type=ActivityEventType.AGENT_STARTED,
                severity=ActivitySeverity.INFO,
                title=f"Agent '{blueprint.name}' deployed",
                description=f"Agent compiled from blueprint and deployed with {blueprint.confidence_floor:.0%} confidence floor",
                source_type="agent", source_id=agent.id,
            )
            session.add(event)

            await session.commit()
            await session.refresh(agent)

            logger.info(f"[Compiler] Deployed agent '{blueprint.name}' (id={agent.id})")

            return {
                "agent_id": agent.id, "agent_name": agent.agent_name,
                "status": agent.status.value, "blueprint_id": blueprint_id,
                "skill_id": skill.id if skill else None,
            }

    async def stop_agent(self, agent_id: str, tenant_id: str) -> dict:
        """Stop a deployed agent."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(DeployedAgent).where(DeployedAgent.id == agent_id, DeployedAgent.tenant_id == tenant_id)
            )
            agent = result.scalar_one_or_none()
            if not agent:
                raise ValueError(f"Agent {agent_id} not found")

            agent.status = AgentStatus.STOPPED
            agent.stopped_at = datetime.now(timezone.utc)

            event = ActivityFeedEvent(
                tenant_id=tenant_id,
                event_type=ActivityEventType.AGENT_STOPPED,
                severity=ActivitySeverity.INFO,
                title=f"Agent '{agent.agent_name}' stopped",
                source_type="agent", source_id=agent.id,
            )
            session.add(event)
            await session.commit()

            return {"agent_id": agent.id, "status": "STOPPED"}

    async def pause_agent(self, agent_id: str, tenant_id: str) -> dict:
        """Pause a deployed agent."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(DeployedAgent).where(DeployedAgent.id == agent_id, DeployedAgent.tenant_id == tenant_id)
            )
            agent = result.scalar_one_or_none()
            if not agent:
                raise ValueError(f"Agent {agent_id} not found")

            agent.status = AgentStatus.PAUSED
            agent.paused_at = datetime.now(timezone.utc)
            await session.commit()

            return {"agent_id": agent.id, "status": "PAUSED"}

    # ─── Legacy: Compile from rules (preserved) ───

    def compile_skill(self, workflow_rules: List[Dict[str, Any]], context: Dict[str, Any]) -> Dict[str, Any]:
        """Compiles graph relationships and rules into an executable SKILL.md agent contract."""
        if not workflow_rules:
            raise ValueError("Cannot compile skill without rules")
        ordered_rules = sorted(workflow_rules, key=lambda x: x.get('priority', 0))
        chain_confidence = min([r.get('confidence_scalar', 0.0) for r in ordered_rules])
        return {
            "skill_id": context.get("workflow_name", "compiled_skill"),
            "version": "1.0.0",
            "domain": context.get("domain", "general"),
            "confidence": chain_confidence,
            "mcp_tool_bindings": context.get("required_tools", []),
            "compliance_tags": list(set([tag for r in ordered_rules for tag in r.get('compliance_tags', [])])),
            "steps": [self._format_step(i, r) for i, r in enumerate(ordered_rules)]
        }

    def export_to_yaml(self, skill_contract: Dict[str, Any]) -> str:
        return yaml.dump(skill_contract, sort_keys=False)

    # ─── Private Helpers ───

    def _nodes_to_steps(self, nodes: list, edges: list) -> list:
        steps = []
        # Build adjacency for ordering
        adj = {}
        for edge in edges:
            adj.setdefault(edge["source"], []).append(edge["target"])

        # Order nodes by topological position (simple: use node order)
        action_nodes = [n for n in nodes if n.get("type") not in ("HITL_CHECKPOINT", "FAIRNESS_GATE")]
        for i, node in enumerate(action_nodes):
            step = {
                "id": f"step_{i + 1}",
                "action": node.get("label", f"Step {i+1}"),
                "node_type": node.get("type", "ACTION"),
                "config": node.get("config", {}),
            }
            if node.get("type") == "DECISION_GATE":
                step["condition"] = node.get("config", {}).get("condition", "")
                # Find true/false branches
                node_id = node.get("id", "")
                for edge in edges:
                    if edge.get("source") == node_id:
                        if edge.get("type") == "CONDITIONAL_TRUE":
                            step["if_true"] = edge.get("target")
                        elif edge.get("type") == "CONDITIONAL_FALSE":
                            step["if_false"] = edge.get("target")
            steps.append(step)
        return steps

    def _extract_exceptions(self, nodes: list, edges: list) -> list:
        exceptions = []
        for node in nodes:
            if node.get("type") == "DECISION_GATE":
                exc = {
                    "id": node.get("id", ""),
                    "condition": node.get("config", {}).get("condition", ""),
                    "override": node.get("config", {}).get("override_action", ""),
                }
                exceptions.append(exc)
        return exceptions

    def _extract_mcp_tools(self, nodes: list, blueprint_tools: list) -> list:
        tools = set(blueprint_tools)
        for node in nodes:
            tool = node.get("config", {}).get("tool")
            if tool:
                tools.add(tool)
        return list(tools)

    def _derive_triggers(self, blueprint: AgentBlueprint) -> list:
        triggers = []
        decomp = blueprint.intent_decomposition or {}
        if blueprint.description:
            triggers.append(blueprint.description[:200])
        action = decomp.get("action_type")
        if action:
            triggers.append(f"intent_classifier: {action.upper()}")
        return triggers

    def _confidence_to_tier(self, confidence: float) -> str:
        if confidence >= 0.85: return "VERIFIED_AGAINST_OUTCOMES"
        if confidence >= 0.75: return "VALIDATED_DEPARTMENT_HEAD"
        if confidence >= 0.60: return "VALIDATED_PEER"
        if confidence >= 0.30: return "INFERRED"
        return "SPECULATIVE"

    def _format_step(self, index: int, rule: Dict[str, Any]) -> Dict[str, Any]:
        return {"id": f"step_{index + 1}", "action": "evaluate_rule", "condition": rule.get("trigger_json"), "on_true": rule.get("action_json")}
