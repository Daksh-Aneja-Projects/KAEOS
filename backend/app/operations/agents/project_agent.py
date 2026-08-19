"""KAEOS Operations Domain - Project Agent

Context-grounding: the agent loads the real entity and reasons over its
content. Passing only an opaque id left the model classifying an identifier
(confirmed ungrounded on real onboarded data), so facts are non-optional.
"""
import logging
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.operations.agents.gated_runner import extract_decision, run_gated_operations_skill
from app.operations.models.projects import Project
from app.services.json_utils import enum_value, plain_facts

logger = logging.getLogger(__name__)


class ProjectAgent:
    async def evaluate_project(self, db: AsyncSession, project_id: str, tenant_id: str) -> Dict[str, Any]:
        logger.info(f"ProjectAgent evaluating project {project_id}")
        project = (await db.execute(
            select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not project:
            raise ValueError(f"Project {project_id} not found")

        facts = {
            "name": project.name,
            "description": (project.description or "")[:1000],
            "status": enum_value(project.status),
            "start_date": str(project.start_date) if project.start_date else None,
            "end_date": str(project.end_date) if project.end_date else None,
            "completion_percentage": project.completion_percentage,
        }
        facts = plain_facts(facts)
        steps = [
            {"step": 1, "name": "Check Timeline",
             "prompt": f"Check the timeline and progress of this project: {facts}"},
            {"step": 2, "name": "Flag Delays",
             "prompt": "Flag any delays or risks given the completion percentage and dates."},
        ]
        result = await run_gated_operations_skill(
            skill_id="operations_project_eval",
            steps=steps,
            context={
                "project_id": project_id, "tenant_id": tenant_id, **facts,
                "instruction": "Output strict JSON: {on_track, delay_risk, blockers, recommended_action}.",
            },
            tenant_id=tenant_id,
        )

        if result.get("status") == "SUCCESS_CLEAN":
            decision = extract_decision(result)
            # Write the outcome onto the real entity. A healthy verdict (no
            # delay risk / no blockers / no recommendation) clears any stale
            # warning rather than leaving it stuck from a prior evaluation.
            note_parts = []
            delay_risk = decision.get("delay_risk")
            if delay_risk and str(delay_risk).strip().upper() not in ("NONE", "LOW", "N/A"):
                note_parts.append(f"Delay risk: {str(delay_risk).replace('_', ' ').title()}.")
            blockers = decision.get("blockers")
            if blockers:
                blockers_text = blockers if isinstance(blockers, str) else ", ".join(str(b) for b in blockers)
                if blockers_text.strip():
                    note_parts.append(f"Blockers: {blockers_text}.")
            action = decision.get("recommended_action")
            if action:
                note_parts.append(f"Recommended action: {action}.")
            project.ai_risk_note = " ".join(note_parts) if note_parts else None
            db.add(project)
            await db.commit()
            result = {**result, "decision": decision}

        return result
