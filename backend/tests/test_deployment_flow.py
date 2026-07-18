import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_deployment_flow_syntax(async_client: AsyncClient):
    """
    Test the deployment flow endpoint to ensure it doesn't fail with a SyntaxError.
    This implicitly validates that workforce_generator.py compiles correctly.
    """
    # Assuming the API requires authentication, we provide a valid dev header
    # or just make a request and assert it's not a 500 SyntaxError.
    
    response = await async_client.post(
        "/api/v1/workforce/deployments",
        json={
            "department": "hr",
            "capabilities": ["recruiting", "onboarding"],
            "compliance_level": "strict"
        },
        headers={"Authorization": "Bearer dev_token"} # Since DEV_MODE=True, this will bypass and get tenant_acme
    )
    
    # We expect a 200 or 201 or 400 (validation), but NOT a 500 SyntaxError
    assert response.status_code in [200, 201, 202, 307, 400, 422], f"Deployment failed: {response.text}"
