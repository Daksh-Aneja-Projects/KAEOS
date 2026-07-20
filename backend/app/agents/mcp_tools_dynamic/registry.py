import logging
from typing import Dict, Any, Callable, Optional, Set
from app.services.sandbox import SandboxExecutor
from app.core.config import get_settings

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
        # SECURITY / prompt-injection: `python_sandbox` executes arbitrary Python.
        # Untrusted content (support tickets, resumes, contract text, connector
        # signals) is interpolated into prompts whose JSON output drives tool
        # calls. An injected instruction that reaches this tool is remote code
        # execution reachable by ANY tenant agent. We therefore DO NOT register
        # it unless an operator has explicitly opted in via config. Default
        # (flag False / absent) => the arbitrary-code tool does not exist in the
        # registry and cannot be invoked. The `calculator` tool (a constrained,
        # short-timeout math evaluator) remains available as a safe alternative.
        if getattr(get_settings(), "ENABLE_PYTHON_SANDBOX_TOOL", False):
            logger.warning(
                "ENABLE_PYTHON_SANDBOX_TOOL is True — registering arbitrary-code "
                "'python_sandbox' tool. This is a prompt-injection RCE surface; "
                "ensure tool allowlists restrict which tenants can reach it."
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

    async def execute_tool(
        self,
        name: str,
        params: Dict[str, Any],
        tenant_id: Optional[str] = None,
        allowed_tools: Optional[Set[str]] = None,
    ) -> str:
        """Execute a registered tool by name.

        Args:
            name: tool name selected (possibly by an LLM whose prompt contained
                untrusted content — treat as adversarial).
            params: keyword params for the tool.
            tenant_id: caller identity, threaded through for logging/attribution
                and so future per-tenant policy can key off it.
            allowed_tools: optional per-tenant allowlist. When provided, any tool
                NOT in the set is refused (a clear message is returned, the tool
                is NOT executed). When None, behavior is backward-compatible:
                every registered tool is callable (minus the now-gated sandbox,
                which is simply not registered by default).
        """
        # Per-tenant tool scoping: refuse anything outside the allowlist BEFORE
        # touching the registry, so a compromised/injected tool choice cannot
        # execute even if the tool exists.
        if allowed_tools is not None and name not in allowed_tools:
            logger.warning(
                f"Tool '{name}' not permitted for tenant '{tenant_id}' "
                f"(allowlist={sorted(allowed_tools)}). Refusing execution."
            )
            return (
                f"Error: Tool '{name}' is not permitted for this tenant. "
                f"Permitted tools: {sorted(allowed_tools)}."
            )

        if name not in self.tools:
            return f"Error: Tool '{name}' not found in registry."

        # Defensive: params must be a mapping we can splat as kwargs. An LLM
        # (or injected content) can emit a list/str/number here.
        if not isinstance(params, dict):
            logger.warning(
                f"Tool '{name}' called with non-dict params of type "
                f"{type(params).__name__} for tenant '{tenant_id}'. Refusing."
            )
            return f"Error: Tool '{name}' requires a JSON object of parameters."

        tool = self.tools[name]
        try:
            if tool["type"] == "local":
                logger.info(f"Executing tool '{name}' for tenant '{tenant_id}'")
                return await tool["func"](**params)
            else:
                return f"Error: Tool type '{tool['type']}' unsupported."
        except TypeError as e:
            # Unexpected/misnamed kwargs from adversarial params land here.
            logger.warning(f"Tool '{name}' rejected params for tenant '{tenant_id}': {e}")
            return f"Error executing '{name}': invalid parameters ({e})"
        except Exception as e:
            return f"Error executing '{name}': {e}"

    def is_registered(self, name: str) -> bool:
        """True if `name` is a currently registered tool. Used by callers to
        validate an LLM-chosen tool name before dispatch."""
        return name in self.tools

    def tool_names(self) -> Set[str]:
        """Set of currently registered tool names."""
        return set(self.tools.keys())

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
