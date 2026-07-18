"""
KAEOS Enterprise Graph Service
High-level service for interacting with the Enterprise Graph using the active provider.
"""

from typing import List, Dict, Any
from app.services.graph.provider import GraphProvider
from app.services.graph.neo4j_client import Neo4jGraphProvider

class GraphService:
    def __init__(self, provider: GraphProvider = None):
        # Default to Neo4j, but can be swapped out
        self.provider = provider or Neo4jGraphProvider()

    async def initialize(self):
        await self.provider.connect()
        
    async def shutdown(self):
        await self.provider.disconnect()

    async def register_entity(self, entity_id: str, label: str, properties: Dict[str, Any]):
        """Registers a node in the graph. Properties must include 'id'."""
        props = properties.copy()
        props["id"] = entity_id
        await self.provider.create_node(label, props)
        
    async def update_entity(self, entity_id: str, label: str, properties: Dict[str, Any]):
        """Updates a node in the graph."""
        await self.provider.update_node(entity_id, label, properties)

    async def link_entities(self, source_id: str, target_id: str, relation: str, properties: Dict[str, Any] = None):
        """Creates a relationship between two entities."""
        await self.provider.create_relationship(source_id, target_id, relation, properties)

    async def get_impact_radius(self, entity_id: str, depth: int = 3) -> List[Dict[str, Any]]:
        """Calculates downstream impact (blast radius)."""
        return await self.provider.traverse_impact(entity_id, depth)
        
    async def get_dependencies(self, entity_id: str, depth: int = 3) -> List[Dict[str, Any]]:
        """Calculates upstream dependencies."""
        return await self.provider.traverse_dependencies(entity_id, depth)
