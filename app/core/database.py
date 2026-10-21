from typing import AsyncGenerator, Optional
import time
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

# Base declarative SQLAlchemy 2.0
class Base(DeclarativeBase):
    pass


def normalize_database_url(url: str) -> str:
    """
    Normalise l'URL de base de données pour la compatibilité SQLAlchemy 2.0 Async.
    Gère notamment le format fourni par Render (postgres:// ou postgresql://)
    en le convertissant en postgresql+asyncpg:// et adapte le paramètre SSL pour asyncpg.
    """
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://") and not url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    
    # asyncpg utilise ?ssl=require et non sslmode=require
    if "sslmode=require" in url:
        url = url.replace("sslmode=require", "ssl=require")
    
    return url


# URL résolue et normalisée (support automatique Render PostgreSQL)
resolved_db_url = normalize_database_url(settings.DATABASE_URL)

# Moteur SQLAlchemy Asynchrone
connect_args = {}
if "sqlite" in resolved_db_url:
    connect_args["check_same_thread"] = False

engine = create_async_engine(
    resolved_db_url,
    echo=False,
    future=True,
    connect_args=connect_args
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dépendance FastAPI pour obtenir une session de base de données asynchrone."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


# ==============================================================================
# GESTIONNAIRE DE CACHE & IDEMPOTENCE (REDIS AVEC FALLBACK EN MÉMOIRE)
# ==============================================================================
class CacheManager:
    """
    Système de cache et de verrouillage d'idempotence.
    Tente de se connecter à Redis. En cas d'indisponibilité, bascule automatiquement
    vers un store mémoire asynchrone thread-safe avec expiration TTL.
    """
    def __init__(self):
        self._memory_store: dict[str, tuple[str, float]] = {}  # key -> (value, expire_timestamp)
        self._memory_locks: dict[str, asyncio.Lock] = {}
        self._redis_client = None
        self._use_redis = False

    async def initialize(self):
        if settings.REDIS_URL:
            try:
                import redis.asyncio as aioredis
                client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
                await client.ping()
                self._redis_client = client
                self._use_redis = True
                logger.info("Connexion Redis établie avec succès.")
            except Exception as e:
                logger.warning(f"Redis indisponible ({e}). Bascule sur le cache mémoire local.")
                self._use_redis = False
        else:
            self._use_redis = False

    async def get(self, key: str) -> Optional[str]:
        if self._use_redis and self._redis_client:
            try:
                return await self._redis_client.get(key)
            except Exception:
                pass
        item = self._memory_store.get(key)
        if not item:
            return None
        val, expires_at = item
        if time.time() > expires_at:
            del self._memory_store[key]
            return None
        return val

    async def set(self, key: str, value: str, ex: int = 300) -> bool:
        if self._use_redis and self._redis_client:
            try:
                await self._redis_client.set(key, value, ex=ex)
                return True
            except Exception:
                pass
        self._memory_store[key] = (value, time.time() + ex)
        return True

    async def delete(self, key: str) -> bool:
        if self._use_redis and self._redis_client:
            try:
                await self._redis_client.delete(key)
                return True
            except Exception:
                pass
        if key in self._memory_store:
            del self._memory_store[key]
            return True
        return False

    async def set_nx_lock(self, key: str, value: str, ex: int = 60) -> bool:
        """Acquiert un verrou idempotent atomique (Set if Not Exists)."""
        if self._use_redis and self._redis_client:
            try:
                result = await self._redis_client.set(key, value, ex=ex, nx=True)
                return bool(result)
            except Exception:
                pass
        if key not in self._memory_locks:
            self._memory_locks[key] = asyncio.Lock()
        
        lock = self._memory_locks[key]
        async with lock:
            existing = await self.get(key)
            if existing is not None:
                return False
            await self.set(key, value, ex=ex)
            return True

    async def close(self):
        if self._use_redis and self._redis_client:
            await self._redis_client.close()


cache_manager = CacheManager()
