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
    # Vérifier si l'utilisateur de démonstration existe déjà
    stmt = select(User).where(User.email == "demo@neobanque.fr")
    res = await db.execute(stmt)
    existing_user = res.scalar_one_or_none()
    
    if existing_user:
        logger.info("Données de démo déjà initialisées.")
        return

    logger.info("Initialisation du jeu de données de démo bancaire...")

    # 1. Utilisateur de démonstration
    demo_user = User(
        email="demo@neobanque.fr",
        hashed_password=hash_password("Password123!"),
        full_name="Alexandre Dumas",
        phone_number="+33 6 12 34 56 78",
        totp_secret="JBSWY3DPEHPK3PXP",  # Clé TOTP standard de démonstration
        is_totp_enabled=True,
        is_pro=True,
        is_active=True
    )
    db.add(demo_user)
    await db.flush()

    # 2. Comptes bancaires (Courant, Épargne, Pro)
    bank_code = settings.DEFAULT_BANK_CODE
    branch_code = settings.DEFAULT_BRANCH_CODE
    bic = settings.DEFAULT_BIC

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

    # 3. Cartes Bancaires (Physique Metal + Virtuelle)
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

    # 4. Bénéficiaires enregistrés
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

    ben3_acc = "00088888888"
    ben3_key = calculate_rib_key(bank_code, branch_code, ben3_acc)
    ben3_iban = generate_french_iban(bank_code, branch_code, ben3_acc, ben3_key)
    ben3 = Beneficiary(
        user_id=demo_user.id,
        name="Marie Curie (Cabinet Conseil)",
        bank_code=bank_code,
        branch_code=branch_code,
        account_number=ben3_acc,
        rib_key=ben3_key,
        iban=ben3_iban,
        bic=bic,
        is_trusted=True
    )
    db.add(ben3)

    # 5. Historique des transactions
    now = datetime.now(timezone.utc)
    sample_txs = [
        ("Virement reçu - Honoraires Tech Q3", Decimal("4850.00"), TransactionType.TRANSFER_CREDIT, "Google Cloud Ireland", now - timedelta(days=1)),
        ("Prélèvement SEPA Loyer Paris 11", Decimal("-1450.00"), TransactionType.TRANSFER_DEBIT, "Jean Dupont", now - timedelta(days=2)),
        ("Paiement Carte - Apple Store Opéra", Decimal("-1299.00"), TransactionType.CARD_PAYMENT, "Apple Store", now - timedelta(days=3)),
        ("Paiement Carte - SNCF Voyageurs", Decimal("-89.50"), TransactionType.CARD_PAYMENT, "SNCF Connect", now - timedelta(days=4)),
        ("Paiement Carte - Monoprix Gourmet", Decimal("-64.30"), TransactionType.CARD_PAYMENT, "Monoprix Paris", now - timedelta(days=5)),
        ("Virement émis - Facture AWS Cloud", Decimal("-320.40"), TransactionType.TRANSFER_DEBIT, "Amazon Web Services", now - timedelta(days=6)),
        ("Abonnement NéoBanque Metal Care", Decimal("-14.90"), TransactionType.FEE, "NéoBanque SAS", now - timedelta(days=7)),
        ("Virement reçu - Remboursement Sécu", Decimal("+142.80"), TransactionType.SEPA_INCOMING, "CPAM Paris", now - timedelta(days=8)),
        ("Paiement Carte - Restaurant Le Gabriel", Decimal("-185.00"), TransactionType.CARD_PAYMENT, "Restaurant Le Gabriel", now - timedelta(days=9)),
    ]

    for idx, (label, amount, tx_type, counterparty, dt) in enumerate(sample_txs, start=1):
        ref = f"TX-{dt.strftime('%Y%m%d')}-{idx:04d}DEMO"
        tx = Transaction(
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
        )
        db.add(tx)

    # 6. Audit log initial
    initial_audit = AuditLog(
        user_id=demo_user.id,
        action="USER_PROVISIONED",
        ip_address="127.0.0.1",
        user_agent="System/Seed",
        status="SUCCESS",
        details='{"message": "Compte de démonstration configuré avec 3 comptes et 2 cartes"}'
    )
    db.add(initial_audit)

    await db.commit()
    logger.info("Jeu de données de démo initialisé avec succès !")

