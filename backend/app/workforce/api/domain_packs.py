from app.core.tenant import get_tenant_id
"""
KAEOS Workforce API — Domain Packs
Browse, install, and manage domain packs.

Domain Packs are the heart of EWOS — they define entire enterprise
departments as deployable packages. HR pack, Finance pack, Legal pack.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.workforce.models.domain_pack import DomainPack, DomainPackInstallation

router = APIRouter(prefix="/workforce/packs", tags=["Workforce — Domain Packs"])


@router.get("/")
async def list_domain_packs(
    category: str = None,
    db: AsyncSession = Depends(get_db),
):
    """Browse available domain packs (marketplace)."""
    q = select(DomainPack).where(DomainPack.status == "ACTIVE")
    if category:
        q = q.where(DomainPack.category == category)
    q = q.order_by(DomainPack.name)

    result = await db.execute(q)
    packs = result.scalars().all()

    return {
        "total": len(packs),
        "packs": [
            {
                "id": p.id,
                "name": p.name,
                "slug": p.slug,
                "description": p.description,
                "version": p.version,
                "icon": p.icon,
                "category": p.category,
                "source": p.source,
                "author": p.author,
                "required_integrations": p.required_integrations or [],
                "optional_integrations": p.optional_integrations or [],
                "capabilities": p.capabilities or [],
                "agent_definitions": p.agent_definitions or [],
                "process_definitions": p.process_definitions or [],
                "knowledge_templates": p.knowledge_templates or [],
                "deployment_config": p.deployment_config or {},
                "compliance_frameworks": p.compliance_frameworks or [],
                "status": p.status,
                "created_at": str(p.created_at) if p.created_at else None,
            }
            for p in packs
        ],
    }


@router.get("/installations")
async def list_installations(
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """List installed domain packs for a tenant."""
    result = await db.execute(
        select(DomainPackInstallation)
        .where(DomainPackInstallation.tenant_id == tenant_id)
        .order_by(DomainPackInstallation.installed_at.desc())
    )
    installs = result.scalars().all()

    return {
        "total": len(installs),
        "installations": [
            {
                "id": i.id,
                "domain_pack_id": i.domain_pack_id,
                "installed_version": i.installed_version,
                "status": i.status,
                "customizations": i.customizations or {},
                "installed_at": str(i.installed_at) if i.installed_at else None,
            }
            for i in installs
        ],
    }


@router.post("/{pack_id}/install")
async def install_domain_pack(
    pack_id: str,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db)
):
    """Install a domain pack — records a real, idempotent installation row."""
    from app.workforce.models.domain_pack import DomainPackInstallation, InstallationStatus

    pack = (await db.execute(
        select(DomainPack).where(DomainPack.id == pack_id)
    )).scalar_one_or_none()
    if not pack:
        raise HTTPException(status_code=404, detail="Domain pack not found")

    existing = (await db.execute(
        select(DomainPackInstallation).where(
            DomainPackInstallation.tenant_id == tenant_id,
            DomainPackInstallation.domain_pack_id == pack_id,
        )
    )).scalar_one_or_none()
    if existing:
        existing.status = InstallationStatus.INSTALLED
        existing.installed_version = pack.version
        db.add(existing)
        await db.commit()
        return {"status": "success", "installation_id": existing.id,
                "message": f"Pack '{pack.name}' already installed — refreshed to v{pack.version}"}

    install = DomainPackInstallation(
        tenant_id=tenant_id,
        domain_pack_id=pack_id,
        installed_version=pack.version,
        status=InstallationStatus.INSTALLED,
    )
    db.add(install)
    await db.commit()
    await db.refresh(install)
    return {"status": "success", "installation_id": install.id,
            "message": f"Pack '{pack.name}' v{pack.version} installed"}


@router.post("/{pack_id}/uninstall")
async def uninstall_domain_pack(
    pack_id: str,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db)
):
    """Uninstall a domain pack — removes the tenant's installation record."""
    from app.workforce.models.domain_pack import DomainPackInstallation

    existing = (await db.execute(
        select(DomainPackInstallation).where(
            DomainPackInstallation.tenant_id == tenant_id,
            DomainPackInstallation.domain_pack_id == pack_id,
        )
    )).scalar_one_or_none()
    if not existing:
        raise HTTPException(status_code=404, detail="Pack is not installed for this tenant")

    await db.delete(existing)
    await db.commit()
    return {"status": "success", "message": f"Pack {pack_id} uninstalled"}


@router.get("/{pack_id}")
async def get_domain_pack(pack_id: str, db: AsyncSession = Depends(get_db)):
    """Get full details of a domain pack including agent/process definitions."""
    result = await db.execute(select(DomainPack).where(DomainPack.id == pack_id))
    pack = result.scalar_one_or_none()
    if not pack:
        raise HTTPException(status_code=404, detail="Domain pack not found")

    return {
        "id": pack.id,
        "name": pack.name,
        "slug": pack.slug,
        "description": pack.description,
        "version": pack.version,
        "icon": pack.icon,
        "category": pack.category,
        "source": pack.source,
        "author": pack.author,
        "required_integrations": pack.required_integrations or [],
        "optional_integrations": pack.optional_integrations or [],
        "capabilities": pack.capabilities or [],
        "agent_definitions": pack.agent_definitions or [],
        "process_definitions": pack.process_definitions or [],
        "knowledge_templates": pack.knowledge_templates or [],
        "deployment_config": pack.deployment_config or {},
        "compliance_frameworks": pack.compliance_frameworks or [],
        "status": pack.status,
        "created_at": str(pack.created_at) if pack.created_at else None,
        "updated_at": str(pack.updated_at) if pack.updated_at else None,
    }


