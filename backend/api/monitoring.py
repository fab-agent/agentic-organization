"""GET /admin/monitoring - one company's operational picture (ADR-0034)."""

from fastapi import APIRouter, Depends

from api.auth import get_current_user
from database import get_session
from models import User
from services import authz, monitoring

router = APIRouter(tags=["monitoring"])


@router.get("/admin/monitoring")
def company_monitoring(
    company_id: str, deep: bool = False, user: User = Depends(get_current_user)
):
    """Founder / executive of the company (company-wide) only: 404 for outsiders, 403 for
    other members. `deep=true` also re-hashes the whole audit chain (it reads every event)."""
    with get_session() as session:
        authz.require_role(session, user.id, company_id, authz.FINAL, company_wide=True)
    return monitoring.summary(company_id, deep=deep)
