"""Reusable SQLAlchemy declarative mixins."""
from sqlalchemy import Boolean, false
from sqlalchemy.orm import Mapped, mapped_column


class LegalHoldMixin:
    """Row-level litigation / legal hold.

    When ``on_legal_hold`` is True the row is PRESERVED against right-to-erasure
    (``erase_subject``), tenant purge (``purge_tenant``), and retention sweeps:
    legal-hold preservation OVERRIDES deletion (GDPR Art.17(3)(b)/(e); FRCP 37(e)
    anti-spoliation). Default False; the erasure/retention guards use ``IS NOT
    TRUE`` so NULL is treated as not-held and only True is skipped (fail-closed).

    Mixed into the record/document tables a hold realistically targets (HR,
    lending, healthcare, sales, finance, support, engineering, operations, legal).
    """
    on_legal_hold: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false(), default=False,
    )
