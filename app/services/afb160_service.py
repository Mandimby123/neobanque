import csv
import io
import re
from decimal import Decimal
from datetime import datetime, timezone
from typing import List, Dict, Any, Tuple
from app.core.exceptions import AFB160FormattingException
from app.core.security import validate_french_rib, calculate_rib_key


class AFB160Service:
    """
    Générateur et analyseur de fichiers conformes aux normes interbancaires
    françaises AFB 160 (CFONB - Comité Français d'Organisation et de Normalisation Bancaires).
    Spécification stricte :
      - Exactement 160 caractères par enregistrement
      - Séparateur de ligne CRLF (\\r\\n)
      - Ligne 03 : En-tête donneur d'ordre
      - Lignes 06 : Détail des virements (montants en centimes cadrés à droite avec zéros)
      - Ligne 08 : Totalisation et contrôle d'intégrité
    """

    @staticmethod
    def _sanitize_string(text: str, max_length: int) -> str:
        """Nettoie la chaîne (ASCII, majuscules, sans caractères spéciaux accentués) et la cadre à gauche."""
        if not text:
            return " " * max_length
        # Remplacement basique des accents pour compatibilité mainframe CFONB
        accents = {
            'é': 'E', 'è': 'E', 'ê': 'E', 'ë': 'E', 'à': 'A', 'â': 'A', 'ä': 'A',
            'î': 'I', 'ï': 'I', 'ô': 'O', 'ö': 'O', 'ù': 'U', 'û': 'U', 'ü': 'U',
            'ç': 'C', 'ñ': 'N'
        }
        clean = text
        for k, v in accents.items():
            clean = clean.replace(k, v).replace(k.upper(), v)
        # Supprimer tout caractère non ASCII standard
        clean = re.sub(r'[^A-Za-z0-9\s\-_./]', ' ', clean).upper()
        return clean[:max_length].ljust(max_length)

    def generate_afb160(
        self,
        sender_bank_code: str,
        sender_branch_code: str,
        sender_account_number: str,
        sender_name: str,
        items: List[Dict[str, Any]],
        execution_date: datetime = None
    ) -> str:
        """
        Génère le contenu complet d'un fichier AFB 160.
        Chaque item doit contenir :
          - recipient_name: str
          - bank_code: str (5)
          - branch_code: str (5)
          - account_number: str (11)
          - rib_key: str (2)
          - amount: Decimal
          - label: str
        """
        if not items:
            raise AFB160FormattingException("Aucun virement à inclure dans le lot AFB 160.")

        now = datetime.now(timezone.utc)
        exec_dt = execution_date or now
        
        date_creation = now.strftime("%d%m%y")
        date_echeance = exec_dt.strftime("%d%m%y")

        lines: List[str] = []

        # ======================================================================
        # 1. EN-TÊTE ÉMETTEUR (CODE 03) - 160 CARACTÈRES
        # ======================================================================
        # 01-02 : Code 03
        # 03-07 : Code banque donneur d'ordre (5)
        # 08-11 : Espace réservé (4)
        # 12-16 : Code guichet donneur d'ordre (5)
        # 17-27 : Numéro de compte donneur d'ordre (11)
        # 28-51 : Raison sociale / Nom donneur d'ordre (24)
        # 52-57 : Date de création JJMMAA (6)
        # 58-63 : Date d'exécution JJMMAA (6)
        # 64-160: Remplissage espaces (97)
        r03 = (
            "03"
            + sender_bank_code.strip()[:5].zfill(5)
            + "    "
            + sender_branch_code.strip()[:5].zfill(5)
            + sender_account_number.strip().upper()[:11].ljust(11)
            + self._sanitize_string(sender_name, 24)
            + date_creation
            + date_echeance
            + (" " * 97)
        )
        if len(r03) != 160:
            raise AFB160FormattingException(f"Erreur d'alignement En-tête 03 : {len(r03)} car. au lieu de 160")
        lines.append(r03)

        # ======================================================================
        # 2. DÉTAILS DES VIREMENTS (CODE 06) - 160 CARACTÈRES CHACUN
        # ======================================================================
        # 01-02 : Code 06
        # 03-07 : Code banque bénéficiaire (5)
        # 08-11 : Espace réservé (4)
        # 12-16 : Code guichet bénéficiaire (5)
        # 17-27 : Numéro de compte bénéficiaire (11)
        # 28-51 : Nom du bénéficiaire (24)
        # 52-63 : Montant en centimes cadré à droite avec des zéros (12)
        # 64-94 : Libellé du virement (31)
        # 95-96 : Clé RIB bénéficiaire (2)
        # 97-160: Remplissage espaces (64)
        total_centimes = 0
        total_records = len(items)

        for idx, item in enumerate(items, start=1):
            amount_decimal: Decimal = item["amount"]
            if amount_decimal <= Decimal("0.00"):
                raise AFB160FormattingException(f"Montant invalide à la ligne {idx} : {amount_decimal}")

            centimes = int(round(amount_decimal * 100))
            total_centimes += centimes

            b_code = item["bank_code"].strip()[:5].zfill(5)
            g_code = item["branch_code"].strip()[:5].zfill(5)
            acc_num = item["account_number"].strip().upper()[:11].ljust(11)
            rib_k = item["rib_key"].strip()[:2].zfill(2)

            r06 = (
                "06"
                + b_code
                + "    "
                + g_code
                + acc_num
                + self._sanitize_string(item["recipient_name"], 24)
                + str(centimes).zfill(12)
                + self._sanitize_string(item["label"], 31)
                + rib_k
                + (" " * 64)
            )
            if len(r06) != 160:
                raise AFB160FormattingException(f"Erreur d'alignement Détail 06 (ligne {idx}) : {len(r06)} car. au lieu de 160")
            lines.append(r06)

        # ======================================================================
        # 3. TOTAL DE CONTRÔLE (CODE 08) - 160 CARACTÈRES
        # ======================================================================
        # 01-02 : Code 08
        # 03-07 : Code banque donneur d'ordre (5)
        # 08-19 : Nombre total d'enregistrements 06 (12)
        # 20-31 : Montant cumulé en centimes (12)
        # 32-160: Remplissage espaces (129)
        r08 = (
            "08"
            + sender_bank_code.strip()[:5].zfill(5)
            + str(total_records).zfill(12)
            + str(total_centimes).zfill(12)
            + (" " * 129)
        )
        if len(r08) != 160:
            raise AFB160FormattingException(f"Erreur d'alignement Total 08 : {len(r08)} car. au lieu de 160")
        lines.append(r08)

        # Norme bancaire stricte CFONB : retour chariot standard Windows CRLF (\r\n)
        return "\r\n".join(lines) + "\r\n"

    def parse_csv_recipients(self, csv_content: str) -> Tuple[List[Dict[str, Any]], List[str], Decimal]:
        """
        Parse un fichier CSV de virements groupés.
        Supporte les séparateurs ';' ou ',' ou tabulations.
        Colonnes attendues : Nom, Code Banque, Code Guichet, Compte, Clé, Montant, Libellé
        Retourne : (valid_items, errors, total_amount)
        """
        valid_items: List[Dict[str, Any]] = []
        errors: List[str] = []
        total_amount = Decimal("0.00")

        # Détection automatique du dialecte
        sample = csv_content[:1024]
        delimiter = ';' if ';' in sample else (',' if ',' in sample else '\t')
        
        reader = csv.reader(io.StringIO(csv_content), delimiter=delimiter)
        
        for row_idx, row in enumerate(reader, start=1):
            if not row or len(row) < 6:
                continue
            
            # Détection d'en-tête éventuel
            first_cell = row[0].strip().lower()
            if row_idx == 1 and ("nom" in first_cell or "name" in first_cell or "beneficiaire" in first_cell):
                continue

            try:
                name = row[0].strip()
                bank_code = row[1].strip()
                branch_code = row[2].strip()
                account_number = row[3].strip().upper()
                
                # Gestion de la clé RIB (si omise ou calculée)
                if len(row) >= 7:
                    rib_key = row[4].strip()
                    amount_str = row[5].strip().replace(" ", "").replace(",", ".")
                    label = row[6].strip() if len(row) > 6 else "VIREMENT COMMERCIAL"
                else:
                    # Cas où la clé n'est pas dans une colonne dédiée
                    rib_key = calculate_rib_key(bank_code, branch_code, account_number)
                    amount_str = row[4].strip().replace(" ", "").replace(",", ".")
                    label = row[5].strip() if len(row) > 5 else "VIREMENT COMMERCIAL"

                if not validate_french_rib(bank_code, branch_code, account_number, rib_key):
                    expected = calculate_rib_key(bank_code, branch_code, account_number)
                    errors.append(f"Ligne {row_idx} ({name}) : Clé RIB {rib_key} invalide (clé attendue : {expected})")
                    continue

                amount = Decimal(amount_str)
                if amount <= Decimal("0.00"):
                    errors.append(f"Ligne {row_idx} ({name}) : Le montant {amount} doit être strictement supérieur à 0")
                    continue

                valid_items.append({
                    "recipient_name": name,
                    "bank_code": bank_code,
                    "branch_code": branch_code,
                    "account_number": account_number,
                    "rib_key": rib_key,
                    "amount": amount,
                    "label": label or "VIREMENT MASSE AFB160"
                })
                total_amount += amount

            except Exception as e:
                errors.append(f"Ligne {row_idx} : Erreur d'analyse des données ({e})")

        return valid_items, errors, total_amount


afb160_service = AFB160Service()

