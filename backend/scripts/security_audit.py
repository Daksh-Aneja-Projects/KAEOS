import os
import re

def audit_security():
    print("Starting KAEOS Security Audit...\n")
    issues_found = 0

    # 1. Check for Hardcoded Secrets
    print("[*] Checking for hardcoded secrets...")
    secret_patterns = [
        r"(?i)secret_key\s*=\s*['\"][a-zA-Z0-9]{10,}['\"]",
        r"(?i)api_key\s*=\s*['\"][a-zA-Z0-9]{10,}['\"]",
        r"(?i)password\s*=\s*['\"][a-zA-Z0-9]{6,}['\"]"
    ]
    
    scan_dirs = ["app/api", "app/core", "app/services"]
    for d in scan_dirs:
        for root, _, files in os.walk(os.path.join(os.path.dirname(__file__), "..", d)):
            for file in files:
                if file.endswith(".py"):
                    filepath = os.path.join(root, file)
                    with open(filepath, "r", encoding="utf-8") as f:
                        content = f.read()
                        for pattern in secret_patterns:
                            matches = re.finditer(pattern, content)
                            for match in matches:
                                # Ignore test files or dummy configurations
                                if "test" not in filepath and "dummy" not in match.group():
                                    print(f"  [!] Potential hardcoded secret in {filepath}: {match.group()}")
                                    issues_found += 1

    # 2. Verify Auth Middleware
    print("\n[*] Verifying Authentication Enforcement...")
    middleware_path = os.path.join(os.path.dirname(__file__), "..", "app", "core", "tenant.py")
    if os.path.exists(middleware_path):
        with open(middleware_path, "r", encoding="utf-8") as f:
            content = f.read()
            if "decode_token" not in content or "_unauthorized" not in content:
                print("  [!] Auth middleware does not appear to strictly enforce 401 Unauthorized.")
                issues_found += 1
            else:
                print("  [OK] Auth middleware enforces 401.")
    else:
        print("  [!] Tenant middleware not found.")
        issues_found += 1

    # 3. Check CORS Settings
    print("\n[*] Checking CORS Configuration...")
    main_path = os.path.join(os.path.dirname(__file__), "..", "app", "main.py")
    if os.path.exists(main_path):
        with open(main_path, "r", encoding="utf-8") as f:
            content = f.read()
            if "allow_origins=[\"*\"]" in content.replace(" ", ""):
                print("  [WARNING] CORS allows all origins (*). Consider restricting in staging/production.")
                issues_found += 1
            else:
                print("  [OK] CORS configuration looks restrictive.")
    else:
        print("  [!] main.py not found.")
        issues_found += 1

    print(f"\nAudit Complete. Total Issues Found: {issues_found}")
    if issues_found > 0:
        exit(1)
    else:
        print("System appears secure for staging deployment.")
        exit(0)

if __name__ == "__main__":
    audit_security()
