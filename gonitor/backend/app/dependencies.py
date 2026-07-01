from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.user import User
from app.services.auth_service import decode_access_token


class RedirectException(Exception):
    def __init__(self, url: str):
        self.url = url


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Dependency that reads the JWT from the HttpOnly cookie,
    decodes it, and returns the authenticated User ORM object.

    - For JSON/API endpoints (Accept: application/json), raises HTTP 401.
    - For HTML page requests, raises HTTP 302 redirect to /login.
    """
    token: Optional[str] = request.cookies.get("access_token")

    def _redirect_or_401(detail: str):
        """Return redirect for browser requests, 401 for API/JS requests."""
        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            raise RedirectException(url="/login")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not token:
        raise _redirect_or_401("Not authenticated")

    payload = decode_access_token(token)
    if payload is None:
        raise _redirect_or_401("Invalid or expired token")

    user_id: Optional[int] = payload.get("sub")
    if user_id is None:
        raise _redirect_or_401("Invalid token payload")

    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()
    if user is None:
        raise _redirect_or_401("User not found")

    return user
