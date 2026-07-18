import logging
from typing import Dict, Any
from app.api.parsers.workday_parser import WorkdayEventParser
from app.api.mappers.neo4j_mapper import Neo4jMutationMapper

logger = logging.getLogger(__name__)

class EventIngestionGateway:
    def __init__(self):
        self.workday_parser = WorkdayEventParser()
        self.neo4j_mapper = Neo4jMutationMapper()
        
    def process_webhook(self, source: str, raw_payload: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"EventIngestionGateway: Received webhook from {source}")
        
        if source == "Workday":
            canonical = self.workday_parser.parse(raw_payload)
            mutations = self.neo4j_mapper.generate_mutations(canonical)
            return {
                "canonical_payload": canonical,
                "mutations": mutations
            }
        else:
            raise NotImplementedError(f"Source {source} not supported yet.")
