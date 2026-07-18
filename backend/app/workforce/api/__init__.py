"""
KAEOS Workforce Layer — API Router Package

Exposes the workforce abstraction layer: departments, domain packs,
deployment state machine, processes, and analytics.

All endpoints query real DB models from workforce/models/*.
Zero mock data. Zero hardcoded values.
"""
from fastapi import APIRouter

router = APIRouter(tags=["Workforce Layer"])
