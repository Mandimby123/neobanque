import uuid
import json
from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, Request, Response, Form, UploadFile, File, status, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import verify_totp_code, format_iban
from app.models.banking import User, Account, Beneficiary, AuditLog
from app.routers.auth import get_current_user
from app.services.cbs_client import cbs_client
from app.services.afb160_service import afb160_service
from app.schemas.banking import BeneficiaryCreate

router = APIRouter(prefix="", tags=["Virements & AFB 160"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/transfers", response_class=HTMLResponse)
async def transfers_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    acc_stmt = select(Account).where(Account.user_id == user.id, Account.is_active == True)
    acc_res = await db.execute(acc_stmt)
    accounts = list(acc_res.scalars().all())

    ben_stmt = select(Beneficiary).where(Beneficiary.user_id == user.id)
    ben_res = await db.execute(ben_stmt)
    beneficiaries = list(ben_res.scalars().all())

    return templates.TemplateResponse(
        request=request,
        name="transfers.html",
        context={
            "user": user,
            "accounts": accounts,
            "beneficiaries": beneficiaries,
            "format_iban": format_iban
        }
    )


# ==============================================================================
# STEPPER HTMX DE VIREMENT UNITAIRE (3 ÉTAPES SÉCURISÉES)
# ==============================================================================
@router.get("/transfers/stepper", response_class=HTMLResponse)
async def transfer_stepper_step1(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    acc_stmt = select(Account).where(Account.user_id == user.id, Account.is_active == True)
    acc_res = await db.execute(acc_stmt)
    accounts = list(acc_res.scalars().all())

    ben_stmt = select(Beneficiary).where(Beneficiary.user_id == user.id)
    ben_res = await db.execute(ben_stmt)
    beneficiaries = list(ben_res.scalars().all())

    return templates.TemplateResponse(
        request=request,
        name="partials/transfer_step1.html",
        context={
            "accounts": accounts,
            "beneficiaries": beneficiaries,
            "format_iban": format_iban
        }
    )


@router.post("/transfers/step2", response_class=HTMLResponse)
async def transfer_stepper_step2(
    request: Request,
    source_account_id: int = Form(...),
    beneficiary_id: int = Form(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    acc_stmt = select(Account).where(Account.id == source_account_id, Account.user_id == user.id)
    acc_res = await db.execute(acc_stmt)
    source_acc = acc_res.scalar_one_or_none()

    ben_stmt = select(Beneficiary).where(Beneficiary.id == beneficiary_id, Beneficiary.user_id == user.id)
    ben_res = await db.execute(ben_stmt)
    beneficiary = ben_res.scalar_one_or_none()

    if not source_acc or not beneficiary:
        return HTMLResponse(
            "<div class='p-3 bg-rose-950/80 border border-rose-800 text-rose-300 rounded-lg'>Sélection invalide.</div>",
            status_code=400
        )

    return templates.TemplateResponse(
        request=request,
        name="partials/transfer_step2.html",
        context={
            "source_acc": source_acc,
            "beneficiary": beneficiary,
            "format_iban": format_iban
        }
    )


@router.post("/transfers/step3", response_class=HTMLResponse)
async def transfer_stepper_step3(
    request: Request,
    source_account_id: int = Form(...),
    beneficiary_id: int = Form(...),
    amount: str = Form(...),
    label: str = Form("Virement NéoBanque"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    try:
        amount_decimal = Decimal(amount.replace(",", ".").strip())
    except Exception:
        return HTMLResponse(
            "<div class='p-3 bg-rose-950/80 border border-rose-800 text-rose-300 rounded-lg'>Montant numérique invalide.</div>",
            status_code=400
        )

    if amount_decimal <= Decimal("0.00"):
        return HTMLResponse(
            "<div class='p-3 bg-rose-950/80 border border-rose-800 text-rose-300 rounded-lg'>Le montant doit être supérieur à 0,00 €.</div>",
            status_code=400
        )

    acc_stmt = select(Account).where(Account.id == source_account_id, Account.user_id == user.id)
    acc_res = await db.execute(acc_stmt)
    source_acc = acc_res.scalar_one_or_none()

    if not source_acc or source_acc.balance < amount_decimal:
        return HTMLResponse(
            f"<div class='p-3 bg-rose-950/80 border border-rose-800 text-rose-300 rounded-lg'>Solde disponible insuffisant ({source_acc.balance if source_acc else 0} €).</div>",
            status_code=422
        )

    ben_stmt = select(Beneficiary).where(Beneficiary.id == beneficiary_id, Beneficiary.user_id == user.id)
    ben_res = await db.execute(ben_stmt)
    beneficiary = ben_res.scalar_one_or_none()

    idempotency_key = str(uuid.uuid4())

    return templates.TemplateResponse(
        request=request,
        name="partials/transfer_step3.html",
        context={
            "source_acc": source_acc,
            "beneficiary": beneficiary,
            "amount": amount_decimal,
            "label": label.strip(),
            "idempotency_key": idempotency_key,
            "format_iban": format_iban
        }
    )


@router.post("/transfers/execute", response_class=HTMLResponse)
async def transfer_execute(
    request: Request,
    source_account_id: int = Form(...),
    beneficiary_id: int = Form(...),
    amount: str = Form(...),
    label: str = Form(...),
    idempotency_key: str = Form(...),
    totp_code: str = Form(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    ip = request.client.host if request.client else "127.0.0.1"
    ua = request.headers.get("User-Agent", "Unknown")

    if not verify_totp_code(user.totp_secret, totp_code):
        audit = AuditLog(
            user_id=user.id,
            action="TRANSFER_REJECTED_TOTP",
            ip_address=ip,
            user_agent=ua,
            status="FAILURE",
            details=json.dumps({"reason": "Invalid TOTP for transfer", "idempotency_key": idempotency_key})
        )
        db.add(audit)
        await db.commit()
        return HTMLResponse(
            "<div class='p-4 bg-rose-950/90 border border-rose-800 text-rose-300 rounded-xl animate-shake font-medium'>"
            "⚠️ Code 2FA TOTP invalide ou expiré. Veuillez vérifier votre application d'authentification."
            "</div>",
            status_code=400
        )

    amount_decimal = Decimal(amount)

    ben_stmt = select(Beneficiary).where(Beneficiary.id == beneficiary_id, Beneficiary.user_id == user.id)
    ben_res = await db.execute(ben_stmt)
    beneficiary = ben_res.scalar_one_or_none()

    if not beneficiary:
        return HTMLResponse("<div class='p-3 bg-rose-950 text-rose-300 rounded-lg'>Bénéficiaire introuvable</div>", status_code=400)

    try:
        tx = await cbs_client.execute_transfer(
            db=db,
            user_id=user.id,
            source_account_id=source_account_id,
            destination_iban=beneficiary.iban,
            counterparty_name=beneficiary.name,
            amount=amount_decimal,
            label=label,
            idempotency_key=idempotency_key,
            ip_address=ip,
            user_agent=ua
        )

        return templates.TemplateResponse(
            request=request,
            name="partials/transfer_success.html",
            context={
                "tx": tx,
                "beneficiary": beneficiary,
                "amount": amount_decimal,
                "format_iban": format_iban
            },
            headers={"HX-Trigger": "refreshAccounts"}
        )

    except Exception as e:
        return HTMLResponse(
            f"<div class='p-4 bg-rose-950/90 border border-rose-800 text-rose-300 rounded-xl font-medium'>"
            f"❌ Échec du virement bancaire : {str(e)}"
            f"</div>",
            status_code=400
        )


@router.post("/beneficiaries/quick-add", response_class=HTMLResponse)
async def quick_add_beneficiary(
    request: Request,
    name: str = Form(...),
    bank_code: str = Form(...),
    branch_code: str = Form(...),
    account_number: str = Form(...),
    rib_key: Optional[str] = Form(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    try:
        b_create = BeneficiaryCreate(
            name=name.strip(),
            bank_code=bank_code.strip(),
            branch_code=branch_code.strip(),
            account_number=account_number.strip().upper(),
            rib_key=rib_key.strip() if rib_key else None
        )
        calculated_key, iban = b_create.resolve_rib_and_iban()

        beneficiary = Beneficiary(
            user_id=user.id,
            name=b_create.name,
            bank_code=b_create.bank_code,
            branch_code=b_create.branch_code,
            account_number=b_create.account_number,
            rib_key=calculated_key,
            iban=iban,
            bic="NEOBFRPPXXX",
            is_trusted=True
        )
        db.add(beneficiary)
        await db.commit()
        await db.refresh(beneficiary)

        return HTMLResponse(
            f"""
            <div class="p-3 bg-emerald-950/80 border border-emerald-800 text-emerald-300 rounded-xl text-sm flex items-center justify-between">
                <div>
                    <span class="font-semibold block">{beneficiary.name} ajouté !</span>
                    <span class="text-xs text-emerald-400">IBAN : {format_iban(beneficiary.iban)}</span>
                </div>
                <span class="text-xs bg-emerald-900/60 px-2 py-1 rounded text-emerald-200">Clé RIB {beneficiary.rib_key} validée</span>
            </div>
            """,
            headers={"HX-Trigger": "beneficiaryAdded"}
        )
    except Exception as e:
        return HTMLResponse(
            f"""
            <div class="p-3 bg-rose-950/80 border border-rose-800 text-rose-300 rounded-xl text-sm">
                <b>Erreur coordonnées bancaires :</b> {str(e)}
            </div>
            """,
            status_code=400
        )


@router.post("/transfers/afb160/preview", response_class=HTMLResponse)
async def preview_afb160_csv(
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user)
):
    if not user.is_pro:
        return HTMLResponse(
            """
            <div class="p-4 bg-amber-950/90 border border-amber-800 text-amber-200 rounded-2xl text-xs flex items-center space-x-3">
                <svg class="w-5 h-5 text-amber-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"/>
                </svg>
                <div>
                    <span class="font-bold block">Accès Restreint aux Clients Corporate</span>
                    <span>L'émission et l'analyse de fichiers de virements de masse AFB 160 sont réservées aux comptes professionnels et entreprises.</span>
                </div>
            </div>
            """,
            status_code=403
        )
    try:
        content_bytes = await file.read()
        csv_text = content_bytes.decode("utf-8", errors="replace")

        items, errors, total_amount = afb160_service.parse_csv_recipients(csv_text)

        return templates.TemplateResponse(
            request=request,
            name="partials/afb160_preview.html",
            context={
                "items": items,
                "errors": errors,
                "total_amount": total_amount,
                "raw_csv": csv_text
            }
        )
    except Exception as e:
        return HTMLResponse(
            f"<div class='p-3 bg-rose-950 text-rose-300 rounded-lg'>Erreur lecture fichier : {str(e)}</div>",
            status_code=400
        )


@router.post("/transfers/afb160/download")
async def download_afb160_file(
    request: Request,
    source_account_id: int = Form(...),
    raw_csv: str = Form(...),
    totp_code: str = Form(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if not user.is_pro:
        return HTMLResponse(
            "<div class='p-3 bg-rose-950 border border-rose-800 text-rose-300 rounded-xl text-xs'>Action réservée aux comptes Corporate.</div>",
            status_code=403
        )

    ip = request.client.host if request.client else "127.0.0.1"
    ua = request.headers.get("User-Agent", "Unknown")

    if not verify_totp_code(user.totp_secret, totp_code):
        return HTMLResponse("<div class='p-3 bg-rose-950 text-rose-300 rounded-lg'>Code 2FA TOTP invalide.</div>", status_code=400)

    acc_stmt = select(Account).where(Account.id == source_account_id, Account.user_id == user.id)
    acc_res = await db.execute(acc_stmt)
    account = acc_res.scalar_one_or_none()

    if not account:
        return HTMLResponse("<div class='p-3 bg-rose-950 text-rose-300 rounded-lg'>Compte émetteur introuvable.</div>", status_code=400)

    items, errors, total_amount = afb160_service.parse_csv_recipients(raw_csv)
    if not items:
        return HTMLResponse("<div class='p-3 bg-rose-950 text-rose-300 rounded-lg'>Aucun virement valide dans le lot.</div>", status_code=400)

    afb160_content = afb160_service.generate_afb160(
        sender_bank_code=account.bank_code,
        sender_branch_code=account.branch_code,
        sender_account_number=account.account_number,
        sender_name=user.full_name,
        items=items
    )

    audit = AuditLog(
        user_id=user.id,
        action="AFB160_GENERATED",
        ip_address=ip,
        user_agent=ua,
        status="SUCCESS",
        details=json.dumps({
            "account_number": account.account_number,
            "transfers_count": len(items),
            "total_amount": str(total_amount)
        })
    )
    db.add(audit)
    await db.commit()

    date_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    filename = f"AFB160_{account.account_number}_{date_str}.txt"

    return Response(
        content=afb160_content.encode("latin-1", errors="replace"),
        media_type="text/plain; charset=iso-8859-1",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "Cache-Control": "no-store, no-cache, must-revalidate"
        }
    )

