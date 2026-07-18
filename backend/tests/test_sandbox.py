import pytest
from app.services.sandbox import SandboxExecutor

@pytest.mark.asyncio
async def test_sandbox_safe_code():
    success, out = await SandboxExecutor.execute("print('Hello from sandbox!')")
    assert success is True
    assert "Hello from sandbox!" in out

@pytest.mark.asyncio
async def test_sandbox_dangerous_import():
    success, out = await SandboxExecutor.execute("import os\nprint(os.getcwd())")
    assert success is False
    assert "Importing 'os' is forbidden" in out

@pytest.mark.asyncio
async def test_sandbox_timeout():
    # Will timeout after 1 second
    success, out = await SandboxExecutor.execute("while True: pass", timeout_seconds=1)
    assert success is False
    assert "Execution timed out" in out or "error" in out.lower()
