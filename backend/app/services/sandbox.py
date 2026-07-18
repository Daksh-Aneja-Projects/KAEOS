import ast
import asyncio
import sys
from typing import Tuple
import logging
import tempfile
import os

logger = logging.getLogger(__name__)

class SandboxSecurityException(Exception):
    pass

class SandboxExecutor:
    """Executes Python code in an isolated subprocess with AST validation."""
    
    ALLOWED_IMPORTS = {"math", "datetime", "json", "re", "typing", "collections", "itertools"}

    @classmethod
    def validate_ast(cls, code: str):
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            raise SandboxSecurityException(f"Syntax error: {e}")
            
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                # Check allowed modules
                module = node.module if isinstance(node, ast.ImportFrom) else node.names[0].name
                if module and module.split('.')[0] not in cls.ALLOWED_IMPORTS:
                    raise SandboxSecurityException(f"Importing '{module}' is forbidden in the sandbox.")
            # Prevent calling builtin dangerous functions
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    if node.func.id in {"exec", "eval", "open", "compile", "globals", "locals", "getattr", "setattr", "delattr", "__import__", "input"}:
                        raise SandboxSecurityException(f"Calling '{node.func.id}' is forbidden in the sandbox.")

    @classmethod
    async def execute(cls, code: str, timeout_seconds: int = 5) -> Tuple[bool, str]:
        """Runs validated code in a subprocess. Returns (success, output)."""
        try:
            cls.validate_ast(code)
        except SandboxSecurityException as e:
            return False, str(e)
            
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            temp_path = f.name
            
        try:
            # Run in subprocess without shell to prevent injection
            proc = await asyncio.create_subprocess_exec(
                sys.executable, temp_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
                if proc.returncode == 0:
                    return True, stdout.decode().strip()
                else:
                    return False, f"Error: {stderr.decode().strip()}"
            except asyncio.TimeoutError:
                proc.kill()
                return False, f"Execution timed out after {timeout_seconds} seconds."
        except Exception as e:
            return False, f"Sandbox fault: {e}"
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
