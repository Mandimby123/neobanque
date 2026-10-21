import enum
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, List
from sqlalchemy import (
    String, Boolean, Integer, Numeric, DateTime, ForeignKey, Enum as SQLEnum, Text
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class AccountType(str, enum.Enum):
    CHECKING = "CHECKING"      # Compte Courant
    SAVINGS = "SAVINGS"        # Compte Épargne / Livret
    PRO = "PRO"                # Compte Professionnel


class TransactionType(str, enum.Enum):
    TRANSFER_DEBIT = "TRANSFER_DEBIT"
    TRANSFER_CREDIT = "TRANSFER_CREDIT"
    CARD_PAYMENT = "CARD_PAYMENT"
    SEPA_INCOMING = "SEPA_INCOMING"
    MASS_TRANSFER = "MASS_TRANSFER"
    FEE = "FEE"


class TransactionStatus(str, enum.Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class CardType(str, enum.Enum):
    PHYSICAL_METAL = "PHYSICAL_METAL"
    VIRTUAL = "VIRTUAL"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    
    # Sécurité & 2FA TOTP
    totp_secret: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    is_totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_pro: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relations
    accounts: Mapped[List["Account"]] = relationship("Account", back_populates="user", cascade="all, delete-orphan")
    beneficiaries: Mapped[List["Beneficiary"]] = relationship("Beneficiary", back_populates="user", cascade="all, delete-orphan")
    audit_logs: Mapped[List["AuditLog"]] = relationship("AuditLog", back_populates="user")


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    account_type: Mapped[AccountType] = mapped_column(
        SQLEnum(AccountType, name="account_type_enum"),
        default=AccountType.CHECKING,
        nullable=False
    )
    
    # Coordonnées bancaires nationales & SEPA
    bank_code: Mapped[str] = mapped_column(String(5), nullable=False)        # Ex: 30004
    branch_code: Mapped[str] = mapped_column(String(5), nullable=False)      # Ex: 02050
    account_number: Mapped[str] = mapped_column(String(11), nullable=False, unique=True, index=True) # 11 car.
    rib_key: Mapped[str] = mapped_column(String(2), nullable=False)         # Ex: 44
    iban: Mapped[str] = mapped_column(String(34), unique=True, index=True, nullable=False)
    bic: Mapped[str] = mapped_column(String(11), nullable=False)            # Ex: NEOBFRPPXXX
    
    # Solde strict Decimal
    balance: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0.00"), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)
    
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relations
    user: Mapped["User"] = relationship("User", back_populates="accounts")
    cards: Mapped[List["Card"]] = relationship("Card", back_populates="account", cascade="all, delete-orphan")


class Card(Base):
    __tablename__ = "cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    
    card_holder: Mapped[str] = mapped_column(String(150), nullable=False)
    card_type: Mapped[CardType] = mapped_column(
        SQLEnum(CardType, name="card_type_enum"),
        default=CardType.PHYSICAL_METAL,
        nullable=False
    )
    
    # Masquage PCI-DSS strict :
    # Le PAN complet et CVV ne sont JAMAIS en clair dans la base
    masked_pan: Mapped[str] = mapped_column(String(25), nullable=False)  # Ex: 4970 **** **** 8821
    encrypted_pan: Mapped[str] = mapped_column(Text, nullable=False)     # Chiffré Fernet AES-256
    encrypted_cvv: Mapped[str] = mapped_column(Text, nullable=False)     # Chiffré Fernet AES-256
    
    expiry_month: Mapped[int] = mapped_column(Integer, nullable=False)   # Ex: 10
    expiry_year: Mapped[int] = mapped_column(Integer, nullable=False)    # Ex: 2028
    
    # Contrôles monétiques temps réel (CMS)
    is_frozen: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    online_payments_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    foreign_payments_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    contactless_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
    # Plafonds
    daily_limit: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("1500.00"), nullable=False)
    monthly_limit: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("5000.00"), nullable=False)
    daily_spent: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"), nullable=False)
    monthly_spent: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"), nullable=False)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relations
    account: Mapped["Account"] = relationship("Account", back_populates="cards")


class Beneficiary(Base):
    __tablename__ = "beneficiaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    bank_code: Mapped[str] = mapped_column(String(5), nullable=False)
    branch_code: Mapped[str] = mapped_column(String(5), nullable=False)
    account_number: Mapped[str] = mapped_column(String(11), nullable=False)
    rib_key: Mapped[str] = mapped_column(String(2), nullable=False)
    iban: Mapped[str] = mapped_column(String(34), nullable=False)
    bic: Mapped[str] = mapped_column(String(11), nullable=False)
    is_trusted: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    user: Mapped["User"] = relationship("User", back_populates="beneficiaries")


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reference: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    counterparty_name: Mapped[str] = mapped_column(String(150), nullable=False)
    counterparty_iban: Mapped[Optional[str]] = mapped_column(String(34), nullable=True)
    
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False) # Positif pour crédit, négatif pour débit
    currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)
    
    transaction_type: Mapped[TransactionType] = mapped_column(
        SQLEnum(TransactionType, name="tx_type_enum"),
        nullable=False
    )
    status: Mapped[TransactionStatus] = mapped_column(
        SQLEnum(TransactionStatus, name="tx_status_enum"),
        default=TransactionStatus.COMPLETED,
        nullable=False
    )
    
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(64), index=True, nullable=True)
    cbs_reference: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    
    execution_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )


class AuditLog(Base):
    """Table d'audit immuable (PCI-DSS & Réglementation bancaire ACPR / EBA)."""
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    ip_address: Mapped[str] = mapped_column(String(64), nullable=False)
    user_agent: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="SUCCESS", nullable=False)
    details: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True
    )

    user: Mapped[Optional["User"]] = relationship("User", back_populates="audit_logs")


class IdempotencyRecord(Base):
    """Stockage persistant des verrous et réponses d'idempotence."""
    __tablename__ = "idempotency_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="PROCESSING", nullable=False) # PROCESSING, COMPLETED, FAILED
    response_payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

