"""
KAEOS Impact Propagation Engine
Phase 4: Impact Engine + Causal Intelligence (Phase 3 of Proof)
Uses the Enterprise Graph (Neo4j) to trace the blast radius of Universal Events.
Translates heuristic distance scoring into semantic Causal Chains.
"""

import logging
from typing import List, Dict, Any

from app.services.graph.graph_service import GraphService
from app.services.llm_router import LLMRouter

logger = logging.getLogger(__name__)


class ImpactPropagationEngine:
    
    def __init__(self, graph_service: GraphService):
        self.graph = graph_service
        self.router = LLMRouter()
    
    async def propagate_impact(self, event_type: str, source_entity_id: str, depth: int = 3) -> Dict[str, Any]:
        """
        Calculates the blast radius of an event across the Enterprise Graph.
        Returns semantic Causal Chains.
        """
        logger.info(f"ImpactEngine: Calculating causal blast radius for {source_entity_id} (Event: {event_type})")
        
        # 1. Ask GraphService for downstream impacts
        impacts = await self.graph.get_impact_radius(source_entity_id, depth)
        
        # 2. Extract semantic causal chains
        causal_chains = await self._generate_causal_chains(event_type, source_entity_id, impacts)
        
        # 3. Analyze for critical risks
        critical_cascades = [c for c in causal_chains if c.get("confidence", 0) > 0.8 and c.get("severity") == "CRITICAL"]
        
        return {
            "source": source_entity_id,
            "event_type": event_type,
            "causal_chains": causal_chains,
            "critical_risks": critical_cascades
        }

    async def _generate_causal_chains(self, event_type: str, root_id: str, raw_paths: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Processes exact paths from the Graph Service without injecting fake narratives.
        Returns a structured causal payload.
        """
        chains = []
        for path in raw_paths:
            downstream_node = path.get("downstream", {})
            nodes = path.get("path_nodes", [])
            rels = path.get("path_rels", [])
            
            node_ids = [n.get("id", "Unknown") for n in nodes]
            node_labels = [n.get("name", n.get("id", "Unknown")) for n in nodes]
            rel_types = [r.get("type", "UNKNOWN") for r in rels]
            
            # Reconstruct the exact path structure
            path_sequence = []
            for i in range(len(nodes) - 1):
                path_sequence.append(node_labels[i])
                path_sequence.append(f"({rel_types[i]})")
            path_sequence.append(node_labels[-1])
            
            path_str = " -> ".join(path_sequence)
            
            target_id = downstream_node.get("id", "")
            target_name = downstream_node.get("name", target_id)
            distance = len(nodes) - 1
            
            target_category = "Unknown"
            if "labels" in downstream_node and downstream_node["labels"]:
                target_category = downstream_node["labels"][0]
            elif "_" in target_id:
                # Dynamic fallback: prefix mapping (e.g. 'emp_1' -> 'Emp')
                target_category = target_id.split("_")[0].capitalize()
                
            # Strict mapping without fake logic
            chains.append({
                "target_node_id": target_id,
                "target_node_name": target_name,
                "target_category": target_category,
                "root_cause_id": root_id,
                "hops": distance,
                "causal_path": path_str,
                "path_nodes": node_ids,
                "path_rels": rel_types
            })
            
        return chains

    async def get_root_cause_analysis(self, impacted_entity_id: str, depth: int = 3) -> List[Dict[str, Any]]:
        """
        Traverses upstream to find potential root causes of an issue at this node.
        """
        dependencies = await self.graph.get_dependencies(impacted_entity_id, depth)
        return dependencies
