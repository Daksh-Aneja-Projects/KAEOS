"""
KAEOS 10X — Polymorphic Engine (L21)
Autonomous Generation and Compilation of MCP Tool Bindings
"""
import logging
import ast
from datetime import datetime, timezone
import os

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.domain import Skill

logger = logging.getLogger(__name__)

class DynamicTool:
    def __init__(self, name: str, source_code: str, status: str):
        self.name = name
        self.source_code = source_code
        self.status = status


class PolymorphicEngine:
    """
    Writes and registers its own code if a required integration is missing.
    """

    @staticmethod
    async def _generate_tool_code(intent: str, integration_name: str) -> str:
        """
        Dynamically generates python code for an MCP tool binding using the LLM Router.
        """
        class_name = "".join(x.capitalize() or "_" for x in integration_name.split("_"))
        
        from app.services.llm_router import LLMRouter
        router = LLMRouter()
        
        prompt = f"""You are the KAEOS Polymorphic Engine.
Write a production-ready Python MCP Tool class named {class_name}Tool for integration: {integration_name}.
Intent: {intent}
Ensure it has an async execute(self, payload: dict) method and uses httpx for API calls. 
Include rigorous error handling and logging. Output strictly the python code. No markdown formatting."""
        
        try:
            response = await router.complete(prompt=prompt, model_tier="fast")
            raw = response if isinstance(response, str) else response.get("content", "")
            code = raw.replace("```python", "").replace("```", "").strip()
            return code
        except Exception as e:
            logger.error(f"Polymorphic LLM generation failed: {e}")
            raise ValueError(f"Failed to synthesize code for {integration_name}")

    @staticmethod
    def validate_syntax(source_code: str) -> bool:
        """Parses the generated code into an AST to ensure basic validity before deployment."""
        try:
            ast.parse(source_code)
            return True
        except SyntaxError as e:
            logger.error(f"Polymorphic syntax error: {e}")
            return False

    @staticmethod
    def _scan_findings(source_code: str) -> list[str]:
        """Real AST scan for dangerous constructs in a generated tool module.

        Returns a list of human-readable findings (empty == clean). This walks the
        AST rather than substring-matching, so it also catches attribute-traversal
        escapes (``().__class__.__bases__[0].__subclasses__()``) that the previous
        name-only blocklist let straight through. It reuses the sandbox's
        ``_FORBIDDEN_ATTRS`` set (the same one that hardens ``SandboxExecutor``).

        Note: unlike ``SandboxExecutor.validate_ast`` (built for tiny sandboxed
        snippets, which forbids ALL imports outside a 9-module allowlist and blocks
        ``super``/``type``/``staticmethod`` …), this scan is tuned for full MCP tool
        MODULES that legitimately ``import httpx`` and define classes — so it flags
        genuine RCE/FS/introspection escapes without rejecting normal module code.
        """
        from app.services.sandbox import _FORBIDDEN_ATTRS

        # Dotted-call prefixes that are RCE / filesystem-destruction vectors.
        _DANGEROUS_DOTTED = (
            "os.system", "os.popen", "os.exec", "os.spawn", "os.remove",
            "os.rmdir", "os.unlink", "os.putenv", "subprocess.", "pty.spawn",
            "shutil.rmtree",
        )
        # Bare builtins that enable dynamic code / arbitrary FS / introspection.
        _DANGEROUS_NAMES = {
            "eval", "exec", "compile", "open", "__import__",
            "getattr", "setattr", "delattr", "globals", "locals", "vars",
        }

        try:
            tree = ast.parse(source_code)
        except SyntaxError as e:
            return [f"unparseable source: {e}"]

        def _dotted(node: ast.AST) -> str:
            parts = []
            while isinstance(node, ast.Attribute):
                parts.append(node.attr)
                node = node.value
            if isinstance(node, ast.Name):
                parts.append(node.id)
            return ".".join(reversed(parts))

        findings: list[str] = []
        for node in ast.walk(tree):
            # Attribute-traversal / introspection escapes. We match the sandbox's
            # curated _FORBIDDEN_ATTRS set (which covers the full __class__ ->
            # __bases__ -> __subclasses__ -> __globals__ chain) rather than every
            # dunder, so benign method dunders a real tool class needs
            # (__init__, __aenter__, __aexit__, __call__ …) are not false-flagged.
            if isinstance(node, ast.Attribute):
                if node.attr in _FORBIDDEN_ATTRS:
                    findings.append(f"forbidden attribute access '.{node.attr}'")
            # Dangerous calls (name-level and dotted).
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in _DANGEROUS_NAMES:
                    findings.append(f"call to dangerous builtin '{func.id}(...)'")
                elif isinstance(func, ast.Attribute):
                    dotted = _dotted(func)
                    if any(dotted.startswith(p) for p in _DANGEROUS_DOTTED):
                        findings.append(f"call to dangerous api '{dotted}(...)'")
        return findings

    @staticmethod
    async def _sandbox_execution_scan(source_code: str, integration_name: str) -> bool:
        """
        Runs the generated code through an AST safety scanner to prevent injection of malicious syscalls.
        Returns True ONLY if the scan finds no dangerous constructs; False (with the
        findings logged) otherwise — the PASS is no longer unconditional.
        """
        logger.info(f"Running L12 Red Team Sandbox Scan on dynamic tool '{integration_name}'...")

        findings = PolymorphicEngine._scan_findings(source_code)
        if findings:
            logger.warning(
                "Red Team Sandbox Scan: FAILED for '%s' — %d finding(s): %s",
                integration_name, len(findings), "; ".join(findings),
            )
            return False

        logger.info(
            "Red Team Sandbox Scan: PASSED for '%s' (0 dangerous constructs detected via AST)",
            integration_name,
        )
        return True

    @staticmethod
    async def synthesize_tool(intent: str, integration_name: str) -> DynamicTool:
        """
        Full polymorphic workflow: Generates, Validates, Sandbox Scans, and Deploys.
        """
        logger.info(f"Initiating Polymorphic Synthesis for '{integration_name}' based on intent: '{intent}'")
        
        # 1. Generate Code via LLM
        code = await PolymorphicEngine._generate_tool_code(intent, integration_name)
        
        # 2. Safety/Syntax Check
        if not PolymorphicEngine.validate_syntax(code):
            return DynamicTool(name=integration_name, source_code=code, status="FAILED_SYNTAX_CHECK")
            
        # 3. L12 Red Team Sandbox Scan
        is_safe = await PolymorphicEngine._sandbox_execution_scan(code, integration_name)
        if not is_safe:
            return DynamicTool(name=integration_name, source_code=code, status="FAILED_SANDBOX_SCAN")
            
        # 4. Write to Disk
        tool_dir = os.path.join(os.path.dirname(__file__), "..", "agents", "mcp_tools_dynamic")
        os.makedirs(tool_dir, exist_ok=True)

        file_path = os.path.join(tool_dir, f"{integration_name}.py")
        # NEVER overwrite an existing tool: a name collision must not let
        # generated code clobber committed source (observed live - an e2e run
        # overwrote legacy_erp_bridge.py). Regenerating a tool requires an
        # explicit delete first.
        if os.path.exists(file_path):
            logger.warning(
                f"Tool file {integration_name}.py already exists - refusing to overwrite"
            )
            return DynamicTool(
                name=integration_name, source_code=code, status="REFUSED_EXISTING_FILE"
            )
        with open(file_path, "w") as f:
            f.write(code)
            
        logger.info(f"Tool {integration_name} synthesized, verified, and written to {file_path}")
        
        # 5. Return status
        return DynamicTool(name=integration_name, source_code=code, status="DEPLOYED_AND_ACTIVE")
        
    @staticmethod
    async def auto_patch_skill(db: AsyncSession, skill_id: str, missing_integration: str, tenant_id: str | None = None):
        """
        If a skill fails because an integration is missing, this function will automatically
        write the tool and patch the skill's dependencies.
        """
        stmt = select(Skill).where(Skill.skill_id == skill_id)
        if tenant_id is not None:
            stmt = stmt.where(Skill.tenant_id == tenant_id)
        skill_q = await db.execute(stmt)
        skill = skill_q.scalar_one_or_none()
        
        if not skill:
            raise ValueError(f"Skill {skill_id} not found.")
            
        # Synthesize the missing piece
        tool = await PolymorphicEngine.synthesize_tool(
            intent=f"Required by {skill_id} to perform automated tasks",
            integration_name=missing_integration
        )
        
        if tool.status == "DEPLOYED_AND_ACTIVE":
            # Patch the DB record
            updated_bindings = list(skill.mcp_tool_bindings)
            if missing_integration not in updated_bindings:
                updated_bindings.append(missing_integration)
            
            skill.mcp_tool_bindings = updated_bindings
            
            # Log the polymorphic event
            if "polymorphic_events" not in skill.guardrails:
                skill.guardrails["polymorphic_events"] = []
                
            skill.guardrails["polymorphic_events"].append({
                "event": "TOOL_SYNTHESIZED",
                "tool": missing_integration,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            
            db.add(skill)
            await db.commit()
            
            return {"status": "SUCCESS", "skill_patched": skill_id, "tool_added": missing_integration}
        
        return {"status": "FAILED", "reason": "Could not synthesize safe code"}
