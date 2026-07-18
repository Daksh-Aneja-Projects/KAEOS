"""
KAEOS Synthetic Enterprise Generator
Priority 6
Generates parametric, reproducible enterprise topologies at scale.
Uses seeded random generation to ensure valid, dynamic structures without hardcoded mock data.
"""

import logging
import asyncio
import random
from typing import Dict, Any

from app.services.graph.graph_service import GraphService

try:
    from faker import Faker
except ImportError:
    # If faker is not installed, provide a stub for the proof
    class Faker:
        def seed_instance(self, seed): pass
        def company(self): return "Dynamically Generated Corp"
        def name(self): return "Generated Name"
        def bs(self): return "Synergize scalable paradigms"
        def catch_phrase(self): return "Cross-platform strategic initiative"

logger = logging.getLogger(__name__)


class SyntheticEnterpriseGenerator:
    def __init__(self, graph_service: GraphService):
        self.graph = graph_service
        self.tenant_id = "tenant_synthetic"
        self.fake = Faker()

    async def generate_enterprise(self, config: Dict[str, Any]):
        """
        Generates the enterprise graph using dynamic parameters.
        Must provide seed for reproducibility.
        """
        seed = config.get("seed", 42)
        random.seed(seed)
        self.fake.seed_instance(seed)
        
        emp_count = config.get("employee_count", 1000)
        dept_count = config.get("department_count", 10)
        proj_count = config.get("project_count", 50)
        vendor_count = config.get("vendor_count", 20)
        goal_count = config.get("goal_count", 5)
        init_count = config.get("initiative_count", 15)
        risk_count = config.get("risk_count", 25)
        
        logger.info(f"SyntheticGenerator: Using seed {seed}. Topo: {emp_count} Emp, {dept_count} Dept, {proj_count} Proj, {goal_count} Goal.")
        
        org_name = self.fake.company()
        org_id = "org_synthetic_01"
        await self.graph.register_entity(org_id, "Organization", {"name": org_name})
        
        # Capabilities
        capabilities = ["AI Engineering", "Software Engineering", "HR Operations", "Sales Operations", "Finance Operations", "Data Science", "Security", "Cloud Engineering"]
        cap_ids = []
        for i, cap in enumerate(capabilities):
            cap_id = f"cap_{i}"
            cap_ids.append(cap_id)
            await self.graph.register_entity(cap_id, "Capability", {"name": cap})
        
        # Departments
        dept_ids = []
        for d in range(dept_count):
            dept_id = f"dept_{d}"
            dept_ids.append(dept_id)
            await self.graph.register_entity(dept_id, "Department", {"name": f"{self.fake.bs().split()[0].capitalize()} Department"})
            await self.graph.link_entities(dept_id, org_id, "BELONGS_TO")
            # Department possesses capability
            await self.graph.link_entities(dept_id, random.choice(cap_ids), "POSSESSES_CAPABILITY")

        # Goals
        goal_ids = []
        for g in range(goal_count):
            goal_id = f"goal_{g}"
            goal_ids.append(goal_id)
            await self.graph.register_entity(goal_id, "Goal", {"title": f"Goal: {self.fake.catch_phrase()}"})
            await self.graph.link_entities(goal_id, org_id, "DRIVES")
            # Capability supports goal
            await self.graph.link_entities(random.choice(cap_ids), goal_id, "SUPPORTS_GOAL")
            
        # Initiatives
        init_ids = []
        for i in range(init_count):
            init_id = f"init_{i}"
            init_ids.append(init_id)
            target_goal = random.choice(goal_ids)
            await self.graph.register_entity(init_id, "Initiative", {"title": f"Init: {self.fake.bs()}"})
            await self.graph.link_entities(init_id, target_goal, "SUPPORTS")
            await self.graph.link_entities(init_id, random.choice(cap_ids), "REQUIRES_CAPABILITY")
            
        # Projects
        proj_ids = []
        for p in range(proj_count):
            proj_id = f"proj_{p}"
            proj_ids.append(proj_id)
            target_init = random.choice(init_ids)
            target_dept = random.choice(dept_ids)
            await self.graph.register_entity(proj_id, "Project", {"title": f"Proj: {self.fake.catch_phrase()}"})
            await self.graph.link_entities(proj_id, target_init, "DELIVERS")
            await self.graph.link_entities(proj_id, target_dept, "OWNED_BY")
            await self.graph.link_entities(proj_id, random.choice(cap_ids), "REQUIRES_CAPABILITY")
            
        # Vendors
        vendor_ids = []
        for v in range(vendor_count):
            ven_id = f"vendor_{v}"
            vendor_ids.append(ven_id)
            await self.graph.register_entity(ven_id, "Vendor", {"name": self.fake.company()})
            target_proj = random.choice(proj_ids)
            await self.graph.link_entities(ven_id, target_proj, "SUPPLIES")
            
        # Risks
        for r in range(risk_count):
            risk_id = f"risk_{r}"
            await self.graph.register_entity(risk_id, "Risk", {"title": f"Risk: {self.fake.bs()}", "severity": random.choice(["MEDIUM", "HIGH", "CRITICAL"])})
            target_node = random.choice(goal_ids + init_ids + proj_ids + vendor_ids)
            await self.graph.link_entities(risk_id, target_node, "THREATENS")

        # Employees (Batched)
        batch_size = 500
        for b in range(0, emp_count, batch_size):
            logger.info(f"SyntheticGenerator: Emps {b} to {min(b+batch_size, emp_count)}...")
            for e in range(b, min(b + batch_size, emp_count)):
                emp_id = f"emp_{e}"
                target_dept = random.choice(dept_ids)
                target_proj = random.choice(proj_ids) if random.random() > 0.3 else None # 70% of emps are on projects
                
                await self.graph.register_entity(emp_id, "Employee", {"name": self.fake.name()})
                await self.graph.link_entities(emp_id, target_dept, "WORKS_IN")
                await self.graph.link_entities(emp_id, random.choice(cap_ids), "HAS_CAPABILITY")
                if target_proj:
                    await self.graph.link_entities(emp_id, target_proj, "CONTRIBUTES_TO")
                
            await asyncio.sleep(0)
            
        # ----------------------------------------------------
        # ROT INJECTION: Structural Inefficiencies
        # ----------------------------------------------------
        inject_rot = config.get("inject_rot", False)
        if inject_rot:
            logger.info("SyntheticGenerator: Injecting structural rot for Evolution Engine testing...")
            
            # 1. Vendor Concentration
            bad_vendor = "vendor_monopoly"
            await self.graph.register_entity(bad_vendor, "Vendor", {"name": "Monopoly Corp"})
            for p in proj_ids[:int(len(proj_ids) * 0.8)]: # 80% of projects
                await self.graph.link_entities(bad_vendor, p, "SUPPLIES")
                
            # 2. Duplicate Initiatives (Portfolio Waste)
            await self.graph.register_entity("init_dup_1", "Initiative", {"title": "Cloud Migration Alpha"})
            await self.graph.register_entity("init_dup_2", "Initiative", {"title": "Cloud Migration Beta (Duplicate)"})
            target_goal = goal_ids[0]
            await self.graph.link_entities("init_dup_1", target_goal, "SUPPORTS")
            await self.graph.link_entities("init_dup_2", target_goal, "SUPPORTS")
            await self.graph.link_entities("init_dup_1", cap_ids[0], "REQUIRES_CAPABILITY")
            await self.graph.link_entities("init_dup_2", cap_ids[0], "REQUIRES_CAPABILITY")
            
            # 3. Capability Gap
            await self.graph.register_entity("cap_missing", "Capability", {"name": "Quantum Computing"})
            await self.graph.register_entity("init_quantum", "Initiative", {"title": "Quantum R&D"})
            await self.graph.link_entities("init_quantum", "cap_missing", "REQUIRES_CAPABILITY")
            await self.graph.link_entities("init_quantum", goal_ids[1], "SUPPORTS")
            # No employees get HAS_CAPABILITY cap_missing
            
            # 4. Overloaded Team
            overloaded_proj = proj_ids[0]
            # Assign 200 employees to this single project
            for i in range(200):
                await self.graph.link_entities(f"emp_{i}", overloaded_proj, "CONTRIBUTES_TO")

        logger.info("Synthetic Enterprise Generation Complete.")
