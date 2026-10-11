"""A fake supplier portal ("Portal de Proveedores TecnoLoja") served at /portal.

Many LATAM suppliers do not email invoices: they publish them on a portal you
have to log into. This mock has the parts that make scraping non-trivial: a
login form with a session cookie, a paginated table and file downloads via
`Content-Disposition`. Everything is synthetic and lives inside this app.
"""

import html
import json
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Cookie, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from opsagent.datagen.records import GroundTruth
from opsagent.settings import Settings

PAGE_SIZE = 4
COOKIE = "portal_session"


@lru_cache
def _portal_invoices(dataset_dir: str) -> tuple[GroundTruth, ...]:
    truths = json.loads((Path(dataset_dir) / "ground_truth.json").read_text(encoding="utf-8"))
    portal = [GroundTruth.model_validate(t) for t in truths if t.get("channel") == "portal"]
    return tuple(sorted(portal, key=lambda t: t.extraction.issue_date, reverse=True))


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} · Portal de Proveedores TecnoLoja (demo)</title>
<style>
body{{font-family:system-ui,sans-serif;margin:0;background:#f4f6f8;color:#1b1f24}}
header{{background:#14532d;color:#fff;padding:14px 24px;font-weight:600}}
main{{max-width:880px;margin:24px auto;background:#fff;border-radius:10px;padding:24px;
box-shadow:0 1px 3px rgba(0,0,0,.08)}}
table{{width:100%;border-collapse:collapse}}th,td{{padding:8px;border-bottom:1px solid #e5e7eb;
text-align:left}}
input{{padding:8px;margin:4px 0 12px;width:100%;box-sizing:border-box}}
button,a.btn{{background:#14532d;color:#fff;border:0;padding:8px 14px;border-radius:6px;
text-decoration:none}}
.note{{font-size:12px;color:#6b7280}}
</style></head><body><header>Portal de Proveedores · TecnoLoja Soluciones (DEMO SINTÉTICA)</header>
<main>{body}</main></body></html>"""
    )


def build_portal_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/portal", include_in_schema=False)
    sessions: set[str] = set()

    def require_session(token: str | None) -> None:
        if token not in sessions:
            raise HTTPException(status_code=303, headers={"Location": "/portal/login"})

    @router.get("", response_class=HTMLResponse)
    @router.get("/login", response_class=HTMLResponse)
    def login_form(error: str | None = None) -> HTMLResponse:
        message = '<p style="color:#b91c1c">Credenciales incorrectas.</p>' if error else ""
        return _page(
            "Ingreso",
            f"""<h1>Ingreso de clientes</h1>{message}
<form method="post" action="/portal/login">
<label for="username">Usuario</label><input id="username" name="username" autocomplete="username">
<label for="password">Contraseña</label>
<input id="password" name="password" type="password" autocomplete="current-password">
<button type="submit">Ingresar</button></form>
<p class="note">Portal ficticio para la demo de invoice-ops-agent.
Credenciales de prueba: ver <code>.env.example</code>.</p>""",
        )

    @router.post("/login")
    def login(
        username: Annotated[str, Form()], password: Annotated[str, Form()]
    ) -> RedirectResponse:
        valid = secrets.compare_digest(
            username, settings.portal_username
        ) and secrets.compare_digest(password, settings.portal_password.get_secret_value())
        if not valid:
            return RedirectResponse("/portal/login?error=1", status_code=303)
        token = secrets.token_urlsafe(24)
        sessions.add(token)
        response = RedirectResponse("/portal/facturas", status_code=303)
        response.set_cookie(COOKIE, token, httponly=True, samesite="lax")
        return response

    @router.get("/facturas", response_class=HTMLResponse)
    def invoices(
        request: Request,
        page: int = 1,
        portal_session: Annotated[str | None, Cookie()] = None,
    ) -> HTMLResponse:
        require_session(portal_session)
        items = _portal_invoices(str(settings.demo_dataset_dir))
        pages = max(1, -(-len(items) // PAGE_SIZE))
        page = min(max(page, 1), pages)
        rows = "".join(
            f"""<tr data-testid="invoice-row">
<td>{html.escape(t.extraction.invoice_number)}</td><td>{t.extraction.issue_date:%d/%m/%Y}</td>
<td>$ {t.extraction.total:,.2f}</td><td>Emitida</td>
<td><a class="btn" data-testid="download" href="/portal/facturas/{html.escape(t.file)}/descargar">
Descargar</a></td></tr>"""
            for t in items[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]
        )
        nav = ""
        if page < pages:
            nav = f'<p><a rel="next" href="/portal/facturas?page={page + 1}">Siguiente »</a></p>'
        return _page(
            "Mis facturas",
            f"""<h1>Facturas emitidas a su empresa</h1>
<p class="note">Página {page} de {pages} · {len(items)} documentos</p>
<table><thead><tr><th>N.º factura</th><th>Emisión</th><th>Total</th><th>Estado</th><th></th>
</tr></thead><tbody>{rows}</tbody></table>{nav}""",
        )

    @router.get("/facturas/{file}/descargar")
    def download(file: str, portal_session: Annotated[str | None, Cookie()] = None) -> Response:
        require_session(portal_session)
        known = {t.file for t in _portal_invoices(str(settings.demo_dataset_dir))}
        if file not in known:  # also blocks any path traversal attempt
            raise HTTPException(status_code=404)
        content = (settings.demo_dataset_dir / "invoices" / file).read_bytes()
        media = "application/pdf" if file.endswith(".pdf") else "image/jpeg"
        return Response(
            content,
            media_type=media,
            headers={"Content-Disposition": f'attachment; filename="{file}"'},
        )

    return router
