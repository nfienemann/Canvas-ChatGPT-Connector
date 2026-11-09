from datetime import timedelta

import pytest

from canvas_bridge.analytics.capture import record_duration
from canvas_bridge.analytics.measurements import Measurement
from canvas_bridge.analytics.observations import Period
from canvas_bridge.analytics.report import report
from canvas_bridge.domain import DomainError, utcnow
from tests.test_analytics_observations import review
from tests.test_independent_intelligence import no_lms_running as no_lms_running
from tests.test_mcp_contract import running as running
from tests.test_permission_consistency_contract import client_session
from tests.test_recovery_independence import parsed_locally as parsed_locally


async def test_report_save_restate_and_duration_correction(bridge, owner, seeded):
    _, courses = bridge.selected(owner, seeded)
    cid = courses[0].id
    await bridge.refresh(owner, seeded)
    t = utcnow() - timedelta(minutes=1)
    m = Measurement(course_id=cid, measurement_id="m", manual={"occurred_at": t, "minutes": 0})
    assert record_duration(bridge, owner, seeded, m, 0).data["version"] == 1
    assert record_duration(bridge, owner, seeded, m, 0).data["version"] == 1
    now = utcnow()
    req = review(
        course_ids=[cid],
        windows=[Period(start=t - timedelta(days=1), end=t + timedelta(seconds=1))],
        as_of=now,
        evidence_cutoff=now,
    )
    original = report(bridge, owner, seeded, req, save=True).data
    assert report(bridge, owner, seeded, req).data["report_id"] == original["report_id"]
    m.manual.minutes = 8
    assert record_duration(bridge, owner, seeded, m, 1).data["version"] == 2
    corrected = report(
        bridge,
        owner,
        seeded,
        req.model_copy(update={"restates": original["report_id"], "evidence_cutoff": utcnow()}),
    ).data
    assert corrected["restatement"]["prior_report_id"] == original["report_id"]
    assert corrected["periods"][0]["families"][-1]["measures"][3]["value"] == 8
    with pytest.raises(DomainError):
        report(bridge, "another", seeded, req)


async def test_http_report(running, bridge, owner, seeded, token_factory):
    snap = await bridge.refresh(owner, seeded)
    now = utcnow()
    req = review(
        course_ids=snap.course_ids,
        windows=[Period(start=now - timedelta(days=7), end=now)],
        as_of=now,
        evidence_cutoff=now,
    )
    async with client_session(running, token_factory()) as session:
        raw = await session.call_tool(
            "get_academic_analytics",
            {"connection_id": seeded, "request": req.model_dump(mode="json")},
        )
        body = raw.structuredContent
        assert body and body["status"] in {"ok", "partial_data"}, str(body or raw)[:1200]
        assert len(body["data"]["periods"][0]["families"]) == 5
        assert body["data"]["inventory_coverage"] and body["data"]["report_id"]


async def test_normal_plan_measurement_and_saved_report_http(
    running, bridge, owner, seeded, token_factory
):
    snap = await bridge.refresh(owner, seeded)
    item = next(
        i
        for i in snap.items
        if i.get("instruction_hash") and i["submission_state"] not in {"submitted", "resubmitted"}
    )
    at = utcnow()
    async with client_session(running, token_factory(), read_timeout=90) as session:

        async def call(name, args):
            raw = await session.call_tool(name, {"connection_id": seeded, **args})
            body = raw.structuredContent
            assert body and body["status"] in {"ok", "partial_data"}, str(body or raw)[:1000]
            return body["data"]

        input_plan = {
            "windows": [
                {
                    "start": (at + timedelta(minutes=5)).isoformat(),
                    "end": (at + timedelta(hours=3)).isoformat(),
                }
            ],
            "effort_overrides": {
                item["id"]: {
                    "minimum_minutes": 20,
                    "maximum_minutes": 40,
                    "origin": "student_estimate",
                    "point_estimate_minutes": 30,
                }
            },
        }
        plan_args = {"snapshot_id": snap.id, "request": input_plan, "expected_version": 0}
        accepted = await call("save_study_plan", plan_args)
        forecast = next(
            f
            for f in accepted["measurement_refs"]
            if f["kind"] == "forecast" and f["work_id"] == item["id"]
        )
        saved_snapshot = next(
            f["id"] for f in accepted["measurement_refs"] if f["kind"] == "schedule"
        )
        draft = await call("save_study_plan", plan_args | {"plan_state": "proposed"})
        draft_snapshot = next(f["id"] for f in draft["measurement_refs"] if f["kind"] == "schedule")
        start = utcnow()
        m = {
            "course_id": item["course_id"],
            "measurement_id": "recorded-zero",
            "work_id": item["id"],
            "actual": {
                "forecast_id": forecast["id"],
                "scope_id": forecast["scope_id"],
                "unit_id": forecast["unit_id"],
                "work_revision": forecast["work_revision"],
                "start": start.isoformat(),
                "completion": start.isoformat(),
                "completed": True,
                "complete_duration": True,
                "minutes": 0,
            },
        }
        await call("record_academic_measurement", {"measurement": m, "expected_version": 0})
        end = utcnow()
        req = review(
            course_ids=snap.course_ids,
            windows=[
                Period(
                    start=at,
                    end=end,
                    accepted_snapshot=saved_snapshot,
                    proposed_snapshot=draft_snapshot,
                )
            ],
            as_of=end,
            evidence_cutoff=end,
        )
        data = await call("save_academic_analytics", {"request": req.model_dump(mode="json")})
        e = data["periods"][0]["families"][3]
        assert e["evaluated"] == 1 and e["zero_actual_pair_count"] == 1
        assert (
            next(x for x in e["measures"] if x["metric_id"] == "point_mae_minutes")["value"] == 30
        )
        assert [s["snapshot_id"] for s in data["periods"][0]["families"][2]["snapshots"]] == [
            saved_snapshot,
            draft_snapshot,
        ]
        m["actual"]["minutes"] = 45
        await call("record_academic_measurement", {"measurement": m, "expected_version": 1})
        prior = await call("get_academic_analytics", {"saved_report_id": data["report_id"]})
        assert prior["periods"] == data["periods"]
        req.evidence_cutoff = utcnow()
        req.restates = data["report_id"]
        corrected = await call("get_academic_analytics", {"request": req.model_dump(mode="json")})
        assert corrected["report_id"] != prior["report_id"]
        assert corrected["periods"][0]["families"][3]["zero_actual_pair_count"] == 0
        from tests.test_analytics_archive import write_evidence

        write_evidence("http-owned-duration", {"original": prior, "restated": corrected})
        # Re-read a saved derived report after its underlying parent has a restrictive review.
        bridge.synthetic.egress_contexts = {item["id"]: {"restricted": True}}
        denied = (
            await session.call_tool(
                "get_academic_analytics",
                {"connection_id": seeded, "saved_report_id": data["report_id"]},
            )
        ).structuredContent
        assert denied["status"] == "permission_denied" and "periods" not in denied["data"]


async def test_legacy_portability_and_course_purge(bridge, owner, seeded):
    from sqlalchemy import select

    from canvas_bridge.analytics.report import read_saved
    from canvas_bridge.storage import LocalRecord

    snap = await bridge.refresh(owner, seeded)
    cid = snap.course_ids[0]
    end = utcnow()
    req = review(
        course_ids=[cid],
        windows=[Period(start=end - timedelta(days=1), end=end)],
        as_of=end,
        evidence_cutoff=end,
    )
    saved = report(bridge, owner, seeded, req, save=True).data
    exported = bridge.store.export_connection(owner, seeded)
    assert any(row["key"] == saved["report_id"] for row in exported["records"]["local_records"])
    with bridge.store.transaction() as session:
        bridge.store.purge_courses(session, owner, seeded, {cid})
        assert not session.scalar(select(LocalRecord).where(LocalRecord.kind == "analytics_report"))
    with pytest.raises(DomainError):
        read_saved(bridge, owner, seeded, saved["report_id"])


async def test_independent_analytics_over_http(
    no_lms_running, bridge, owner, token_factory, parsed_locally
):
    import json

    from tests.test_independent_intelligence import imported

    now = utcnow()
    dataset = {
        "schema_version": "independent-academic-1",
        "complete": True,
        "work": [
            {
                "key": "parent",
                "title": "Synthetic essay",
                "aliases": ["alias"],
                "due": {"kind": "timestamp", "timestamp": now.isoformat()},
            }
        ],
        "declarations": [
            {
                "work_key": "alias",
                "version": 1,
                "recorded_at": now.isoformat(),
                "progress": "student_marked_done",
            }
        ],
    }
    selection = await imported(bridge, owner, json.dumps(dataset))
    end = utcnow()
    req = review(
        course_ids=[selection["document_id"]],
        as_of=end,
        evidence_cutoff=end,
        windows=[Period(start=now - timedelta(days=1), end=end)],
        families=["personal_completion", "deadline_outcomes"],
    )
    args = {
        "request": {
            "capability": "analytics",
            "dataset": selection,
            "analytics": req.model_dump(mode="json"),
        }
    }
    async with client_session(no_lms_running, token_factory()) as session:
        body = (
            await session.call_tool("run_independent_academic_workflow", args)
        ).structuredContent
        assert body and body["status"] == "partial_data", str(body)[:1000]
        deadline, progress = body["data"]["periods"][0]["families"]
        assert deadline["unknown"] == 1 and progress["counts"]["student_marked_done"] == 1
        assert body["data"]["diagnostics"]["institutional_network_attempted"] is False


async def test_authoritative_receipt_recovery_and_real_workflow_attempts(bridge, owner, seeded):
    import hashlib

    from canvas_bridge.analytics.report import report
    from canvas_bridge.semester_notifications import delivery_receipt_state
    from canvas_bridge.workflow_registry import WorkflowRequest
    from canvas_bridge.workflows import run_workflow

    courses = [c.id for c in bridge.selected(owner, seeded)[1]]
    at = utcnow()
    workflow = await run_workflow(
        bridge,
        owner,
        seeded,
        WorkflowRequest(workflow="weekly_course_priorities", course_ids=courses),
    )
    assert "execution" in workflow.data
    key = hashlib.sha256(b"fixture-confirmed-notification").hexdigest()
    decision = {
        "delivery_key": key,
        "delivery_state": "eligible_for_approved_host",
        "delivery_course_ids": courses,
        "eligible_findings": [{"issue_key": "f", "finding_revision": "r1"}],
    }
    state = delivery_receipt_state({}, decision, provider_receipt="synthetic-ack", delivered_at=at)
    replay = delivery_receipt_state(
        state, decision, provider_receipt="synthetic-ack", delivered_at=at
    )
    assert state["confirmed_deliveries"] == replay["confirmed_deliveries"]
    bridge.store.save_local(owner, seeded, "semester_state", "default", replay, 0)
    now = utcnow()
    req = review(
        course_ids=courses,
        windows=[Period(start=at, end=now)],
        as_of=now,
        evidence_cutoff=now,
        families=["coordination"],
    )
    coordination = report(bridge, owner, seeded, req).data["periods"][0]["families"][0]
    m = {r["metric_id"]: r["value"] for r in coordination["measures"]}
    assert m["logical_requests"] == 1 and m["attempts"] >= 1 and m["confirmed_effects"] == 1
    assert (
        m["system_runtime_ms"] == workflow.data["execution"]["elapsed_ms"]
        and m["recorded_manual_minutes"] is None
    )
