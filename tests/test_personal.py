import asyncio
import json
import warnings
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from canvas_bridge.auth import JWTVerifier
from canvas_bridge.canvas import CanvasClient
from canvas_bridge.config import Settings
from canvas_bridge.domain import DomainError
from canvas_bridge.linking import begin_link, delete_account, disconnect, finish_link
from canvas_bridge.personal import link_personal_token, read_personal_token, run_personal_setup
from canvas_bridge.storage import Connection, Course


@pytest.fixture
def personal_bridge(bridge, monkeypatch):
    # Only fixture HTTP is used. Live Settings still require PostgreSQL and HTTPS.
    provider = bridge.synthetic
    bridge.synthetic = None
    bridge.settings.profile = "personal"
    bridge.settings.personal_subject = "student-one"
    bridge.settings.live_access_enabled = True
    bridge.registry.entries["synthetic"].status = "personal_testing"

    def client(institution, token, settings, *args):
        result = CanvasClient(institution, token, settings, http=provider.client())
        result.owns_http = True
        return result

    monkeypatch.setattr("canvas_bridge.personal.CanvasClient", client)
    monkeypatch.setattr("canvas_bridge.service.CanvasClient", client)
    return bridge


async def test_T13_T23_personal_import_verifies_identity_encrypts_and_requires_course_choice(
    personal_bridge, owner
):
    bridge = personal_bridge
    token = "private-fixture-token"
    result = await link_personal_token(bridge, "synthetic", "101", token)
    ref = result.data["connection_id"]
    assert result.data["actual_chatgpt"] == "not_tested"
    assert token not in result.model_dump_json()
    with bridge.store.transaction() as session:
        conn = session.get(Connection, ref)
        assert conn.owner == owner and conn.canvas_user == "101"
        assert conn.token_expires_at is None  # No invented OAuth expiry / refresh grant.
        assert token not in conn.credential
        assert bridge.vault.open(conn.credential, owner, ref) == {"access_token": token}
        assert list(session.scalars(select(Course))) == []
    courses = await bridge.list_courses(owner, ref)
    assert len(courses.data["courses"]) == 2
    assert not any(course["selected"] for course in courses.data["courses"])
    bridge.select_courses(owner, ref, [c["id"] for c in courses.data["courses"]], "UTC")
    snapshot = await bridge.refresh(owner, ref)
    assert snapshot.complete and len(snapshot.items) == 5
    with pytest.raises(DomainError, match="limited to its owner"):
        async with bridge.client("other-owner", ref):
            pytest.fail("Another principal must never reach Canvas.")


@pytest.mark.parametrize("profile", ["synthetic", "hosted"])
async def test_T38_personal_import_disabled_in_other_profiles(bridge, profile):
    bridge.settings.profile = profile
    with pytest.raises(DomainError, match="private personal profile"):
        await link_personal_token(bridge, "synthetic", "101", "fixture")
    with bridge.store.transaction() as session:
        assert not list(session.scalars(select(Connection)))


async def test_T13_T38_personal_import_rejects_mismatch_and_unapproved_origin(personal_bridge):
    bridge = personal_bridge
    with pytest.raises(DomainError, match="expected Canvas user"):
        await link_personal_token(bridge, "synthetic", "202", "fixture")
    for institution in ("rowan-candidate", "https://arbitrary.invalid"):
        with pytest.raises(DomainError):
            await link_personal_token(bridge, institution, "101", "fixture")
    for token in ("", "Bearer credential", "fixture\nheader", "x" * 4097):
        with pytest.raises(DomainError, match="valid personal testing token"):
            await link_personal_token(bridge, "synthetic", "101", token)
    with pytest.raises(DomainError):
        bridge.registry.require("synthetic")  # Private status never enables hosted OAuth.
    with pytest.raises(DomainError, match="operator-only"):
        begin_link(bridge, "another-owner", "synthetic", "browser")
    with pytest.raises(DomainError, match="operator-only"):
        await finish_link(bridge, "pending-state", "browser", "code")
    with bridge.store.transaction() as session:
        assert not list(session.scalars(select(Connection)))


async def test_T18_personal_import_cannot_overwrite_or_resurrect_deleted_account(
    personal_bridge, owner, monkeypatch
):
    bridge = personal_bridge
    first = await link_personal_token(bridge, "synthetic", "101", "fixture-one")
    with pytest.raises(DomainError, match="Disconnect the existing"):
        await link_personal_token(bridge, "synthetic", "101", "fixture-two")
    with bridge.store.transaction() as session:
        conn = session.get(Connection, first.data["connection_id"])
        assert bridge.vault.open(conn.credential, owner, conn.id)["access_token"] == "fixture-one"
    monkeypatch.setattr("canvas_bridge.linking.revoke_token", AsyncMock(return_value="confirmed"))
    await delete_account(bridge, owner)

    started, release = asyncio.Event(), asyncio.Event()

    async def delayed_profile(*args):
        started.set()
        await release.wait()
        return {"id": 101}

    monkeypatch.setattr(CanvasClient, "one", delayed_profile)
    task = asyncio.create_task(link_personal_token(bridge, "synthetic", "101", "fixture-new"))
    await started.wait()
    await delete_account(bridge, owner)
    release.set()
    with pytest.raises(DomainError, match="deletion cancelled"):
        await task
    with bridge.store.transaction() as session:
        assert not list(session.scalars(select(Connection)))


async def test_T14_T18_personal_disconnect_revokes_only_its_approved_origin(
    personal_bridge, owner, monkeypatch
):
    import httpx

    bridge = personal_bridge
    result = await link_personal_token(bridge, "synthetic", "101", "fixture-token")
    calls = []

    def revoke(request):
        calls.append(request)
        return httpx.Response(204)

    monkeypatch.setattr(
        "canvas_bridge.linking.public_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(revoke)),
    )
    receipt = await disconnect(bridge, owner, result.data["connection_id"])
    assert receipt.data["remote_revocation"] == "confirmed"
    assert len(calls) == 1 and calls[0].method == "DELETE"
    assert str(calls[0].url) == "https://canvas.synthetic.invalid/login/oauth2/token"
    assert calls[0].headers["authorization"] == "Bearer fixture-token"
    assert "fixture-token" not in receipt.model_dump_json()


async def test_T21_personal_identity_allowlist_still_checks_signature_and_claims(
    settings, token_factory, monkeypatch
):
    settings.profile = "personal"
    settings.personal_subject = "student-one"
    keys = json.loads(settings.local_jwks_file.read_text())["keys"]
    verifier = JWTVerifier(settings)
    monkeypatch.setattr(verifier, "_keys", AsyncMock(return_value=keys))
    assert await verifier.verify_token(token_factory())
    for changes in (
        {"sub": "student-two", "email": "same@example.invalid"},
        {"iss": "https://wrong-issuer.invalid"},
        {"aud": "https://wrong-resource.invalid"},
        {"exp": 1},
    ):
        assert await verifier.verify_token(token_factory(**changes)) is None


def test_T21_personal_settings_require_an_owner_and_live_prerequisites():
    config = {
        "_env_file": None,
        "profile": "personal",
        "live_access_enabled": True,
        "database_url": "postgresql+psycopg://fixture:fixture@localhost/fixture",
        "resource_url": "https://bridge.invalid",
        "issuer_url": "https://issuer.invalid",
        "jwks_url": "https://issuer.invalid/keys",
    }
    with pytest.raises(ValidationError, match="one configured"):
        Settings(**config)
    assert Settings(**config, personal_subject="subject-one").profile == "personal"
    for overrides in (
        {"live_access_enabled": False},
        {"database_url": "sqlite:///:memory:"},
        {"resource_url": "http://localhost"},
        {"local_jwks_file": "fixture-key"},
    ):
        with pytest.raises(ValidationError):
            Settings(**(config | overrides), personal_subject="subject-one")


def test_T23_personal_prompt_refuses_echo_fallback_and_redacts_failures(monkeypatch, capsys):
    import getpass

    monkeypatch.setattr("canvas_bridge.personal.sys.stdin.isatty", lambda: False)
    with pytest.raises(DomainError, match="interactive private"):
        read_personal_token()
    monkeypatch.setattr("canvas_bridge.personal.sys.stdin.isatty", lambda: True)

    def unsafe_prompt(*args):
        warnings.warn("fixture-secret", getpass.GetPassWarning, stacklevel=2)

    monkeypatch.setattr("canvas_bridge.personal.getpass.getpass", unsafe_prompt)
    with pytest.raises(DomainError, match="Hidden terminal input"):
        read_personal_token()

    def fail_settings():
        raise ValueError("fixture-secret")

    monkeypatch.setattr("canvas_bridge.config.Settings", fail_settings)
    with pytest.raises(SystemExit, match="Private setup failed") as exc:
        run_personal_setup("synthetic", "101")
    assert "fixture-secret" not in str(exc.value)
    assert "fixture-secret" not in str(capsys.readouterr())


async def test_T21_T37_read_only_catalog_omits_writes_instead_of_relabeling(bridge, settings):
    from canvas_bridge.app import create_app

    settings.mcp_read_only = True
    server = create_app(settings, bridge).state.mcp
    tools = await server.list_tools()
    assert len(tools) == 31
    assert {"render_course_file_page", "interpret_course_schedule"} <= {tool.name for tool in tools}
    assert "propose_course_study_plan" in {tool.name for tool in tools}
    assert all(tool.annotations.readOnlyHint for tool in tools)
    assert {"get_workload", "propose_study_plan", "fetch_course_material"} <= {
        tool.name for tool in tools
    }
    for name in ("update_study_preferences", "record_personal_progress", "save_study_plan"):
        # Unknown tools fail before any authenticated handler or storage write.
        with pytest.raises(Exception, match="Unknown tool"):
            await server.call_tool(name, {})
