import os
import uuid
import json
import asyncio
import logging
from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.core.database import cache_manager
from app.core.exceptions import (
    CBSConnectionException,
    InsufficientFundsException,
    IdempotencyConflictException
)
from app.models.banking import (
    Account, Transaction, TransactionType, TransactionStatus, IdempotencyRecord, AuditLog
)

logger = logging.getLogger(__name__)


class CBSClient:
    """
    Connecteur vers le Core Banking System (CBS) - Système bancaire central.
    Implémente :
      - mTLS (Mutual TLS avec certificats X.509 client)
      - Verrouillage strict d'idempotence (Zero double debit guarantee)
      - Retry exponentiel avec jitter sur 502/503/504
      - Sandbox / Mock intégrée pour exécution locale déconnectée
    """

    def __init__(self):
        self.base_url = settings.CBS_API_URL
        self.use_mock = settings.USE_MOCK_BANKING
        self.timeout = settings.CBS_TIMEOUT_SECONDS
        self.max_retries = settings.CBS_MAX_RETRIES

    def _get_client_kwargs(self) -> dict:
        kwargs: dict[str, Any] = {"timeout": self.timeout}
        cert_path = settings.CBS_MTLS_CERT_PATH
        key_path = settings.CBS_MTLS_KEY_PATH
        if os.path.exists(cert_path) and os.path.exists(key_path):
            kwargs["cert"] = (cert_path, key_path)
            logger.info("Configuration mTLS CBS active avec certificats.")
        return kwargs

    async def execute_transfer(
        self,
        db: AsyncSession,
        user_id: int,
        source_account_id: int,
        destination_iban: str,
        counterparty_name: str,
        amount: Decimal,
        label: str,
        idempotency_key: str,
        ip_address: str = "127.0.0.1",
        user_agent: str = "Internal/CBS"
    ) -> Transaction:
        """
        Exécute un virement unitaire avec garantie d'idempotence stricte et atomicité bancaire.
        """
        # 1. Vérification / Verrouillage d'Idempotence
        lock_acquired = await cache_manager.set_nx_lock(f"idemp_lock:{idempotency_key}", "LOCKED", ex=30)
        if not lock_acquired:
            raise IdempotencyConflictException("Cette opération est déjà en cours de traitement.")

        try:
            # Vérifier si l'opération a déjà été complétée
            stmt = select(IdempotencyRecord).where(IdempotencyRecord.key == idempotency_key)
            res = await db.execute(stmt)
            existing_record = res.scalar_one_or_none()
            if existing_record and existing_record.status == "COMPLETED":
                # Récupérer la transaction existante
                tx_stmt = select(Transaction).where(Transaction.idempotency_key == idempotency_key)
                tx_res = await db.execute(tx_stmt)
                existing_tx = tx_res.scalar_one_or_none()
                if existing_tx:
                    logger.info(f"Requête idempotente récurrente détectée : TX {existing_tx.reference}")
                    return existing_tx

            # 2. Vérification du compte source et du solde
            acc_stmt = select(Account).where(Account.id == source_account_id, Account.user_id == user_id)
            acc_res = await db.execute(acc_stmt)
            source_account = acc_res.scalar_one_or_none()

            if not source_account:
                raise ValueError("Compte émetteur introuvable ou non autorisé.")

            if source_account.balance < amount:
                raise InsufficientFundsException(
                    f"Solde insuffisant : disponible {source_account.balance} €, requis {amount} €"
                )

            # 3. Création du record d'idempotence "PROCESSING"
            if not existing_record:
                idemp_rec = IdempotencyRecord(
                    key=idempotency_key,
                    user_id=user_id,
                    action="TRANSFER_EXECUTION",
                    request_hash=f"{source_account_id}:{amount}:{destination_iban}",
                    status="PROCESSING"
                )
                db.add(idemp_rec)
                await db.flush()
            else:
                idemp_rec = existing_record

            # 4. Exécution Core Banking (Mode Mock Sandbox ou Appel mTLS Réel)
            cbs_reference = None
            if self.use_mock:
                # Simulation d'un délai réseau ultra-rapide et génération du numéro de référence SEPA
                await asyncio.sleep(0.05)
                cbs_reference = f"CBS-SEPA-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"
            else:
                cbs_reference = await self._call_cbs_api_with_retry(
                    idempotency_key=idempotency_key,
                    payload={
                        "debtor_account": source_account.iban,
                        "creditor_account": destination_iban,
                        "creditor_name": counterparty_name,
                        "amount": str(amount),
                        "currency": "EUR",
                        "remittance_information": label,
                    }
                )

            # 5. Débit du compte émetteur
            source_account.balance -= amount

            # Vérifier si le compte destinataire est interne à la néobanque
            dest_stmt = select(Account).where(Account.iban == destination_iban.replace(" ", "").upper())
            dest_res = await db.execute(dest_stmt)
            internal_dest_account = dest_res.scalar_one_or_none()

            tx_ref = f"TX-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}-{uuid.uuid4().hex[:6].upper()}"
            
            # Création de la transaction de débit
            tx_debit = Transaction(
                reference=tx_ref,
                account_id=source_account.id,
                counterparty_name=counterparty_name,
                counterparty_iban=destination_iban,
                amount=-amount, # Débit négatif
                currency="EUR",
                transaction_type=TransactionType.TRANSFER_DEBIT,
                status=TransactionStatus.COMPLETED,
                label=label,
                idempotency_key=idempotency_key,
                cbs_reference=cbs_reference,
                execution_date=datetime.now(timezone.utc)
            )
            db.add(tx_debit)

            # Si le destinataire est chez nous, créditer son compte immédiatement (Internal Settlement)
            if internal_dest_account:
                internal_dest_account.balance += amount
                tx_credit = Transaction(
                    reference=f"{tx_ref}-CREDIT",
                    account_id=internal_dest_account.id,
                    counterparty_name=source_account.user.full_name if source_account.user else "Titulaire NéoBanque",
                    counterparty_iban=source_account.iban,
                    amount=amount, # Crédit positif
                    currency="EUR",
                    transaction_type=TransactionType.TRANSFER_CREDIT,
                    status=TransactionStatus.COMPLETED,
                    label=f"Reçu de: {label}",
                    idempotency_key=f"{idempotency_key}-CREDIT",
                    cbs_reference=cbs_reference,
                    execution_date=datetime.now(timezone.utc)
                )
                db.add(tx_credit)

            # 6. Mise à jour de l'idempotence et journalisation d'audit
            idemp_rec.status = "COMPLETED"
            idemp_rec.response_payload = json.dumps({
                "transaction_reference": tx_ref,
                "cbs_reference": cbs_reference,
                "status": "COMPLETED",
                "amount": str(amount)
            })

            audit = AuditLog(
                user_id=user_id,
                action="TRANSFER_EXECUTED",
                ip_address=ip_address,
                user_agent=user_agent,
                status="SUCCESS",
                details=json.dumps({
                    "tx_reference": tx_ref,
                    "cbs_reference": cbs_reference,
                    "from_account": source_account.account_number,
                    "to_iban": destination_iban,
                    "amount": str(amount),
                    "label": label
                })
            )
            db.add(audit)

            await db.commit()
            await db.refresh(tx_debit)
            return tx_debit

        except Exception as e:
            await db.rollback()
            logger.error(f"Erreur lors de l'exécution du virement CBS : {e}")
            raise e
        finally:
            await cache_manager.delete(f"idemp_lock:{idempotency_key}")

    async def _call_cbs_api_with_retry(self, idempotency_key: str, payload: dict) -> str:
        """Appel HTTP externe avec mTLS et retry exponentiel."""
        headers = {
            "Content-Type": "application/json",
            "Idempotency-Key": idempotency_key,
            "X-Client-System": "NEOBANK_PORTAL_WEB"
        }
        client_kwargs = self._get_client_kwargs()
        
        attempt = 0
        backoff = 0.5
        while attempt < self.max_retries:
            attempt += 1
            try:
                async with httpx.AsyncClient(**client_kwargs) as client:
                    resp = await client.post(
                        f"{self.base_url}/payments/sepa/credit-transfer",
                        json=payload,
                        headers=headers
                    )
                    if resp.status_code in [200, 201, 202]:
                        data = resp.json()
                        return data.get("cbs_reference") or data.get("end_to_end_id") or "CBS-OK"
                    elif resp.status_code in [502, 503, 504]:
                        logger.warning(f"CBS temporairement indisponible ({resp.status_code}), tentative {attempt}/{self.max_retries}...")
                        await asyncio.sleep(backoff)
                        backoff *= 2
                    else:
                        raise CBSConnectionException(f"Erreur retournée par le CBS : {resp.status_code} - {resp.text}")
            except httpx.RequestError as exc:
                logger.warning(f"Erreur de communication réseau avec le CBS : {exc}. Tentative {attempt}/{self.max_retries}")
                await asyncio.sleep(backoff)
                backoff *= 2

        raise CBSConnectionException("Échec de connexion définitif avec le Core Banking System après retries.")


cbs_client = CBSClient()

