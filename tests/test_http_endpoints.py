import pytest
import httpx
from app.main import app, lifespan
from app.core.security import create_access_token


@pytest.mark.asyncio
async def test_health_check_endpoint():
    async with lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.get("/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "healthy"
            assert "app" in data


@pytest.mark.asyncio
async def test_security_headers_and_login_page():
    async with lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.get("/login")
            assert resp.status_code == 200
            
            # Vérification des en-têtes de cybersécurité stricts
            assert resp.headers["X-Frame-Options"] == "DENY"
            assert resp.headers["X-Content-Type-Options"] == "nosniff"
            assert "Content-Security-Policy" in resp.headers


@pytest.mark.asyncio
async def test_dashboard_authenticated():
    async with lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            # Sans cookie -> redirection
            resp_unauth = await client.get("/dashboard", follow_redirects=False)
            assert resp_unauth.status_code in [302, 303, 307]

            # Avec token valide
            token = create_access_token({"sub": "1"})
            client.cookies.set("neobank_session", token)

            resp_auth = await client.get("/dashboard")
            assert resp_auth.status_code == 200
            assert "Tableau de Bord" in resp_auth.text
            assert "Alexandre Dumas" in resp_auth.text


@pytest.mark.asyncio
async def test_rib_pdf_download():
    async with lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            token = create_access_token({"sub": "1"})
            client.cookies.set("neobank_session", token)

            resp = await client.get("/accounts/1/rib/pdf")
            assert resp.status_code == 200
            assert resp.headers["Content-Type"] == "application/pdf"
            assert resp.content.startswith(b"%PDF-")  # Magic bytes officiels PDF
