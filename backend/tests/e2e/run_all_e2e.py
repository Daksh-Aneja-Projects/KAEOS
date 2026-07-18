"""
KAEOS — Master E2E Test Runner
Executes the full E2E test suite against a running backend.
Uses real Ollama (phi4-mini) for all LLM-dependent tests.

Prerequisites:
  1. Backend running: cd backend && uvicorn app.main:app --port 8001 --reload
  2. Ollama running: ollama serve (with phi4-mini:latest pulled)
  3. Database seeded: cd backend && python -m scripts.seed_master

Usage:
  cd backend
  python -m tests.e2e.run_all_e2e           # Full suite
  python -m tests.e2e.run_all_e2e --quick   # Skip LLM tests
  python -m tests.e2e.run_all_e2e --domain hr  # Single domain
"""
import subprocess
import sys
import os
import socket
import time
import argparse


def check_backend(url="localhost", port=8001):
    try:
        with socket.create_connection((url, port), timeout=2):
            return True
    except Exception:
        return False


def check_ollama(url="localhost", port=11434):
    try:
        with socket.create_connection((url, port), timeout=2):
            return True
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(description="KAEOS E2E Test Runner")
    parser.add_argument("--quick", action="store_true", help="Skip LLM-dependent tests")
    parser.add_argument("--domain", type=str, help="Run only a specific domain test (e.g., hr, finance)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--parallel", action="store_true", help="Run tests in parallel")
    args = parser.parse_args()

    print("=" * 70)
    print("KAEOS E2E TEST RUNNER — Comprehensive Platform Validation")
    print("=" * 70)

    # Pre-flight checks
    print("\n[Pre-flight] Checking dependencies...")

    if not check_backend():
        print("  ✗ Backend NOT running on localhost:8001")
        print("    Start it: cd backend && uvicorn app.main:app --port 8001 --reload")
        sys.exit(1)
    print("  ✓ Backend running on localhost:8001")

    ollama_running = check_ollama()
    if ollama_running:
        print("  ✓ Ollama running on localhost:11434")
    else:
        print("  ⚠ Ollama NOT running — LLM tests will be skipped")

    # Build pytest command
    test_dir = os.path.dirname(os.path.abspath(__file__))
    cmd = [sys.executable, "-m", "pytest", test_dir]

    if args.verbose:
        cmd.append("-v")
    else:
        cmd.append("-v")
        cmd.append("--tb=short")

    if args.quick and not ollama_running:
        cmd.extend(["-k", "not ollama and not has_ollama"])

    if args.domain:
        domain_map = {
            "brain": "test_01", "hr": "test_02", "finance": "test_03",
            "legal": "test_04", "sales": "test_05", "support": "test_06",
            "operations": "test_07", "cross": "test_08", "agents": "test_09",
            "infra": "test_10", "executive": "test_11", "connectors": "test_12",
        }
        prefix = domain_map.get(args.domain, args.domain)
        cmd.extend(["-k", prefix])

    if args.parallel:
        try:
            import xdist  # noqa
            cmd.extend(["-n", "auto"])
        except ImportError:
            print("  ⚠ pytest-xdist not installed — running sequentially")

    cmd.extend(["--asyncio-mode=auto"])

    print(f"\n[Running] {' '.join(cmd)}\n")
    print("=" * 70)

    start = time.time()
    result = subprocess.run(cmd, cwd=os.path.dirname(test_dir))
    elapsed = time.time() - start

    print("\n" + "=" * 70)
    print(f"KAEOS E2E TESTS {'PASSED ✓' if result.returncode == 0 else 'FAILED ✗'}")
    print(f"Duration: {elapsed:.1f}s")
    print("=" * 70)

    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
