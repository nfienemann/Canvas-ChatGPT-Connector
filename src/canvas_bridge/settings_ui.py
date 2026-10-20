"""Small, server-rendered auth/privacy surface; no academic dashboard."""

import base64
import functools
import hashlib
import html
import secrets
from datetime import timedelta
from urllib.parse import urlencode, urlsplit

from sqlalchemy import select
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

from canvas_bridge.auth import SETTINGS_SCOPE, principal_id
from canvas_bridge.domain import DomainError, utcnow
from canvas_bridge.linking import begin_link, delete_account, digest, disconnect, finish_link
from canvas_bridge.network import public_client
from canvas_bridge.policy import validate_https
from canvas_bridge.storage import BrowserSession, OAuthState, PrincipalState, aware

CSS = """
:root{font-family:system-ui,sans-serif;color:#182e32;background:#f3f7f6;color-scheme:light}
body{margin:0;padding:32px 20px}main{max-width:760px;margin:auto}
h1{font-size:2.4rem;letter-spacing:-.05em;margin-bottom:8px}
.eyebrow{font-size:.8rem;text-transform:uppercase;letter-spacing:.16em;color:#386363}
.card{background:white;border:1px solid #c8d7d3;border-radius:16px;padding:24px;margin:24px 0}
p{line-height:1.6}label{display:block;margin:12px 0}input,select,button{font:inherit}
input[type=text],select{box-sizing:border-box;max-width:100%;padding:10px;border:1px solid #657c79;border-radius:6px}
button,.button{display:inline-block;padding:11px 18px;background:#174e49;color:white;border:0;border-radius:7px;text-decoration:none;cursor:pointer}
button.danger{background:#872f35}a{color:#175c56}small{display:block;line-height:1.6;color:#435e59}
:focus-visible{outline:3px solid #e09a1c;outline-offset:3px}.notice{border-left:4px solid #ae720b;padding:12px 16px;background:#fff6e6}
fieldset{border:1px solid #c8d7d3;border-radius:8px}footer{font-size:.85rem;margin-top:32px}
@media(max-width:500px){body{padding:20px 12px}.card{padding:16px}h1{font-size:2rem}}
"""


def page(title: str, body: str, status: int = 200):
    return HTMLResponse(
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(title)} · Canvas Bridge</title><style>{CSS}</style></head>"
        '<body><main><div class="eyebrow">Canvas Bridge</div>'
        f"<h1>{html.escape(title)}</h1>{body}"
        '<footer><a href="/settings/privacy">Privacy &amp; limitations</a> · '
        '<a href="/settings">Connection settings</a></footer></main></body></html>',
        status_code=status,
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
            "X-Content-Type-Options": "nosniff",
        },
    )


def hidden(name: str, value: str) -> str:
    return (
        f'<input type="hidden" name="{html.escape(name)}" value="{html.escape(value, quote=True)}">'
    )


def add_settings_routes(mcp, bridge, verifier):
    settings = bridge.settings
    root = settings.resource_url.rstrip("/")
    secure = root.startswith("https://")

    def route(path: str, methods: list[str]):
        def decorate(fn):
            @functools.wraps(fn)
            async def safe(request):
                try:
                    return await fn(request)
                except DomainError as exc:
                    return page(
                        "Request unavailable",
                        f'<p role="alert">{html.escape(exc.message)}</p>',
                        403,
                    )
                except Exception:
                    return page(
                        "Try again",
                        '<p role="alert">The request could not be completed safely.</p>',
                        503,
                    )

            return mcp.custom_route(path, methods=methods)(safe)

        return decorate

    async def identity(request, write: bool = False):
        handle = request.cookies.get("bridge_session", "")
        with bridge.store.transaction() as session:
            row = session.get(BrowserSession, digest(handle))
            if not row or aware(row.expires_at) < utcnow():
                raise DomainError("permission_denied", "Sign in to manage your connection.")
            credential = bridge.vault.open(row.credential, row.owner, "browser-session")
        token = await verifier.verify_token(credential["token"])
        if not token or principal_id(token.claims["iss"], token.subject) != row.owner:
            raise DomainError("permission_denied", "Session expired. Sign in again.")
        if write and SETTINGS_SCOPE not in token.scopes:
            raise DomainError("permission_denied", "Settings permission is required.")
        with bridge.store.transaction() as database:
            current = database.get(BrowserSession, row.digest)
            principal = database.get(PrincipalState, row.owner)
            if not current or (principal and current.generation != principal.generation):
                raise DomainError("permission_denied", "This settings session was revoked.")
        return row

    async def form(request, session):
        origin = request.headers.get("origin")
        expected = f"{urlsplit(root).scheme}://{urlsplit(root).netloc}"
        same_origin_without_referrer = (
            origin in {None, "null"} and request.headers.get("sec-fetch-site") == "same-origin"
        )
        if origin != expected and not same_origin_without_referrer:
            raise DomainError(
                "permission_denied", "Settings requests must originate from this site."
            )
        if int(request.headers.get("content-length", "0")) > 16_000:
            raise DomainError("permission_denied", "Form exceeds the size limit.")
        values = await request.form(max_fields=100)
        if not secrets.compare_digest(str(values.get("csrf", "")), session.csrf):
            raise DomainError("permission_denied", "Form session expired; reload settings.")
        return values

    async def open_session(raw_token: str):
        token = await verifier.verify_token(raw_token)
        if not token:
            raise DomainError(
                "permission_denied", "Identity provider did not issue a valid access token."
            )
        owner = principal_id(token.claims["iss"], token.subject)
        handle = secrets.token_urlsafe(32)
        with bridge.store.transaction() as session:
            principal = bridge.store.principal(session, owner)
            session.add(
                BrowserSession(
                    digest=digest(handle),
                    owner=owner,
                    credential=bridge.vault.seal({"token": raw_token}, owner, "browser-session"),
                    csrf=secrets.token_urlsafe(32),
                    expires_at=utcnow() + timedelta(hours=1),
                    generation=principal.generation,
                )
            )
        response = RedirectResponse("/settings", status_code=303)
        response.set_cookie(
            "bridge_session", handle, httponly=True, secure=secure, samesite="lax", max_age=3600
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @route("/settings", ["GET"])
    async def settings_page(request):
        try:
            session = await identity(request)
        except DomainError:
            if bridge.synthetic:
                nonce = secrets.token_urlsafe(32)
                response = page(
                    "Connection settings",
                    "<p>Connect coursework to the conversations you already use.</p>"
                    '<div class="notice">Local synthetic preview. All courses and records are fictional.</div>'
                    '<section class="card"><h2>Try the settings flow</h2>'
                    "<p>The local demo uses a generated test identity. No Canvas account is contacted.</p>"
                    '<form method="post" action="/settings/demo">'
                    + hidden("csrf", nonce)
                    + "<button>Open synthetic settings</button></form></section>",
                )
                response.set_cookie(
                    "bridge_start", nonce, httponly=True, samesite="strict", secure=secure
                )
                return response
            return page(
                "Connection settings",
                "<p>Sign in through the configured identity provider to connect your supported institution.</p>"
                '<a class="button" href="/settings/login">Sign in securely</a>',
            )
        status = bridge.connection_status(session.owner)
        body = "<p>Manage access here. Ask academic questions in ChatGPT.</p>"
        if bridge.synthetic:
            body += '<div class="notice">Synthetic local environment · not a live institution connection</div>'
        for connection in status.data["connections"]:
            if connection["state"] != "active":
                body += '<section class="card"><h2>Disconnected</h2><p>Local access is disabled.</p></section>'
                continue
            courses = await bridge.list_courses(session.owner, connection["id"])
            body += f'<section class="card"><h2>{html.escape(connection["institution"])}</h2>'
            body += '<form method="post" action="/settings/select">' + hidden("csrf", session.csrf)
            body += (
                hidden("connection", connection["id"])
                + "<fieldset><legend>Selected courses</legend>"
            )
            for course in courses.data.get("courses", []):
                checked = " checked" if course["selected"] else ""
                body += (
                    f'<label><input type="checkbox" name="courses" value="{html.escape(course["id"])}"{checked}> '
                    f"{html.escape(course['name'])}</label>"
                )
            body += '</fieldset><label for="timezone">Display timezone (IANA)</label>'
            body += f'<input id="timezone" name="timezone" type="text" required value="{html.escape(connection["timezone"])}">'
            body += "<p><button>Save selection</button></p></form>"
            body += '<form method="post" action="/settings/export">' + hidden("csrf", session.csrf)
            body += (
                hidden("connection", connection["id"])
                + "<button>Export my retained records</button></form>"
            )
            body += "<h3>Disconnect and delete local records</h3>"
            body += "<p>This stops access and queued work and removes active-store records. "
            body += "Existing ChatGPT conversations and independent copies are controlled separately.</p>"
            body += '<form method="post" action="/settings/disconnect">' + hidden(
                "csrf", session.csrf
            )
            body += (
                hidden("connection", connection["id"])
                + '<button class="danger">Disconnect and delete</button></form></section>'
            )
        supported = [
            x
            for x in bridge.registry.entries.values()
            if x.status in {"supported", "pilot_supported"}
        ]
        if supported and not bridge.synthetic:
            body += '<section class="card"><h2>Link an institution</h2><form method="post" action="/settings/link">'
            body += (
                hidden("csrf", session.csrf)
                + '<label for="institution">Supported institution</label><select id="institution" name="institution">'
            )
            for institution in supported:
                body += f'<option value="{html.escape(institution.id)}">{html.escape(institution.name)}</option>'
            body += "</select><p>Only selected coursework will be read. Review privacy and retention before continuing.</p><button>Continue to Canvas</button></form></section>"
        else:
            body += "<p>No live institution is currently advertised as supported. "
            body += "An institution administrator must enable an approved OAuth access path.</p>"
        body += '<section class="card"><h2>Delete all local account data</h2>'
        body += "<p>Disconnect every institution, delete retained coursework and plans, cancel pending linking and queued work, and sign out.</p>"
        body += "<p>Minimal deletion fences remain. Existing ChatGPT conversations, institution records and downloaded copies are controlled separately.</p>"
        body += '<form method="post" action="/settings/delete-account">' + hidden(
            "csrf", session.csrf
        )
        body += '<label><input type="checkbox" name="confirm" value="delete" required> Delete all my local account data</label>'
        body += (
            '<button class="danger">Delete all local data and sign out</button></form></section>'
        )
        return page("Connection settings", body)

    @route("/settings/demo", ["POST"])
    async def demo_login(request):
        if not bridge.synthetic:
            raise DomainError("permission_denied", "Synthetic login is disabled.")

        class Start:
            csrf = request.cookies.get("bridge_start", "")

        if not Start.csrf:
            raise DomainError("permission_denied", "Start from the settings page.")
        await form(request, Start)
        raw_token = settings.local_jwks_file.with_name("demo-token").read_text(encoding="utf-8")
        return await open_session(raw_token.strip())

    @route("/settings/login", ["GET"])
    async def login(request):
        if not all(
            (
                settings.browser_client_id,
                settings.browser_authorization_url,
                settings.browser_token_url,
            )
        ):
            raise DomainError(
                "unsupported_feature", "Operator identity-provider setup has not been completed."
            )
        allowed = {f"https://{urlsplit(settings.issuer_url).hostname}"}
        validate_https(settings.browser_authorization_url, allowed)
        validate_https(settings.browser_token_url, allowed)
        nonce, state, verifier_secret = (secrets.token_urlsafe(32) for _ in range(3))
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier_secret.encode()).digest())
            .decode()
            .rstrip("=")
        )
        callback = root + "/settings/callback"
        with bridge.store.transaction() as session:
            session.add(
                OAuthState(
                    digest=digest(state),
                    owner="identity",
                    institution="__identity__",
                    redirect=callback,
                    browser_digest=digest(nonce),
                    expires_at=utcnow() + timedelta(minutes=10),
                    payload=bridge.vault.seal(
                        {"verifier": verifier_secret}, "identity", digest(state)
                    ),
                )
            )
        response = RedirectResponse(
            settings.browser_authorization_url
            + "?"
            + urlencode(
                {
                    "client_id": settings.browser_client_id,
                    "response_type": "code",
                    "redirect_uri": callback,
                    "scope": "academic:read preferences:write settings:write",
                    "resource": settings.resource_url,
                    "state": state,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                }
            )
        )
        response.set_cookie(
            "bridge_oauth", nonce, httponly=True, secure=secure, samesite="lax", max_age=600
        )
        response.headers.update({"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
        return response

    @route("/settings/callback", ["GET"])
    async def login_callback(request):
        state = request.query_params.get("state", "")
        with bridge.store.transaction() as session:
            record = session.scalar(
                select(OAuthState)
                .where(
                    OAuthState.digest == digest(state),
                    OAuthState.institution == "__identity__",
                )
                .with_for_update()
            )
            if (
                not record
                or aware(record.expires_at) < utcnow()
                or not secrets.compare_digest(
                    record.browser_digest, digest(request.cookies.get("bridge_oauth", ""))
                )
                or request.query_params.get("iss") != settings.issuer_url
            ):
                raise DomainError(
                    "permission_denied", "Identity callback did not match this login."
                )
            verifier_secret = bridge.vault.open(record.payload, "identity", digest(state))[
                "verifier"
            ]
            callback = record.redirect
            session.delete(record)
        code = request.query_params.get("code")
        if not code:
            return page("Sign-in cancelled", "<p>No connection was created.</p>")
        data = {
            "grant_type": "authorization_code",
            "client_id": settings.browser_client_id,
            "code": code,
            "redirect_uri": callback,
            "code_verifier": verifier_secret,
            "resource": settings.resource_url,
        }
        if settings.browser_client_secret_file:
            data["client_secret"] = settings.browser_client_secret_file.read_text().strip()
        async with public_client() as client:
            response = await client.post(settings.browser_token_url, data=data)
            if response.status_code != 200 or len(response.content) > 32_000:
                raise DomainError("permission_denied", "Identity-provider token exchange failed.")
        return await open_session(response.json().get("access_token", ""))

    @route("/settings/select", ["POST"])
    async def select_courses(request):
        session = await identity(request, True)
        values = await form(request, session)
        await bridge.list_courses(session.owner, str(values["connection"]))
        bridge.select_courses(
            session.owner,
            str(values["connection"]),
            values.getlist("courses"),
            str(values["timezone"]),
        )
        return RedirectResponse("/settings", 303)

    @route("/settings/link", ["POST"])
    async def link(request):
        session = await identity(request, True)
        values = await form(request, session)
        nonce = secrets.token_urlsafe(32)
        response = RedirectResponse(
            begin_link(
                bridge, session.owner, str(values["institution"]), nonce, session.generation
            ),
            303,
        )
        response.set_cookie(
            "bridge_canvas", nonce, httponly=True, secure=secure, samesite="lax", max_age=600
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @route("/settings/canvas/callback", ["GET"])
    async def canvas_callback(request):
        result = await finish_link(
            bridge,
            request.query_params.get("state", ""),
            request.cookies.get("bridge_canvas", ""),
            request.query_params.get("code"),
        )
        return page("Canvas authorization", f"<p>{html.escape(result.summary)}</p>")

    @route("/settings/disconnect", ["POST"])
    async def remove(request):
        session = await identity(request, True)
        values = await form(request, session)
        result = await disconnect(bridge, session.owner, str(values["connection"]))
        return page(
            "Disconnected",
            f"<p>{html.escape(result.summary)}</p><p>Remote revocation: {html.escape(result.data['remote_revocation'])}.</p>"
            "<p>Existing conversations, downloaded copies and independently created calendar events are unchanged.</p>",
        )

    @route("/settings/export", ["POST"])
    async def export(request):
        session = await identity(request, True)
        values = await form(request, session)
        ref = str(values["connection"])
        return JSONResponse(
            bridge.store.export_connection(session.owner, ref),
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": 'attachment; filename="canvas-bridge-export.json"',
            },
        )

    @route("/settings/delete-account", ["POST"])
    async def remove_account(request):
        session = await identity(request, True)
        values = await form(request, session)
        if values.get("confirm") != "delete":
            raise DomainError("needs_input", "Select the deletion confirmation before continuing.")
        result = await delete_account(bridge, session.owner, session.generation)
        unconfirmed = sum(
            outcome["remote_revocation"] == "not_confirmed"
            for outcome in result.data["remote_revocations"]
        )
        response = page(
            "Local account data deleted",
            f"<p>{html.escape(result.summary)}</p>"
            f"<p>Unconfirmed remote revocations: {unconfirmed}.</p>"
            "<p>Minimal deletion fences remain. Existing conversations, institution records and downloaded copies are controlled separately.</p>",
        )
        for name in ("bridge_session", "bridge_canvas", "bridge_oauth", "bridge_start"):
            response.delete_cookie(name, secure=secure, httponly=True, samesite="lax")
        return response

    @route("/settings/privacy", ["GET"])
    async def privacy(request):
        return page(
            "Privacy & limitations",
            """
        <section class="card"><h2>What this service does</h2>
        <p>Canvas Bridge reads your selected coursework and returns facts to your authenticated
        conversation. It does not submit coursework, edit grades, sell academic records or require
        a model API key. Calendar writes and notifications are disabled.</p>
        <h2>Local development status</h2><p>This build is verified with synthetic data.
        No school, ChatGPT client or public listing is currently certified as supported.
        A deployed service needs its own reviewed operator, region and privacy arrangements.</p>
        <h2>Retention and deletion</h2><p>Current normalized records remain while selected and authorized.
        Observation history is purged after 30 days when the worker or purge command runs.
        Disconnect removes active connection records and credentials and stops queued work.
        Delete all local account data applies this to every linked institution and cancels
        pending Canvas authorization and browser sessions.
        A minimal deletion fence remains for safe restore. Backup expiry is an operator responsibility,
        with a proposed maximum of 30 days before a real-data pilot.</p>
        <p>Deleting here cannot delete prior ChatGPT conversations, downloaded exports,
        institution records or independently created calendar events.</p>
        <h2>Help</h2><p>For this development build, contact the repository owner through the
        repository support instructions. Do not send tokens, private grades or course content.</p></section>
        """,
        )
