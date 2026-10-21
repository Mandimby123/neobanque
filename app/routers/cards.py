import json
from decimal import Decimal
from typing import Optional
from fastapi import APIRouter, Depends, Request, Form, status, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import verify_totp_code, decrypt_card_data
from app.models.banking import User, Card, Account, AuditLog
from app.routers.auth import get_current_user
from app.services.cms_client import cms_client

router = APIRouter(prefix="", tags=["Cartes & Monétique"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/cards", response_class=HTMLResponse)
async def cards_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Card).join(Account).where(Account.user_id == user.id)
    res = await db.execute(stmt)
    cards = list(res.scalars().all())

    return templates.TemplateResponse(
        request=request,
        name="cards.html",
        context={
            "user": user,
            "cards": cards,
            "active_card": cards[0] if cards else None
        }
    )


@router.post("/cards/{card_id}/freeze", response_class=HTMLResponse)
async def freeze_card(
    card_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Card).join(Account).where(Card.id == card_id, Account.user_id == user.id)
    res = await db.execute(stmt)
    card = res.scalar_one_or_none()

    if not card:
        return HTMLResponse("<div class='text-rose-400'>Carte introuvable</div>", status_code=404)

    await cms_client.freeze_card(card.id)

    card.is_frozen = True
    
    ip = request.client.host if request.client else "127.0.0.1"
    ua = request.headers.get("User-Agent", "Unknown")
    audit = AuditLog(
        user_id=user.id,
        action="CARD_FROZEN",
        ip_address=ip,
        user_agent=ua,
        status="SUCCESS",
        details=json.dumps({"card_id": card.id, "masked_pan": card.masked_pan})
    )
    db.add(audit)
    await db.commit()

    return templates.TemplateResponse(
        request=request,
        name="partials/card_widget.html",
        context={"card": card}
    )


@router.post("/cards/{card_id}/unfreeze", response_class=HTMLResponse)
async def unfreeze_card(
    card_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Card).join(Account).where(Card.id == card_id, Account.user_id == user.id)
    res = await db.execute(stmt)
    card = res.scalar_one_or_none()

    if not card:
        return HTMLResponse("<div class='text-rose-400'>Carte introuvable</div>", status_code=404)

    await cms_client.unfreeze_card(card.id)

    card.is_frozen = False
    
    ip = request.client.host if request.client else "127.0.0.1"
    ua = request.headers.get("User-Agent", "Unknown")
    audit = AuditLog(
        user_id=user.id,
        action="CARD_UNFROZEN",
        ip_address=ip,
        user_agent=ua,
        status="SUCCESS",
        details=json.dumps({"card_id": card.id, "masked_pan": card.masked_pan})
    )
    db.add(audit)
    await db.commit()

    return templates.TemplateResponse(
        request=request,
        name="partials/card_widget.html",
        context={"card": card}
    )


@router.post("/cards/{card_id}/limits", response_class=HTMLResponse)
async def update_card_limits(
    card_id: int,
    request: Request,
    daily_limit: str = Form(...),
    monthly_limit: str = Form(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Card).join(Account).where(Card.id == card_id, Account.user_id == user.id)
    res = await db.execute(stmt)
    card = res.scalar_one_or_none()

    if not card:
        return HTMLResponse("<div class='text-rose-400'>Carte introuvable</div>", status_code=404)

    try:
        new_daily = Decimal(daily_limit.replace(",", "."))
        new_monthly = Decimal(monthly_limit.replace(",", "."))
    except Exception:
        return HTMLResponse("<div class='text-rose-400'>Valeurs de plafond invalides</div>", status_code=400)

    await cms_client.update_limits(card.id, new_daily, new_monthly)

    card.daily_limit = new_daily
    card.monthly_limit = new_monthly

    ip = request.client.host if request.client else "127.0.0.1"
    ua = request.headers.get("User-Agent", "Unknown")
    audit = AuditLog(
        user_id=user.id,
        action="CARD_LIMITS_UPDATED",
        ip_address=ip,
        user_agent=ua,
        status="SUCCESS",
        details=json.dumps({
            "card_id": card.id,
            "daily_limit": str(new_daily),
            "monthly_limit": str(new_monthly)
        })
    )
    db.add(audit)
    await db.commit()

    return HTMLResponse(
        f"""
        <div class="p-3 bg-emerald-950/80 border border-emerald-800 text-emerald-300 rounded-xl text-sm flex items-center justify-between animate-fade-in">
            <span>✅ Plafonds mis à jour : <b>{new_daily} € / jour</b> &bull; <b>{new_monthly} € / mois</b></span>
        </div>
        """
    )


@router.post("/cards/{card_id}/toggle-setting", response_class=HTMLResponse)
async def toggle_card_setting(
    card_id: int,
    request: Request,
    setting_name: str = Form(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Card).join(Account).where(Card.id == card_id, Account.user_id == user.id)
    res = await db.execute(stmt)
    card = res.scalar_one_or_none()

    if not card:
        return HTMLResponse("<div class='text-rose-400'>Carte introuvable</div>", status_code=404)

    if setting_name == "online":
        card.online_payments_enabled = not card.online_payments_enabled
        await cms_client.toggle_online_payments(card.id, card.online_payments_enabled)
        val = card.online_payments_enabled
    elif setting_name == "foreign":
        card.foreign_payments_enabled = not card.foreign_payments_enabled
        await cms_client.toggle_foreign_payments(card.id, card.foreign_payments_enabled)
        val = card.foreign_payments_enabled
    elif setting_name == "contactless":
        card.contactless_enabled = not card.contactless_enabled
        await cms_client.toggle_contactless(card.id, card.contactless_enabled)
        val = card.contactless_enabled
    else:
        return HTMLResponse("<div class='text-rose-400'>Paramètre inconnu</div>", status_code=400)

    ip = request.client.host if request.client else "127.0.0.1"
    ua = request.headers.get("User-Agent", "Unknown")
    audit = AuditLog(
        user_id=user.id,
        action=f"CARD_TOGGLE_{setting_name.upper()}",
        ip_address=ip,
        user_agent=ua,
        status="SUCCESS",
        details=json.dumps({"card_id": card.id, "setting": setting_name, "value": val})
    )
    db.add(audit)
    await db.commit()

    return templates.TemplateResponse(
        request=request,
        name="partials/card_settings_toggles.html",
        context={"card": card}
    )


@router.post("/cards/{card_id}/reveal", response_class=HTMLResponse)
async def reveal_sensitive_card_data(
    card_id: int,
    request: Request,
    totp_code: str = Form(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    ip = request.client.host if request.client else "127.0.0.1"
    ua = request.headers.get("User-Agent", "Unknown")

    if not verify_totp_code(user.totp_secret, totp_code):
        audit = AuditLog(
            user_id=user.id,
            action="CARD_REVEAL_FAILED_TOTP",
            ip_address=ip,
            user_agent=ua,
            status="FAILURE",
            details=json.dumps({"card_id": card_id, "reason": "Invalid TOTP"})
        )
        db.add(audit)
        await db.commit()
        return HTMLResponse(
            "<div class='p-3 bg-rose-950 border border-rose-800 text-rose-300 rounded-lg text-sm animate-shake'>"
            "❌ Code TOTP invalide. Révélation refusée par la politique PCI-DSS."
            "</div>",
            status_code=400
        )

    stmt = select(Card).join(Account).where(Card.id == card_id, Account.user_id == user.id)
    res = await db.execute(stmt)
    card = res.scalar_one_or_none()

    if not card:
        return HTMLResponse("<div class='text-rose-400'>Carte introuvable</div>", status_code=404)

    try:
        full_pan = decrypt_card_data(card.encrypted_pan)
        cvv = decrypt_card_data(card.encrypted_cvv)
    except Exception as e:
        return HTMLResponse(f"<div class='text-rose-400'>Erreur cryptographique : {str(e)}</div>", status_code=500)

    audit = AuditLog(
        user_id=user.id,
        action="CARD_DETAILS_REVEALED",
        ip_address=ip,
        user_agent=ua,
        status="SUCCESS",
        details=json.dumps({"card_id": card.id, "masked_pan": card.masked_pan})
    )
    db.add(audit)
    await db.commit()

    return templates.TemplateResponse(
        request=request,
        name="partials/card_reveal_modal.html",
        context={
            "card": card,
            "full_pan": full_pan,
            "cvv": cvv,
            "expiry": f"{card.expiry_month:02d}/{str(card.expiry_year)[-2:]}"
        }
    )

