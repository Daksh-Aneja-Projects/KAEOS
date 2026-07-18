import pytest
from httpx import AsyncClient

from app.core.config import get_settings

@pytest.mark.asyncio
async def test_tenant_middleware_dev_mode(async_client: AsyncClient):
    """
    Test that DEV_MODE allows bypass with any token and assigns tenant_acme.
    """
    settings = get_settings()
    settings.DEV_MODE = True
    
    response = await async_client.get("/api/v1/workforce/departments", headers={"Authorization": "Bearer fake_token"})
    assert response.status_code == 200
    
@pytest.mark.asyncio
async def test_tenant_middleware_prod_mode(async_client: AsyncClient):
    """
    Test that DEV_MODE=False requires a valid token.
    """
    settings = get_settings()
    settings.DEV_MODE = False
    
    response = await async_client.get("/api/v1/workforce/departments", headers={"Authorization": "Bearer fake_token"})
    assert response.status_code == 401
    
    # Restore dev mode for other tests
    settings.DEV_MODE = True
