import time
import json
import asyncio
import logging
from decimal import Decimal
from typing import Dict, Any, Optional
import httpx

from app.core.config import settings
from app.core.security import generate_hmac_signature
from app.core.exceptions import CMSConnectionException

logger = logging.getLogger(__name__)


class CMSClient:
    """
    Connecteur vers le Switch Monétique / Card Management System (CMS).
    Gère les ordres temps réel sur le cycle de vie des cartes :
      - Signature cryptographique HMAC-SHA256 de chaque trame
      - En-têtes horodatés anti-rejeu (X-Timestamp, X-Signature, X-Client-Id)
      - Timeouts stricts
      - Mode Mock/Sandbox pour le développement et la résilience locale
    """

    def __init__(self):
        self.base_url = settings.CMS_API_URL
        self.secret = settings.CMS_HMAC_SECRET
        self.client_id = settings.CMS_CLIENT_ID
        self.timeout = settings.CMS_TIMEOUT_SECONDS
        self.use_mock = settings.USE_MOCK_BANKING

    def _prepare_headers(self, path: str, method: str, body_str: str) -> dict[str, str]:
        """Génère les en-têtes signés HMAC-SHA256 selon les standards monétiques."""
        timestamp = str(int(time.time()))
        # Payload de signature : timestamp.method.path.body
        message_to_sign = f"{timestamp}.{method.upper()}.{path}.{body_str}"
        signature = generate_hmac_signature(self.secret, message_to_sign)

        return {
            "Content-Type": "application/json",
            "X-Client-Id": self.client_id,
            "X-Timestamp": timestamp,
            "X-Signature": signature
        }

    async def _dispatch_cms_command(self, action: str, card_id: int, payload: dict) -> dict[str, Any]:
        """Envoie la commande au serveur monétique ou l'exécute en mode Sandbox Mock."""
        path = f"/cards/{card_id}/{action}"
        body_str = json.dumps(payload, separators=(',', ':'))

        if self.use_mock:
            # Simulation d'un aller-retour monétique de 60ms
            await asyncio.sleep(0.06)
            logger.info(f"[CMS MOCK] Action '{action}' validée avec succès pour la carte {card_id}.")
            return {
                "status": "APPROVED",
                "action": action,
                "card_id": card_id,
                "authorization_code": f"AUTH-{int(time.time()) % 1000000:06d}",
                "timestamp": time.time()
            }

        headers = self._prepare_headers(path, "POST", body_str)
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}{path}",
                    content=body_str,
                    headers=headers
                )
                if response.status_code == 200:
                    return response.json()
                else:
                    raise CMSConnectionException(f"Rejet du switch monétique ({response.status_code}): {response.text}")
        except httpx.RequestError as exc:
            logger.error(f"Erreur réseau CMS : {exc}")
            raise CMSConnectionException("Impossible de joindre le switch monétique (timeout ou réseau).")

    async def freeze_card(self, card_id: int) -> dict[str, Any]:
        return await self._dispatch_cms_command("freeze", card_id, {"reason": "USER_REQUEST_PORTAL"})

    async def unfreeze_card(self, card_id: int) -> dict[str, Any]:
        return await self._dispatch_cms_command("unfreeze", card_id, {"reason": "USER_REQUEST_PORTAL"})

    async def update_limits(self, card_id: int, daily_limit: Decimal, monthly_limit: Decimal) -> dict[str, Any]:
        return await self._dispatch_cms_command("limits", card_id, {
            "daily_limit": str(daily_limit),
            "monthly_limit": str(monthly_limit)
        })

    async def toggle_online_payments(self, card_id: int, enabled: bool) -> dict[str, Any]:
        return await self._dispatch_cms_command("settings/online", card_id, {"enabled": enabled})

    async def toggle_foreign_payments(self, card_id: int, enabled: bool) -> dict[str, Any]:
        return await self._dispatch_cms_command("settings/foreign", card_id, {"enabled": enabled})

    async def toggle_contactless(self, card_id: int, enabled: bool) -> dict[str, Any]:
        return await self._dispatch_cms_command("settings/contactless", card_id, {"enabled": enabled})


cms_client = CMSClient()

