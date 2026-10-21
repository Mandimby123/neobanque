from decimal import Decimal
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, EmailStr, Field, field_validator, ConfigDict
from app.models.banking import AccountType, CardType, TransactionType, TransactionStatus
from app.core.security import validate_french_rib, calculate_rib_key, validate_iban, generate_french_iban


# ==============================================================================
# SCHÉMAS AUTHENTIFICATION & SÉCURITÉ
# ==============================================================================
class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, description="Mot de passe utilisateur")


class TOTPVerifyRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=6, description="Code TOTP à 6 chiffres")

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        clean = v.strip().replace(" ", "")
        if not clean.isdigit() or len(clean) != 6:
            raise ValueError("Le code TOTP doit contenir exactement 6 chiffres.")
        return clean


class PasswordResetRequest(BaseModel):
    email: EmailStr
    totp_code: str = Field(..., min_length=6, max_length=6)
    new_password: str = Field(..., min_length=8)


class UserResponse(BaseModel):
    id: int
    email: str
    full_name: str
    phone_number: Optional[str] = None
    is_totp_enabled: bool
    is_pro: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# SCHÉMAS COMPTES & RIB
# ==============================================================================
class AccountResponse(BaseModel):
    id: int
    user_id: int
    name: str
    account_type: AccountType
    bank_code: str
    branch_code: str
    account_number: str
    rib_key: str
    iban: str
    bic: str
    balance: Decimal
    currency: str
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class RIBResponse(BaseModel):
    account_name: str
    holder_name: str
    bank_code: str
    branch_code: str
    account_number: str
    rib_key: str
    iban: str
    bic: str
    formatted_iban: str
    formatted_rib: str


# ==============================================================================
# SCHÉMAS CARTES & PCI-DSS
# ==============================================================================
class CardResponse(BaseModel):
    id: int
    account_id: int
    card_holder: str
    card_type: CardType
    masked_pan: str
    expiry_month: int
    expiry_year: int
    is_frozen: bool
    online_payments_enabled: bool
    foreign_payments_enabled: bool
    contactless_enabled: bool
    daily_limit: Decimal
    monthly_limit: Decimal
    daily_spent: Decimal
    monthly_spent: Decimal

    model_config = ConfigDict(from_attributes=True)


class CardLimitsUpdate(BaseModel):
    daily_limit: Decimal = Field(..., gt=0, le=10000, description="Plafond journalier en EUR")
    monthly_limit: Decimal = Field(..., gt=0, le=50000, description="Plafond mensuel en EUR")


class CardRevealRequest(BaseModel):
    totp_code: str = Field(..., min_length=6, max_length=6, description="Code 2FA requis pour lever le masquage PCI-DSS")


class CardSensitiveData(BaseModel):
    full_pan: str
    cvv: str
    expiry: str


# ==============================================================================
# SCHÉMAS BÉNÉFICIAIRES
# ==============================================================================
class BeneficiaryCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=150)
    bank_code: str = Field(..., min_length=5, max_length=5)
    branch_code: str = Field(..., min_length=5, max_length=5)
    account_number: str = Field(..., min_length=11, max_length=11)
    rib_key: Optional[str] = None
    bic: Optional[str] = "NEOBFRPPXXX"

    @field_validator("bank_code", "branch_code")
    @classmethod
    def check_digits(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError("Le code banque et le code guichet doivent être numériques.")
        return v

    def resolve_rib_and_iban(self) -> tuple[str, str]:
        """Calcule ou valide la clé RIB et génère l'IBAN conforme."""
        expected_key = calculate_rib_key(self.bank_code, self.branch_code, self.account_number)
        if self.rib_key:
            if self.rib_key != expected_key:
                raise ValueError(f"Clé RIB invalide. Clé fournie: {self.rib_key}, clé calculée: {expected_key}")
            final_key = self.rib_key
        else:
            final_key = expected_key
        
        iban = generate_french_iban(self.bank_code, self.branch_code, self.account_number, final_key)
        return final_key, iban


class BeneficiaryResponse(BaseModel):
    id: int
    name: str
    bank_code: str
    branch_code: str
    account_number: str
    rib_key: str
    iban: str
    bic: str

    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# SCHÉMAS VIREMENTS & CORE BANKING
# ==============================================================================
class TransferExecutionRequest(BaseModel):
    idempotency_key: str = Field(..., min_length=16, description="UUIDv4 unique d'idempotence")
    source_account_id: int
    beneficiary_id: int
    amount: Decimal = Field(..., gt=Decimal("0.00"), le=Decimal("100000.00"), description="Montant strict Decimal")
    label: str = Field(..., min_length=1, max_length=140)
    totp_code: str = Field(..., min_length=6, max_length=6, description="Code 2FA requis")


class TransactionFilterParams(BaseModel):
    account_id: Optional[int] = None
    search: Optional[str] = None
    tx_type: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    page: int = 1
    page_size: int = 10


# ==============================================================================
# SCHÉMAS VIREMENTS DE MASSE & AFB 160
# ==============================================================================
class AFB160RecipientItem(BaseModel):
    recipient_name: str = Field(..., max_length=24)
    bank_code: str = Field(..., min_length=5, max_length=5)
    branch_code: str = Field(..., min_length=5, max_length=5)
    account_number: str = Field(..., min_length=11, max_length=11)
    rib_key: str = Field(..., min_length=2, max_length=2)
    amount: Decimal = Field(..., gt=Decimal("0.00"))
    label: str = Field(..., max_length=31)

    @field_validator("rib_key")
    @classmethod
    def validate_rib(cls, v: str, info) -> str:
        values = info.data
        if "bank_code" in values and "branch_code" in values and "account_number" in values:
            if not validate_french_rib(values["bank_code"], values["branch_code"], values["account_number"], v):
                raise ValueError(f"Clé RIB {v} invalide pour le compte {values['account_number']}")
        return v
