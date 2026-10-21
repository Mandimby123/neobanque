import pytest
import pyotp
from app.core.security import (
    hash_password, verify_password,
    create_access_token, decode_access_token,
    generate_totp_secret, verify_totp_code,
    encrypt_card_data, decrypt_card_data, mask_pan,
    generate_hmac_signature, verify_hmac_signature,
    calculate_rib_key, validate_french_rib, generate_french_iban, validate_iban
)


def test_password_hashing():
    pwd = "UltraSecretPassword2026!"
    hashed = hash_password(pwd)
    assert hashed != pwd
    assert verify_password(pwd, hashed) is True
    assert verify_password("WrongPassword!", hashed) is False


def test_jwt_token():
    payload = {"sub": "42", "role": "TREASURER"}
    token = create_access_token(payload)
    decoded = decode_access_token(token)
    assert decoded is not None
    assert decoded["sub"] == "42"
    assert decoded["role"] == "TREASURER"
    assert "exp" in decoded


def test_totp_rfc6238():
    secret = generate_totp_secret()
    totp = pyotp.TOTP(secret)
    current_code = totp.now()

    assert verify_totp_code(secret, current_code) is True
    assert verify_totp_code(secret, "000000") is False
    assert verify_totp_code(secret, "abcdef") is False


def test_pci_dss_card_encryption():
    pan = "4970123456788821"
    cvv = "742"

    encrypted_pan = encrypt_card_data(pan)
    encrypted_cvv = encrypt_card_data(cvv)

    # Vérification que le texte clair n'apparaît nulle part
    assert pan not in encrypted_pan
    assert cvv not in encrypted_cvv

    # Déchiffrement
    assert decrypt_card_data(encrypted_pan) == pan
    assert decrypt_card_data(encrypted_cvv) == cvv

    # Masquage PCI-DSS
    assert mask_pan(pan) == "4970 **** **** 8821"


def test_hmac_sha256():
    secret = "monetique_secret_key"
    message = "1729490000.POST./cards/1/freeze.{}"

    sig = generate_hmac_signature(secret, message)
    assert len(sig) == 64
    assert verify_hmac_signature(secret, message, sig) is True
    assert verify_hmac_signature(secret, message + "altered", sig) is False


def test_french_rib_and_iban():
    # Coordonnées réelles de référence
    bank_code = "30004"
    branch_code = "02050"
    account_number = "00012345678"

    key = calculate_rib_key(bank_code, branch_code, account_number)
    assert len(key) == 2
    assert key == "44"

    # Validation RIB
    assert validate_french_rib(bank_code, branch_code, account_number, "44") is True
    assert validate_french_rib(bank_code, branch_code, account_number, "99") is False

    # Génération IBAN FR
    iban = generate_french_iban(bank_code, branch_code, account_number, key)
    assert len(iban) == 27
    assert iban.startswith("FR")
    assert iban == "FR7630004020500001234567844"

    # Validation IBAN ISO 13616 Modulo 97
    assert validate_iban(iban) is True
    assert validate_iban("FR7630004020500001234567899") is False

