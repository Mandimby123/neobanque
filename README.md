# 🏦 NÉOBANQUE CORE BANKING PORTAL
### *Self-Service Banking Portal — Architecture Fintech Critique & Prête pour la Production*

Plateforme web bancaire moderne et sécurisée conçue selon les plus hauts standards de la finance (**PCI-DSS**, **ISO 20022**, **CFONB / AFB 160**, **Réglementation ACPR / EBA**).

---

## 🚀 Fonctionnalités Clés & Architecture Métier

### 🛡️ 1. Authentification & Sécurité Critique (Module A)
* **Double Authentification 2FA TOTP (RFC 6238) :** Compatible Google Authenticator, Authy, 1Password. Exigée pour la connexion, les virements, la récupération de mot de passe et la révélation des numéros de carte.
* **Chiffrement fort :** Hachage des mots de passe avec `bcrypt` (12 rounds) et gestion de session via cookies `HttpOnly` / `Secure` / `SameSite=Lax` contenant un JWT signé en `HS256`.
* **Traçabilité Immuable (`AuditLog`) :** Journalisation inaltérable de chaque événement sensible (connexion, tentative échouée, virement, gel de carte, modification de plafonds, révélation PAN/CVV, export AFB 160, téléchargement RIB) avec horodatage UTC, IP et User-Agent.

### 💳 2. Tableaux de Bord & Multi-Comptes (Module B)
* **Vue Consolidée :** Agrégation en temps réel des soldes (Courant, Épargne Livret A+, Professionnel) avec bascule instantanée "Afficher / Masquer le solde".
* **Génération de RIB Officiel :** Affichage des identifiants nationaux (Code Banque 5, Code Guichet 5, N° Compte 11, Clé RIB 2) et internationaux (IBAN / BIC).
* **Export PDF Haute Définition :** Moteur `pdf_service.py` (`ReportLab`) générant des Relevés d'Identité Bancaire officiels conformes Banque de France.
* **Historique des Transactions Réactif :** Recherche textuelle en direct, filtrage par type (crédit, débit, carte) et pagination sans rechargement via **HTMX**.

### 🔒 3. Module Monétique CMS & Conformité PCI-DSS (Module C)
* **Widget Carte Virtuelle Réaliste :** Carte 3D animée avec effet métallique, retournement recto/verso (puce EMV, bande magnétique, zone de signature).
* **Masquage PCI-DSS Strict :** Le PAN complet (16 chiffres) et le CVV ne sont jamais stockés en clair en base (chiffrement Fernet AES-128-CBC / HMAC-SHA256 au repos). Révélation temporaire (15s) uniquement après validation d'un code TOTP.
* **Contrôles Temps Réel :** Gel/Dégel instantané (`Freeze/Unfreeze`), modification dynamique des plafonds journaliers/mensuels, interrupteurs pour paiements en ligne, à l'étranger et sans contact NFC.
* **Connecteur `cms_client.py` :** Client asynchrone signant cryptographiquement chaque trame avec **HMAC-SHA256**, gestion des timeouts et mode Sandbox/Mock.

### 💸 4. Virements Unitaires & Connecteur CBS (Module D)
* **Stepper HTMX Sécurisé en 3 Étapes :**
  1. Choix du compte source et sélection/ajout d'un bénéficiaire avec **validation stricte de la clé RIB modulo 97**.
  2. Saisie du montant (type `Decimal` strict, jamais de `float` imprécis) et du motif SEPA.
  3. Récapitulatif et signature électronique forte par code **2FA TOTP à 6 chiffres**.
* **Connecteur `cbs_client.py` (Core Banking System) :**
  - **Idempotence Native :** Clé unique UUIDv4 générée à chaque transaction pour garantir **zéro double débit** même en cas de re-soumission ou de coupure réseau.
  - **mTLS :** Prise en charge des certificats clients X.509 (`cert.pem`, `key.pem`).
  - **Résilience Réseau :** Retry exponentiel avec backoff sur codes 502/503/504 et mode Sandbox intégré.

### 📂 5. Virements de Masse & Norme AFB 160 / CFONB (Module E)
* **Import & Analyse CSV :** Téléversement de fichiers de virements (salaires, fournisseurs) avec contrôle automatique de la clé RIB modulo 97 de chaque destinataire.
* **Générateur `afb160_service.py` :** Production de fichiers texte strictement conformes à la norme interbancaire française **AFB 160** :
  - Exactement **160 caractères par enregistrement**.
  - Fin de ligne Windows standard CRLF (`\r\n`).
  - Ligne `03` : En-tête donneur d'ordre.
  - Lignes `06` : Détail des virements (montants en centimes cadrés à droite avec des zéros `zfill`, chaînes cadrées à gauche `ljust`).
  - Ligne `08` : Total de contrôle (somme des montants et nombre total d'enregistrements).

---

## 🛠️ Stack Technique

| Composant | Technologie | Rôle |
|---|---|---|
| **Backend** | Python 3.11+ / 3.13, FastAPI (Async) | API asynchrone, routage haute performance |
| **Base de Données** | PostgreSQL + asyncpg (ou SQLite / aiosqlite en local) | Persistance ACID, SQLAlchemy 2.0 Async |
| **Cache & Verrous** | Redis (ou cache mémoire thread-safe avec TTL) | Idempotence, rate-limiting |
| **Frontend** | Jinja2, HTMX, Tailwind CSS, Lucide Icons | UX SPA réactive sans framework JS lourd |
| **Sécurité** | PyOTP, Cryptography (AES-256), PyJWT, bcrypt | 2FA TOTP, PCI-DSS, HMAC-SHA256 |
| **Édition Document** | ReportLab | Génération PDF vectoriel certifié |

---

## 📦 Démarrage Rapide

### Option A : Lancement Local Immédiat (Zero-Friction)

1. **Cloner et installer les dépendances :**
   ```bash
   pip install -r requirements.txt
   ```

2. **Démarrer l'application :**
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```
   *L'application s'initialise automatiquement avec une base SQLite asynchrone locale, un cache mémoire de repli et amorce le jeu complet de données de démonstration.*

3. **Accéder au portail :**
   - URL : **[http://localhost:8000](http://localhost:8000)**

---

### Option B : Déploiement Conteneurisé avec Docker Compose (PostgreSQL + Redis)

```bash
docker compose up --build
```
*Démarre l'application FastAPI, le serveur PostgreSQL 16 et l'instance Redis 7.*

---

## 🔑 Identifiants de Démonstration

| Rôle | Email | Mot de passe | Clé TOTP (Base32) |
|---|---|---|---|
| **Client / Pro** | `demo@neobanque.fr` | `Password123!` | `JBSWY3DPEHPK3PXP` |

> 💡 **Astuce Démo :** Lors de la saisie du code 2FA TOTP (connexion ou virement), un bouton d'assistance *"Insérer le code TOTP actuel"* permet de renseigner automatiquement le code à 6 chiffres valide sans nécessiter d'application tierce.

---

## 🧪 Exécution des Tests Automatisés

Le projet comprend une suite complète de tests unitaires et d'intégration validant chaque couche :

```bash
python -m pytest tests/ -v
```

### Couverture des Tests :
* `test_banking_security.py` : Hachage bcrypt, JWT, RFC 6238 TOTP, chiffrement PCI-DSS, HMAC-SHA256, validation Modulo 97 RIB et IBAN.
* `test_afb160.py` : Longueur exacte de 160 caractères par enregistrement, formatage CRLF, validation de totaux de contrôle (Ligne 08) et analyseur CSV.
* `test_cbs_cms_connectors.py` : Idempotence stricte (zéro double débit lors de rejeux), solde insuffisant, switch monétique.
* `test_http_endpoints.py` : En-têtes de sécurité HTTP, redirection d'authentification, tableau de bord et génération du PDF de RIB.

---

## 📜 Licence & Conformité
Conforme aux recommandations de l'ANSSI, de l'ACPR et des exigences de niveau 1 de la norme PCI-DSS.

