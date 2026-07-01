"""
Logs router — kept for backward compat; redirects to host detail.
The detailed service log view is now served from host_services router.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from app.dependencies import get_current_user
from app.models.user import User

router = APIRouter(tags=["logs"])


@router.get("/resources/{resource_id}/detail")
async def legacy_resource_detail(
    resource_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Legacy redirect — old resource detail URLs redirect to hosts page."""
    return RedirectResponse(url="/hosts", status_code=302)
