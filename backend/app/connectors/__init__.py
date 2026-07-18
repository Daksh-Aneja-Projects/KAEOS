"""
KAEOS L0 — Connector Registry (merged from Extract-OS)
"""
from app.connectors.base import BaseConnector

CONNECTOR_REGISTRY: dict[str, type[BaseConnector]] = {}


def register_connector(slug: str, cls: type[BaseConnector]):
    CONNECTOR_REGISTRY[slug] = cls


def get_connector_class(slug: str) -> type[BaseConnector]:
    # Lazy-load to avoid circular imports
    if not CONNECTOR_REGISTRY:
        from app.connectors.csv_connector import CSVConnector
        from app.connectors.rest_api_connector import RESTAPIConnector
        CONNECTOR_REGISTRY["csv"] = CSVConnector
        CONNECTOR_REGISTRY["rest_api"] = RESTAPIConnector

    cls = CONNECTOR_REGISTRY.get(slug)
    if not cls:
        raise ValueError(f"Unknown connector: {slug}. Available: {list(CONNECTOR_REGISTRY.keys())}")
    return cls
