from app.core.tenant import get_tenant_id
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.models.domain import Rule, Workflow

router = APIRouter(prefix="/topology", tags=["Topology — L4 Knowledge Graph"])

@router.get("/graph")
async def get_knowledge_graph(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    # Tenant-scoped to the caller.
    rules_res = await db.execute(select(Rule).where(Rule.tenant_id == tenant_id).limit(50))
    workflows_res = await db.execute(select(Workflow).where(Workflow.tenant_id == tenant_id).limit(10))
    
    rules = rules_res.scalars().all()
    workflows = workflows_res.scalars().all()
    
    nodes = []
    edges = []
    
    # Workflows as core nodes
    for w in workflows:
        nodes.append({"id": w.id, "label": w.name, "group": "workflow", "department": w.department})
        
    for r in rules:
        nodes.append({
            "id": r.id, 
            "label": r.statement[:30] + "..." if len(r.statement)>30 else r.statement, 
            "group": "rule", 
            "confidence": r.confidence_scalar,
            "domain": r.domain
        })
        
        # Link to workflow
        if r.workflow_id:
            edges.append({"source": r.id, "target": r.workflow_id, "label": "APPLIES_TO"})
            
        # Link refinement
        if r.parent_version:
            edges.append({"source": r.id, "target": r.parent_version, "label": "REFINES"})
            
    return {"nodes": nodes, "edges": edges}


@router.get("/knowledge/graph")
async def get_knowledge_graph_alias(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Alias for /topology/graph — matches directive naming convention."""
    return await get_knowledge_graph(tenant_id, db)
