"""Operator-only personal proof. Never registered as an MCP tool or browser route."""

import asyncio
import getpass
import sys
import warnings

from sqlalchemy import select

from canvas_bridge.auth import principal_id
from canvas_bridge.canvas import CanvasClient
from canvas_bridge.domain import DomainError, Result, opaque_id
from canvas_bridge.policy import Endpoint, source_id
from canvas_bridge.storage import Connection


def personal_setup(bridge, institution_id: str, expected_canvas_user: str):
    settings = bridge.settings
    if (
        settings.profile != "personal"
        or not settings.live_access_enabled
        or not settings.personal_subject
        or bridge.synthetic is not None
    ):
        raise DomainError("permission_denied", "This command requires a private personal profile.")
    institution = bridge.registry.require(institution_id, personal=True)
    owner = principal_id(settings.issuer_url, settings.personal_subject)
    return owner, institution, source_id(expected_canvas_user)


def no_existing_connection(session, owner: str, institution_id: str):
    if session.scalar(
        select(Connection.id).where(
            Connection.owner == owner,
            Connection.institution == institution_id,
            Connection.state == "active",
        )
    ):
        raise DomainError(
            "needs_input", "Disconnect the existing account in settings before replacing access."
        )


async def link_personal_token(
    bridge, institution_id: str, expected_canvas_user: str, token: str
) -> Result:
    owner, institution, expected_user = personal_setup(bridge, institution_id, expected_canvas_user)
    if not 1 <= len(token) <= 4096 or any(not 33 <= ord(c) <= 126 for c in token):
        raise DomainError(
            "needs_input", "Enter a valid personal testing token in the private prompt."
        )
    with bridge.store.transaction() as session:
        principal = bridge.store.principal(session, owner)
        generation = principal.generation
        no_existing_connection(session, owner, institution_id)
    client = CanvasClient(institution, token, bridge.settings)
    try:
        async with asyncio.timeout(bridge.settings.refresh_budget_seconds):
            profile = await client.one(Endpoint.PROFILE)
        if source_id(profile.get("id", "")) != expected_user:
            raise DomainError(
                "permission_denied", "The token does not match the expected Canvas user."
            )
    except TimeoutError:
        raise DomainError(
            "retry_later", "Canvas identity verification timed out; nothing was saved."
        ) from None
    finally:
        await client.close()
    ref = opaque_id()
    with bridge.store.transaction() as session:
        principal = bridge.store.principal(session, owner)
        if principal.generation != generation:
            raise DomainError(
                "permission_denied", "Account deletion cancelled this setup; nothing was saved."
            )
        # The principal lock serializes simultaneous imports on PostgreSQL.
        no_existing_connection(session, owner, institution_id)
        session.add(
            Connection(
                id=ref,
                owner=owner,
                institution=institution_id,
                canvas_user=expected_user,
                credential=bridge.vault.seal({"access_token": token}, owner, ref),
            )
        )
    return Result(
        summary="Private Canvas identity verified. Sign in to settings and choose courses next.",
        data={
            "connection_id": ref,
            "institution": institution_id,
            "courses_selected": False,
            "actual_chatgpt": "not_tested",
        },
    )


def read_personal_token() -> str:
    # getpass otherwise falls back to echoed input when terminal control is unavailable.
    if not sys.stdin.isatty():
        raise DomainError("needs_input", "Open an interactive private operator terminal for setup.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            return getpass.getpass("Your own Canvas testing token (hidden): ")
    except (getpass.GetPassWarning, EOFError, OSError):
        raise DomainError(
            "needs_input", "Hidden terminal input is unavailable; nothing was saved."
        ) from None


def run_personal_setup(institution_id: str, expected_canvas_user: str):
    from canvas_bridge.app import create_bridge
    from canvas_bridge.config import Settings

    bridge = None
    try:
        bridge = create_bridge(Settings())
        personal_setup(bridge, institution_id, expected_canvas_user)
        result = asyncio.run(
            link_personal_token(bridge, institution_id, expected_canvas_user, read_personal_token())
        )
        print(result.model_dump_json(indent=2))
    except DomainError as exc:
        raise SystemExit(str(exc)) from None
    except KeyboardInterrupt:
        raise SystemExit("Private setup cancelled.") from None
    except Exception:
        # Configuration validation / transport / DB exceptions may contain private values.
        raise SystemExit(
            "Private setup failed. Check the private configuration and database; no diagnostic secrets were printed."
        ) from None
    finally:
        if bridge:
            bridge.store.close()
