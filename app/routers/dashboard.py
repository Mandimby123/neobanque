import json
from decimal import Decimal
from typing import Optional
from fastapi import APIRouter, Depends, Request, Response, Query, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, or_, and_

from app.core.database import get_db
from app.core.security import format_iban
from app.models.banking import (
    User, Account, Card, Beneficiary, Transaction, AuditLog, TransactionType
)
from app.routers.auth import get_current_user
from app.services.pdf_service import pdf_service

router = APIRouter(prefix="", tags=["Dashboard & Comptes"])
templates = Jinja2Templates(directory="app/templates")


@router.api_route("/", methods=["GET", "HEAD"])
async def root(request: Request):
    if request.method == "HEAD":
        return Response(status_code=status.HTTP_200_OK)
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)


@router.api_route("/dashboard", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def dashboard_view(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    acc_stmt = select(Account).where(Account.user_id == user.id, Account.is_active == True)
    acc_res = await db.execute(acc_stmt)
    accounts = list(acc_res.scalars().all())

    total_balance = sum((acc.balance for acc in accounts), Decimal("0.00"))

    card_stmt = select(Card).join(Account).where(Account.user_id == user.id)
    card_res = await db.execute(card_stmt)
    cards = list(card_res.scalars().all())

    tx_stmt = (
        select(Transaction)
        .join(Account)
        .where(Account.user_id == user.id)
        .order_by(desc(Transaction.execution_date))
        .limit(10)
    )
    tx_res = await db.execute(tx_stmt)
    recent_transactions = list(tx_res.scalars().all())

    ben_stmt = select(Beneficiary).where(Beneficiary.user_id == user.id)
    ben_res = await db.execute(ben_stmt)
    beneficiaries = list(ben_res.scalars().all())

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "user": user,
            "accounts": accounts,
            "cards": cards,
            "total_balance": total_balance,
            "recent_transactions": recent_transactions,
            "beneficiaries": beneficiaries,
            "format_iban": format_iban
        }
    )


@router.get("/accounts/{account_id}/rib", response_class=HTMLResponse)
async def get_rib_modal(
    account_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Account).where(Account.id == account_id, Account.user_id == user.id)
    res = await db.execute(stmt)
    account = res.scalar_one_or_none()

    if not account:
        return HTMLResponse("<div class='p-4 text-rose-400'>Compte introuvable</div>", status_code=404)

    return templates.TemplateResponse(
        request=request,
        name="partials/rib_modal.html",
        context={
            "user": user,
            "account": account,
            "formatted_iban": format_iban(account.iban)
        }
    )


@router.get("/accounts/{account_id}/rib/pdf")
async def download_rib_pdf(
    account_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Account).where(Account.id == account_id, Account.user_id == user.id)
    res = await db.execute(stmt)
    account = res.scalar_one_or_none()

    if not account:
        return Response(content="Compte introuvable", status_code=404)

    pdf_bytes = pdf_service.generate_rib_pdf(account, user)

    ip = request.client.host if request.client else "127.0.0.1"
    ua = request.headers.get("User-Agent", "Unknown")
    audit = AuditLog(
        user_id=user.id,
        action="RIB_DOWNLOADED",
        ip_address=ip,
        user_agent=ua,
        status="SUCCESS",
        details=json.dumps({"account_number": account.account_number, "iban": account.iban})
    )
    db.add(audit)
    await db.commit()

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=RIB_{account.account_number}.pdf",
            "Cache-Control": "no-store, no-cache, must-revalidate"
        }
    )


@router.get("/transactions", response_class=HTMLResponse)
async def filter_transactions(
    request: Request,
    account_id: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    tx_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(8, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    query = select(Transaction).join(Account).where(Account.user_id == user.id)

    if account_id:
        query = query.where(Transaction.account_id == account_id)

    if tx_type:
        if tx_type == "CREDIT":
            query = query.where(Transaction.amount > 0)
        elif tx_type == "DEBIT":
            query = query.where(Transaction.amount < 0)
        elif tx_type == "CARD":
            query = query.where(Transaction.transaction_type == TransactionType.CARD_PAYMENT)

    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.where(
            or_(
                Transaction.label.ilike(term),
                Transaction.counterparty_name.ilike(term),
                Transaction.reference.ilike(term)
            )
        )

    query = query.order_by(desc(Transaction.execution_date))
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size + 1)

    res = await db.execute(query)
    all_results = list(res.scalars().all())

    has_next = len(all_results) > page_size
    transactions = all_results[:page_size]

    return templates.TemplateResponse(
        request=request,
        name="partials/tx_table.html",
        context={
            "transactions": transactions,
            "page": page,
            "has_next": has_next,
            "account_id": account_id,
            "search": search,
            "tx_type": tx_type
        }
    )


@router.get("/audit", response_class=HTMLResponse)
async def audit_logs_view(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = (
        select(AuditLog)
        .where(AuditLog.user_id == user.id)
        .order_by(desc(AuditLog.timestamp))
        .limit(50)
    )
    res = await db.execute(stmt)
    logs = list(res.scalars().all())

    return templates.TemplateResponse(
        request=request,
        name="audit.html",
        context={
            "user": user,
            "logs": logs
        }
    )

