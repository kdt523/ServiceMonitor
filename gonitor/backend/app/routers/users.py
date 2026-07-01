"""
Users router — admin user management (add, edit, delete, toggle).
"""
from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone

from app.database import get_db
from app.config import TEMPLATES_DIR
from app.dependencies import get_current_user
from app.models.user import User
from app.services.auth_service import hash_password

router = APIRouter(prefix="/admin/users", tags=["users"])
templates = Jinja2Templates(directory=TEMPLATES_DIR)


# ── List users ──────────────────────────────────────────────────────────────
@router.get("", response_class=HTMLResponse)
async def list_users(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(User).where(User.deleted_at == None).order_by(User.id)  # noqa
    )
    users = result.scalars().all()
    return templates.TemplateResponse(
        request=request,
        name="users/index.html",
        context={"user": current_user, "users": users},
    )


# ── Add user — GET ──────────────────────────────────────────────────────────
@router.get("/add", response_class=HTMLResponse)
async def add_user_page(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    return templates.TemplateResponse(
        request=request,
        name="users/add.html",
        context={"user": current_user, "error": None},
    )


# ── Add user — POST ─────────────────────────────────────────────────────────
@router.post("/add")
async def add_user(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    first_name: Optional[str] = Form(None),
    last_name: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none():
        return templates.TemplateResponse(
            request=request,
            name="users/add.html",
            context={"user": current_user, "error": "Email already in use"},
            status_code=400,
        )
    new_user = User(
        email=email,
        password_hash=hash_password(password),
        first_name=first_name or None,
        last_name=last_name or None,
        phone=phone or None,
        is_active=True,
    )
    db.add(new_user)
    await db.commit()
    return RedirectResponse(url="/admin/users", status_code=302)


# ── Edit user — GET ─────────────────────────────────────────────────────────
@router.get("/{user_id}/edit", response_class=HTMLResponse)
async def edit_user_page(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    target = await _get_user(db, user_id)
    return templates.TemplateResponse(
        request=request,
        name="users/edit.html",
        context={"user": current_user, "target": target, "error": None},
    )


# ── Edit user — POST ────────────────────────────────────────────────────────
@router.post("/{user_id}/edit")
async def edit_user(
    user_id: int,
    request: Request,
    email: str = Form(...),
    first_name: Optional[str] = Form(None),
    last_name: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    new_password: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    target = await _get_user(db, user_id)
    target.email = email
    target.first_name = first_name or None
    target.last_name = last_name or None
    target.phone = phone or None
    if new_password and new_password.strip():
        target.password_hash = hash_password(new_password.strip())
    await db.commit()
    return RedirectResponse(url="/admin/users", status_code=302)


# ── Toggle active status ────────────────────────────────────────────────────
@router.post("/{user_id}/toggle")
async def toggle_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    target = await _get_user(db, user_id)
    if target.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate yourself")
    target.is_active = not target.is_active
    await db.commit()
    return RedirectResponse(url="/admin/users", status_code=302)


# ── Soft delete ─────────────────────────────────────────────────────────────
@router.post("/{user_id}/delete")
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    target = await _get_user(db, user_id)
    target.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()
    return RedirectResponse(url="/admin/users", status_code=302)


# ── Helper ──────────────────────────────────────────────────────────────────
async def _get_user(db: AsyncSession, user_id: int) -> User:
    result = await db.execute(select(User).where(User.id == user_id, User.deleted_at == None))  # noqa
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user
