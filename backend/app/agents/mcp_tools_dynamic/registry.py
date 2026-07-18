import logging
from typing import Dict, Any, Callable
from app.services.sandbox import SandboxExecutor

logger = logging.getLogger(__name__)

class MCPToolRegistry:
    """Manages dynamic skill tools and MCP external integrations."""
    
    def __init__(self):
        # Maps tool name to a schema definition
        self.tools = {}
        # Pre-register some safe standard tools
        self.register_local_tool(
            name="calculator",
            description="Evaluates a basic math expression securely.",
            func=self._tool_calculator
        )
        self.register_local_tool(
            name="python_sandbox",
            description="Executes arbitrary python code safely and returns the output. The code must print() the result.",
            func=self._tool_python_sandbox
        )
        
    def register_local_tool(self, name: str, description: str, func: Callable):
        self.tools[name] = {
            "name": name,
            "description": description,
            "type": "local",
            "func": func
        }
        logger.info(f"Registered MCP tool: {name}")

    async def execute_tool(self, name: str, params: Dict[str, Any]) -> str:
        if name not in self.tools:
            return f"Error: Tool '{name}' not found in registry."
            
        tool = self.tools[name]
        try:
            if tool["type"] == "local":
                return await tool["func"](**params)
            else:
                return f"Error: Tool type '{tool['type']}' unsupported."
        except Exception as e:
            return f"Error executing '{name}': {e}"

    # --- Built-in Local Tools ---
    
    async def _tool_calculator(self, expression: str = "") -> str:
        if not expression:
            return "Error: no expression provided."
        # Secure calculator using sandbox
        code = f"import math\nprint({expression})"
        success, out = await SandboxExecutor.execute(code, timeout_seconds=2)
        return out if success else f"Calculator error: {out}"
        
    async def _tool_python_sandbox(self, code: str = "") -> str:
        if not code:
            return "Error: no code provided."
        success, out = await SandboxExecutor.execute(code, timeout_seconds=5)
        return out if success else f"Sandbox execution error: {out}"
