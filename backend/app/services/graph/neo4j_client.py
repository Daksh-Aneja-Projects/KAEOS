"""
KAEOS Graph Provider Implementation (In-Memory Fallback)
Automatically engaged to ensure execution stability when Docker/Neo4j is absent.
"""

import json
import os
import logging
from typing import List, Dict, Any
from app.services.graph.provider import GraphProvider

logger = logging.getLogger(__name__)

GRAPH_FILE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../artifacts/enterprise_graph.json"))

class Neo4jGraphProvider(GraphProvider):
    def __init__(self, uri: str = None, user: str = None, password: str = None):
        self.nodes = {}  # id -> dict
        self.edges = []  # {source, target, type, props}
        
    def load(self):
        if os.path.exists(GRAPH_FILE_PATH):
            try:
                with open(GRAPH_FILE_PATH, "r") as f:
                    data = json.load(f)
                    self.nodes = data.get("nodes", {})
                    self.edges = data.get("edges", [])
                logger.info(f"Loaded {len(self.nodes)} nodes and {len(self.edges)} edges from disk.")
            except Exception as e:
                logger.error(f"Failed to load graph: {e}")

    def save(self):
        try:
            os.makedirs(os.path.dirname(GRAPH_FILE_PATH), exist_ok=True)
            with open(GRAPH_FILE_PATH, "w") as f:
                json.dump({"nodes": self.nodes, "edges": self.edges}, f)
        except Exception as e:
            logger.error(f"Failed to save graph: {e}")
        
    async def connect(self):
        logger.info("Connected to In-Memory Graph Provider (Fallback Mode).")
        self.load()

    async def disconnect(self):
        logger.info("Disconnected from In-Memory Graph Provider.")

    async def create_node(self, label: str, properties: Dict[str, Any]) -> str:
        node_id = properties.get("id") or str(len(self.nodes))
        self.nodes[node_id] = {"id": node_id, "label": label, **properties}
        return node_id

    async def update_node(self, node_id: str, label: str, properties: Dict[str, Any]) -> None:
        if node_id in self.nodes:
            self.nodes[node_id].update(properties)

    async def delete_node(self, node_id: str, label: str) -> None:
        if node_id in self.nodes:
            del self.nodes[node_id]
        self.edges = [e for e in self.edges if e["source"] != node_id and e["target"] != node_id]

    async def create_relationship(self, source_id: str, target_id: str, rel_type: str, properties: Dict[str, Any] = None) -> None:
        props = properties or {}
        self.edges.append({"source": source_id, "target": target_id, "type": rel_type, "props": props})

    async def traverse_dependencies(self, node_id: str, max_depth: int = 3) -> List[Dict[str, Any]]:
        """Mock traversing dependencies TO this node."""
        results = []
        for e in self.edges:
            if e["target"] == node_id:
                upstream = self.nodes.get(e["source"])
                if upstream:
                    results.append({"upstream": upstream, "path_nodes": [upstream, self.nodes.get(node_id)], "path_rels": [{"type": e["type"]}]})
        return results

    async def traverse_impact(self, node_id: str, max_depth: int = 3) -> List[Dict[str, Any]]:
        """Traversing downstream blast radius using BFS."""
        results = []
        # queue stores tuples of (current_node_id, current_path_nodes, current_path_rels)
        # We also track visited nodes to avoid cycles
        
        start_node = self.nodes.get(node_id)
        if not start_node:
            return results
            
        queue = [(node_id, [start_node], [])]
        visited = set([node_id])
        
        while queue:
            curr_id, p_nodes, p_rels = queue.pop(0)
            
            # Stop if we reach max_depth. Number of edges is len(p_nodes) - 1.
            # We want to explore outgoing edges from curr_id if depth allows.
            if len(p_nodes) - 1 >= max_depth:
                continue
                
            for e in self.edges:
                if e["source"] == curr_id:
                    target_id = e["target"]
                    if target_id not in visited: # Cycle detection
                        visited.add(target_id)
                        target_node = self.nodes.get(target_id)
                        if target_node:
                            new_p_nodes = p_nodes + [target_node]
                            new_p_rels = p_rels + [{"type": e["type"]}]
                            
                            results.append({
                                "downstream": target_node,
                                "path_nodes": new_p_nodes,
                                "path_rels": new_p_rels
                            })
                            
                            queue.append((target_id, new_p_nodes, new_p_rels))
                            
        return results
