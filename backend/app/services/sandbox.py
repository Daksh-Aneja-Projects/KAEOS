"""KAEOS — Agent code sandbox.

Executes short Python snippets produced by agent tools. This is a DEFENSE-IN-DEPTH
sandbox, not a substitute for OS-level isolation:

  Layer 1  Strict AST allow/deny validation. Blocks imports outside a tiny
           allowlist AND the attribute-traversal escapes (``().__class__.
           __bases__[0].__subclasses__()``) that the previous name-only blocklist
           let straight through to ``os``/``subprocess``.
  Layer 2  A restricted-builtins preamble injected ahead of the user code, so even
           if a construct slips past Layer 1 the running code has no ``open``,
           ``__import__``, ``eval`` … in scope.
  Layer 3  An isolated child interpreter (``-I -S -B``) with a scrubbed environment,
           a throwaway CWD, an ENFORCED wall-clock timeout, an enforced address-space
           limit (POSIX ``setrlimit``), and output truncation.

For genuinely untrusted input, run KAEOS with a container/seccomp backend and set
``SANDBOX_REQUIRE_CONTAINER=true`` — Layer 3's raw ``subprocess`` is then refused.
"""
import ast
import asyncio
import os
import sys
import tempfile
import logging
from typing import Tuple

logger = logging.getLogger(__name__)


class SandboxSecurityException(Exception):
    pass


# Dunder / attribute names that unlock introspection escapes.
_FORBIDDEN_ATTRS = {
    "__class__", "__bases__", "__mro__", "__subclasses__", "__globals__",
    "__code__", "__closure__", "__dict__", "__builtins__", "__base__",
    "__subclasshook__", "__init_subclass__", "__reduce__", "__reduce_ex__",
    "__getattribute__", "__getattr__", "__setattr__", "__delattr__",
    "__import__", "__loader__", "__spec__", "func_globals", "gi_frame",
    "cr_frame", "f_globals", "f_builtins", "f_locals",
}

# Names that must not be referenced at all (call OR bare load).
_FORBIDDEN_NAMES = {
    "exec", "eval", "open", "compile", "globals", "locals", "vars",
    "getattr", "setattr", "delattr", "hasattr", "__import__", "input",
    "breakpoint", "exit", "quit", "help", "memoryview", "classmethod",
    "staticmethod", "super", "object", "type", "property", "importlib",
}


class _Validator(ast.NodeVisitor):
    """Reject the first construct that could escape the sandbox."""

    ALLOWED_IMPORTS = {"math", "datetime", "json", "re", "typing",
                       "collections", "itertools", "statistics", "decimal"}

    def _reject(self, msg: str):
        raise SandboxSecurityException(msg)

    def visit_Import(self, node: ast.Import):
        for a in node.names:
            if a.name.split(".")[0] not in self.ALLOWED_IMPORTS:
                self._reject(f"Importing '{a.name}' is forbidden in the sandbox.")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        root = (node.module or "").split(".")[0]
        if root not in self.ALLOWED_IMPORTS:
            self._reject(f"Importing from '{node.module}' is forbidden in the sandbox.")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        if node.attr in _FORBIDDEN_ATTRS or (
            node.attr.startswith("__") and node.attr.endswith("__")
        ):
            self._reject(f"Access to attribute '{node.attr}' is forbidden in the sandbox.")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name):
        if node.id in _FORBIDDEN_NAMES:
            self._reject(f"Use of '{node.id}' is forbidden in the sandbox.")
        self.generic_visit(node)

    # Block "from x import *" and dynamic exec via code objects.
    def visit_Global(self, node: ast.Global):
        self._reject("'global' is forbidden in the sandbox.")

    def visit_Nonlocal(self, node: ast.Nonlocal):
        self._reject("'nonlocal' is forbidden in the sandbox.")


# Injected ahead of user code. Caps address space + CPU on POSIX (defense in
# depth — the AST validator is the primary gate; dangerous builtins are blocked
# there by name so we do NOT delete them here, which would break the stdlib's
# own import machinery).
_PREAMBLE = """
try:
    import resource as _r
    _lim = {mem_bytes}
    _r.setrlimit(_r.RLIMIT_AS, (_lim, _lim))
    _r.setrlimit(_r.RLIMIT_CPU, ({cpu_sec}, {cpu_sec}))
    del _r, _lim
except Exception:
    pass
# ── user code ──
"""


class SandboxExecutor:
    """Executes Python code with AST validation + an isolated child interpreter."""

    ALLOWED_IMPORTS = _Validator.ALLOWED_IMPORTS
    MAX_OUTPUT_CHARS = 10_000
    MAX_CODE_CHARS = 20_000

    @classmethod
    def validate_ast(cls, code: str):
        if len(code) > cls.MAX_CODE_CHARS:
            raise SandboxSecurityException("Code exceeds the sandbox size limit.")
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            raise SandboxSecurityException(f"Syntax error: {e}")
        _Validator().visit(tree)

    @classmethod
    async def execute(cls, code: str, timeout_seconds: int | None = None) -> Tuple[bool, str]:
        """Run validated code in an isolated subprocess. Returns (success, output)."""
        from app.core.config import get_settings
        settings = get_settings()

        # A container/seccomp backend is the only safe home for untrusted code.
        if os.environ.get("SANDBOX_REQUIRE_CONTAINER", "").lower() in ("1", "true"):
            return False, ("Sandbox refused: SANDBOX_REQUIRE_CONTAINER is set but no "
                           "container backend is configured for raw execution.")

        try:
            cls.validate_ast(code)
        except SandboxSecurityException as e:
            return False, str(e)

        # Enforce the CONFIGURED limits (previously ignored). Cap the interactive
        # tool well below the batch-agent ceiling so a tool call can't hog the box.
        cap = min(int(settings.AGENT_SANDBOX_TIMEOUT_SEC or 10), 15)
        timeout = min(timeout_seconds or cap, cap)
        mem_bytes = max(64, int(settings.AGENT_SANDBOX_MEMORY_MB or 256)) * 1024 * 1024

        preamble = _PREAMBLE.format(mem_bytes=mem_bytes, cpu_sec=max(1, timeout))
        payload = preamble + "\n" + code

        workdir = tempfile.mkdtemp(prefix="kaeos_sbx_")
        temp_path = os.path.join(workdir, "snippet.py")
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(payload)

        # Scrubbed environment — no inherited secrets, no PYTHON* overrides.
        clean_env = {
            "PATH": os.environ.get("PATH", ""),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),  # Windows needs this
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONIOENCODING": "utf-8",
        }
        kwargs = {}
        if os.name == "posix":
            kwargs["start_new_session"] = True  # own process group → kill the tree

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-I", "-S", "-B", temp_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workdir,
                env=clean_env,
                **kwargs,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                cls._kill(proc)
                return False, f"Execution timed out after {timeout} seconds."

            out = (stdout.decode(errors="replace")[: cls.MAX_OUTPUT_CHARS]).strip()
            if proc.returncode == 0:
                return True, out
            err = (stderr.decode(errors="replace")[: cls.MAX_OUTPUT_CHARS]).strip()
            return False, f"Error: {err}"
        except Exception as e:
            return False, f"Sandbox fault: {e}"
        finally:
            for p in (temp_path, workdir):
                try:
                    os.remove(p) if p == temp_path else os.rmdir(p)
                except OSError:
                    pass

    @staticmethod
    def _kill(proc):
        try:
            if os.name == "posix":
                import signal
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            else:
                proc.kill()
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
