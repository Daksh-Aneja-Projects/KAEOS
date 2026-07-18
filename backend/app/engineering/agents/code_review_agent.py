"""KAEOS Engineering Domain — Code Review Agent"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engineering.agents.gated_runner import extract_decision, run_gated_engineering_skill
from app.engineering.models.delivery import PullRequest, RiskLevel

logger = logging.getLogger(__name__)


class CodeReviewAgent:
    """Reviews a pull request and writes a risk assessment back onto the PR."""

    async def review_pull_request(
        self, db: AsyncSession, pr_id: str, tenant_id: str
    ) -> Dict[str, Any]:
        pr = (await db.execute(
            select(PullRequest).where(
                PullRequest.id == pr_id, PullRequest.tenant_id == tenant_id
            )
        )).scalar_one_or_none()
        if not pr:
            raise ValueError("Pull request not found")

        # Deterministic change-surface facts, given to the model as grounding
        # so its judgement is anchored to the real diff rather than invented.
        surface = {
            "title": pr.title,
            "files_changed": pr.files_changed,
            "additions": pr.additions,
            "deletions": pr.deletions,
            "touches_migrations": pr.touches_migrations,
            "touches_auth": pr.touches_auth,
            "ci_passing": pr.ci_passing,
            "test_coverage_delta": pr.test_coverage_delta,
        }

        steps = [
            {"step": 1, "name": "Load Change Surface",
             "prompt": f"Load pull request {pr.number}: {surface}"},
            {"step": 2, "name": "Assess Risk",
             "prompt": (
                 "Assess the risk of merging this change. Weigh: size of the diff, "
                 "whether it touches auth or database migrations, CI status, and any "
                 "drop in test coverage. Respond as JSON with keys "
                 '"risk_level" (LOW|MEDIUM|HIGH|CRITICAL), "summary" (one sentence), '
                 'and "findings" (array of short strings).'
             )},
        ]

        result = await run_gated_engineering_skill(
            skill_id="engineering_code_review",
            steps=steps,
            context={"pr_id": pr_id, "tenant_id": tenant_id, "surface": surface},
            tenant_id=tenant_id,
        )

        decision = extract_decision(result)
        risk = self._resolve_risk(decision.get("risk_level"), surface)

        pr.ai_risk_level = risk
        pr.ai_summary = decision.get("summary") or self._deterministic_summary(surface, risk)
        pr.ai_findings = decision.get("findings") or self._deterministic_findings(surface)
        pr.ai_reviewed_at = datetime.now(timezone.utc)
        await db.commit()

        return {
            **result,
            "pr_number": pr.number,
            "risk_level": risk.value,
            "summary": pr.ai_summary,
            "findings": pr.ai_findings,
        }

    @staticmethod
    def _resolve_risk(model_answer: Any, surface: Dict[str, Any]) -> RiskLevel:
        """
        Trust the model's label only when it is a valid one; otherwise fall back
        to deterministic rules over the real change surface. The gates must never
        depend on the model returning a well-formed answer.
        """
        if isinstance(model_answer, str):
            try:
                return RiskLevel(model_answer.strip().upper())
            except ValueError:
                pass
        if surface["touches_auth"] or surface["touches_migrations"] or not surface["ci_passing"]:
            return RiskLevel.HIGH
        if (surface["additions"] or 0) + (surface["deletions"] or 0) > 500:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    @staticmethod
    def _deterministic_summary(surface: Dict[str, Any], risk: RiskLevel) -> str:
        return (
            f"{surface['files_changed']} files changed "
            f"(+{surface['additions']}/-{surface['deletions']}); assessed {risk.value} risk."
        )

    @staticmethod
    def _deterministic_findings(surface: Dict[str, Any]) -> list:
        findings = []
        if surface["touches_auth"]:
            findings.append("Touches authentication code — requires security review.")
        if surface["touches_migrations"]:
            findings.append("Contains a database migration — verify rollback path.")
        if not surface["ci_passing"]:
            findings.append("CI is failing — do not merge until green.")
        delta = surface.get("test_coverage_delta")
        if delta is not None and delta < 0:
            findings.append(f"Test coverage drops {abs(delta):.1f} points.")
        return findings
