"""KAEOS — Marketplace API (L19 Developer Platform)"""
from app.core.tenant import get_tenant_id
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.domain import MarketplaceTemplate

router = APIRouter(prefix="/marketplace", tags=["Marketplace — L19 Platform"])


@router.get("")
async def list_templates(
    category: str | None = None,
    tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
):
    """List marketplace templates from DB."""
    q = select(MarketplaceTemplate).where(MarketplaceTemplate.status == "PUBLISHED")
    if category:
        q = q.where(MarketplaceTemplate.category == category)
    q = q.order_by(MarketplaceTemplate.installs.desc())

    result = await db.execute(q)
    templates = result.scalars().all()

    return {
        "templates": [
            {
                "id": t.id, "name": t.name, "category": t.category,
                "description": t.description, "author": t.author,
                "version": t.version, "rating": t.rating,
                "installs": t.installs, "rules_count": t.rules_count,
                "skills_count": t.skills_count, "tags": t.tags,
                "compliance_frameworks": t.compliance_frameworks,
                "certified": t.certified, "preview_data": t.preview_data,
            }
            for t in templates
        ],
        "total": len(templates),
        "categories": list(set(t.category for t in templates)),
    }

from pydantic import BaseModel
from typing import List

class MarketplaceTemplateCreate(BaseModel):
    name: str
    category: str
    description: str
    author: str
    tags: List[str]

@router.post("")
async def create_template(
    body: MarketplaceTemplateCreate,
    tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)
):
    import uuid
    template = MarketplaceTemplate(
        id=str(uuid.uuid4()),
        name=body.name,
        category=body.category,
        description=body.description,
        author=body.author,
        tags=body.tags,
        status="PUBLISHED",
        certified=False,
        version="1.0",
        rating=0.0,
        installs=0,
        rules_count=0,
        skills_count=0,
        compliance_frameworks=[]
    )
    db.add(template)
    await db.commit()
    return {"status": "success", "id": template.id}
