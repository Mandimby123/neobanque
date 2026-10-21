# 🚀 Guide de Déploiement sur Render (render.com)
### *NéoBanque Core Banking Portal*

Ce guide détaille les étapes pour déployer l'application sur **Render** en quelques minutes, soit via le Blueprint automatisé (**Infrastructure as Code**), soit manuellement via le tableau de bord Render.

---

## 🌟 Méthode 1 : Déploiement Automatique par Blueprint (`render.yaml`) *(Recommandé)*

Render prend nativement en charge le fichier [`render.yaml`](file:///d:/NOUVELLE%20APPLICATION%202025/A%20PRESENTER/neobanque/render.yaml) situé à la racine du projet. Ce fichier configure automatiquement le Web Service et la base de données PostgreSQL gérée.

### Étapes :
1. **Pousser votre code sur GitHub / GitLab :**
   ```bash
   git init
   git add .
   git commit -m "feat: Neobanque production ready for Render"
   git branch -M main
   git remote add origin https://github.com/votre-compte/neobanque.git
   git push -u origin main
   ```

2. **Connecter Render au dépôt :**
   - Rendez-vous sur votre tableau de bord [Render Dashboard](https://dashboard.render.com).
   - Cliquez sur le bouton bleu **"New +"** en haut à droite.
   - Sélectionnez **"Blueprint"**.
   - Choisissez votre dépôt `neobanque`.

3. **Lancement automatique :**
   - Render analyse le fichier `render.yaml` et affiche la liste des ressources à créer :
     - 🗄️ **neobank-postgres** : Instance PostgreSQL gérée (Région Francfort).
     - 🌐 **neobank-portal** : Web Service Python (FastAPI + Uvicorn).
   - Cliquez sur **"Apply"**.
   - Render va provisionner la base, injecter automatiquement `DATABASE_URL`, générer la clé `SECRET_KEY`, exécuter `render-build.sh` et démarrer le service !

---

## 🛠️ Méthode 2 : Déploiement Manuel depuis le Dashboard Render

Si vous préférez configurer les services étape par étape :

### Étape 1 : Créer la Base de Données PostgreSQL
1. Sur Render, cliquez sur **"New +"** &rarr; **"PostgreSQL"**.
2. Renseignez les paramètres :
   - **Name :** `neobank-postgres`
   - **Database :** `neobank`
   - **User :** `neouser`
   - **Region :** `Frankfurt (EU Central)`
   - **Plan :** `Free` (ou supérieur)
3. Cliquez sur **"Create Database"**.
4. Copiez l'**Internal Database URL** (ex: `postgres://neouser:...@dpg-...-a.frankfurt-postgres.render.com/neobank`).

---

### Étape 2 : Créer le Web Service
1. Cliquez sur **"New +"** &rarr; **"Web Service"**.
2. Connectez votre dépôt GitHub.
3. Configurez les options :
   - **Name :** `neobank-portal`
   - **Region :** `Frankfurt (EU Central)`
   - **Branch :** `main`
   - **Runtime :** `Python 3`
   - **Build Command :**
     ```bash
     chmod +x ./render-build.sh && ./render-build.sh
     ```
   - **Start Command :**
     ```bash
     uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 2
     ```
   - **Health Check Path :** `/health`

---

### Étape 3 : Configurer les Variables d'Environnement

Dans la section **"Environment Variables"** de votre Web Service, ajoutez :

| Clé | Valeur | Description |
|---|---|---|
| `DATABASE_URL` | Coller l'Internal Database URL de l'étape 1 | *(L'application convertit automatiquement `postgres://` en `postgresql+asyncpg://`)* |
| `ENVIRONMENT` | `production` | Active le mode production sécurisé |
| `DEBUG` | `false` | Désactive la documentation publique / logs verbeux |
| `COOKIE_SECURE` | `true` | Active les cookies sécurisés en HTTPS |
| `SECRET_KEY` | *(Cliquez sur Generate)* | Clé de signature JWT |
| `CARD_ENCRYPTION_KEY` | `HooHd-zYeuRqjmfbcvL3fQBr8WaHls8mVISfaIhen5A=` | Clé Fernet AES-256 pour les numéros de carte PCI-DSS |
| `USE_MOCK_BANKING` | `true` | Active la sandbox CBS / CMS intégrée |
| `DEFAULT_BANK_CODE` | `30004` | Code banque SEPA |
| `DEFAULT_BRANCH_CODE` | `02050` | Code guichet SEPA |
| `DEFAULT_BIC` | `NEOBFRPPXXX` | Code BIC international |

*(Optionnel) Si vous activez un Redis géré sur Render, ajoutez `REDIS_URL`. Sinon, l'application utilise automatiquement son cache mémoire thread-safe avec TTL.*

4. Cliquez sur **"Save Changes"**. Le déploiement se lance instantanément.

---

## 🔍 Adaptations & Résilience Intégrées pour Render

1. **Conversion automatique d'URL PostgreSQL :**
   Render fournit des URLs au format `postgres://...` ou `postgresql://...?sslmode=require`. Notre module `app/core/database.py` normalise automatiquement la chaîne en `postgresql+asyncpg://...` avec `ssl=require`, assurant une compatibilité 100% transparente avec SQLAlchemy 2.0 Async sans intervention manuelle.

2. **Gestion dynamique du Port (`$PORT`) :**
   Render alloue dynamiquement un port via la variable `$PORT`. La commande de démarrage `uvicorn app.main:app --host 0.0.0.0 --port $PORT` s'y adapte nativement.

3. **Vérification de Santé (`/health`) :**
   L'endpoint `/health` permet à Render de surveiller la disponibilité du conteneur et de procéder à des déploiements "zero-downtime" (le nouveau conteneur ne reçoit du trafic qu'une fois la route `/health` validée).

4. **Amorçage Automatique (`lifespan`) :**
   Lors du premier démarrage sur Render, le cycle de vie de FastAPI crée automatiquement toutes les tables PostgreSQL et injecte les données de démonstration (`demo@neobanque.fr`).

