import json

import pytest
from sqlalchemy import select

from canvas_bridge.domain import DomainError, utcnow
from canvas_bridge.inventory_cursor import KIND, binding, load, save
from canvas_bridge.storage import Connection, LocalRecord
from tests.conftest import seed
from tests.test_mcp_contract import running as running
from tests.test_permission_consistency_contract import client_session


def checkpoint(index, expires):
    return LocalRecord(
        id=f"checkpoint-{index:02}",
        key=f"checkpoint-{index:02}",
        kind=KIND,
        payload={
            "binding": {"epoch": 1, "course": "private-course", "source": "private-source"},
            "state": {"unfinished": "private-traversal"},
            "expires": expires,
        },
    )


def store_rows(bridge, owner, connection, rows):
    with bridge.store.transaction() as db:
        for row in rows:
            row.owner = owner
            row.connection_id = connection
            db.add(row)


async def test_23_active_checkpoints_are_an_empty_study_state(
    bridge, owner, seeded, running, token_factory
):
    expires = utcnow().timestamp() + 86400
    store_rows(bridge, owner, seeded, [checkpoint(i, expires) for i in range(23)])
    async with client_session(running, token_factory()) as session:
        reply = await session.call_tool(
            "get_saved_study_state", {"connection_id": seeded, "include_institutional": True}
        )
    result = reply.structuredContent
    assert result["status"] == "ok"
    assert result["data"]["records"] == []
    assert "No saved" in result["summary"]
    assert not result["meta"].get("next_cursor")
    for secret in (KIND, "checkpoint-", "private-source", "private-traversal"):
        assert secret not in reply.model_dump_json()
    with bridge.store.transaction() as db:
        rows = db.scalars(select(LocalRecord).where(LocalRecord.kind == KIND)).all()
        assert len(rows) == 23 and all(row.payload["expires"] == expires for row in rows)


@pytest.mark.parametrize("with_checkpoints", [False, True])
async def test_study_pages_and_scope(
    bridge, owner, seeded, running, token_factory, with_checkpoints
):
    bridge.store.save_local(owner, seeded, "preferences", "default", {"timezone": "UTC"}, 0)
    bridge.independent.preferences(owner, {"timezone": "Europe/Paris"}, 0)
    study = [
        LocalRecord(id=f"study-{i:02}", kind="progress", key=f"work-{i}", payload={"minutes": i})
        for i in range(27)
    ]
    study.append(LocalRecord(kind="plan", key="current", payload={"title": "Synthetic plan"}))
    store_rows(bridge, owner, seeded, study)
    if with_checkpoints:
        now = utcnow().timestamp()
        store_rows(
            bridge, owner, seeded, [checkpoint(i, now + (-1 if i % 2 else 3600)) for i in range(40)]
        )
        for kind in ("semester_state", "practice", "future_internal_kind"):
            store_rows(
                bridge,
                owner,
                seeded,
                [LocalRecord(kind=kind, key="internal", payload={"title": "internal-only"})],
            )
    other = await seed(bridge, "another-owner", "other-connection")
    store_rows(
        bridge, "another-owner", other, [LocalRecord(kind="plan", key="foreign-plan", payload={})]
    )
    args = {"connection_id": seeded, "include_institutional": True}
    async with client_session(running, token_factory()) as session:

        async def read(arguments):
            reply = await session.call_tool("get_saved_study_state", arguments)
            result = reply.structuredContent
            assert result["status"] == "ok", result
            return result

        first = await read(args)
        cursor = first["meta"]["next_cursor"]
        assert cursor and first["meta"]["warnings"]
        second = await read({**args, "cursor": cursor})
        assert not second["meta"].get("next_cursor")
        records = first["data"]["records"] + second["data"]["records"]
        assert len(first["data"]["records"]) == 25
        assert len(records) == 29
        assert {(r["kind"], r["key"]) for r in records} == {
            ("preferences", "default"),
            ("plan", "current"),
            *(("progress", f"work-{i}") for i in range(27)),
        }
        assert "_provenance" not in json.dumps(records)
        assert owner not in json.dumps(records)
        local = (await read({"connection_id": seeded}))["data"]["records"]
        assert len(local) == 1 and local[0]["value"]["timezone"] == "UTC"
        independent = (await read({}))["data"]["records"]
        assert len(independent) == 1 and independent[0]["value"]["timezone"] == "Europe/Paris"
    for who, ref, institutional in (
        (owner, other, True),
        ("another-owner", other, True),
        (owner, seeded, False),
    ):
        with pytest.raises(DomainError):
            bridge.local_state(who, ref, include_institutional=institutional, cursor=cursor)
    with bridge.store.transaction() as db:
        db.get(Connection, seeded).epoch += 1
    with pytest.raises(DomainError, match="invalid or expired"):
        bridge.local_state(owner, seeded, include_institutional=True, cursor=cursor)


async def test_empty_connection_in_both_modes(bridge, owner, seeded):
    for institutional in (False, True):
        result = bridge.local_state(owner, seeded, include_institutional=institutional)
        assert result.data["records"] == [] and result.meta.next_cursor is None
        assert "No saved" in result.summary


async def test_study_read_preserves_resumable_inventory_checkpoint(bridge, owner, seeded):
    conn, courses = bridge.selected(owner, seeded)
    bound = binding(conn, courses[0])
    state = {"unfinished": "synthetic-page"}
    token = save(bridge, owner, seeded, bound, state)
    for institutional in (False, True):
        assert (
            bridge.local_state(owner, seeded, include_institutional=institutional).data["records"]
            == []
        )
    with pytest.raises(DomainError):
        bridge.local_state(owner, seeded, include_institutional=True, cursor=token)
    assert load(bridge, owner, seeded, bound, token) == state
