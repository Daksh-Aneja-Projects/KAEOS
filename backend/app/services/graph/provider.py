"""
KAEOS Enterprise Graph Abstraction Layer
Defines the interface for Graph storage providers.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any

class GraphProvider(ABC):
    
    @abstractmethod
    async def connect(self):
        """Establish connection to graph database."""
        pass
        
    @abstractmethod
    async def disconnect(self):
        """Close connection to graph database."""
        pass

    @abstractmethod
    async def create_node(self, label: str, properties: Dict[str, Any]) -> str:
        """Create a node and return its ID."""
        pass

    @abstractmethod
    async def update_node(self, node_id: str, label: str, properties: Dict[str, Any]) -> None:
        """Update node properties."""
        pass
        
    @abstractmethod
    async def delete_node(self, node_id: str, label: str) -> None:
        """Delete a node."""
        pass

    @abstractmethod
    async def create_relationship(self, source_id: str, target_id: str, rel_type: str, properties: Dict[str, Any] = None) -> None:
        """Create a directed relationship between two nodes."""
        pass

    @abstractmethod
    async def traverse_dependencies(self, node_id: str, max_depth: int = 3) -> List[Dict[str, Any]]:
        """Traverse upstream dependencies."""
        pass
        
    @abstractmethod
    async def traverse_impact(self, node_id: str, max_depth: int = 3) -> List[Dict[str, Any]]:
        """Traverse downstream impact (blast radius)."""
        pass
