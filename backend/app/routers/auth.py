"""
Auth router — login, register, logout with optional Remember Me.
"""
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.user import User
from app.schemas.user import UserCreate
from app.services.auth_service import (
    create_access_token,
    hash_password,
    verify_password,
)
from app.config import get_settings, TEMPLATES_DIR
router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory=TEMPLATES_DIR)
settings = get_settings()


# ── GET /login ───────────────────────────────────────────────────────────────
@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(
        request=request, name="auth/login.html", context={"error": None}
    )


# ── POST /login ──────────────────────────────────────────────────────────────
@router.post("/login")
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    remember_me: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.email == email))
    user: Optional[User] = result.scalar_one_or_none()

    if user is None or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            context={"error": "Invalid email or password"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if not user.is_active:
        return templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            context={"error": "Account is inactive"},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    # Remember Me → 30 days, otherwise 1 day
    expire_minutes = (
        settings.remember_me_expire_minutes
        if remember_me
        else settings.access_token_expire_minutes
    )

    access_token = create_access_token(
        data={"sub": str(user.id)},
        expires_delta=timedelta(minutes=expire_minutes),
    )

    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        samesite="lax",
        max_age=expire_minutes * 60,
    )
    return response


# ── GET /register ────────────────────────────────────────────────────────────
@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse(
        request=request, name="auth/register.html", context={"error": None}
    )


# ── POST /register ───────────────────────────────────────────────────────────
@router.post("/register")
async def register(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.email == email))
    if result.scalar_one_or_none():
        return templates.TemplateResponse(
            request=request,
            name="auth/register.html",
            context={"error": "Email already registered"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    user = User(email=email, password_hash=hash_password(password))
    db.add(user)
    await db.commit()
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)


# ── POST /logout ─────────────────────────────────────────────────────────────
@router.post("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie("access_token")
    return response
