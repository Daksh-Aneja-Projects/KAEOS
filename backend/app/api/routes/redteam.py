"""KAEOS — Red Team API (L12 Adversarial Harness) — DB-Backed"""
from collections import defaultdict
import time
import uuid

from app.core.tenant import get_tenant_id
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.domain import Skill, RedTeamScanResult
from app.services.redteam import RedTeamHarness

router = APIRouter(prefix="/redteam", tags=["RedTeam — L12 Adversarial Harness"])


@router.get("/scans/recent")
async def get_recent_scans(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Get recent scan results from DB, aggregated per skill. Tenant-scoped to the caller."""
    # Single query over all of the tenant's scan rows, newest first; grouped in
    # Python below (previously one query per distinct skill_id — an N+1).
    result = await db.execute(
        select(RedTeamScanResult)
        .where(RedTeamScanResult.tenant_id == tenant_id)
        .order_by(RedTeamScanResult.scanned_at.desc())
    )
    by_skill: "defaultdict[str, list]" = defaultdict(list)
    for row in result.scalars().all():
        by_skill[row.skill_id].append(row)

    scans = []
    for sid, skill_scans in by_skill.items():
        # skill_scans is already newest-first from the ordered query above.
        total_vulns = sum(s.vulnerabilities_found for s in skill_scans)
        worst_status = "PASSED"
        if any(s.status == "FAILED" for s in skill_scans):
            worst_status = "FAILED"
        elif any(s.status == "WARNING" for s in skill_scans):
            worst_status = "WARNING"

        scans.append({
            "skill_id": sid,
            "department": skill_scans[0].skill_department if skill_scans else "",
            "status": worst_status,
            "vulnerabilities": total_vulns,
            "scan_count": len(skill_scans),
            "last_scan": skill_scans[0].scanned_at.isoformat() if skill_scans else None,
            "scan_types": list(set(s.scan_type for s in skill_scans)),
            "details": [
                {
                    "scan_type": s.scan_type,
                    "status": s.status,
                    "vulnerabilities": s.vulnerabilities_found,
                    "details": s.details,
                    "confidence_at_scan": s.confidence_at_scan,
                    "duration_ms": s.duration_ms,
                    "scanned_at": s.scanned_at.isoformat() if s.scanned_at else None,
                }
                for s in skill_scans
            ],
        })

    total_vulns = sum(s["vulnerabilities"] for s in scans)
    failed = sum(1 for s in scans if s["status"] == "FAILED")
    return {
        "scans": scans,
        "summary": {
            "total_skills_scanned": len(scans),
            "total_vulnerabilities": total_vulns,
            "failed_skills": failed,
            "passed_skills": len(scans) - failed,
        },
    }


@router.post("/scan/{skill_id}")
async def run_skill_scan(skill_id: str, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Run a new adversarial scan against a skill and persist results. Tenant-scoped to the caller."""
    result = await db.execute(
        select(Skill)
        .where(Skill.tenant_id == tenant_id)
        .where(Skill.skill_id == skill_id)
    )
    skill = result.scalars().first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    # Feed the real L12 harness the skill contract rather than fabricating results.
    harness = RedTeamHarness()
    skill_payload = {
        "skill_id": skill.skill_id,
        "department": skill.department,
        "domain": skill.domain,
        "confidence": skill.confidence,
        "guardrails": skill.guardrails or {},
        "steps": skill.steps or [],
        "triggers": skill.triggers or [],
    }

    def _status_for(vulns: list) -> str:
        if any(str(v.get("severity", "")).upper() in ("CRITICAL", "HIGH") for v in vulns):
            return "FAILED"
        return "WARNING" if vulns else "PASSED"

    new_scans = []

    # ── BOUNDARY: real guardrail range analysis ──
    t0 = time.perf_counter()
    boundary_vulns = harness.test_boundary_conditions(skill_payload)
    boundary_ms = int((time.perf_counter() - t0) * 1000)

    # ── ADVERSARIAL: real LLM-driven prompt-injection probe ──
    t0 = time.perf_counter()
    adversarial_vulns = await harness.test_adversarial_inputs(skill_payload)
    adversarial_ms = int((time.perf_counter() - t0) * 1000)

    # ── CONFIDENCE_CALIBRATION: heuristic threshold check (NOT an adversarial scan) ──
    # Honest labelling: this is a cheap confidence-calibration heuristic, not a
    # real attack. Details are marked heuristic so the UI cannot pass it off as
    # a genuine adversarial finding.
    t0 = time.perf_counter()
    conf_vulns = []
    if skill.confidence < 0.90:
        conf_vulns.append({
            "type": "LOW_CONFIDENCE_CALIBRATION",
            "severity": "MODERATE",
            "heuristic": True,
            "description": f"Heuristic: confidence {skill.confidence:.2f} below the 0.90 "
                           f"calibration threshold (no adversarial testing performed).",
        })
    conf_ms = int((time.perf_counter() - t0) * 1000)

    scan_specs = [
        ("BOUNDARY", boundary_vulns, boundary_ms),
        ("ADVERSARIAL", adversarial_vulns, adversarial_ms),
        ("CONFIDENCE_CALIBRATION", conf_vulns, conf_ms),
    ]

    for stype, vulns, duration_ms in scan_specs:
        status = _status_for(vulns)
        scan = RedTeamScanResult(
            id=str(uuid.uuid4()), tenant_id=tenant_id,
            skill_id=skill.skill_id, skill_department=skill.department,
            scan_type=stype, status=status,
            vulnerabilities_found=len(vulns), details=vulns,
            confidence_at_scan=skill.confidence, duration_ms=duration_ms,
        )
        db.add(scan)
        new_scans.append({"scan_type": stype, "status": status, "vulnerabilities": len(vulns)})

    await db.commit()
    return {"skill_id": skill_id, "scans": new_scans, "status": "COMPLETED"}
