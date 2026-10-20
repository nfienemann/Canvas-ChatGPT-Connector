import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import select

from canvas_bridge.domain import DomainError, utcnow
from canvas_bridge.linking import begin_link, digest, finish_link, refresh_credential
from canvas_bridge.policy import Institution
from canvas_bridge.storage import Connection, OAuthState


def configure(bridge, monkeypatch):
    bridge.settings.profile = "hosted"
    bridge.registry.entries["synthetic"] = Institution(
        id="synthetic",
        name="Fictional school",
        origin="https://canvas.synthetic.invalid",
        status="pilot_supported",
        scopes=["url:GET|/api/v1/courses"],
        client_id_env="FIXTURE_CANVAS_CLIENT",
        client_secret_env="FIXTURE_CANVAS_SECRET",
    )
    monkeypatch.setenv("FIXTURE_CANVAS_CLIENT", "fixture")
    monkeypatch.setenv("FIXTURE_CANVAS_SECRET", "fixture-only")


async def test_T14_oauth_state_bound_to_browser_and_one_use(bridge, owner, monkeypatch):
    configure(bridge, monkeypatch)
    from urllib.parse import parse_qs, urlsplit

    url = begin_link(bridge, owner, "synthetic", "browser-one")
    state = parse_qs(urlsplit(url).query)["state"][0]
    with pytest.raises(DomainError):
        await finish_link(bridge, state, "browser-two", None)
    cancelled = await finish_link(bridge, state, "browser-one", None)
    assert "cancelled" in cancelled.summary
    with pytest.raises(DomainError):
        await finish_link(bridge, state, "browser-one", None)
    with bridge.store.transaction() as session:
        assert not list(session.scalars(select(Connection)))


async def test_T14_expired_state_cannot_link(bridge, owner, monkeypatch):
    configure(bridge, monkeypatch)
    with bridge.store.transaction() as session:
        session.add(
            OAuthState(
                digest=digest("old-state"),
                owner=owner,
                institution="synthetic",
                redirect="https://bridge.invalid/callback",
                browser_digest=digest("browser"),
                expires_at=utcnow() - timedelta(seconds=1),
            )
        )
    with pytest.raises(DomainError):
        await finish_link(bridge, "old-state", "browser", "code")


async def test_T14_refresh_race_only_one_provider_exchange(bridge, owner, seeded, monkeypatch):
    configure(bridge, monkeypatch)
    with bridge.store.transaction() as session:
        conn = session.get(Connection, seeded)
        conn.token_expires_at = utcnow() - timedelta(seconds=1)
        conn.credential = bridge.vault.seal(
            {"access_token": "old", "refresh_token": "renewal"},
            owner,
            seeded,
        )
    started, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def exchange(*args, **kwargs):
        calls.append(1)
        started.set()
        await release.wait()
        return {"access_token": "new", "expires_in": 3600}

    monkeypatch.setattr("canvas_bridge.linking.exchange", exchange)
    first = asyncio.create_task(refresh_credential(bridge, owner, seeded))
    await started.wait()
    with pytest.raises(DomainError, match="already in progress"):
        await refresh_credential(bridge, owner, seeded)
    release.set()
    value = await first
    assert len(calls) == 1
    assert bridge.vault.open(value, owner, seeded)["access_token"] == "new"


async def test_T18_disconnect_during_refresh_cannot_resurrect_token(
    bridge, owner, seeded, monkeypatch
):
    configure(bridge, monkeypatch)
    with bridge.store.transaction() as session:
        conn = session.get(Connection, seeded)
        conn.token_expires_at = utcnow() - timedelta(seconds=1)
        conn.credential = bridge.vault.seal(
            {"access_token": "old", "refresh_token": "r"}, owner, seeded
        )

    async def exchange(*args, **kwargs):
        bridge.store.disconnect(owner, seeded)
        return {"access_token": "new", "expires_in": 3600}

    monkeypatch.setattr("canvas_bridge.linking.exchange", exchange)
    with pytest.raises(DomainError):
        await refresh_credential(bridge, owner, seeded)
    with bridge.store.transaction() as session:
        assert session.get(Connection, seeded).credential is None
