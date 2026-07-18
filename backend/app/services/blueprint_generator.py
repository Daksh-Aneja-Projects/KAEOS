"""KAEOS — Agent Blueprint Generator (AEOS Agent Factory Core)
Takes natural language prompt → queries Company Brain → generates visual DAG blueprint.
"""
import logging
import json
from datetime import timezone
from typing import Optional

from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.agent_factory import AgentBlueprint, BlueprintStatus
from app.models.domain import Rule, Skill, Connector
from app.models.settings import MCPToolConfig
from app.services.llm_router import LLMRouter
from app.services.temporal_calendar import TemporalReasoningEngine

logger = logging.getLogger(__name__)


class BlueprintGenerator:
    """The brain of the Agent Factory.
    
    Flow:
    1. Decompose NL prompt into intent, domain, department, capabilities
    2. Query Company Brain for matching rules, skills, connectors, tools
    3. Use LLM to compose DAG from decomposed intent + brain context
    4. Auto-derive guardrails from compliance tags
    5. Calculate confidence floor from weakest-link rules
    6. Persist as AgentBlueprint
    """

    def __init__(self):
        self.llm = LLMRouter()
        self.temporal = TemporalReasoningEngine()

    async def generate_blueprint(self, prompt: str, tenant_id: str, created_by: Optional[str] = None) -> dict:
        """Generate a full agent blueprint from natural language."""

        # Step 1: Decompose intent
        decomposition = await self._decompose_intent(prompt)
        domain = decomposition.get("domain", "general")
        department = decomposition.get("department", "general")

        # Step 2: Query Company Brain
        brain_context = await self._query_brain(domain, department, tenant_id)

        # Step 3: Get temporal context
        temporal_ctx = await self.temporal.get_seasonality_context(department, tenant_id)

        # Step 4: Generate DAG
        dag = await self._generate_dag(prompt, decomposition, brain_context, temporal_ctx)

        # Step 5: Derive compliance and guardrails
        compliance_tags = self._derive_compliance_tags(brain_context, decomposition)
        guardrails = self._derive_guardrails(compliance_tags, decomposition)

        # Step 6: Calculate confidence floor
        confidence_floor = self._calculate_confidence_floor(brain_context)

        # Step 7: Persist blueprint
        blueprint = AgentBlueprint(
            tenant_id=tenant_id,
            name=decomposition.get("agent_name", f"Agent: {prompt[:50]}"),
            description=prompt,
            domain=domain,
            department=department,
            status=BlueprintStatus.BLUEPRINT_READY,
            blueprint_graph=dag,
            source_skill_ids=brain_context.get("skill_ids", []),
            source_rule_ids=brain_context.get("rule_ids", []),
            mcp_tools_required=brain_context.get("available_tools", []),
            guardrails=guardrails,
            compliance_tags=compliance_tags,
            confidence_floor=confidence_floor,
            intent_decomposition=decomposition,
            created_by=created_by,
        )

        async with AsyncSessionLocal() as session:
            session.add(blueprint)
            await session.commit()
            await session.refresh(blueprint)

        logger.info(f"[BlueprintGen] Created blueprint '{blueprint.name}' with {len(dag.get('nodes', []))} nodes")

        return self._serialize(blueprint)

    async def refine_blueprint(self, blueprint_id: str, user_edits: dict, tenant_id: str) -> dict:
        """Accept user modifications to the DAG and re-validate."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(AgentBlueprint).where(AgentBlueprint.id == blueprint_id, AgentBlueprint.tenant_id == tenant_id)
            )
            blueprint = result.scalar_one_or_none()
            if not blueprint:
                raise ValueError(f"Blueprint {blueprint_id} not found")

            # Apply edits
            if "blueprint_graph" in user_edits:
                blueprint.blueprint_graph = user_edits["blueprint_graph"]
            if "name" in user_edits:
                blueprint.name = user_edits["name"]
            if "mcp_tools_required" in user_edits:
                blueprint.mcp_tools_required = user_edits["mcp_tools_required"]

            # Re-derive guardrails if graph changed
            if "blueprint_graph" in user_edits:
                blueprint.guardrails = self._derive_guardrails(blueprint.compliance_tags, blueprint.intent_decomposition or {})

            await session.commit()
            await session.refresh(blueprint)
            return self._serialize(blueprint)

    async def approve_blueprint(self, blueprint_id: str, tenant_id: str, approved_by: Optional[str] = None) -> dict:
        """Mark blueprint as approved for compilation."""
        from datetime import datetime
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(AgentBlueprint).where(AgentBlueprint.id == blueprint_id, AgentBlueprint.tenant_id == tenant_id)
            )
            blueprint = result.scalar_one_or_none()
            if not blueprint:
                raise ValueError(f"Blueprint {blueprint_id} not found")

            blueprint.status = BlueprintStatus.APPROVED
            blueprint.approved_by = approved_by
            blueprint.approved_at = datetime.now(timezone.utc)
            await session.commit()
            await session.refresh(blueprint)
            return self._serialize(blueprint)

    # ─── Private Methods ───

    async def _decompose_intent(self, prompt: str) -> dict:
        """Use LLM to decompose natural language into structured intent."""
        try:
            sys_prompt = f"""Decompose this user request into structured intent for an enterprise AI agent.

USER REQUEST: "{prompt}"

Respond in JSON:
{{"agent_name":"Short name","domain":"e.g. support_cx, finance, hr, legal, engineering, sales","department":"e.g. customer_support, finance, human_resources","action_type":"e.g. monitor, analyze, process, notify, approve, build, test, deploy","data_sources_needed":["e.g. crm, hris, jira, slack"],"capabilities_needed":["e.g. read_data, write_data, send_notification, create_ticket"],"involves_hcm_data":false,"risk_level":"low|medium|high"}}"""

            resp = await self.llm.complete(prompt=sys_prompt, model_tier="reasoning", temperature=0.3)
            return self._parse_json(resp)
        except Exception as e:
            logger.error(f"[BlueprintGen] Intent decomposition failed: {e}")
            return {"agent_name": prompt[:50], "domain": "general", "department": "general", "action_type": "process", "data_sources_needed": [], "capabilities_needed": [], "involves_hcm_data": False, "risk_level": "medium"}

    async def _query_brain(self, domain: str, department: str, tenant_id: str) -> dict:
        """Query the Company Brain for matching knowledge."""
        async with AsyncSessionLocal() as session:
            # Matching rules
            rules_q = select(Rule).where(Rule.tenant_id == tenant_id).limit(20)
            if domain != "general":
                rules_q = rules_q.where(Rule.domain == domain)
            rules_result = await session.execute(rules_q)
            rules = rules_result.scalars().all()

            # Matching skills
            skills_q = select(Skill).where(Skill.tenant_id == tenant_id, Skill.status == "ACTIVE").limit(10)
            if department != "general":
                skills_q = skills_q.where(Skill.department == department)
            skills_result = await session.execute(skills_q)
            skills = skills_result.scalars().all()

            # Available connectors
            conn_result = await session.execute(
                select(Connector).where(Connector.tenant_id == tenant_id, Connector.status == "CONNECTED")
            )
            connectors = conn_result.scalars().all()

            # Available MCP tools
            tools_result = await session.execute(
                select(MCPToolConfig).where(MCPToolConfig.tenant_id == tenant_id, MCPToolConfig.is_active == True)  # noqa: E712
            )
            tools = tools_result.scalars().all()

        return {
            "rules": [{"id": r.id, "statement": r.statement, "domain": r.domain, "confidence": r.confidence_scalar, "compliance_tags": r.compliance_tags} for r in rules[:10]],
            "rule_ids": [r.id for r in rules],
            "skills": [{"id": s.id, "skill_id": s.skill_id, "department": s.department, "confidence": s.confidence, "steps": len(s.steps or [])} for s in skills[:5]],
            "skill_ids": [s.id for s in skills],
            "connectors": [{"name": c.name, "category": c.category, "status": c.status} for c in connectors],
            "available_tools": [t.tool_id for t in tools],
            "total_rules": len(rules),
            "total_skills": len(skills),
        }

    async def _generate_dag(self, prompt: str, decomposition: dict, brain: dict, temporal: dict) -> dict:
        """Use LLM to compose the DAG from intent + brain context."""
        try:
            brain_summary = f"Rules found: {brain['total_rules']} | Skills found: {brain['total_skills']} | Connectors: {[c['name'] for c in brain['connectors'][:5]]} | Tools: {brain['available_tools'][:5]}"
            temporal_summary = f"Quarter: {temporal.get('current_quarter')} | Calendar events: {[e['name'] for e in temporal.get('active_calendar_events', [])]}"

            prompt_text = f"""Generate an agent execution DAG (directed acyclic graph) for this request.

USER REQUEST: "{prompt}"

INTENT: {json.dumps(decomposition, default=str)[:500]}
COMPANY BRAIN: {brain_summary}
TEMPORAL: {temporal_summary}

Node types: DATA_SOURCE, TRANSFORM, DECISION_GATE, ACTION, OUTPUT, HITL_CHECKPOINT, FAIRNESS_GATE
Edge types: DATA_FLOW, CONDITIONAL_TRUE, CONDITIONAL_FALSE, ESCALATION

Generate 4-8 nodes representing the agent's execution flow.
Each node needs: id (node_1, node_2...), type, label, config (tool, condition, etc.), position (x,y for layout).
Each edge needs: id (edge_1...), source, target, type, label.

Respond in JSON: {{"nodes":[{{"id":"node_1","type":"DATA_SOURCE","label":"...","config":{{}},"position":{{"x":0,"y":0}}}}],"edges":[{{"id":"edge_1","source":"node_1","target":"node_2","type":"DATA_FLOW","label":"..."}}]}}"""

            resp = await self.llm.complete(prompt=prompt_text, model_tier="reasoning", temperature=0.4)
            dag = self._parse_json(resp)

            # Validate and enrich
            if "nodes" not in dag:
                dag = {"nodes": [], "edges": []}
            
            # Auto-insert FAIRNESS_GATE if HCM data involved
            if decomposition.get("involves_hcm_data"):
                fairness_node = {"id": "node_fairness", "type": "FAIRNESS_GATE", "label": "Ethical AI Fairness Check", "config": {"threshold": 0.85, "protected_attributes": ["gender", "ethnicity", "age", "disability", "nationality"]}, "position": {"x": 200, "y": 0}}
                dag["nodes"].insert(1, fairness_node)

            return dag
        except Exception as e:
            logger.error(f"[BlueprintGen] DAG generation failed: {e}")
            # Return a minimal valid DAG
            return {
                "nodes": [
                    {"id": "node_1", "type": "DATA_SOURCE", "label": "Input Data", "config": {}, "position": {"x": 0, "y": 0}},
                    {"id": "node_2", "type": "ACTION", "label": decomposition.get("action_type", "Process"), "config": {}, "position": {"x": 300, "y": 0}},
                    {"id": "node_3", "type": "OUTPUT", "label": "Result", "config": {}, "position": {"x": 600, "y": 0}},
                ],
                "edges": [
                    {"id": "edge_1", "source": "node_1", "target": "node_2", "type": "DATA_FLOW", "label": ""},
                    {"id": "edge_2", "source": "node_2", "target": "node_3", "type": "DATA_FLOW", "label": ""},
                ]
            }

    def _derive_compliance_tags(self, brain: dict, decomposition: dict) -> list:
        tags = set()
        for rule in brain.get("rules", []):
            tags.update(rule.get("compliance_tags", []))
        if decomposition.get("involves_hcm_data"):
            tags.update(["EEOC", "GDPR"])
        return list(tags)

    def _derive_guardrails(self, compliance_tags: list, decomposition: dict) -> dict:
        pre = []
        post = []
        if "SOX" in compliance_tags:
            pre.append({"type": "verify", "condition": "human_approver_assigned"})
        if "GDPR" in compliance_tags:
            pre.append({"type": "verify", "condition": "data_subject_consent_verified"})
        if "PCI_DSS" in compliance_tags:
            pre.append({"type": "verify", "condition": "no_raw_card_data_in_context"})
        if decomposition.get("involves_hcm_data"):
            pre.append({"type": "fairness_gate", "condition": "fairness_score >= 0.85"})
        post.append({"type": "assert", "condition": "audit_trail_written"})
        post.append({"type": "assert", "condition": "provenance_entry_created"})
        return {"pre_execution": pre, "post_execution": post}

    def _calculate_confidence_floor(self, brain: dict) -> float:
        confidences = [r.get("confidence", 0) for r in brain.get("rules", []) if r.get("confidence", 0) > 0]
        if not confidences:
            return 0.5
        return min(confidences)

    def _parse_json(self, response: str) -> dict:
        cleaned = response.strip()
        for p in ["```json", "```"]:
            if cleaned.startswith(p): cleaned = cleaned[len(p):]
        if cleaned.endswith("```"): cleaned = cleaned[:-3]
        try:
            return json.loads(cleaned.strip())
        except json.JSONDecodeError:
            try:
                return json.loads(response[response.index("{"):response.rindex("}") + 1])
            except (ValueError, json.JSONDecodeError):
                return {}

    def _serialize(self, bp: AgentBlueprint) -> dict:
        return {
            "id": bp.id, "name": bp.name, "description": bp.description,
            "domain": bp.domain, "department": bp.department,
            "status": bp.status.value if bp.status else None,
            "blueprint_graph": bp.blueprint_graph, "source_skill_ids": bp.source_skill_ids,
            "source_rule_ids": bp.source_rule_ids, "mcp_tools_required": bp.mcp_tools_required,
            "guardrails": bp.guardrails, "compliance_tags": bp.compliance_tags,
            "confidence_floor": bp.confidence_floor, "intent_decomposition": bp.intent_decomposition,
            "created_by": bp.created_by, "approved_by": bp.approved_by,
            "created_at": bp.created_at.isoformat() if bp.created_at else None,
            "approved_at": bp.approved_at.isoformat() if bp.approved_at else None,
        }
