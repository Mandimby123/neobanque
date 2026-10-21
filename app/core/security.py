import base64
import hmac
import hashlib
import io
import re
from datetime import datetime, timedelta, timezone
from typing import Optional, Any
import bcrypt
import jwt
import pyotp
import qrcode
from cryptography.fernet import Fernet
from app.core.config import settings


# ==============================================================================
# HACHAGE DES MOTS DE PASSE (BCRYPT / ARGON2)
# ==============================================================================
def hash_password(password: str) -> str:
    """Hache un mot de passe avec bcrypt en appliquant un sel aléatoire."""
    pwd_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(pwd_bytes, salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Vérifie la correspondance entre le mot de passe clair et le hash."""
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8")
        )
    except Exception:
        return False


# ==============================================================================
# GESTION DES TOKENS JWT
# ==============================================================================
def create_access_token(data: dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Génère un JWT signé pour la session utilisateur."""
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire, "iat": now})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict[str, Any]]:
    """Décode et valide un JWT. Retourne le payload ou None si invalide/expiré."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except jwt.PyJWTError:
        return None


# ==============================================================================
# AUTHENTIFICATION À DEUX FACTEURS (2FA TOTP RFC 6238)
# ==============================================================================
def generate_totp_secret() -> str:
    """Génère une clé secrète TOTP Base32 compatible Google Authenticator."""
    return pyotp.random_base32()


def get_totp_uri(secret: str, email: str, issuer: str = "NéoBanque") -> str:
    """Construit l'URI otpauth standard."""
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=email, issuer_name=issuer)


def generate_totp_qr_data_url(uri: str) -> str:
    """Génère un QR code sous forme de Data URL (PNG base64) intégrable directement dans du HTML."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=6,
        border=2,
    )
    qr.add_data(uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0f172a", back_color="#ffffff")
    
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    b64_img = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{b64_img}"


def verify_totp_code(secret: str, code: str) -> bool:
    """
    Vérifie un code TOTP à 6 chiffres.
    Autorise un décalage de 1 intervalle (valid_window=1) pour tolérer le drift temporel.
    """
    if not secret or not code:
        return False
    # Nettoyage
    clean_code = code.strip().replace(" ", "")
    if len(clean_code) != 6 or not clean_code.isdigit():
        return False
    
    totp = pyotp.TOTP(secret)
    return totp.verify(clean_code, valid_window=1)


# ==============================================================================
# SÉCURITÉ MONÉTIQUE & CHIFFREMENT PCI-DSS
# ==============================================================================
_fernet = Fernet(settings.CARD_ENCRYPTION_KEY.encode("utf-8"))


def encrypt_card_data(data: str) -> str:
    """Chiffre une donnée monétique sensible (PAN ou CVV) avec AES-128-CBC / HMAC-SHA256."""
    return _fernet.encrypt(data.encode("utf-8")).decode("utf-8")


def decrypt_card_data(encrypted_data: str) -> str:
    """Déchiffre une donnée monétique sensible."""
    return _fernet.decrypt(encrypted_data.encode("utf-8")).decode("utf-8")


def mask_pan(pan: str) -> str:
    """
    Masque un PAN selon la norme PCI-DSS : seuls les 4 premiers et 4 derniers
    chiffres ou seulement les 4 derniers sont visibles.
    Exemple : 4970 **** **** 8821
    """
    clean_pan = pan.replace(" ", "").replace("-", "")
    if len(clean_pan) < 8:
        return "**** **** **** " + clean_pan[-4:]
    first4 = clean_pan[:4]
    last4 = clean_pan[-4:]
    return f"{first4} **** **** {last4}"


# ==============================================================================
# SIGNATURE CRYPTOGRAPHIQUE HMAC-SHA256 (CONNECTEUR CMS)
# ==============================================================================
def generate_hmac_signature(secret: str, message: str) -> str:
    """Génère une signature hexadécimale HMAC-SHA256."""
    return hmac.new(
        secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()


def verify_hmac_signature(secret: str, message: str, signature: str) -> bool:
    """Vérifie une signature HMAC-SHA256 en temps constant pour contrer les timing attacks."""
    expected = generate_hmac_signature(secret, message)
    return hmac.compare_digest(expected, signature)


# ==============================================================================
# MOTEUR BANCAIRE FRANÇAIS : RIB MODULO 97 & IBAN SEPA
# ==============================================================================
_RIB_LETTER_MAP = {
    'A': '1', 'B': '2', 'C': '3', 'D': '4', 'E': '5', 'F': '6', 'G': '7', 'H': '8', 'I': '9',
    'J': '1', 'K': '2', 'L': '3', 'M': '4', 'N': '5', 'O': '6', 'P': '7', 'Q': '8', 'R': '9',
    'S': '2', 'T': '3', 'U': '4', 'V': '5', 'W': '6', 'X': '7', 'Y': '8', 'Z': '9'
}


def convert_rib_account_to_digits(account_number: str) -> str:
    """Convertit les caractères alphanumériques du compte selon la table officielle RIB."""
    result = []
    for char in account_number.upper():
        if char.isdigit():
            result.append(char)
        elif char in _RIB_LETTER_MAP:
            result.append(_RIB_LETTER_MAP[char])
        else:
            raise ValueError(f"Caractère non valide dans le numéro de compte RIB : {char}")
    return "".join(result)


def calculate_rib_key(bank_code: str, branch_code: str, account_number: str) -> str:
    """
    Calcule la clé RIB officielle française (modulo 97).
    Formule : 97 - ((89 * CodeBanque + 15 * CodeGuichet + 3 * NumCompte) % 97)
    """
    b = int(bank_code)
    g = int(branch_code)
    c_digits = convert_rib_account_to_digits(account_number)
    c = int(c_digits)
    
    remainder = (89 * b + 15 * g + 3 * c) % 97
    key = 97 - remainder
    return f"{key:02d}"


def validate_french_rib(bank_code: str, branch_code: str, account_number: str, rib_key: str) -> bool:
    """Valide les 5 composants d'un RIB français."""
    try:
        bank_code = bank_code.strip()
        branch_code = branch_code.strip()
        account_number = account_number.strip().upper()
        rib_key = rib_key.strip()

        if len(bank_code) != 5 or not bank_code.isdigit():
            return False
        if len(branch_code) != 5 or not branch_code.isdigit():
            return False
        if len(account_number) != 11:
            return False
        if len(rib_key) != 2 or not rib_key.isdigit():
            return False

        expected_key = calculate_rib_key(bank_code, branch_code, account_number)
        return expected_key == rib_key
    except Exception:
        return False


def generate_french_iban(bank_code: str, branch_code: str, account_number: str, rib_key: str) -> str:
    """Génère l'IBAN français normalisé (27 caractères) à partir des données de RIB."""
    bban = f"{bank_code.strip()}{branch_code.strip()}{account_number.strip().upper()}{rib_key.strip()}"
    
    # ISO 13616 pour IBAN : A=10, B=11 ... Z=35
    def char_to_iban_val(c: str) -> str:
        if c.isdigit():
            return c
        return str(ord(c.upper()) - 55)

    # FR00 -> F=15, R=27, 00
    iban_check_str = "".join(char_to_iban_val(c) for c in bban) + "152700"
    checksum = 98 - (int(iban_check_str) % 97)
    return f"FR{checksum:02d}{bban}"


def format_iban(iban: str) -> str:
    """Formate un IBAN en blocs de 4 caractères pour la lisibilité humaine."""
    clean = iban.replace(" ", "").upper()
    return " ".join([clean[i:i+4] for i in range(0, len(clean), 4)])


def validate_iban(iban: str) -> bool:
    """Valide un IBAN selon la norme internationale ISO 7064 Mod 97-10."""
    clean_iban = iban.replace(" ", "").upper()
    if len(clean_iban) < 15 or len(clean_iban) > 34:
        return False
    
    # Déplacement des 4 premiers caractères à la fin
    rearranged = clean_iban[4:] + clean_iban[:4]
    
    def char_to_val(c: str) -> str:
        if c.isdigit():
            return c
        return str(ord(c) - 55)
    
    try:
        num_str = "".join(char_to_val(c) for c in rearranged)
        return int(num_str) % 97 == 1
    except Exception:
        return False

