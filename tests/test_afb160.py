from decimal import Decimal
from datetime import datetime, timezone
from app.services.afb160_service import afb160_service
from app.core.exceptions import AFB160FormattingException


def test_afb160_strict_160_character_lines():
    sender_bank = "30004"
    sender_branch = "02050"
    sender_account = "00012345678"
    sender_name = "NÉOBANQUE SAS"

    items = [
        {
            "recipient_name": "FOURNISSEUR CLOUD",
            "bank_code": "30004",
            "branch_code": "02050",
            "account_number": "00098765432",
            "rib_key": "54",
            "amount": Decimal("1450.75"),
            "label": "FACTURE SERVEURS 10-2026"
        },
        {
            "recipient_name": "CONSULTING EXPERT",
            "bank_code": "30004",
            "branch_code": "02050",
            "account_number": "00055566677",
            "rib_key": "12",
            "amount": Decimal("3200.00"),
            "label": "HONORAIRES AUDIT"
        }
    ]

    afb_content = afb160_service.generate_afb160(
        sender_bank_code=sender_bank,
        sender_branch_code=sender_branch,
        sender_account_number=sender_account,
        sender_name=sender_name,
        items=items,
        execution_date=datetime(2026, 10, 21, tzinfo=timezone.utc)
    )

    # 1. Vérification du format CRLF (\r\n)
    assert "\r\n" in afb_content
    raw_lines = afb_content.split("\r\n")
    # Enlever la dernière ligne vide causée par le \r\n terminal
    lines = [l for l in raw_lines if l]

    # Nombre de lignes : 1 en-tête (03) + 2 détails (06) + 1 total (08) = 4 lignes
    assert len(lines) == 4

    # 2. VÉRIFICATION STRICTE DE LA LONGUEUR DE CHAQUE ENREGISTREMENT (160 CARACTÈRES)
    for idx, line in enumerate(lines, start=1):
        assert len(line) == 160, f"La ligne {idx} fait {len(line)} caractères au lieu de 160 !"

    # 3. Vérification En-tête 03
    r03 = lines[0]
    assert r03.startswith("03")
    assert r03[2:7] == "30004"
    assert r03[11:16] == "02050"
    assert r03[16:27] == "00012345678"

    # 4. Vérification Détails 06
    r06_1 = lines[1]
    assert r06_1.startswith("06")
    assert r06_1[2:7] == "30004"
    # Montant 1450.75 EUR = 145075 centimes cadré à droite avec des zéros sur 12 car.
    assert r06_1[51:63] == "000000145075"

    r06_2 = lines[2]
    assert r06_2.startswith("06")
    # Montant 3200.00 EUR = 320000 centimes
    assert r06_2[51:63] == "000000320000"

    # 5. Vérification Total 08
    r08 = lines[3]
    assert r08.startswith("08")
    # Total enregistrements : 2
    assert r08[7:19] == "000000000002"
    # Montant total : 145075 + 320000 = 465075 centimes
    assert r08[19:31] == "000000465075"


def test_afb160_csv_parser():
    sample_csv = """Nom;Code Banque;Code Guichet;Compte;Clé;Montant;Libellé
SARL DUPONT;30004;02050;00012345678;44;1250.00;FACTURE OCTOBRE
CABINET MARTIN;30004;02050;00098765432;54;450.50;HONORAIRES
INVALID ENTRY;30004;02050;00012345678;99;100.00;TEST ERREUR RIB"""

    valid_items, errors, total_amount = afb160_service.parse_csv_recipients(sample_csv)

    assert len(valid_items) == 2
    assert len(errors) == 1
    assert "Clé RIB 99 invalide" in errors[0]
    assert total_amount == Decimal("1700.50")
