"""
KAEOS HR Vertical — Recruiting Agent

Autonomous agent responsible for talent acquisition processes.
Handles resume screening, interview scheduling, and offer generation.
"""
import logging
from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.services.llm_router import LLMRouter
from app.hr.models.recruiting import Candidate, JobRequisition, CandidateStage

logger = logging.getLogger(__name__)

class RecruitingAgent:
    """Agent for Talent Acquisition."""
    
    def __init__(self):
        self.router = LLMRouter()
        self.persona = "You are the KAEOS Recruiting Agent. You are an expert in talent acquisition, unbiased screening, and providing a great candidate experience."

    async def screen_candidate(self, db: AsyncSession, candidate_id: str) -> Dict[str, Any]:
        """Screens a candidate's resume against the job requisition."""
        q = await db.execute(select(Candidate).where(Candidate.id == candidate_id))
        candidate = q.scalar_one_or_none()
        
        if not candidate:
            raise ValueError(f"Candidate {candidate_id} not found")
            
        req_q = await db.execute(select(JobRequisition).where(JobRequisition.id == candidate.requisition_id))
        req = req_q.scalar_one()
        
        logger.info(f"RecruitingAgent screening candidate {candidate_id} for req {req.id}")
        
        # Fetch resume text from candidate.resume_path
        resume_text = "No resume provided or file not found."
        if candidate.resume_path:
            import os
            import aiofiles
            if os.path.exists(candidate.resume_path):
                try:
                    async with aiofiles.open(candidate.resume_path, 'r') as f:
                        resume_text = await f.read()
                except Exception as e:
                    logger.warning(f"Failed to read resume {candidate.resume_path}: {e}")
        
        # NOTE: the prompt is not built here — the gated runner composes it from
        # `context` below, which carries the same fields (see json_utils.compact_context).
        
        # Route through the full 7-gate AgentExecutor (Compliance -> Fairness ->
        # Confidence/HITL -> Debate -> Execute -> Audit), not the raw skill engine.
        from app.hr.agents.gated_runner import run_gated_hr_skill, extract_decision

        steps = [
            {
                "id": "screen_1",
                "action": "Evaluate candidate against job requisition using only job-related qualifications; output strict JSON with score, summary, red_flags, recommend_advance",
                "tool": "none",
                "condition": "Always",
                "thresholds": "None",
            }
        ]
        context = {
            "persona": self.persona,
            "job_requirements": req.requirements,
            "job_description": req.job_description,
            "candidate_resume_text": resume_text,
            "intent": f"screen candidate {candidate_id} for requisition {req.id}",
            # Fairness gate context — HCM decision touching protected attributes.
            "affected_entity_type": "Candidate",
            "affected_count": 1,
            "instruction": "Output strict JSON in the decision field with keys: score (0-100), summary (string), red_flags (list), recommend_advance (bool).",
        }

        try:
            result = await run_gated_hr_skill(
                skill_id="hr_recruitment_screening",
                steps=steps,
                context=context,
                tenant_id=req.tenant_id,
                compliance_tags=["EEOC", "GDPR"],
            )

            status = result.get("status")
            if status != "SUCCESS_CLEAN":
                # Fairness/compliance/debate gate intervened, or HITL/override.
                logger.warning(f"RecruitingAgent screening gated: {status} for {candidate_id}")
                candidate.stage = CandidateStage.RECRUITER_SCREEN  # hold for human review
                db.add(candidate)
                await db.commit()
                return {
                    "status": status,
                    "gated": True,
                    "detail": {k: v for k, v in result.items() if k != "reasoning_chain"},
                }

            eval_data = extract_decision(result)
            if not eval_data:
                eval_data = {"score": 50, "summary": "No structured decision produced.",
                             "red_flags": [], "recommend_advance": False}

            # Update candidate record
            candidate.ai_score = eval_data.get("score")
            candidate.ai_summary = eval_data.get("summary")
            candidate.ai_red_flags = eval_data.get("red_flags", [])

            if eval_data.get("recommend_advance"):
                candidate.stage = CandidateStage.RECRUITER_SCREEN
            else:
                candidate.stage = CandidateStage.REJECTED

            db.add(candidate)
            await db.commit()

            eval_data["status"] = status
            eval_data["execution_id"] = result.get("execution_id")
            return eval_data

        except Exception as e:
            logger.error(f"RecruitingAgent screening failed via gated executor: {e}")
            raise
