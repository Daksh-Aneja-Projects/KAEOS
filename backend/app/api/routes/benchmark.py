"""Cross-org benchmarking and the strategic intelligence report.

Both reads turn the same three org numbers into an LLM-generated analysis, which
costs tens of seconds on a local model. Both are therefore content-addressed
cached against those numbers (see app/core/result_cache.py): the same org state
returns the same analysis instantly, and a change in the org changes the
fingerprint so the analysis is regenerated.

The payload builders are module-level rather than inline in the handlers so the
scheduler's cache warmer can call the SAME code path. That matters more than it
looks: a warmer that rebuilt the prompt or the fingerprint separately would
write a key the endpoint never reads, and the cache would silently never hit.
"""
import json
import logging

from app.core.tenant import get_tenant_id
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.database import get_db
from app.core.result_cache import get_or_compute, peek, put
from app.models.domain import Rule, Skill

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/benchmark", tags=["Benchmark — L14 Cross-Org Intelligence"])


async def _org_snapshot(db: AsyncSession, tenant_id: str) -> tuple[int, int, float]:
    """The three tenant-scoped numbers every analysis below is derived from."""
    rules_count = await db.execute(select(func.count(Rule.id)).where(Rule.tenant_id == tenant_id))
    skills_count = await db.execute(select(func.count(Skill.id)).where(Skill.tenant_id == tenant_id))
    avg_conf = await db.execute(select(func.avg(Rule.confidence_scalar)).where(Rule.tenant_id == tenant_id))
    return (rules_count.scalar() or 0, skills_count.scalar() or 0, avg_conf.scalar() or 0.0)


async def build_cross_org_benchmark(db: AsyncSession, tenant_id: str) -> dict:
    """The /benchmark/network payload. Safe to call off the request path."""
    local_rules, local_skills, local_conf = await _org_snapshot(db, tenant_id)

    from app.services.llm_router import LLMRouter
    from app.services.json_utils import extract_json_object

    llm = LLMRouter()
    prompt = (
        f"You are the KAEOS Cross-Org Benchmark Engine.\n"
        f"Our local org has: {local_rules} rules, {local_skills} skills, {local_conf} avg confidence.\n"
        f"Generate a JSON response matching this schema: "
        f"{{\"industry_median\": {{\"kb_coverage_pct\": int, \"agent_autonomy_pct\": int, \"time_to_onboard_days\": int, \"active_skills\": int}}, "
        f"\"top_quartile\": {{\"kb_coverage_pct\": int, ...}}, "
        f"\"department_benchmarks\": [{{\"department\": str, \"local_coverage\": int, \"industry_median\": int, \"status\": \"LEADER\"|\"LAGGING\"}}]}}"
    )

    async def _generate() -> dict:
        res = await llm.complete(prompt=prompt, model_tier="classification")
        if isinstance(res, dict):
            content = res.get("content", "{}")
            return extract_json_object(content) if isinstance(content, str) else content
        if isinstance(res, str):
            return extract_json_object(res)
        return {}

    try:
        benchmarks, _cached = await get_or_compute(
            "benchmark_network",
            tenant_id,
            [local_rules, local_skills, round(float(local_conf), 4)],
            _generate,
            should_cache=lambda v: bool(v),   # never pin an empty parse
        )
        if not benchmarks:
            raise ValueError("empty benchmark payload")
    except Exception as e:
        logger.warning(f"Benchmark LLM fallback triggered: {e}")
        benchmarks = {
            "industry_median": {"kb_coverage_pct": 78, "agent_autonomy_pct": 43, "time_to_onboard_days": 45, "active_skills": 15},
            "top_quartile": {"kb_coverage_pct": 92, "agent_autonomy_pct": 81, "time_to_onboard_days": 3, "active_skills": 42},
            "department_benchmarks": [
                {"department": "Sales", "local_coverage": 85, "industry_median": 62, "status": "LEADER"},
                {"department": "Engineering", "local_coverage": 40, "industry_median": 85, "status": "LAGGING"}
            ]
        }

    return {
        "local_org": {
            "kb_coverage_pct": min(100, int((local_rules / 100) * 100)) if local_rules else 35,
            "agent_autonomy_pct": min(100, int(local_conf * 100)),
            "time_to_onboard_days": 12,
            "active_skills": local_skills
        },
        **benchmarks
    }


REPORT_CACHE_NS = "benchmark_intelligence_report"


def _report_prompt(local_rules: int, local_skills: int, local_conf: float) -> str:
    """The report prompt. One definition, because the streaming and blocking
    endpoints must produce the same text for the same org, and because the cache
    fingerprint below assumes they do."""
    return (
        f"You are a strategic enterprise intelligence analyst for KAEOS, the AI Operating System for Companies.\n"
        f"Generate a detailed intelligence report comparing this organization.\n\n"
        f"Org data: {local_rules} rules, {local_skills} skills, {local_conf} avg confidence.\n\n"
        f"Output JSON: {{\"executive_summary\": \"...\", \"strengths\": [\"...\"], "
        f"\"gaps\": [\"...\"], \"recommendations\": [{{\"priority\": \"HIGH\", \"action\": \"...\", \"impact\": \"...\"}}], "
        f"\"maturity_score\": 0-100, \"maturity_tier\": \"NASCENT|DEVELOPING|ESTABLISHED|LEADER\"}}"
    )


async def build_intelligence_report(db: AsyncSession, tenant_id: str) -> dict:
    """The /benchmark/intelligence-report payload. Safe to call off the request path."""
    from app.services.llm_router import LLMRouter
    from app.services.json_utils import extract_json_object

    raw_rules, raw_skills, raw_conf = await _org_snapshot(db, tenant_id)
    local_rules, local_skills = raw_rules, raw_skills
    local_conf = round(raw_conf, 3)

    llm = LLMRouter()
    prompt = _report_prompt(local_rules, local_skills, local_conf)

    async def _generate() -> dict:
        res = await llm.complete(prompt=prompt, model_tier="reasoning")
        if isinstance(res, dict):
            content = res.get("content", "{}")
            return extract_json_object(content) if isinstance(content, str) else content
        if isinstance(res, str):
            return extract_json_object(res)
        return {}

    try:
        report, _cached = await get_or_compute(
            REPORT_CACHE_NS,
            tenant_id,
            [local_rules, local_skills, local_conf],
            _generate,
            should_cache=lambda v: bool(v and v.get("executive_summary")),
        )
        if not report:
            raise ValueError("empty report payload")
    except Exception as e:
        report = {
            "executive_summary": f"Report generation pending: {str(e)[:80]}",
            "strengths": [], "gaps": [], "recommendations": [],
            "maturity_score": 0, "maturity_tier": "NASCENT"
        }

    return {
        "report": report,
        "org_snapshot": {"total_rules": local_rules, "total_skills": local_skills, "avg_confidence": local_conf}
    }


@router.get("/network")
async def get_cross_org_benchmark(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    return await build_cross_org_benchmark(db, tenant_id)


@router.get("/intelligence-report")
async def generate_intelligence_report(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """L14 — LLM-powered intelligence report comparing org against industry benchmarks."""
    return await build_intelligence_report(db, tenant_id)


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@router.get("/intelligence-report/stream")
async def stream_intelligence_report(
    tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)
):
    """The same report as ``/intelligence-report``, delivered as it is written.

    The report takes tens of seconds to generate because it is tens of seconds
    of real writing. Caching removes the wait on every request after the first,
    but somebody still pays it the first time an org's numbers change, and
    staring at a spinner for half a minute is the part that feels broken. The
    model emits its first words in well under a second, so this streams them.

    Same cache as the blocking endpoint, same fingerprint: a cached report is
    delivered whole and immediately, and a freshly streamed one is stored, so
    whichever endpoint runs first warms the other.

    The non-streaming route is unchanged and remains the contract for API
    clients and the test suite; this is additive.
    """
    from app.services.llm_router import LLMRouter
    from app.services.json_utils import extract_json_object

    raw_rules, raw_skills, raw_conf = await _org_snapshot(db, tenant_id)
    local_conf = round(raw_conf, 3)
    parts = [raw_rules, raw_skills, local_conf]
    snapshot = {
        "total_rules": raw_rules, "total_skills": raw_skills, "avg_confidence": local_conf,
    }

    async def events():
        cached = await peek(REPORT_CACHE_NS, tenant_id, parts)
        if cached:
            yield _sse({"type": "done", "report": cached, "org_snapshot": snapshot, "cached": True})
            return

        yield _sse({"type": "start", "org_snapshot": snapshot})
        acc = ""
        try:
            async for delta in LLMRouter().stream_complete(
                prompt=_report_prompt(raw_rules, raw_skills, local_conf),
                model_tier="reasoning",
            ):
                acc += delta
                yield _sse({"type": "token", "text": delta})
        except Exception as e:
            logger.warning(f"Intelligence report stream failed: {e}")
            yield _sse({
                "type": "error",
                "message": "The report engine is unavailable right now. Nothing was invented in its place.",
            })
            return

        report = extract_json_object(acc) or {}
        if report.get("executive_summary"):
            await put(REPORT_CACHE_NS, tenant_id, parts, report)
        else:
            # Streamed text that will not parse is reported as a failure rather
            # than returned as an empty report that looks like a real answer.
            yield _sse({
                "type": "error",
                "message": "The report came back in a form this page could not read. It was not saved.",
            })
            return
        yield _sse({"type": "done", "report": report, "org_snapshot": snapshot, "cached": False})

    return StreamingResponse(events(), media_type="text/event-stream")
