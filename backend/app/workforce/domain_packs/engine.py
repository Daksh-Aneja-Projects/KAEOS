"""
KAEOS Workforce Layer — Domain Pack Engine

Manages the catalog of available domain packs and handles installations.
"""
import logging
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.workforce.models.domain_pack import DomainPack, DomainPackSource, DomainPackInstallation, InstallationStatus
from app.workforce.domain_packs.loader import DomainPackLoader

logger = logging.getLogger(__name__)


class DomainPackEngine:
    
    @staticmethod
    async def sync_built_in_packs(db: AsyncSession):
        """Loads YAML packs from disk and syncs them to the database."""
        logger.info("Syncing built-in domain packs...")
        packs_data = DomainPackLoader.load_all_built_in_packs()
        
        for data in packs_data:
            slug = data["slug"]
            
            # Check if exists
            q = await db.execute(select(DomainPack).where(DomainPack.slug == slug))
            existing_pack = q.scalar_one_or_none()
            
            if existing_pack:
                # Update existing
                existing_pack.name = data.get("name", existing_pack.name)
                existing_pack.description = data.get("description", existing_pack.description)
                existing_pack.long_description = data.get("long_description", existing_pack.long_description)
                existing_pack.icon = data.get("icon", existing_pack.icon)
                existing_pack.category = data.get("category", existing_pack.category)
                existing_pack.version = str(data.get("version", existing_pack.version))
                existing_pack.required_integrations = data.get("required_integrations", [])
                existing_pack.optional_integrations = data.get("optional_integrations", [])
                existing_pack.capabilities = data.get("capabilities", [])
                existing_pack.agent_definitions = data.get("agent_definitions", [])
                existing_pack.process_definitions = data.get("process_definitions", [])
                existing_pack.knowledge_templates = data.get("knowledge_templates", [])
                existing_pack.deployment_config = data.get("deployment_config", {})
                existing_pack.compliance_frameworks = data.get("compliance_frameworks", [])
            else:
                # Create new
                new_pack = DomainPack(
                    name=data["name"],
                    slug=slug,
                    description=data.get("description"),
                    long_description=data.get("long_description"),
                    icon=data.get("icon", "📦"),
                    category=data.get("category", "general"),
                    industry_verticals=data.get("industry_verticals", ["all"]),
                    version=str(data.get("version", "1.0.0")),
                    source=DomainPackSource.BUILT_IN,
                    author=data.get("author", "KAEOS"),
                    required_integrations=data.get("required_integrations", []),
                    optional_integrations=data.get("optional_integrations", []),
                    capabilities=data.get("capabilities", []),
                    agent_definitions=data.get("agent_definitions", []),
                    process_definitions=data.get("process_definitions", []),
                    knowledge_templates=data.get("knowledge_templates", []),
                    deployment_config=data.get("deployment_config", {}),
                    compliance_frameworks=data.get("compliance_frameworks", [])
                )
                db.add(new_pack)
                
        await db.commit()
        logger.info(f"Synced {len(packs_data)} built-in domain packs.")

    @staticmethod
    async def get_available_packs(db: AsyncSession) -> List[DomainPack]:
        """Returns all active domain packs from the catalog."""
        q = await db.execute(select(DomainPack).where(DomainPack.status == "ACTIVE"))
        return list(q.scalars().all())

    @staticmethod
    async def install_pack(db: AsyncSession, pack_id: str, tenant_id: str) -> DomainPackInstallation:
        """Records that a tenant has installed a pack."""
        # Check if pack exists
        q = await db.execute(select(DomainPack).where(DomainPack.id == pack_id))
        pack = q.scalar_one_or_none()
        
        if not pack:
            raise ValueError(f"Domain pack {pack_id} not found")
            
        # Check if already installed
        q_inst = await db.execute(
            select(DomainPackInstallation)
            .where(DomainPackInstallation.tenant_id == tenant_id)
            .where(DomainPackInstallation.domain_pack_id == pack_id)
        )
        existing = q_inst.scalar_one_or_none()
        
        if existing:
            return existing
            
        # Create installation record
        installation = DomainPackInstallation(
            tenant_id=tenant_id,
            domain_pack_id=pack_id,
            installed_version=pack.version,
            status=InstallationStatus.INSTALLED
        )
        db.add(installation)
        
        # Increment install count
        pack.install_count += 1
        
        await db.commit()
        await db.refresh(installation)
        
        logger.info(f"Tenant {tenant_id} installed domain pack {pack.slug} (v{pack.version})")
        return installation
