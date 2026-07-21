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

## Starlette advisories — disposition

KAEOS pins **FastAPI 0.119.1 / Starlette 0.48.0** — the newest installable
combo, since no released FastAPI supports the Starlette 1.x line (0.119.x caps
`starlette <0.49.0`) and Starlette 1.x breaks `require_role` routing. Every open
Starlette advisory is tracked below with its disposition; none are silenced
without a reason recorded here.

| Advisory | Severity | Disposition |
| --- | --- | --- |
| [GHSA-f96h-pmfr-66vw](https://github.com/advisories/GHSA-f96h-pmfr-66vw) — DoS via `multipart/form-data` | High | **Fixed** in 1.1.1 (Starlette ≥ 0.40.0). |
| [GHSA-2c2j-9gv5-cj73](https://github.com/advisories/GHSA-2c2j-9gv5-cj73) — DoS parsing large multipart files | Medium | **Fixed** in 1.1.1 (Starlette ≥ 0.47.2). |
| [GHSA-86qp-5c8j-p5mr](https://github.com/advisories/GHSA-86qp-5c8j-p5mr) — Host header poisons `request.url.path`, bypassing path-based auth | Medium | **Mitigated in code** (1.1.2). The upstream fix ships only in Starlette 1.0.1 (unreachable), so KAEOS's security gates (tenant/auth gate, rate-limit exemption) now key off the raw ASGI `scope["path"]` — the router's matched path — instead of the Host-reconstructed `request.url.path`. Regression test: `tests/test_tenant_middleware.py::test_poisoned_host_header_cannot_bypass_auth_gate`. |
| [GHSA-x746-7m8f-x49c](https://github.com/advisories/GHSA-x746-7m8f-x49c) — arbitrary HTTP method dispatched to `HTTPEndpoint` via `getattr` | Medium | **Not applicable** — KAEOS uses no Starlette `HTTPEndpoint` class-based views (FastAPI function routes / `APIRouter` only). Alert dismissed. |
| [GHSA-wqp7-x3pw-xc5r](https://github.com/advisories/GHSA-wqp7-x3pw-xc5r) — StaticFiles SSRF / NTLM credential theft via UNC paths on Windows | High | **Not applicable** — KAEOS serves no `StaticFiles` and deploys on Linux (`python:3.11-slim`). Alert dismissed. |
| [GHSA-82w8-qh3p-5jfq](https://github.com/advisories/GHSA-82w8-qh3p-5jfq) — `request.form()` limits ignored for `application/x-www-form-urlencoded` (DoS) | High (CVSS 7.5) | **Accepted / tracked.** Only patched in Starlette 1.3.1 (unreachable). A resource-exhaustion DoS — out of scope per this policy — mitigated at ingress with a reverse-proxy request-body size limit (e.g. nginx `client_max_body_size`). Remediated once FastAPI adopts Starlette 1.x; Dependabot is configured to stop proposing the un-installable bump (`.github/dependabot.yml`). |

The three advisories whose only fix is Starlette ≥ 1.x (86qp, wqp7, 82w8, plus
x746) will be revisited — and the `starlette >=1.0.0` ignore in
`.github/dependabot.yml` removed — as soon as FastAPI ships support for the
Starlette 1.x line.

## Acknowledgements

We appreciate security researchers who help keep KAEOS safe. Contributors who responsibly disclose vulnerabilities will be credited in release notes (with permission).
