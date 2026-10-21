import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import engine, Base, AsyncSessionLocal, cache_manager
from app.core.exceptions import BankingException, banking_exception_handler
from app.services.seed_service import seed_demo_data
from app.routers import auth, dashboard, transfers, cards

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("neobank")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Cycle de vie de l'application : initialisation de la base et des services."""
    logger.info(f"Démarrage de {settings.APP_NAME} en mode {settings.ENVIRONMENT}...")
    
    # 1. Initialisation des tables de données
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Tables de base de données synchronisées.")

    # 2. Initialisation du cache / Redis
    await cache_manager.initialize()

    # 3. Amorçage des données de démonstration
    async with AsyncSessionLocal() as session:
        try:
            await seed_demo_data(session)
        except Exception as e:
            logger.error(f"Erreur lors du seeding initial : {e}")

    yield

    # Arrêt propre
    logger.info("Fermeture des connexions et extinction...")
    await cache_manager.close()
    await engine.dispose()


# Application FastAPI
app = FastAPI(
    title=settings.APP_NAME,
    description="Portail bancaire de nouvelle génération conforme PCI-DSS, CBS, CMS et normes CFONB AFB 160.",
    version="2.0.0",
    docs_url="/api/docs" if settings.DEBUG else None,
    redoc_url=None,
    lifespan=lifespan
)

# Exception handlers
app.add_exception_handler(BankingException, banking_exception_handler)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.DEBUG else [],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# ==============================================================================
# MIDDLEWARE EN-TÊTES DE SÉCURITÉ HTTP (PCI-DSS COMPLIANT)
# ==============================================================================
@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response: Response = await call_next(request)
    
    # En-têtes stricts de cybersécurité
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    
    # Content-Security-Policy autorisant Tailwind, HTMX, Lucide et scripts d'interaction
    response.headers["Content-Security-Policy"] = (
        "default-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://unpkg.com https://fonts.googleapis.com https://fonts.gstatic.com; "
        "img-src 'self' data: https: blob:; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.tailwindcss.com https://unpkg.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com data:;"
    )
    return response


# Route de santé pour Render (Health Check)
@app.api_route("/health", methods=["GET", "HEAD"], tags=["Monitoring"])
async def health_check():
    """Endpoint de surveillance de santé pour le load balancer et Render."""
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "environment": settings.ENVIRONMENT
    }


# Inclusion des routeurs
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(transfers.router)
app.include_router(cards.router)

# Montage sécurisé des fichiers statiques (avec création automatique si absent)
static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")
