import pytest
import pytest_asyncio
import uuid
from decimal import Decimal
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select

from app.core.database import Base, cache_manager
from app.models.banking import User, Account, AccountType, Transaction, IdempotencyRecord
from app.services.cbs_client import cbs_client
from app.services.cms_client import cms_client
from app.core.exceptions import InsufficientFundsException


@pytest_asyncio.fixture
async def async_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_cbs_transfer_with_idempotency(async_db: AsyncSession):
    # Création d'un utilisateur et d'un compte de test
    user = User(
        email="test_cbs@neobanque.fr",
        hashed_password="hash",
        full_name="Tester CBS",
        is_totp_enabled=True
    )
    async_db.add(user)
    await async_db.flush()

    source_acc = Account(
        user_id=user.id,
        name="Compte Courant Test",
        account_type=AccountType.CHECKING,
        bank_code="30004",
        branch_code="02050",
        account_number="00011111111",
        rib_key="44",
        iban="FR7630004020500001111111144",
        bic="NEOBFRPPXXX",
        balance=Decimal("1000.00"),
        currency="EUR"
    )
    async_db.add(source_acc)
    await async_db.commit()

    idempotency_key = str(uuid.uuid4())

    # Premier appel : exécution nominale
    tx1 = await cbs_client.execute_transfer(
        db=async_db,
        user_id=user.id,
        source_account_id=source_acc.id,
        destination_iban="FR7630004020500009999999944",
        counterparty_name="Fournisseur Test",
        amount=Decimal("150.00"),
        label="Facture Test 1",
        idempotency_key=idempotency_key
    )

    assert tx1 is not None
    assert tx1.amount == Decimal("-150.00")
    assert tx1.cbs_reference is not None

    # Vérification du solde décrémenté
    await async_db.refresh(source_acc)
    assert source_acc.balance == Decimal("850.00")

    # SECOND APPEL AVEC LA MÊME CLÉ D'IDEMPOTENCE (SIMULATION COUPURE RÉSEAU / RE-SOUMISSION)
    tx2 = await cbs_client.execute_transfer(
        db=async_db,
        user_id=user.id,
        source_account_id=source_acc.id,
        destination_iban="FR7630004020500009999999944",
        counterparty_name="Fournisseur Test",
        amount=Decimal("150.00"),
        label="Facture Test 1",
        idempotency_key=idempotency_key
    )

    # Doit retourner exactement la même transaction SANS re-débiter !
    assert tx2.id == tx1.id
    assert tx2.reference == tx1.reference
    await async_db.refresh(source_acc)
    assert source_acc.balance == Decimal("850.00")  # Solde STRICTEMENT INCHANGÉ (ZÉRO DOUBLE DÉBIT)


@pytest.mark.asyncio
async def test_cbs_insufficient_funds(async_db: AsyncSession):
    user = User(email="poor@neobanque.fr", hashed_password="h", full_name="Poor User")
    async_db.add(user)
    await async_db.flush()

    acc = Account(
        user_id=user.id,
        name="Compte Vide",
        account_type=AccountType.CHECKING,
        bank_code="30004",
        branch_code="02050",
        account_number="00022222222",
        rib_key="44",
        iban="FR7630004020500002222222244",
        bic="NEOBFRPPXXX",
        balance=Decimal("20.00"),
        currency="EUR"
    )
    async_db.add(acc)
    await async_db.commit()

    with pytest.raises(InsufficientFundsException):
        await cbs_client.execute_transfer(
            db=async_db,
            user_id=user.id,
            source_account_id=acc.id,
            destination_iban="FR7630004020500009999999944",
            counterparty_name="Fournisseur",
            amount=Decimal("100.00"),
            label="Tentative dépassement",
            idempotency_key=str(uuid.uuid4())
        )


@pytest.mark.asyncio
async def test_cms_monetique_commands():
    # Test des commandes monétiques temps réel
    res_freeze = await cms_client.freeze_card(1)
    assert res_freeze["status"] == "APPROVED"
    assert res_freeze["action"] == "freeze"

    res_unfreeze = await cms_client.unfreeze_card(1)
    assert res_unfreeze["status"] == "APPROVED"
    assert res_unfreeze["action"] == "unfreeze"

    res_limits = await cms_client.update_limits(1, Decimal("3000.00"), Decimal("12000.00"))
    assert res_limits["status"] == "APPROVED"
