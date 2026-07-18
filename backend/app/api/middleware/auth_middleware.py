import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class AzureADOIDCMiddleware:
    def __init__(self):
        self.public_keys = "mock_keys"

    def validate_token(self, token: str) -> Dict[str, Any]:
        """Validates token and returns execution context claims."""
        logger.info("AzureADOIDCMiddleware: Validating JWT signature.")
        # In a real app, this parses JWT. Here we mock parsing for the pilot.
        if token == "mock_valid_jwt":
            return {
                "sub": "user_123",
                "roles": ["HRBP", "Executive"],
                "tenant_id": "mock_tenant_01"
            }
        raise Exception("Invalid Token")

    def create_execution_context(self, token: str) -> Dict[str, Any]:
        claims = self.validate_token(token)
        return {
            "actor_id": claims["sub"],
            "actor_role": claims["roles"][0],
            "auth_status": "AUTHENTICATED"
        }
