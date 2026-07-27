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

## Starlette advisories - disposition

KAEOS pins **FastAPI 0.140.0 / Starlette 1.3.1**. Every Starlette advisory is
tracked below with its disposition; none are silenced without a reason recorded
here.

**The ceiling is lifted (2026-07-25).** KAEOS was previously stuck on Starlette
0.48.0 because no released FastAPI supported the 1.x line (0.119.x capped
`starlette <0.49.0`), which made every advisory patched only in >=1.x
*structurally unreachable*. FastAPI 0.140.0 removed that cap, so KAEOS moved to
Starlette 1.3.1 and **the previously-accepted advisories are now genuinely
fixed** - including the form-urlencoded DoS (GHSA-82w8) and the Host-header
auth-bypass (GHSA-86qp). `prometheus-fastapi-instrumentator` was co-bumped to
8.0.2 (7.x caps `starlette<1.0.0`). The `starlette >=1.0.0` ignore rule has been
removed from `.github/dependabot.yml`.

FastAPI's routing rework (each `include_router` is now one `_IncludedRouter`
entry rather than flattened `APIRoute`s on `app.routes`) does **not** affect
request routing or the `require_role` gates - verified by
`tests/test_rbac_coverage.py::test_viewer_denied_on_gated_endpoint`, which
asserts a real 403 for a viewer on every gated endpoint. It does break naive
route *introspection*, so the authorization-coverage lints
(`test_default_deny.py`, `test_rbac_coverage.py`) enumerate routes via
`tests/route_introspection.py`, which supports both layouts and fails loudly
(`test_route_enumeration_is_not_vacuous`) if a future framework change ever
blinds the walk again.

| Advisory | Severity | Disposition |
| --- | --- | --- |
| [GHSA-f96h-pmfr-66vw](https://github.com/advisories/GHSA-f96h-pmfr-66vw) - DoS via `multipart/form-data` | High | **Fixed** in 1.1.1 (Starlette ≥ 0.40.0). |
| [GHSA-2c2j-9gv5-cj73](https://github.com/advisories/GHSA-2c2j-9gv5-cj73) - DoS parsing large multipart files | Medium | **Fixed** in 1.1.1 (Starlette ≥ 0.47.2). |
| [GHSA-86qp-5c8j-p5mr](https://github.com/advisories/GHSA-86qp-5c8j-p5mr) - Host header poisons `request.url.path`, bypassing path-based auth | Medium | **Fixed upstream** (Starlette ≥ 1.0.1) **and mitigated in code** (defense in depth, since 1.1.2). KAEOS's security gates (tenant/auth gate, rate-limit exemption) key off the raw ASGI `scope["path"]` - the router's matched path - never the Host-reconstructed `request.url.path`; that mitigation is retained deliberately. Regression test: `tests/test_tenant_middleware.py::test_poisoned_host_header_cannot_bypass_auth_gate` (asserts 401 + handler never runs on a poisoned Host, on both patched and unpatched Starlette). |
| [GHSA-x746-7m8f-x49c](https://github.com/advisories/GHSA-x746-7m8f-x49c) - arbitrary HTTP method dispatched to `HTTPEndpoint` via `getattr` | Medium | **Fixed** (Starlette ≥ 1.1.0) and **not applicable** regardless - KAEOS uses no Starlette `HTTPEndpoint` class-based views (FastAPI function routes / `APIRouter` only). |
| [GHSA-wqp7-x3pw-xc5r](https://github.com/advisories/GHSA-wqp7-x3pw-xc5r) - StaticFiles SSRF / NTLM credential theft via UNC paths on Windows | High | **Fixed** (Starlette ≥ 1.1.0) and **not applicable** regardless - KAEOS serves no `StaticFiles` and deploys on Linux (`python:3.12-slim`, see `backend/Dockerfile`). |
| [GHSA-82w8-qh3p-5jfq](https://github.com/advisories/GHSA-82w8-qh3p-5jfq) - `request.form()` limits ignored for `application/x-www-form-urlencoded` (DoS) | High (CVSS 7.5) | **Fixed** (Starlette ≥ 1.3.1). Previously accepted/tracked while 1.x was unreachable; the FastAPI 0.140.0 bump made the patched version installable. A reverse-proxy request-body size limit (e.g. nginx `client_max_body_size`) remains recommended as defense in depth. |

Every Starlette advisory above is now either **fixed** by the FastAPI 0.140.0 /
Starlette 1.3.1 pin or **not applicable** to how KAEOS uses the framework. None
remain in an "accepted" state.

## Acknowledgements

We appreciate security researchers who help keep KAEOS safe. Contributors who responsibly disclose vulnerabilities will be credited in release notes (with permission).
