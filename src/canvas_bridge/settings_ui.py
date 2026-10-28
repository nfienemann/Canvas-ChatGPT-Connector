"""Small, server-rendered auth/privacy surface; no academic dashboard."""

import base64
import functools
import hashlib
import html
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode, urlsplit

from sqlalchemy import select
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

from canvas_bridge.auth import SETTINGS_SCOPE, principal_id
from canvas_bridge.domain import DomainError, utcnow
from canvas_bridge.linking import (
    begin_link,
    delete_account,
    digest,
    disconnect,
    finish_link,
    terminate_sessions,
)
from canvas_bridge.network import infrastructure_http, public_client
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

    def authorization_context():
        return {
            "issuer": settings.issuer_url,
            "authorization_url": settings.browser_authorization_url,
            "token_url": settings.browser_token_url,
            "client_id": settings.browser_client_id,
            "resource": settings.resource_url,
            "require_issuer": settings.browser_require_issuer_parameter,
        }

    def route(path: str, methods: list[str]):
        def decorate(fn):
            @functools.wraps(fn)
            async def safe(request):
                try:
                    canonical = urlsplit(root)
                    if path in {"/settings", "/settings/login"} and (
                        request.url.scheme,
                        request.url.netloc,
                    ) != (canonical.scheme, canonical.netloc):
                        return RedirectResponse(
                            f"{canonical.scheme}://{canonical.netloc}{path}",
                            status_code=303,
                            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
                        )
                    response = await fn(request)
                    check = getattr(request.state, "validate_bridge_session", None)
                    if check and fn.__name__ not in {"sign_out", "remove_account"}:
                        check()
                    return response
                except DomainError as exc:
                    return page(
                        "Request unavailable",
                        f'<p role="alert">{html.escape(exc.message)}</p><p>Reason: {html.escape(exc.data.get("reason_code", "REQUEST_UNAVAILABLE"))}</p>',
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
        from canvas_bridge.egress_models import RecipientIdentity

        row.egress_identity = RecipientIdentity(
            "user_download",
            token.claims["iss"],
            token.claims.get("client_id") or "",
            token.claims.get("bridge_recipient_environment") or "",
            token.claims.get("bridge_recipient_workspace") or "",
        )
        with bridge.store.transaction() as database:
            current = database.get(BrowserSession, row.digest)
            principal = database.get(PrincipalState, row.owner)
            if not current or (principal and current.generation != principal.generation):
                raise DomainError("permission_denied", "This settings session was revoked.")

        def recheck_session():
            verifier.require_current(token)
            with bridge.store.transaction() as database:
                current = database.get(BrowserSession, row.digest)
                principal = database.get(PrincipalState, row.owner)
                if (
                    not current
                    or aware(current.expires_at) <= utcnow()
                    or (principal and current.generation != principal.generation)
                ):
                    raise DomainError("permission_denied", "This settings session was revoked.")

        request.state.validate_bridge_session = recheck_session
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
        check = getattr(request.state, "validate_bridge_session", None)
        if check:
            check()
        return values

    async def open_session(
        raw_token: str, *, expected_owner=None, replaced_digest=None, started_at=None
    ):
        token = await verifier.verify_token(raw_token)
        if not token:
            from canvas_bridge.auth import last_rejection

            raise DomainError(
                "permission_denied",
                "Identity provider did not issue a valid access token. The operator must verify issuer, audience and the configured stable owner subject; email equality does not establish identity.",
                reason_code=last_rejection.get() or "MCP_TOKEN_VALIDATION_FAILED",
            )
        owner = principal_id(token.claims["iss"], token.subject)
        if expected_owner and owner != expected_owner:
            raise DomainError(
                "permission_denied", "Sign out before switching application accounts."
            )
        handle = secrets.token_urlsafe(32)
        with bridge.store.transaction() as session:
            principal = bridge.store.principal(session, owner)
            if (
                principal.tokens_valid_after
                and min(
                    token.claims["iat"],
                    started_at if started_at is not None else token.claims["iat"],
                )
                <= aware(principal.tokens_valid_after).timestamp()
            ):
                raise DomainError("permission_denied", "Application session was revoked.")
            if replaced_digest:
                old = session.get(BrowserSession, replaced_digest)
                if old:
                    session.delete(old)
            session.add(
                BrowserSession(
                    digest=digest(handle),
                    owner=owner,
                    credential=bridge.vault.seal({"token": raw_token}, owner, "browser-session"),
                    csrf=secrets.token_urlsafe(32),
                    expires_at=min(
                        utcnow() + timedelta(hours=1), datetime.fromtimestamp(token.expires_at, UTC)
                    ),
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
                (
                    "<p>Sign in to your private Canvas test.</p>"
                    if settings.profile == "personal"
                    else "<p>Sign in through the configured identity provider to connect your supported institution.</p>"
                )
                + '<a class="button" href="/settings/login">Sign in securely</a>',
            )
        status = bridge.connection_status(session.owner)
        body = '<p>Manage access here. Ask academic questions in ChatGPT.</p><p><a href="/settings/storage">Stored data and deletion controls</a> · <a href="/settings/documents">Import independent documents</a></p><p>Independent documents and local study preferences remain available without Canvas approval.</p>'
        if bridge.synthetic:
            body += '<div class="notice">Synthetic local environment · not a live institution connection</div>'
        elif settings.profile == "personal":
            body += '<div class="notice">Private developer test · access is limited to the configured owner.</div>'
        from canvas_bridge.authorization_status import stages

        institution_stages = {
            key: stages(bridge, session.owner, value)
            for key, value in bridge.registry.entries.items()
        }
        for key, assessment in institution_stages.items():
            body += (
                '<section class="card"><h2>Authorization stages: ' + html.escape(key) + "</h2><dl>"
            )
            for label, value in assessment.items():
                if label not in {"link_action_available", "next_action"}:
                    body += (
                        "<dt>"
                        + html.escape(label.replace("_", " "))
                        + "</dt><dd>"
                        + html.escape(str(value))
                        + "</dd>"
                    )
            body += "</dl><p>" + html.escape(assessment["next_action"]) + "</p></section>"
        for connection in status.data["connections"]:
            if connection["state"] != "active":
                body += (
                    '<section class="card"><h2>Disconnected</h2><p>Authentication: '
                    + html.escape(connection.get("authentication_state", "unverified"))
                    + ". Local access is disabled.</p></section>"
                )
                continue
            authentication = connection.get("authentication_state", "unverified")
            if (
                connection.get("live_integration") == "disabled"
                or authentication != "verified"
                or settings.capability_profile != "institutional_pilot"
            ):
                body += f'<section class="card"><h2>{html.escape(connection["institution"])}</h2>'
                body += f"<p>Authentication: {html.escape(authentication)}.</p>"
                body += "<p>Live access is disabled until the required approvals and identity verification are established.</p>"
                body += '<form method="post" action="/settings/disconnect">' + hidden(
                    "csrf", session.csrf
                )
                body += hidden("connection", connection["id"])
                body += '<button class="danger">Disconnect and delete</button></form></section>'
                continue
            courses = await bridge.list_courses(session.owner, connection["id"])
            body += f'<section class="card"><h2>{html.escape(connection["institution"])}</h2>'
            body += f"<p>Authentication at page load: {html.escape(authentication)}. Integration approval is checked separately.</p>"
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
            if institution_stages[x.id]["link_action_available"]
        ]
        if settings.profile == "personal":
            body += "<p>Canvas access is configured privately by the operator. "
            body += "After setup, choose your courses here. This test cannot onboard other students.</p>"
        elif supported and not bridge.synthetic:
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
        body += '<form method="post" action="/settings/sign-out">' + hidden("csrf", session.csrf)
        body += "<button>Sign out all Bridge sessions</button></form>"
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
        try:
            previous = await identity(request) if request.cookies.get("bridge_session") else None
        except DomainError:
            previous = None  # Expired sessions must not prevent a fresh sign-in.
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier_secret.encode()).digest())
            .decode()
            .rstrip("=")
        )
        callback = settings.browser_callback_url
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
                        {
                            "verifier": verifier_secret,
                            "context": authorization_context(),
                            "expected_owner": previous.owner if previous else None,
                            "replaced_digest": previous.digest if previous else None,
                            "started_at": utcnow().timestamp(),
                        },
                        "identity",
                        digest(state),
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
                    "scope": "academic:read settings:write"
                    + (" preferences:write" if not settings.mcp_read_only else ""),
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

    @route("/settings/callback/{issuer_key}", ["GET"])
    @route("/settings/callback", ["GET"])
    async def login_callback(request):
        canonical = urlsplit(root)
        if (request.url.scheme, request.url.netloc) != (canonical.scheme, canonical.netloc):
            raise DomainError(
                "permission_denied",
                "Restart sign-in from the configured service origin.",
                reason_code="OAUTH_CALLBACK_ORIGIN_MISMATCH",
            )
        if any(
            len(request.query_params.getlist(name)) > 1
            for name in ("state", "code", "iss", "error")
        ):
            raise DomainError("permission_denied", "Identity callback parameters are ambiguous.")
        state = request.query_params.get("state", "")
        response_issuer = request.query_params.get("iss")
        with bridge.store.transaction() as session:
            record = session.scalar(
                select(OAuthState)
                .where(
                    OAuthState.digest == digest(state),
                    OAuthState.institution == "__identity__",
                )
                .with_for_update()
            )
            failures = [
                (not record, "OAUTH_STATE_UNKNOWN"),
                (bool(record) and aware(record.expires_at) < utcnow(), "OAUTH_STATE_EXPIRED"),
                (not request.cookies.get("bridge_oauth"), "OAUTH_BROWSER_COOKIE_MISSING"),
                (
                    bool(record)
                    and not secrets.compare_digest(
                        record.browser_digest, digest(request.cookies.get("bridge_oauth", ""))
                    ),
                    "OAUTH_BROWSER_COOKIE_MISMATCH",
                ),
                (
                    bool(record)
                    and (
                        record.redirect != settings.browser_callback_url
                        or request.url.path != urlsplit(record.redirect).path
                    ),
                    "OAUTH_REDIRECT_MISMATCH",
                ),
                (
                    (response_issuer is not None and response_issuer != settings.issuer_url)
                    or (settings.browser_require_issuer_parameter and response_issuer is None),
                    "OAUTH_ISSUER_MISMATCH",
                ),
            ]
            for failed, code in failures:
                if failed:
                    raise DomainError(
                        "permission_denied",
                        "Identity callback did not match this login. Restart sign-in from the canonical settings page.",
                        reason_code=code,
                    )
            payload = bridge.vault.open(record.payload, "identity", digest(state))
            if payload.get("context") != authorization_context():
                raise DomainError(
                    "permission_denied", "Identity-provider configuration changed; sign in again."
                )
            verifier_secret = payload["verifier"]
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
            async with infrastructure_http(
                client, method="POST", url=settings.browser_token_url
            ).stream("POST", settings.browser_token_url, data=data) as response:
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 32_000:
                        raise DomainError(
                            "permission_denied", "Identity-provider response exceeded the limit."
                        )
            if response.status_code != 200:
                raise DomainError(
                    "permission_denied",
                    "Identity-provider token exchange failed. Start a new login; the single-use code cannot be retried.",
                    reason_code="OAUTH_TOKEN_EXCHANGE_FAILED",
                )
        import json

        return await open_session(
            json.loads(raw).get("access_token", ""),
            expected_owner=payload.get("expected_owner"),
            replaced_digest=payload.get("replaced_digest"),
            started_at=payload.get("started_at", 0),
        )

    @route("/settings/select", ["POST"])
    async def select_courses(request):
        session = await identity(request, True)
        values = await form(request, session)
        await bridge.list_courses(session.owner, str(values["connection"]))
        request.state.validate_bridge_session()
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

    @route("/settings/canvas/callback/{issuer_key}", ["GET"])
    @route("/settings/canvas/callback", ["GET"])
    async def canvas_callback(request):
        session = await identity(request, True)
        if any(
            len(request.query_params.getlist(name)) > 1
            for name in ("state", "code", "iss", "error")
        ):
            raise DomainError("permission_denied", "Canvas callback parameters are ambiguous.")
        result = await finish_link(
            bridge,
            request.query_params.get("state", ""),
            request.cookies.get("bridge_canvas", ""),
            request.query_params.get("code"),
            callback=urlsplit(root)._replace(path=request.url.path, query="", fragment="").geturl(),
            response_issuer=request.query_params.get("iss"),
            expected_owner=session.owner,
        )
        return page("Canvas authorization", f"<p>{html.escape(result.summary)}</p>")

    @route("/settings/sign-out", ["POST"])
    async def sign_out(request):
        session = await identity(request)
        await form(request, session)
        terminate_sessions(bridge, session.owner, session.generation)
        response = page(
            "Signed out",
            "<p>Existing Bridge sessions and pending work were stopped. Sign in again to continue.</p>",
        )
        for name in ("bridge_session", "bridge_canvas", "bridge_oauth", "bridge_start"):
            response.delete_cookie(name, secure=secure, httponly=True, samesite="lax")
        return response

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
        from canvas_bridge.approval_policy import CATEGORIES

        bridge.connection_policy(
            session.owner, ref, CATEGORIES, activity="share", recipient="user_download"
        )
        exported = bridge.store.export_connection(session.owner, ref)
        bridge.connection_policy(
            session.owner, ref, CATEGORIES, activity="share", recipient="user_download"
        )
        exported = bridge.egress.connection_export(
            session.owner, ref, session.egress_identity, exported
        )
        return JSONResponse(
            exported,
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": 'attachment; filename="canvas-bridge-export.json"',
            },
        )

    @route("/settings/storage", ["GET"])
    async def storage_page(request):
        session = await identity(request)
        inventory = bridge.retention.inventory(session.owner)
        body = "<p>These counts cover this account's local database. Temporary source files and renderings expire separately.</p><ul>"
        for category, count in inventory["stored_categories"].items():
            body += f"<li>{html.escape(category)}: {count}</li>"
        body += "</ul>"
        for source in inventory["sources"]:
            if source["state"] != "active":
                continue
            body += f'<section class="card"><h2>{html.escape(source["institution"])}</h2>'
            for action, label, description in (
                (
                    "delete-caches",
                    "Delete local caches",
                    "Remove cached documents, downloads, images and workload snapshots. Saved study records and course selection remain.",
                ),
                (
                    "delete-records",
                    "Delete retained academic records",
                    "Remove coursework, documents, saved plans and progress, and clear course selection. The provider connection remains until disconnected.",
                ),
            ):
                body += f'<form method="post" action="/settings/{action}"><p>{description}</p>'
                body += hidden("csrf", session.csrf) + hidden("connection", source["id"])
                body += f'<label><input type="checkbox" name="confirm" value="{action}" required> Authorize this local deletion</label><button class="danger">{label}</button></form>'
            body += "</section>"
        body += "<h2>Retention policies</h2>"
        for category, rule in inventory["policies"].items():
            body += f"<p><strong>{html.escape(category.replace('_', ' '))}</strong>: {html.escape(rule['expiry'])}.</p>"
        body += "<p>Deletion does not disconnect the provider or prevent a later authorized retrieval. Disconnect in connection settings to stop future access.</p>"
        body += f"<p>{html.escape(inventory['outside_control'])}</p><p>Deletion does not guarantee immediate physical erasure from disks or immutable backups. Restores apply deletion fences.</p>"
        return page("Stored data and deletion", body)

    async def delete_local(request, *, academic):
        session = await identity(request, True)
        values = await form(request, session)
        action = "delete-records" if academic else "delete-caches"
        if values.get("confirm") != action:
            raise DomainError("needs_input", "Select the explicit deletion confirmation first.")
        result = bridge.retention.delete_local(
            session.owner,
            str(values["connection"]),
            academic=academic,
            confirmed=True,
            generation=session.generation,
        )
        return page(
            "Local deletion receipt",
            "<p>Local access to the deleted data is blocked.</p>"
            + f"<p>Receipt: {html.escape(result['receipt_id'])}. Cleanup status: {html.escape(result['local_deletion'])}.</p>"
            + f"<p>Removed database rows: {sum(result['deleted_rows'].values())}. Pending temporary cleanup: {result['pending_temporary_cleanup']}.</p>"
            + "<p>Other services and existing backup copies are unchanged. Physical erasure is not guaranteed; restoration is fenced.</p>",
        )

    @route("/settings/delete-caches", ["POST"])
    async def delete_caches(request):
        return await delete_local(request, academic=False)

    @route("/settings/delete-records", ["POST"])
    async def delete_records(request):
        return await delete_local(request, academic=True)

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
        <h2>Retention and deletion</h2><p>Normalized academic records, observation history and saved study records expire after 30 days.
        File text expires within 24 hours; page text within one hour. Connections expire after 90 days.
        Disconnect removes active connection records and credentials and stops queued work.
        Delete all local account data applies this to every linked institution and cancels
        pending Canvas authorization and browser sessions.
        A minimal deletion fence remains for 31 days for safe restore. Logical backups expire after 30 days,
        exclude credentials and raw document text, and restore connections inactive. Operators must separately remove physical backup copies.</p>
        <p>Deleting here cannot delete prior ChatGPT conversations, downloaded exports,
        institution records or independently created calendar events.</p>
        <h2>Help</h2><p>For this development build, contact the repository owner through the
        repository support instructions. Do not send tokens, private grades or course content.</p></section>
        """,
        )

    from canvas_bridge.independent_ui import register_import_routes

    register_import_routes(bridge, route, identity, form, page, hidden)
