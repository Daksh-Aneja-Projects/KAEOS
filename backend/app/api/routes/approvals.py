"""Approver persona - decide a pending approval straight from the notification.

A HITL notification carries a signed, short-lived, single-purpose link. Opening
it resolves the approval without a KAEOS session, so an approver who lives in
email or Slack never has to log in to unblock governed autonomy.

Security: the token is an HS256 JWT with audience "kaeos-approval", a 7-day
expiry, and it names exactly one execution AND one decision - it cannot be
replayed against a different execution or flipped to the other outcome. The
approver identity recorded is the token's subject, and the decision still runs
through the same resolve path (and audit trail) as an in-app approval.
"""
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.core.audit import record_security_event
from app.services.auth import _get_secret_key

router = APIRouter(prefix="/approvals", tags=["Approvals"])

_AUD = "kaeos-approval"
_ALG = "HS256"
LINK_TTL_DAYS = 7


def mint_approval_token(execution_id: str, tenant_id: str, approved: bool,
                        approver: str = "email-approver") -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({
        "execution_id": execution_id,
        "tenant_id": tenant_id,
        "approved": approved,
        "approver": approver,
        "aud": _AUD,
        "iat": now,
        "exp": now + timedelta(days=LINK_TTL_DAYS),
    }, _get_secret_key(), algorithm=_ALG)


def approval_links(execution_id: str, tenant_id: str, base_url: str) -> dict:
    base = (base_url or "").rstrip("/")
    return {
        "approve": f"{base}/api/v1/approvals/decide?token="
                   f"{mint_approval_token(execution_id, tenant_id, True)}",
        "reject": f"{base}/api/v1/approvals/decide?token="
                  f"{mint_approval_token(execution_id, tenant_id, False)}",
    }


def _page(title: str, message: str, ok: bool) -> HTMLResponse:
    color = "#22c55e" if ok else "#ef4444"
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>KAEOS - {title}</title></head>
<body style="font-family:system-ui,sans-serif;background:#0b0c0e;color:#f7f8f8;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
<div style="text-align:center;max-width:420px;padding:32px;border:1px solid #2a2d33;
border-radius:12px;background:#0f1011">
<div style="font-size:20px;font-weight:600;color:{color};margin-bottom:8px">{title}</div>
<div style="font-size:14px;color:#8a8f98;line-height:1.5">{message}</div>
</div></body></html>"""
    return HTMLResponse(content=html, status_code=200 if ok else 400)


@router.get("/decide", response_class=HTMLResponse)
async def decide(token: str):
    """Resolve an approval from a signed link (no session required)."""
    try:
        claims = jwt.decode(token, _get_secret_key(), algorithms=[_ALG], audience=_AUD)
    except jwt.ExpiredSignatureError:
        return _page("Link expired",
                     "This approval link has expired. Open KAEOS to decide it there.", False)
    except jwt.InvalidTokenError:
        return _page("Invalid link",
                     "This approval link is not valid.", False)

    execution_id = claims.get("execution_id")
    tenant_id = claims.get("tenant_id")
    approved = bool(claims.get("approved"))
    approver = claims.get("approver") or "email-approver"

    from app.services.hitl_manager import hitl_manager
    success = await hitl_manager.resolve_hitl(
        execution_id, approved=approved, approver=approver,
        reason="decided from notification link", tenant_id=tenant_id)
    if not success:
        return _page("Already decided",
                     "This approval is no longer pending. It may have been "
                     "resolved already or it expired.", False)

    await record_security_event(
        tenant_id=tenant_id, event_type="HITL_DECISION",
        action="APPROVE" if approved else "REJECT",
        actor=approver, actor_role="approver",
        resource_type="hitl_execution", resource_id=execution_id,
        details={"channel": "notification_link"})

    verb = "Approved" if approved else "Rejected"
    return _page(f"{verb}",
                 f"Execution {execution_id} was {verb.lower()}. "
                 f"You can close this window.", True)
