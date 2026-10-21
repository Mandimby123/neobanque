import json
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Request, Response, Form, status, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.core.database import get_db
from app.core.security import (
    verify_password, hash_password, create_access_token, decode_access_token,
    verify_totp_code, generate_totp_secret, get_totp_uri, generate_totp_qr_data_url
)
from app.models.banking import User, AuditLog

router = APIRouter(prefix="", tags=["Authentification"])
templates = Jinja2Templates(directory="app/templates")


# ==============================================================================
# DÉPENDANCES D'AUTHENTIFICATION
# ==============================================================================
async def get_current_user_optional(request: Request, db: AsyncSession = Depends(get_db)) -> Optional[User]:
    token = request.cookies.get(settings.COOKIE_NAME)
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]

    if not token:
        return None

    payload = decode_access_token(token)
    if not payload:
        return None

    user_id = payload.get("sub")
    if not user_id:
        return None

    stmt = select(User).where(User.id == int(user_id))
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()
    return user


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    user = await get_current_user_optional(request, db)
    if not user:
        if request.headers.get("HX-Request") == "true":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                headers={"HX-Redirect": "/login"}
            )
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": "/login"}
        )
    return user


# ==============================================================================
# ROUTES D'AUTHENTIFICATION
# ==============================================================================
@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, user: Optional[User] = Depends(get_current_user_optional)):
    if user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        request=request,
        name="auth/login.html",
        context={"error": None}
    )


@router.post("/login")
async def process_login(
    request: Request,
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    ip = request.client.host if request.client else "127.0.0.1"
    ua = request.headers.get("User-Agent", "Unknown")

    stmt = select(User).where(User.email == email.strip().lower())
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()

    if not user or not verify_password(password, user.hashed_password):
        audit = AuditLog(
            user_id=user.id if user else None,
            action="LOGIN_FAILED",
            ip_address=ip,
            user_agent=ua,
            status="FAILURE",
            details=json.dumps({"email": email, "reason": "Bad credentials"})
        )
        db.add(audit)
        await db.commit()
        return templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            context={"error": "Email ou mot de passe incorrect."},
            status_code=status.HTTP_401_UNAUTHORIZED
        )

    # Si l'utilisateur a le 2FA TOTP activé
    if user.is_totp_enabled:
        temp_token = create_access_token(
            {"sub": str(user.id), "stage": "totp_pending"},
            expires_delta=timedelta(minutes=5)
        )
        resp = RedirectResponse(url="/auth/totp", status_code=status.HTTP_303_SEE_OTHER)
        resp.set_cookie(
            key="neobank_preauth",
            value=temp_token,
            httponly=True,
            secure=settings.COOKIE_SECURE,
            samesite="lax",
            max_age=300
        )
        return resp

    token = create_access_token({"sub": str(user.id)})
    resp = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    resp.set_cookie(
        key=settings.COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )
    return resp


@router.get("/auth/totp", response_class=HTMLResponse)
async def totp_verify_page(request: Request, db: AsyncSession = Depends(get_db)):
    preauth_token = request.cookies.get("neobank_preauth")
    if not preauth_token:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    payload = decode_access_token(preauth_token)
    if not payload or payload.get("stage") != "totp_pending":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    stmt = select(User).where(User.id == int(payload.get("sub")))
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()

    return templates.TemplateResponse(
        request=request,
        name="auth/totp_verify.html",
        context={"email": user.email if user else "", "error": None}
    )


@router.post("/auth/totp")
async def process_totp_verification(
    request: Request,
    response: Response,
    code: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    preauth_token = request.cookies.get("neobank_preauth")
    if not preauth_token:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    payload = decode_access_token(preauth_token)
    if not payload or payload.get("stage") != "totp_pending":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    user_id = int(payload.get("sub"))
    stmt = select(User).where(User.id == user_id)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()

    ip = request.client.host if request.client else "127.0.0.1"
    ua = request.headers.get("User-Agent", "Unknown")

    if not user or not verify_totp_code(user.totp_secret, code):
        audit = AuditLog(
            user_id=user_id,
            action="TOTP_FAILED",
            ip_address=ip,
            user_agent=ua,
            status="FAILURE",
            details=json.dumps({"reason": "Invalid TOTP code"})
        )
        db.add(audit)
        await db.commit()
        return templates.TemplateResponse(
            request=request,
            name="auth/totp_verify.html",
            context={"email": user.email if user else "", "error": "Code TOTP invalide ou expiré."},
            status_code=status.HTTP_400_BAD_REQUEST
        )

    final_token = create_access_token({"sub": str(user.id), "email": user.email})

    audit = AuditLog(
        user_id=user.id,
        action="LOGIN_SUCCESS_2FA",
        ip_address=ip,
        user_agent=ua,
        status="SUCCESS",
        details=json.dumps({"method": "TOTP_2FA"})
    )
    db.add(audit)
    await db.commit()

    resp = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    resp.set_cookie(
        key=settings.COOKIE_NAME,
        value=final_token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )
    resp.delete_cookie(key="neobank_preauth")
    return resp


@router.get("/logout")
async def logout(request: Request, user: Optional[User] = Depends(get_current_user_optional), db: AsyncSession = Depends(get_db)):
    if user:
        ip = request.client.host if request.client else "127.0.0.1"
        ua = request.headers.get("User-Agent", "Unknown")
        audit = AuditLog(
            user_id=user.id,
            action="LOGOUT",
            ip_address=ip,
            user_agent=ua,
            status="SUCCESS",
            details="{}"
        )
        db.add(audit)
        await db.commit()

    resp = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    resp.delete_cookie(key=settings.COOKIE_NAME)
    resp.delete_cookie(key="neobank_preauth")
    return resp


@router.get("/auth/reset-password", response_class=HTMLResponse)
async def reset_password_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="auth/reset_password.html",
        context={"error": None, "success": None}
    )


@router.post("/auth/reset-password")
async def process_reset_password(
    request: Request,
    email: str = Form(...),
    totp_code: str = Form(...),
    new_password: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    ip = request.client.host if request.client else "127.0.0.1"
    ua = request.headers.get("User-Agent", "Unknown")

    stmt = select(User).where(User.email == email.strip().lower())
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()

    if not user:
        return templates.TemplateResponse(
            request=request,
            name="auth/reset_password.html",
            context={"error": "Email ou code TOTP invalide.", "success": None},
            status_code=status.HTTP_400_BAD_REQUEST
        )

    if not verify_totp_code(user.totp_secret, totp_code):
        audit = AuditLog(
            user_id=user.id,
            action="PASSWORD_RESET_FAILED",
            ip_address=ip,
            user_agent=ua,
            status="FAILURE",
            details=json.dumps({"reason": "Invalid TOTP"})
        )
        db.add(audit)
        await db.commit()
        return templates.TemplateResponse(
            request=request,
            name="auth/reset_password.html",
            context={"error": "Code TOTP invalide ou expiré.", "success": None},
            status_code=status.HTTP_400_BAD_REQUEST
        )

    user.hashed_password = hash_password(new_password)
    audit = AuditLog(
        user_id=user.id,
        action="PASSWORD_RESET_SUCCESS",
        ip_address=ip,
        user_agent=ua,
        status="SUCCESS",
        details="{}"
    )
    db.add(audit)
    await db.commit()

    return templates.TemplateResponse(
        request=request,
        name="auth/reset_password.html",
        context={"error": None, "success": "Votre mot de passe a été mis à jour avec succès. Vous pouvez maintenant vous connecter."},
        status_code=status.HTTP_200_OK
    )

