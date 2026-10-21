from fastapi import Request, status
from fastapi.responses import JSONResponse, HTMLResponse


class BankingException(Exception):
    """Exception de base pour les erreurs métiers bancaires."""
    def __init__(self, message: str, code: str = "BANKING_ERROR", status_code: int = 400):
        self.message = message
        self.code = code
        self.status_code = status_code
        super().__init__(message)


class AuthenticationFailedException(BankingException):
    def __init__(self, message: str = "Identifiants invalides."):
        super().__init__(message, code="AUTH_FAILED", status_code=status.HTTP_401_UNAUTHORIZED)


class TOTPRequiredException(BankingException):
    def __init__(self, message: str = "Code d'authentification à deux facteurs (TOTP) requis."):
        super().__init__(message, code="TOTP_REQUIRED", status_code=status.HTTP_403_FORBIDDEN)


class InvalidTOTPCodeException(BankingException):
    def __init__(self, message: str = "Code 2FA invalide ou expiré."):
        super().__init__(message, code="INVALID_TOTP", status_code=status.HTTP_400_BAD_REQUEST)


UNPROCESSABLE_STATUS = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422)


class InsufficientFundsException(BankingException):
    def __init__(self, message: str = "Solde insuffisant pour exécuter cette opération."):
        super().__init__(message, code="INSUFFICIENT_FUNDS", status_code=UNPROCESSABLE_STATUS)


class CardFrozenException(BankingException):
    def __init__(self, message: str = "Cette carte bancaire est actuellement verrouillée/gelée."):
        super().__init__(message, code="CARD_FROZEN", status_code=status.HTTP_403_FORBIDDEN)


class CardLimitExceededException(BankingException):
    def __init__(self, message: str = "Le montant dépasse les plafonds autorisés pour cette carte."):
        super().__init__(message, code="CARD_LIMIT_EXCEEDED", status_code=UNPROCESSABLE_STATUS)


class InvalidRIBException(BankingException):
    def __init__(self, message: str = "Les coordonnées bancaires (RIB / IBAN) sont invalides."):
        super().__init__(message, code="INVALID_RIB", status_code=status.HTTP_400_BAD_REQUEST)


class IdempotencyConflictException(BankingException):
    def __init__(self, message: str = "Une requête identique avec cette clé d'idempotence est déjà en cours ou a déjà été exécutée."):
        super().__init__(message, code="IDEMPOTENCY_CONFLICT", status_code=status.HTTP_409_CONFLICT)


class CBSConnectionException(BankingException):
    def __init__(self, message: str = "Le système central Core Banking (CBS) est momentanément inaccessible."):
        super().__init__(message, code="CBS_UNAVAILABLE", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)


class CMSConnectionException(BankingException):
    def __init__(self, message: str = "Le système monétique (CMS) a rejeté ou échoué la transaction."):
        super().__init__(message, code="CMS_UNAVAILABLE", status_code=status.HTTP_502_BAD_GATEWAY)


class AFB160FormattingException(BankingException):
    def __init__(self, message: str = "Erreur de formatage du fichier selon la norme bancaire AFB 160."):
        super().__init__(message, code="AFB160_ERROR", status_code=status.HTTP_400_BAD_REQUEST)


async def banking_exception_handler(request: Request, exc: BankingException):
    """
    Handler global pour les exceptions métiers :
    Si la requête provient de HTMX (`HX-Request` header), renvoie un fragment d'alerte UI.
    Sinon, renvoie une réponse JSON standardisée.
    """
    is_htmx = request.headers.get("HX-Request") == "true"
    
    if is_htmx:
        html = f"""
        <div class="p-4 mb-4 text-sm text-rose-300 rounded-xl bg-rose-950/80 border border-rose-800/60 shadow-lg flex items-center space-x-3 transition-all animate-shake" role="alert">
            <svg class="w-5 h-5 flex-shrink-0 text-rose-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path>
            </svg>
            <div>
                <span class="font-semibold block">{exc.code}</span>
                <span>{exc.message}</span>
            </div>
        </div>
        """
        return HTMLResponse(content=html, status_code=exc.status_code)

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": {
                "code": exc.code,
                "message": exc.message
            }
        }
    )
