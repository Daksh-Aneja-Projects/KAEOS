# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.x     | :white_check_mark: |

## Reporting a Vulnerability

**Please do NOT open public GitHub issues for security vulnerabilities.**

If you discover a security vulnerability in KAEOS, please report it responsibly:

1. **GitHub Private Vulnerability Reporting**: use the ["Report a vulnerability"](https://github.com/Daksh-Aneja-Projects/KAEOS/security/advisories/new) button on the repository's Security tab
2. **Include**:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

## Response Timeline

- **Acknowledgement**: Within 48 hours
- **Initial Assessment**: Within 5 business days
- **Fix & Disclosure**: We aim to release a fix within 30 days of confirmation

## Scope

The following are in scope:
- Backend API vulnerabilities (authentication bypass, injection, etc.)
- Frontend XSS or CSRF vulnerabilities
- Secret/credential exposure in source code
- Dependency vulnerabilities with known exploits
- LLM prompt injection that bypasses guardrails

The following are out of scope:
- Vulnerabilities in third-party dependencies without a working exploit
- Social engineering attacks
- Denial of service attacks

## Security Best Practices for Deployment

1. **Always set `SECRET_KEY`** in your `.env` file - never use the default
2. **Use environment variables** for all API keys - never commit them to source control
3. **Enable HTTPS** in production via a reverse proxy (nginx, Caddy, etc.)
4. **Restrict CORS origins** to your actual frontend domain
5. **Use PostgreSQL** in production - SQLite is for development only
6. **Provision the admin account** via `ADMIN_EMAIL` / `ADMIN_PASSWORD` (there is no default public login), keep `DEV_MODE=false`, and confirm RLS is effective at startup (`assert_rls_effective` runs on boot; `scripts/verify_rls.py` as an extra gate) before exposing to the internet

## Accepted / tracked advisories

Some upstream advisories cannot currently be remediated by upgrading, because
the only patched version is incompatible with the rest of the stack. These are
tracked here and mitigated at deployment rather than silenced blindly.

| Advisory | Severity | Status | Rationale & mitigation |
| --- | --- | --- | --- |
| [GHSA-82w8-qh3p-5jfq](https://github.com/advisories/GHSA-82w8-qh3p-5jfq) — Starlette `request.form()` limits silently ignored for `application/x-www-form-urlencoded` (DoS) | High (CVSS 7.5) | **Accepted / tracked** | Only patched in Starlette **1.3.1**, which **no released FastAPI supports** (0.119.x caps `starlette <0.49.0`) and which breaks KAEOS's `require_role` routing. It is a resource-exhaustion DoS — out of scope per this policy — and is mitigated at ingress: enforce a request-body size limit at the reverse proxy (e.g. nginx `client_max_body_size`) in front of the API. Will be remediated by bumping Starlette once FastAPI adopts the 1.x line. Dependabot is configured to stop proposing the un-installable `1.3.1` bump (see `.github/dependabot.yml`). |

Advisories reachable within the supported FastAPI range are remediated by
upgrade, not accepted — e.g. GHSA-f96h-pmfr-66vw and GHSA-2c2j-9gv5-cj73
(Starlette multipart DoS) were cleared in 1.1.1 by moving to Starlette 0.48.0.

## Acknowledgements

We appreciate security researchers who help keep KAEOS safe. Contributors who responsibly disclose vulnerabilities will be credited in release notes (with permission).
