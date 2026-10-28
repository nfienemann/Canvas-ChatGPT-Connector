"""October 23 report reproductions use fictional records, never live identifiers."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from alembic import command
from alembic.config import Config
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from canvas_bridge.academic_intelligence import academic_request
from canvas_bridge.assignment_links import references
from canvas_bridge.calendar_sync import CalendarContext, propose_sync
from canvas_bridge.domain import DomainError, FactDate
from canvas_bridge.evidence import attach
from canvas_bridge.normalize import normalize_assignment
from canvas_bridge.planning import PlanRequest, propose
from canvas_bridge.service import Bridge
from canvas_bridge.storage import Connection, Snapshot, Store
from tests.conftest import seed
from tests.test_course_files import file_record
from tests.test_domain_planning import task
from tests.test_file_reading import readable as readable
from tests.test_mcp_contract import running as running

NOW = datetime(2026, 10, 24, 1, 7, tzinfo=UTC)


def effort(minutes=60):
    return {
        "minimum_minutes": minutes,
        "maximum_minutes": minutes,
        "origin": "assistant_estimate",
        "assumptions": "Synthetic regression input only.",
    }


def request(start="2026-10-24T10:00:00-04:00", end="2026-10-24T12:00:00-04:00", **kwargs):
    return PlanRequest(
        windows=[{"start": start, "end": end}],
        break_minutes=0,
        buffer_minutes=0,
        max_block_minutes=60,
        **kwargs,
    )


@pytest.fixture
async def workload_case(bridge, owner, seeded, monkeypatch):
    monkeypatch.setattr("canvas_bridge.service.utcnow", lambda: NOW)
    monkeypatch.setattr("canvas_bridge.normalize.utcnow", lambda: NOW)
    monkeypatch.setattr("canvas_bridge.authorization.utcnow", lambda: NOW)
    with bridge.store.transaction() as session:
        session.get(Connection, seeded).entitlement_at = NOW
    rows = []
    for index, due in enumerate(
        [
            "2026-10-26T10:30:00-04:00",
            "2026-10-28T10:30:00-04:00",
            None,
            None,
            "2026-11-02T10:30:00-05:00",
            "2026-11-04T10:30:00-05:00",
        ],
        401,
    ):
        rows.append(
            {
                "id": index,
                "name": f"Synthetic task {index}",
                "due_at": due,
                "description": "Synthetic requirements",
                "published": True,
                "locked_for_user": index >= 405,
                "unlock_at": None,
                "lock_at": "2026-12-02T16:00:00Z",
                "submission_types": ["online_quiz"],
                "submission": {"user_id": 101, "workflow_state": "unsubmitted"},
            }
        )
    rows[4]["unlock_at"] = "2026-10-27T04:00:00Z"
    rows[5]["unlock_at"] = "2026-10-29T04:00:00Z"
    bridge.synthetic.data["assignments"]["11"] = rows
    course = next(c for c in bridge.selected(owner, seeded)[1] if c.source_id == "11")
    return course


async def workload(
    bridge,
    owner,
    seeded,
    course,
    *,
    end="2026-10-27T00:00:00-04:00",
    start="2026-10-23T00:00:00-04:00",
    **kwargs,
):
    result = await bridge.workload(
        owner,
        seeded,
        datetime.fromisoformat(start),
        datetime.fromisoformat(end),
        "America/New_York",
        [course.id],
        include_overdue=False,
        include_undated=False,
        **kwargs,
    )
    with bridge.store.transaction() as session:
        session.get(Snapshot, result.meta.snapshot_id).created_at = NOW
    return result


async def test_filtered_workload_plan_scope_busy_time_and_coverage(
    bridge, owner, seeded, workload_case
):
    result = await workload(bridge, owner, seeded, workload_case)
    ref = result.data["items"][0]["id"]
    assert len(result.data["items"]) == 1
    plan = attach(
        bridge.study_plan(
            owner,
            seeded,
            result.meta.snapshot_id,
            request(
                effort_overrides={ref: effort()},
                busy_times=[
                    {"start": "2026-10-24T10:30:00-04:00", "end": "2026-10-24T11:30:00-04:00"}
                ],
            ),
        )
    )
    assert {r["work_id"] for r in plan.data["recommendations"]} == {ref}
    assert set(plan.data["timing_constraints"]) == {ref}
    assert set(plan.data["work_accounting"]) == {ref}
    assert [b["minutes"] for b in plan.data["blocks"]] == [30, 30]
    assert plan.data["blocks"][1]["start"] == "2026-10-24T15:30:00+00:00"
    assert plan.data["unmet_work"] == []
    assert plan.data["known_shortfall_minutes"] == 0
    assert plan.data["known_capacity_status"] == "fits"
    assert plan.data["feasibility"] == "provisional"  # Prerequisites remain unknown.
    assert plan.meta.coverage == result.meta.coverage
    assert plan.meta.display_timezone == "America/New_York"
    assert plan.sources[0].retrieved_at == result.sources[0].retrieved_at
    assert not any(
        "completeness were not established" in u for e in plan.evidence for u in e["uncertainty"]
    )
    assert {c.resource for c in plan.meta.coverage} == {"assignments"}
    assert plan.data["workload_scope"] == result.data["workload_scope"]


async def test_paginated_view_keeps_all_selected_work_and_rejects_excluded_override(
    bridge, owner, seeded, workload_case
):
    kwargs = {"end": "2026-10-30T00:00:00-04:00", "limit": 1}
    first = await workload(bridge, owner, seeded, workload_case, **kwargs)
    second = await workload(
        bridge, owner, seeded, workload_case, cursor=first.meta.next_cursor, **kwargs
    )
    assert first.meta.snapshot_id == second.meta.snapshot_id
    refs = {first.data["items"][0]["id"], second.data["items"][0]["id"]}
    assert len(refs) == 2 and second.meta.next_cursor is None
    plan = bridge.study_plan(
        owner, seeded, first.meta.snapshot_id, request(effort_overrides={r: effort() for r in refs})
    )
    assert set(plan.data["work_accounting"]) == refs
    assert sum(b["minutes"] for b in plan.data["blocks"]) == 120
    snapshot = bridge.snapshot(owner, seeded, first.meta.snapshot_id)
    assert len(snapshot.items) == 6  # Raw inventory still supports historical comparison.
    excluded = next(x["id"] for x in snapshot.items if x["id"] not in refs)
    with pytest.raises(DomainError, match="outside this workload"):
        bridge.study_plan(
            owner, seeded, snapshot.id, request(effort_overrides={excluded: effort()})
        )
    with pytest.raises(DomainError):
        bridge.study_plan("different-owner", seeded, snapshot.id, request())
    bridge.select_courses(owner, seeded, [], "UTC")
    with pytest.raises(DomainError):
        bridge.study_plan(owner, seeded, snapshot.id, request())


async def test_future_locked_tasks_allocate_after_opening_across_dst(
    bridge, owner, seeded, workload_case
):
    view = await workload(
        bridge,
        owner,
        seeded,
        workload_case,
        start="2026-11-01T00:00:00-04:00",
        end="2026-11-06T00:00:00-05:00",
    )
    refs = {x["id"] for x in view.data["items"]}
    assert len(refs) == 2
    before = len(bridge.synthetic.requests)
    plan = bridge.study_plan(
        owner,
        seeded,
        view.meta.snapshot_id,
        request(
            "2026-11-01T12:00:00-05:00",
            "2026-11-01T14:00:00-05:00",
            effort_overrides={r: effort() for r in refs},
        ),
    ).data
    assert len(bridge.synthetic.requests) == before  # Planning makes no content request.
    assert {b["work_id"] for b in plan["blocks"]} == refs
    assert sum(b["minutes"] for b in plan["blocks"]) == 120
    assert all(b["conditional_on_future_access"] for b in plan["blocks"])
    assert plan["feasibility"] == "provisional" and plan["unmet_work"] == []
    assert plan["known_shortfall_minutes"] == 0


@pytest.mark.parametrize(
    "case", ["before", "closing", "unknown_opening", "closed", "inaccessible", "pinned"]
)
def test_future_timing_and_accounting(case):
    item = task("future", 60, NOW + timedelta(days=4))
    item.availability_state = "future_locked"
    item.available_from = FactDate(kind="timestamp", timestamp=NOW + timedelta(days=1))
    item.closes_at = FactDate(kind="timestamp", timestamp=NOW + timedelta(days=3))
    start = NOW + timedelta(days=2)
    if case == "before":
        start = NOW
    elif case == "closing":
        start = NOW + timedelta(days=3)
    elif case == "unknown_opening":
        item.available_from = FactDate()
    elif case in {"closed", "inaccessible"}:
        item.availability_state = case
    kwargs = {}
    if case == "pinned":
        kwargs["pinned_blocks"] = [
            {"work_id": item.id, "start": start, "end": start + timedelta(hours=1)}
        ]
    plan = propose(
        [item], request(start.isoformat(), (start + timedelta(hours=1)).isoformat(), **kwargs), NOW
    )
    assert set(plan["work_accounting"]) == {item.id}
    if case == "pinned":
        assert plan["blocks"][0]["conditional_on_future_access"]
    else:
        assert not plan["blocks"]
        assert plan["unmet_work"] or plan["omitted_work"]
    if case == "unknown_opening":
        assert plan["unmet_work"][0]["reason"] == "source_opening_unknown"
    if case == "before":
        with pytest.raises(ValueError, match="source timing"):
            propose(
                [item],
                request(
                    start.isoformat(),
                    (start + timedelta(hours=1)).isoformat(),
                    pinned_blocks=[
                        {"work_id": item.id, "start": start, "end": start + timedelta(hours=1)}
                    ],
                ),
                NOW,
            )


@pytest.mark.parametrize(
    "extra,expected,shortfall",
    [(None, "feasible", 0), ("unknown", "provisional", 0), ("demand", "shortfall", 60)],
)
def test_known_capacity_separate_from_unknown_information(extra, expected, shortfall):
    items = [task("known", 60, NOW + timedelta(days=1))]
    if extra:
        items.append(task(extra, 60 if extra == "demand" else None, NOW + timedelta(days=1)))
    result = propose(items, request(NOW.isoformat(), (NOW + timedelta(hours=1)).isoformat()), NOW)
    assert result["feasibility"] == expected
    assert result["known_shortfall_minutes"] == shortfall
    if extra == "unknown":
        assert result["unmet_work"][0]["minutes"] is None
        assert result["known_capacity_status"] == "fits"
        assert result["information_status"] == "uncertain"


@pytest.mark.parametrize("state", ["submitted", "graded", "excused"])
def test_completed_past_due_items_never_imply_recovery(state):
    item = task("finished", 60, NOW - timedelta(days=1))
    if state == "submitted":
        item.submission_state = "submitted"
    else:
        item.assessment_state = state
    result = propose([item], request(), NOW)
    assert result["timing_constraints"][item.id]["past_due"]
    assert not result["timing_constraints"][item.id]["overdue_recovery"]
    assert not result["recommendations"] and not result["blocks"]


def test_future_allocation_preserves_capacity_before_opening_for_other_work():
    future = task("future", 60, NOW + timedelta(hours=3))
    future.availability_state = "future_locked"
    future.available_from = FactDate(kind="timestamp", timestamp=NOW + timedelta(hours=1))
    available = task("available", 60, NOW + timedelta(hours=4))
    result = propose(
        [future, available], request(NOW.isoformat(), (NOW + timedelta(hours=2)).isoformat()), NOW
    )
    assert [b["work_id"] for b in result["blocks"]] == ["available", "future"]
    assert result["known_shortfall_minutes"] == 0
    assert result["feasibility"] == "provisional"


async def test_assignment_links_authorized_without_downloading_or_guessing(
    bridge, owner, seeded, readable
):
    course, file_id = readable
    raw = bridge.synthetic.data["assignments"]["11"][0]
    raw[
        "description"
    ] = """<p><a href="/courses/11/files/51/download?verifier=secret">Instructions.pdf</a></p>
        <a href="https://elsewhere.invalid/files/51?token=secret">External</a>
        <a href="/courses/12/files/51">Other course</a>
        <a href="/courses/11/files/52">Denied</a><p>GuessThisFilename.docx</p>"""
    bridge.synthetic.data["files"]["11"].append(file_record(id=52, locked_for_user=True))
    snap = await bridge.refresh(owner, seeded, [course.id])
    work_id = next(i["id"] for i in snap.items if i["source_id"] == "1")
    bridge.synthetic.requests.clear()
    result = await bridge.assignment_details(owner, seeded, work_id)
    links = result.data["linked_materials"]["references"]
    assert [r["state"] for r in links] == [
        "resolved",
        "external_not_followed",
        "outside_assignment_course",
        "denied",
    ]
    assert links[0]["material_id"] == file_id
    assert links[0]["continuation"]["file_id"] == file_id
    assert "secret" not in str(result.data)
    assert not any(r.url.path.endswith("/download") for r in bridge.synthetic.requests)
    assert not any("/courses/12/files/" in r.url.path for r in bridge.synthetic.requests)
    assert all(r.method == "GET" for r in bridge.synthetic.requests)


@pytest.mark.parametrize("parser_blocked", [False, True])
@pytest.mark.parametrize("explicit", [False, True])
async def test_review_prioritizes_explicit_links_and_reports_parser_guard(
    bridge, owner, seeded, readable, monkeypatch, parser_blocked, explicit
):
    course, file_id = readable
    raw = bridge.synthetic.data["assignments"]["11"][0]
    raw["description"] = '<a href="/courses/11/files/51">Instructions.pdf</a>'
    from tests.test_file_reading import scientific_pdf

    body = scientific_pdf(["Write 900 words. Include 4 references."])
    bridge.synthetic.data["file_bodies"]["51"] = body
    bridge.synthetic.data["files"]["11"][0]["size"] = len(body)
    snap = await bridge.refresh(owner, seeded, [course.id])
    work_id = next(i["id"] for i in snap.items if i["source_id"] == "1")
    monkeypatch.setattr("canvas_bridge.academic_intelligence.MAX_DOCUMENTS", 1)
    if parser_blocked:

        async def blocked(*args, **kwargs):
            raise DomainError(
                "retry_later",
                "Synthetic parser restart guard",
                reason_code="DOCUMENT_PARSER_VERSION_CHANGED",
                processing_stage="result_validation",
            )

        monkeypatch.setattr("canvas_bridge.academic_intelligence.fetch_material", blocked)
    result = await academic_request(
        bridge,
        owner,
        seeded,
        course.id,
        "instructions",
        work_id=work_id,
        material_ids=[file_id] if explicit else None,
    )
    reviewed = result.data["material_discovery"]["documents"][0]
    assert reviewed["material_id"] == file_id
    assert reviewed["discovery_basis"] == [
        "explicit_selection" if explicit else "explicit_assignment_link"
    ]
    assert result.data["instruction_document_review"]["description_present"]
    assert result.data["instruction_document_review"]["documents"][0]["material_id"] == file_id
    if parser_blocked:
        assert reviewed["state"] == "failed"
        assert reviewed["reason_code"] == "DOCUMENT_PARSER_VERSION_CHANGED"
    else:
        assert reviewed["state"] == "reviewed"
        assert result.data["linked_materials"]["references"][0]["content_reviewed"]
        assert any("900" in str(rule) for rule in result.data["rules"])
        assert any(p["source_id"] == file_id for p in result.data["source_passages"])


def test_link_parser_limits_and_hidden_or_unsafe_links():
    rows, truncated = references(
        '<script><a href="/files/51">hidden</a></script><a href="javascript:bad()">bad</a>'
        + '<a href="/files/51">file</a>' * 25,
        "https://canvas.synthetic.invalid",
        "11",
    )
    assert truncated and len(rows) == 20
    assert rows[0]["state"] == "unsafe_reference"
    assert not any(r["title"] == "hidden" for r in rows)


def normalized(raw, now=NOW):
    return normalize_assignment(
        raw,
        owner="synthetic-owner",
        connection="synthetic-connection",
        institution="synthetic",
        course="synthetic-course",
        canvas_course="11",
        canvas_user="101",
        origin="https://canvas.synthetic.invalid",
        now=now,
    )


def test_raw_and_semantic_hashes_distinguish_rotating_transport_and_real_changes():
    raw = {
        "id": 1,
        "name": "Synthetic task",
        "description": '<a href="/courses/11/files/51?verifier=first">Instructions</a>',
        "due_at": "2026-10-28T10:00:00Z",
        "submission": {
            "user_id": 101,
            "workflow_state": "submitted",
            "submitted_at": "2026-10-23T10:00:00Z",
            "preview_url": "https://canvas.synthetic.invalid/preview?token=first",
        },
    }
    first = normalized(raw)
    assert (
        normalized(raw, NOW + timedelta(minutes=1)).source.content_hash == first.source.content_hash
    )
    rotated = deepcopy(raw)
    rotated["description"] = raw["description"].replace("first", "second")
    rotated["submission"]["preview_url"] = raw["submission"]["preview_url"].replace(
        "first", "second"
    )
    second = normalized(rotated)
    assert first.source.content_hash != second.source.content_hash
    assert first.source.semantic_hash == second.source.semantic_hash
    for field, value in [
        ("description", raw["description"].replace("51", "52")),
        ("description", "New instructions"),
        ("due_at", "2026-10-29T10:00:00Z"),
        ("rubric", [{"description": "New criterion"}]),
        ("submission", {"user_id": 101, "workflow_state": "unsubmitted"}),
    ]:
        changed = {**raw, field: value}
        assert normalized(changed).source.semantic_hash != first.source.semantic_hash


async def test_rotating_hash_does_not_break_fresh_submission_reconciliation(bridge, owner, seeded):
    raw = bridge.synthetic.data["assignments"]["11"][0]
    raw["updated_at"] = "2026-10-23T10:00:00Z"
    raw["submission"].update(
        workflow_state="submitted",
        submitted_at="2026-10-23T10:00:00Z",
        preview_url="https://canvas.synthetic.invalid/preview?token=one",
    )
    snap = await bridge.refresh(owner, seeded)
    item = next(i for i in snap.items if i["source_id"] == "1" and i["title"] == raw["name"])
    raw["submission"]["preview_url"] = "https://canvas.synthetic.invalid/preview?token=two"
    details = await bridge.assignment_details(owner, seeded, item["id"])
    # Private preview URLs are now removed at the provider boundary.
    assert details.sources[0].content_hash == item["source"]["content_hash"]
    assert details.sources[0].semantic_hash == item["source"]["semantic_hash"]
    assert details.data["submission_consistency"]["state"] == "submitted"
    assert details.data["submission_consistency"]["conflict"] is False


@pytest.mark.contract
async def test_mcp_filtered_future_plan_contract(
    running, token_factory, bridge, owner, seeded, workload_case
):
    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token_factory(scope='academic:read')}"}
    ) as http:
        async with streamable_http_client(running + "/mcp", http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                result = await session.call_tool(
                    "get_workload",
                    {
                        "connection_id": seeded,
                        "course_ids": [workload_case.id],
                        "start": "2026-11-01T00:00:00-04:00",
                        "end": "2026-11-06T00:00:00-05:00",
                        "timezone": "America/New_York",
                        "include_overdue": False,
                        "include_undated": False,
                        "limit": 1,
                    },
                )
                view = result.structuredContent
                refs = view["data"]["workload_scope"]["work_ids"]
                assert len(refs) == 2 and len(view["data"]["items"]) == 1
                plan_result = await session.call_tool(
                    "propose_study_plan",
                    {
                        "connection_id": seeded,
                        "snapshot_id": view["meta"]["snapshot_id"],
                        "request": request(
                            "2026-11-01T12:00:00-05:00",
                            "2026-11-01T14:00:00-05:00",
                            effort_overrides={r: effort() for r in refs},
                        ).model_dump(mode="json"),
                    },
                )
                plan = plan_result.structuredContent
                assert {b["work_id"] for b in plan["data"]["blocks"]} == set(refs)
                assert plan["meta"]["coverage"] == view["meta"]["coverage"]
                assert plan["data"]["feasibility"] == "provisional"
                assert all(b["conditional_on_future_access"] for b in plan["data"]["blocks"])


async def test_snapshot_scope_migration_preserves_inventory_and_requires_legacy_refresh(
    bridge, owner, tmp_path
):
    config = Config("alembic.ini")
    url = "sqlite:///" + (tmp_path / "migration-fixture.db").as_posix()
    config.attributes["database_url"] = url
    command.upgrade(config, "head")
    store = Store(url)
    service = Bridge(bridge.settings, store, bridge.vault, bridge.registry, bridge.synthetic)
    try:
        ref = await seed(service, owner)
        snap = await service.refresh(owner, ref)
        original = snap.items
        with pytest.raises(RuntimeError, match="plaintext"):
            command.downgrade(config, "4be2ca7831f0")
        with store.transaction() as session:
            session.get(Snapshot, snap.id).workload_scope = {}
        restored = service.snapshot(owner, ref, snap.id)
        assert restored.items == original
        assert restored.workload_scope == {}
        with pytest.raises(DomainError, match="planning scope"):
            service.study_plan(owner, ref, snap.id, PlanRequest())
    finally:
        store.close()


async def test_calendar_composition_preserves_workload_view(
    bridge, owner, seeded, workload_case, monkeypatch
):
    monkeypatch.setattr("canvas_bridge.calendar_sync.utcnow", lambda: NOW)
    view = await workload(bridge, owner, seeded, workload_case)
    ref = view.data["items"][0]["id"]
    context = CalendarContext(
        calendar_id="synthetic-calendar",
        timezone="America/New_York",
        retrieved_at=NOW,
        window_start=NOW,
        window_end=NOW + timedelta(days=7),
        pagination_complete=True,
        mapping_search_complete=True,
        availability_complete=True,
        events=[],
    )
    result = await propose_sync(
        bridge,
        owner,
        seeded,
        view.meta.snapshot_id,
        context,
        request(effort_overrides={ref: effort()}),
    )
    assert set(result.data["study_plan"]["work_accounting"]) == {ref}
    assert {x["work_id"] for x in result.data["proposals"]} == {ref}
    assert result.data["provider_writes_executed"] is False
