import logging
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.banking import (
    User, Account, AccountType, Card, CardType, Beneficiary,
    Transaction, TransactionType, TransactionStatus, AuditLog
)
from app.core.security import (
    hash_password, encrypt_card_data, calculate_rib_key, generate_french_iban
)
from app.core.config import settings

logger = logging.getLogger(__name__)


async def seed_demo_data(db: AsyncSession):
    """Initialise un jeu complet et réaliste de données bancaires au premier démarrage."""
    bank_code = settings.DEFAULT_BANK_CODE
    branch_code = settings.DEFAULT_BRANCH_CODE
    bic = settings.DEFAULT_BIC
    now = datetime.now(timezone.utc)

    # 1. Vérification / Création de l'utilisateur Corporate
    stmt = select(User).where(User.email == "demo@neobanque.fr")
    res = await db.execute(stmt)
    demo_user = res.scalar_one_or_none()
    
    if not demo_user:
        logger.info("Amorçage de l'utilisateur Corporate (demo@neobanque.fr)...")
        demo_user = User(
            email="demo@neobanque.fr",
            hashed_password=hash_password("Password123!"),
            full_name="Alexandre Dumas",
            phone_number="+33 6 12 34 56 78",
            totp_secret="JBSWY3DPEHPK3PXP",
            is_totp_enabled=True,
            is_pro=True,
            is_active=True
        )
        db.add(demo_user)
        await db.flush()

        # Compte Courant Principal
        acc1_num = "00012345678"
        acc1_key = calculate_rib_key(bank_code, branch_code, acc1_num)
        acc1_iban = generate_french_iban(bank_code, branch_code, acc1_num, acc1_key)
        account_current = Account(
            user_id=demo_user.id,
            name="Compte Courant Principal",
            account_type=AccountType.CHECKING,
            bank_code=bank_code,
            branch_code=branch_code,
            account_number=acc1_num,
            rib_key=acc1_key,
            iban=acc1_iban,
            bic=bic,
            balance=Decimal("14850.50"),
            currency="EUR"
        )
        db.add(account_current)

        # Compte Épargne Livret A+
        acc2_num = "00098765432"
        acc2_key = calculate_rib_key(bank_code, branch_code, acc2_num)
        acc2_iban = generate_french_iban(bank_code, branch_code, acc2_num, acc2_key)
        account_savings = Account(
            user_id=demo_user.id,
            name="Livret Épargne A+",
            account_type=AccountType.SAVINGS,
            bank_code=bank_code,
            branch_code=branch_code,
            account_number=acc2_num,
            rib_key=acc2_key,
            iban=acc2_iban,
            bic=bic,
            balance=Decimal("22500.00"),
            currency="EUR"
        )
        db.add(account_savings)

        # Compte Professionnel
        acc3_num = "00055566677"
        acc3_key = calculate_rib_key(bank_code, branch_code, acc3_num)
        acc3_iban = generate_french_iban(bank_code, branch_code, acc3_num, acc3_key)
        account_pro = Account(
            user_id=demo_user.id,
            name="Compte Professionnel SARL",
            account_type=AccountType.PRO,
            bank_code=bank_code,
            branch_code=branch_code,
            account_number=acc3_num,
            rib_key=acc3_key,
            iban=acc3_iban,
            bic=bic,
            balance=Decimal("58400.00"),
            currency="EUR"
        )
        db.add(account_pro)
        await db.flush()

        # Cartes Bancaires (Physique Metal + Virtuelle)
        card_metal = Card(
            account_id=account_current.id,
            card_holder="ALEXANDRE DUMAS",
            card_type=CardType.PHYSICAL_METAL,
            masked_pan="4970 **** **** 8821",
            encrypted_pan=encrypt_card_data("4970123456788821"),
            encrypted_cvv=encrypt_card_data("742"),
            expiry_month=12,
            expiry_year=2028,
            is_frozen=False,
            online_payments_enabled=True,
            foreign_payments_enabled=True,
            contactless_enabled=True,
            daily_limit=Decimal("2500.00"),
            monthly_limit=Decimal("10000.00"),
            daily_spent=Decimal("345.50"),
            monthly_spent=Decimal("1890.00")
        )
        db.add(card_metal)

        card_virtual = Card(
            account_id=account_current.id,
            card_holder="ALEXANDRE DUMAS (VIRTUAL)",
            card_type=CardType.VIRTUAL,
            masked_pan="4970 **** **** 3319",
            encrypted_pan=encrypt_card_data("4970987654323319"),
            encrypted_cvv=encrypt_card_data("915"),
            expiry_month=9,
            expiry_year=2027,
            is_frozen=False,
            online_payments_enabled=True,
            foreign_payments_enabled=False,
            contactless_enabled=False,
            daily_limit=Decimal("1000.00"),
            monthly_limit=Decimal("3000.00"),
            daily_spent=Decimal("49.99"),
            monthly_spent=Decimal("120.00")
        )
        db.add(card_virtual)

        # Bénéficiaires enregistrés
        ben1_acc = "00099999999"
        ben1_key = calculate_rib_key(bank_code, branch_code, ben1_acc)
        ben1_iban = generate_french_iban(bank_code, branch_code, ben1_acc, ben1_key)
        ben1 = Beneficiary(
            user_id=demo_user.id,
            name="Jean Dupont (Propriétaire)",
            bank_code=bank_code,
            branch_code=branch_code,
            account_number=ben1_acc,
            rib_key=ben1_key,
            iban=ben1_iban,
            bic=bic,
            is_trusted=True
        )
        db.add(ben1)

        ben2_acc = "00077777777"
        ben2_key = calculate_rib_key(bank_code, branch_code, ben2_acc)
        ben2_iban = generate_french_iban(bank_code, branch_code, ben2_acc, ben2_key)
        ben2 = Beneficiary(
            user_id=demo_user.id,
            name="Amazon Web Services EMEA",
            bank_code=bank_code,
            branch_code=branch_code,
            account_number=ben2_acc,
            rib_key=ben2_key,
            iban=ben2_iban,
            bic=bic,
            is_trusted=True
        )
        db.add(ben2)

        # Transactions initiales Corporate
        now = datetime.now(timezone.utc)
        sample_txs = [
            ("Virement reçu - Honoraires Tech Q3", Decimal("4850.00"), TransactionType.TRANSFER_CREDIT, "Google Cloud Ireland", now - timedelta(days=1)),
            ("Prélèvement SEPA Loyer Paris 11", Decimal("-1450.00"), TransactionType.TRANSFER_DEBIT, "Jean Dupont", now - timedelta(days=2)),
            ("Paiement Carte - Apple Store Opéra", Decimal("-1299.00"), TransactionType.CARD_PAYMENT, "Apple Store", now - timedelta(days=3)),
            ("Paiement Carte - SNCF Voyageurs", Decimal("-89.50"), TransactionType.CARD_PAYMENT, "SNCF Connect", now - timedelta(days=4)),
            ("Abonnement NéoBanque Metal Care", Decimal("-14.90"), TransactionType.FEE, "NéoBanque SAS", now - timedelta(days=7)),
        ]
        for idx, (label, amount, tx_type, counterparty, dt) in enumerate(sample_txs, start=1):
            ref = f"TX-{dt.strftime('%Y%m%d')}-{idx:04d}DEMO"
            db.add(Transaction(
                reference=ref,
                account_id=account_current.id,
                counterparty_name=counterparty,
                counterparty_iban=ben1_iban,
                amount=amount,
                currency="EUR",
                transaction_type=tx_type,
                status=TransactionStatus.COMPLETED,
                label=label,
                cbs_reference=f"CBS-DEMO-REF-{idx:04d}",
                execution_date=dt,
                created_at=dt
            ))

        db.add(AuditLog(
            user_id=demo_user.id,
            action="USER_PROVISIONED",
            ip_address="127.0.0.1",
            user_agent="System/Seed",
            status="SUCCESS",
            details='{"message": "Compte Corporate configuré avec 3 comptes et 2 cartes", "profile": "CORPORATE"}'
        ))

    # 7. Utilisateur Client Particulier (sans accès AFB 160)
    stmt_part = select(User).where(User.email == "particulier@neobanque.fr")
    res_part = await db.execute(stmt_part)
    if not res_part.scalar_one_or_none():
        part_user = User(
            email="particulier@neobanque.fr",
            hashed_password=hash_password("Password123!"),
            full_name="Camille Bernard",
            phone_number="+33 6 98 76 54 32",
            totp_secret="JBSWY3DPEHPK3PXP",
            is_totp_enabled=True,
            is_pro=False,  # Profil Client Particulier (Virements unitaires uniquement)
            is_active=True
        )
        db.add(part_user)
        await db.flush()

        part_acc_num = "00033334444"
        part_acc_key = calculate_rib_key(bank_code, branch_code, part_acc_num)
        part_iban = generate_french_iban(bank_code, branch_code, part_acc_num, part_acc_key)
        part_acc = Account(
            user_id=part_user.id,
            name="Compte Courant Personnel",
            account_type=AccountType.CHECKING,
            bank_code=bank_code,
            branch_code=branch_code,
            account_number=part_acc_num,
            rib_key=part_acc_key,
            iban=part_iban,
            bic=bic,
            balance=Decimal("3850.20"),
            currency="EUR"
        )
        db.add(part_acc)
        await db.flush()

        part_card = Card(
            account_id=part_acc.id,
            card_holder="CAMILLE BERNARD",
            card_type=CardType.PHYSICAL_METAL,
            masked_pan="4970 **** **** 6023",
            encrypted_pan=encrypt_card_data("4970112233446023"),
            encrypted_cvv=encrypt_card_data("418"),
            expiry_month=6,
            expiry_year=2028,
            is_frozen=False,
            online_payments_enabled=True,
            foreign_payments_enabled=False,
            contactless_enabled=True,
            daily_limit=Decimal("1200.00"),
            monthly_limit=Decimal("4000.00"),
            daily_spent=Decimal("85.00"),
            monthly_spent=Decimal("650.00")
        )
        db.add(part_card)

        part_ben_num = "00012345678"
        part_ben_key = calculate_rib_key(bank_code, branch_code, part_ben_num)
        part_ben_iban = generate_french_iban(bank_code, branch_code, part_ben_num, part_ben_key)
        part_ben = Beneficiary(
            user_id=part_user.id,
            name="Alexandre Dumas (Ami)",
            bank_code=bank_code,
            branch_code=branch_code,
            account_number=part_ben_num,
            rib_key=part_ben_key,
            iban=part_ben_iban,
            bic=bic,
            is_trusted=True
        )
        db.add(part_ben)

        part_tx = Transaction(
            reference=f"TX-{now.strftime('%Y%m%d')}-PART01",
            account_id=part_acc.id,
            counterparty_name="Employeur Tech SAS",
            counterparty_iban=part_ben_iban,
            amount=Decimal("2850.00"),
            currency="EUR",
            transaction_type=TransactionType.TRANSFER_CREDIT,
            status=TransactionStatus.COMPLETED,
            label="Salaire Mensuel Net",
            cbs_reference="CBS-SALAIRE-PART-01",
            execution_date=now - timedelta(days=2),
            created_at=now - timedelta(days=2)
        )
        db.add(part_tx)

        db.add(AuditLog(
            user_id=part_user.id,
            action="USER_PROVISIONED",
            ip_address="127.0.0.1",
            user_agent="System/Seed",
            status="SUCCESS",
            details='{"profile": "PARTICULIER"}'
        ))

    await db.commit()
    logger.info("Jeu de données de démo initialisé avec succès !")

