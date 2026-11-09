"""Grade-auditing regressions use fictional student/course data only."""

import asyncio
import json
from copy import deepcopy
from decimal import Decimal as D

import httpx
import jsonschema
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from canvas_bridge.domain import DomainError
from canvas_bridge.grade_audit import grading_request
from canvas_bridge.grading_engine import (
    GradeAssessment as A,
)
from canvas_bridge.grading_engine import (
    GradeGroup as G,
)
from canvas_bridge.grading_engine import (
    GradePolicy as P,
)
from canvas_bridge.grading_engine import (
    GradeScenario,
    PolicyReview,
    calculate,
    reconcile,
)
from canvas_bridge.grading_policy import extract_policy
from tests.test_file_reading import readable as readable
from tests.test_file_reading import scientific_pdf
from tests.test_mcp_contract import running as running


def graded(id="a", group="exam", score=80, possible=100, **kwargs):
    return A(
        id=id,
        title=id,
        group_id=group,
        score=D(score) if score is not None else None,
        possible=D(possible) if possible is not None else None,
        score_state="posted",
        **kwargs,
    )


def policy(weighted=False):
    return P(
        method="weighted" if weighted else "points",
        empty_categories="renormalize",
        groups=[G(id="exam", name="Exams", weight=D(70)), G(id="lab", name="Labs", weight=D(30))],
    )


def doc(text, id="syllabus", version="v1", complete=True):
    return {
        "id": id,
        "title": "Syllabus",
        "url": "https://canvas.example/courses/1/files/1",
        "version": version,
        "complete": complete,
        "parts": [{"locator": "PDF page 2", "text": text}],
    }


def reviewed(documents, p=None, **kwargs):
    p = p or policy(True)
    data, _ = extract_policy(documents, p, [])
    review = PolicyReview(
        policy_version=data["policy_version"],
        confirmed_rule_ids=[r["id"] for r in data["rules"] if r["supported"]],
        complete_policy_confirmed=True,
        applicability_confirmed=True,
        **kwargs,
    )
    return extract_policy(documents, p, [], review)


def test_T08_T28_weight_mismatch_explained_without_asserting_error():
    rows = [graded(), graded("b", "lab", 20, 20)]
    canvas = policy(True)
    _, syllabus = reviewed([doc("Exams: 60%\nLabs: 40%")])
    c = calculate(canvas, rows)
    s = calculate(syllabus, rows, "syllabus_current")
    result = reconcile({"current_score": 86}, c, s, canvas, syllabus, reported_comparable=True)
    assert c["calculated_percentage"] == "86.0000"
    assert s["calculated_percentage"] == "88.0000"
    assert result["outcome"] == "explainable_difference"
    assert result["difference_percentage_points"] == "2.0000"
    assert result["verification"] != "confirmed_configuration_mismatch"


def test_T08_empty_category_requires_explicit_mode_policy():
    p = policy(True)
    current = calculate(p, [graded()])
    assert current["calculated_percentage"] == "80.0000"
    assert "70% active" in current["assumptions"][0]
    _, syllabus = reviewed([doc("Exams: 70%\nLabs: 30%")])
    refused = calculate(syllabus, [graded()], "syllabus_current")
    assert refused["calculated_percentage"] is None
    assert any("no usable denominator" in m for m in refused["missing_information"])


def test_T08_missing_unsubmitted_excused_and_submitted_ungraded_never_zero():
    rows = [
        graded(),
        A(
            id="b",
            title="Missing",
            group_id="exam",
            possible=100,
            score_state="ungraded",
            submission_state="not_submitted",
            missing=True,
        ),
        A(
            id="c",
            title="Waiting",
            group_id="exam",
            possible=100,
            score_state="ungraded",
            submission_state="submitted",
        ),
        A(id="d", title="Excused", group_id="exam", possible=100, score_state="excused"),
    ]
    result = calculate(policy(), rows)
    assert result["calculated_percentage"] == "80.0000"
    assert len(result["excluded_assessments"]) == 3
    rows.append(A(id="e", title="Unknown", group_id="exam", possible=100))
    assert calculate(policy(), rows)["calculated_percentage"] is None


def test_T08_extra_credit_zero_points_requires_usable_denominator():
    assert (
        calculate(policy(), [graded(), graded("bonus", score=5, possible=0)])[
            "calculated_percentage"
        ]
        == "85.0000"
    )
    assert (
        calculate(policy(), [graded("bonus", score=5, possible=0)])["calculated_percentage"] is None
    )
    assert (
        calculate(policy(True), [graded(), graded("bonus", "lab", 5, 0)])["calculated_percentage"]
        is None
    )


def test_T08_drop_lowest_ties_deterministic_and_never_drop():
    p = policy()
    p.groups[0].drop_lowest = 1
    rows = [graded("a", score=60), graded("b", score=60), graded("c", score=90)]
    result = calculate(p, rows)
    assert result["calculated_percentage"] == "75.0000"
    assert result["excluded_assessments"] == [{"id": "a", "reason": "drop_lowest_equal_points"}]
    assert calculate(p, list(reversed(rows)))["calculation_id"] == result["calculation_id"]
    p.groups[0].never_drop = ["a"]
    assert calculate(p, rows)["excluded_assessments"][0]["id"] == "b"
    rows[0].possible = D(50)
    assert calculate(p, rows)["calculated_percentage"] is None


def test_T08_unpublished_final_cannot_be_assumed_or_simulated():
    rows = [
        graded(),
        A(id="final", title="Restricted", excluded_reason="unpublished_or_restricted"),
    ]
    assert calculate(policy(), rows)["calculated_percentage"] == "80.0000"
    result = calculate(
        policy(), rows, "projected_final", GradeScenario(acknowledge_visible_scope=True)
    )
    assert result["calculated_percentage"] is None


def test_T08_conflicting_versions_no_latest_wins():
    _, p = reviewed(
        [
            doc("Exams: 70%\nLabs: 30%", version="old"),
            doc("Exams: 60%\nLabs: 40%", id="new", version="new"),
        ]
    )
    assert any("Conflicting" in x for x in p.blockers)


def test_T08_ambiguous_categories_and_unmodeled_conditions_block():
    p = policy(True)
    p.groups.append(G(id="second_exam", name="Exams", weight=0))
    _, result = reviewed([doc("Exams: 70%\nLabs: 30%")], p)
    assert result.blockers
    for text in (
        "Extra credit is available.",
        "Late work loses 10%.",
        "The final replaces an exam.",
        "Grades are curved.",
        "A: 90%",
        "Participation is required.",
    ):
        data, result = reviewed([doc("Exams: 70%\nLabs: 30%\n" + text)])
        assert any(not r["supported"] for r in data["rules"])
        assert result.blockers


def test_T08_points_vs_weighted_and_rounding_are_distinct():
    rows = [graded(), graded("b", "lab", 20, 20)]
    assert calculate(policy(), rows)["calculated_percentage"] == "83.3333"
    assert calculate(policy(True), rows)["calculated_percentage"] == "86.0000"
    p = policy()
    a = calculate(p, rows)
    result = reconcile({"current_score": 83.33}, a, a, p, p, reported_comparable=True)
    assert result["outcome"] == "consistent"


def test_T08_incomplete_syllabus_or_no_grade_refuses_precision():
    for docs in ([], [doc("Exams: 70%\nLabs: 30%", complete=False)]):
        _, p = reviewed(docs)
        assert calculate(p, [graded()], "syllabus_current")["calculated_percentage"] is None
    assert calculate(policy(), [])["calculated_percentage"] is None


def test_T08_new_grade_changes_calculation_version():
    rows = [graded(), A(id="b", title="b", group_id="exam", possible=100, score_state="ungraded")]
    before = calculate(policy(), rows)
    rows[1].score_state, rows[1].score = "posted", D(100)
    after = calculate(policy(), rows)
    assert (before["calculated_percentage"], after["calculated_percentage"]) == (
        "80.0000",
        "90.0000",
    )
    assert before["calculation_id"] != after["calculation_id"]


def test_T28_projection_and_required_score_are_reproducible_and_conditional():
    rows = [
        graded(),
        A(id="final", title="final", group_id="exam", possible=100, score_state="ungraded"),
    ]
    scenario = GradeScenario(scores={"final": D(90)}, acknowledge_visible_scope=True)
    assert (
        calculate(policy(), rows, "projected_final", scenario)["calculated_percentage"] == "85.0000"
    )
    required = calculate(
        policy(),
        rows,
        "required_score",
        GradeScenario(target_percent=90, acknowledge_visible_scope=True),
    )
    assert required["calculated_percentage"] is None
    assert required["required_score"]["uniform_remaining_percent"] == "100.0000"
    assert required["classification"] == "hypothetical_scenario"
    impossible = calculate(
        policy(),
        rows,
        "required_score",
        GradeScenario(target_percent=99, acknowledge_visible_scope=True),
    )
    assert impossible["required_score"]["status"] == "infeasible"
    assert calculate(policy(), rows, "projected_final")["calculated_percentage"] is None
    invalid = GradeScenario(scores={"a": 90, "other_user": 100}, acknowledge_visible_scope=True)
    assert calculate(policy(), rows, "projected_final", invalid)["calculated_percentage"] is None
    p = policy()
    p.groups[0].drop_lowest = 1
    assert "required_score" not in calculate(
        p, rows, "required_score", GradeScenario(target_percent=80, acknowledge_visible_scope=True)
    )


def test_T08_policy_quotes_versions_and_student_review_are_bound():
    docs = [doc("Exams: 70%\nLabs: 30%")]
    data, p = extract_policy(docs, policy(True), [])
    assert p.blockers
    assert data["rules"][0]["source_passage"] == "Exams: 70%"
    assert data["rules"][0]["source_location"]["locator"] == "PDF page 2"
    assert data["rules"][0]["document_version"] == "v1"
    bad = PolicyReview(
        policy_version="0" * 64,
        confirmed_rule_ids=[],
        complete_policy_confirmed=True,
        applicability_confirmed=True,
    )
    assert extract_policy(docs, policy(True), [], bad)[1].blockers
    assert not reviewed(docs)[1].blockers
    _, points = reviewed([doc("Grade is based on points earned / points possible.")])
    assert points.method == "points" and not points.blockers


@pytest.fixture
def grade_data(bridge, owner, seeded):
    _, courses = bridge.selected(owner, seeded)
    course = next(c for c in courses if c.source_id == "11")
    bridge.synthetic.data["course_details"] = {
        "11": {
            "id": 11,
            "apply_assignment_group_weights": True,
            "grading_periods": [],
            "has_grading_periods": False,
            "hide_final_grades": False,
            "syllabus_body": "<p>Exams: 60%</p><p>Labs: 40%</p>",
        }
    }
    bridge.synthetic.data["assignment_groups"] = {
        "11": [
            {"id": 1, "name": "Exams", "group_weight": 70, "rules": {}},
            {"id": 2, "name": "Labs", "group_weight": 30, "rules": {}},
        ]
    }
    bridge.synthetic.data["assignments"]["11"] = [
        {
            "id": i,
            "name": "Exam" if i == 1 else "Lab",
            "assignment_group_id": i,
            "published": True,
            "omit_from_final_grade": False,
            "grading_type": "points",
            "points_possible": 100 if i == 1 else 20,
            "submission_types": ["online_upload"],
            "submission": {
                "user_id": 101,
                "assignment_id": i,
                "workflow_state": "graded",
                "score": 80 if i == 1 else 20,
                "submitted_at": "2026-10-01T12:00:00Z",
                "posted_at": "2026-10-02T12:00:00Z",
                "missing": False,
                "late": False,
            },
        }
        for i in (1, 2)
    ]
    bridge.synthetic.data["enrollments"][0]["grades"].update(
        current_score=86, current_points=100, unposted_current_score=999
    )
    return course.id


async def test_T08_native_service_reports_reproduces_and_audits(bridge, owner, seeded, grade_data):
    p = await grading_request(bridge, owner, seeded, grade_data, material_ids=[])
    assert p.data["canvas"]["reported"]["current_score"] == 86
    assert "unposted" not in p.model_dump_json()
    s = p.data["syllabus_policy"]
    review = PolicyReview(
        policy_version=s["policy_version"],
        confirmed_rule_ids=[r["id"] for r in s["rules"]],
        complete_policy_confirmed=True,
        applicability_confirmed=True,
    )
    audited = await grading_request(
        bridge, owner, seeded, grade_data, "audit", material_ids=[], review=review
    )
    assert audited.data["reconciliation"]["outcome"] == "explainable_difference"
    assert audited.data["syllabus_calculation"]["calculated_percentage"] == "88.0000"
    assert all(r.method == "GET" for r in bridge.synthetic.requests)
    assert any(r.url.path.endswith("assignment_groups") for r in bridge.synthetic.requests)


async def test_T08_phase_one_does_not_require_syllabus(bridge, owner, seeded, grade_data):
    bridge.synthetic.data["course_details"]["11"].pop("syllabus_body")
    result = await grading_request(bridge, owner, seeded, grade_data, "calculate")
    assert result.data["calculation"]["calculated_percentage"] == "86.0000"
    assert not any(
        "modules" in r.url.path or "pages" in r.url.path for r in bridge.synthetic.requests
    )
    refused = await grading_request(bridge, owner, seeded, grade_data, "audit", material_ids=[])
    assert refused.data["reconciliation"]["outcome"] == "insufficient_evidence"
    assert refused.data["syllabus_calculation"]["calculated_percentage"] is None


async def test_T08_manual_adjustment_and_periods_remain_explicit(bridge, owner, seeded, grade_data):
    bridge.synthetic.data["enrollments"][0]["override_score"] = 91
    result = await grading_request(bridge, owner, seeded, grade_data, "audit", material_ids=[])
    assert result.data["canvas"]["reported"]["current_score"] == 86
    assert result.data["canvas"]["manual_adjustments"][0]["override_score"] == 91
    assert result.data["reconciliation"]["outcome"] == "insufficient_evidence"
    bridge.synthetic.data["course_details"]["11"]["has_grading_periods"] = True
    result = await grading_request(bridge, owner, seeded, grade_data, "calculate")
    assert result.data["calculation"]["calculated_percentage"] is None
    assert any("grading periods" in m for m in result.data["calculation"]["missing_information"])


@pytest.mark.parametrize(
    "mutation",
    ["other_user", "unposted", "null_score", "excused", "conflicting_assignment"],
    ids=str,
)
async def test_T08_T02_score_visibility_and_identity(bridge, owner, seeded, grade_data, mutation):
    sub = bridge.synthetic.data["assignments"]["11"][0]["submission"]
    if mutation == "other_user":
        sub.update(user_id=202, score=987654)
    elif mutation == "unposted":
        sub.update(posted_at=None, score=987654)
    elif mutation == "null_score":
        sub["score"] = None
    elif mutation == "excused":
        sub["excused"] = True
    else:
        sub.update(assignment_id=999, score=987654)
    result = await grading_request(bridge, owner, seeded, grade_data, "calculate")
    assert "987654" not in result.model_dump_json()
    first = next(a for a in result.data["assessment_evidence"] if a["title"] == "Exam")
    assert first["score"] is None
    if mutation == "excused":
        assert result.data["calculation"]["calculated_percentage"] == "100.0000"
    else:
        assert result.data["calculation"]["calculated_percentage"] is None


async def test_T08_summary_detail_conflict_blocks_instead_of_picking(
    bridge, owner, seeded, grade_data, monkeypatch
):
    original = bridge.synthetic.handle

    def handle(request):
        if request.url.path.endswith("/assignments/1"):
            raw = deepcopy(bridge.synthetic.data["assignments"]["11"][0])
            raw["submission"]["score"] = 95
            return httpx.Response(200, json=raw)
        return original(request)

    monkeypatch.setattr(bridge.synthetic, "handle", handle)
    result = await grading_request(bridge, owner, seeded, grade_data, "calculate")
    assert result.data["canvas"]["summary_detail_conflicts"]
    assert result.data["calculation"]["calculated_percentage"] is None


async def test_T08_T02_hidden_totals_not_reconstructed_and_cross_user_denied(
    bridge, owner, seeded, grade_data
):
    bridge.synthetic.data["course_details"]["11"]["hide_final_grades"] = True
    result = await grading_request(bridge, owner, seeded, grade_data, "calculate")
    assert result.data["canvas"]["reported"]["current_score"] is None
    assert result.data["canvas"]["reported_rows"] == []
    assert result.data["calculation"]["calculated_percentage"] is None
    with pytest.raises(DomainError):
        await grading_request(bridge, "another-owner", seeded, grade_data)


async def test_T08_inaccessible_configuration_and_timeouts_refuse(
    bridge, owner, seeded, grade_data, monkeypatch
):
    bridge.synthetic.failures["/api/v1/courses/11"] = 403
    result = await grading_request(bridge, owner, seeded, grade_data, "calculate")
    assert result.data["calculation"]["calculated_percentage"] is None

    scopes = {c.resource: c for c in result.meta.coverage}
    assert scopes["grade_configuration"].state == "permission_denied"
    assert scopes["grade_calculation_inputs"].state == "partial"

    async def timed_out(*args):
        raise TimeoutError

    monkeypatch.setattr("canvas_bridge.grade_audit.collect", timed_out)
    result = await grading_request(bridge, owner, seeded, grade_data, "calculate")
    assert result.meta.freshness == "not_refreshed"
    assert result.meta.coverage[0].reason_code == "UPSTREAM_REQUEST_TIMEOUT"
    assert result.data["classification"] == "indeterminate"


async def test_T08_T11_pdf_syllabus_uses_authenticated_reader_and_exact_pages(
    bridge, owner, seeded, grade_data, readable
):
    _, ref = readable
    bridge.synthetic.data["course_details"]["11"]["syllabus_body"] = ""
    body = scientific_pdf(["Exams: 60%", "Labs: 40%"])
    bridge.synthetic.data["file_bodies"]["51"] = body
    bridge.synthetic.data["files"]["11"][0]["size"] = len(body)
    result = await grading_request(bridge, owner, seeded, grade_data, material_ids=[ref])
    syllabus = result.data["syllabus_policy"]
    assert [r["source_passage"] for r in syllabus["rules"]] == ["Exams: 60%", "Labs: 40%"]
    assert syllabus["rules"][1]["source_location"]["locator"] == "PDF page 2"
    assert len(syllabus["rules"][0]["document_version"]) == 64
    assert sum("download" in r.url.path for r in bridge.synthetic.requests) == 1
    await grading_request(bridge, owner, seeded, grade_data, material_ids=[ref])
    assert sum("download" in r.url.path for r in bridge.synthetic.requests) == 1
    _, courses = bridge.selected(owner, seeded)
    other = next(c for c in courses if c.id != grade_data)
    with pytest.raises(DomainError, match="outside this course"):
        await grading_request(bridge, owner, seeded, other.id, material_ids=[ref])


async def test_T08_T02_deselection_during_audit_prevents_response(
    bridge, owner, seeded, grade_data, monkeypatch
):
    from canvas_bridge.grade_audit import collect

    async def withdrawing(*args):
        evidence = await collect(*args)
        bridge.select_courses(owner, seeded, [], "UTC")
        return evidence

    monkeypatch.setattr("canvas_bridge.grade_audit.collect", withdrawing)
    with pytest.raises(DomainError):
        await grading_request(bridge, owner, seeded, grade_data, "calculate")


async def test_T08_missing_inclusion_flags_and_grade_scope_are_unknown(
    bridge, owner, seeded, grade_data
):
    bridge.synthetic.data["assignments"]["11"][0].pop("omit_from_final_grade")
    result = await grading_request(bridge, owner, seeded, grade_data, "calculate")
    assert result.data["calculation"]["calculated_percentage"] is None
    assert any("inclusion" in m for m in result.data["calculation"]["missing_information"])
    bridge.synthetic.data["course_details"]["11"].pop("has_grading_periods")
    bridge.synthetic.data["course_details"]["11"].pop("grading_periods")
    result = await grading_request(bridge, owner, seeded, grade_data, "calculate")
    assert any("Grading-period" in m for m in result.data["calculation"]["missing_information"])


async def test_T08_changed_syllabus_invalidates_review_and_conflicting_enrollments(
    bridge, owner, seeded, grade_data
):
    result = await grading_request(bridge, owner, seeded, grade_data, material_ids=[])
    s = result.data["syllabus_policy"]
    review = PolicyReview(
        policy_version=s["policy_version"],
        confirmed_rule_ids=[r["id"] for r in s["rules"]],
        complete_policy_confirmed=True,
        applicability_confirmed=True,
    )
    bridge.synthetic.data["course_details"]["11"]["syllabus_body"] = (
        "<p>Exams: 50%</p><p>Labs: 50%</p>"
    )
    conflicting = deepcopy(bridge.synthetic.data["enrollments"][0])
    conflicting["grades"]["current_score"] = 50
    bridge.synthetic.data["enrollments"].append(conflicting)
    result = await grading_request(
        bridge, owner, seeded, grade_data, "audit", material_ids=[], review=review
    )
    assert result.data["canvas"]["reported"]["current_score"] is None
    assert result.data["syllabus_calculation"]["calculated_percentage"] is None
    assert result.data["reconciliation"]["outcome"] == "insufficient_evidence"


async def test_T08_assessment_budget_never_claims_complete_grade(bridge, owner, seeded, grade_data):
    first = bridge.synthetic.data["assignments"]["11"][0]
    bridge.synthetic.data["assignments"]["11"] = [dict(deepcopy(first), id=i) for i in range(1, 62)]
    bridge.settings.max_pages = 40
    result = await grading_request(bridge, owner, seeded, grade_data, "calculate")
    assert result.meta.coverage[-1].state == "partial"
    assert not result.data["coverage"]["visible_assignment_collection_complete"]
    assert result.data["calculation"]["calculated_percentage"] is None


@pytest.mark.contract
async def test_T08_T12_native_mcp_grade_tools_and_deliberate_refusal(
    running, token_factory, bridge, seeded, grade_data, monkeypatch
):
    # Exercise authorized assignment-detail reuse only after the first calculation.
    ttl = 0
    get = bridge.upstream_cache.get

    async def with_fixture_ttl(key, authorize, fetch, **kwargs):
        return await get(key, authorize, fetch, ttl=ttl)

    monkeypatch.setattr(bridge.upstream_cache, "get", with_fixture_ttl)
    async with httpx.AsyncClient(
        headers={"Authorization": "Bearer " + token_factory(scope="academic:read")}
    ) as http:
        async with streamable_http_client(running + "/mcp", http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                catalog = await session.list_tools()
                schemas = {t.name: t.outputSchema for t in catalog.tools}

                names = {
                    "get_course_grading_policy",
                    "calculate_course_grade",
                    "audit_course_grade",
                    "simulate_grade_scenario",
                }
                assert names <= {t.name for t in catalog.tools}
                assert all(t.annotations.readOnlyHint for t in catalog.tools if t.name in names)
                result = await session.call_tool(
                    "get_course_grading_policy",
                    {"connection_id": seeded, "course_id": grade_data, "syllabus_material_ids": []},
                )
                assert result.structuredContent["data"]["syllabus_policy"]["rules"]
                result = await session.call_tool(
                    "simulate_grade_scenario",
                    {
                        "connection_id": seeded,
                        "course_id": grade_data,
                        "scenario": {"acknowledge_visible_scope": True},
                        "mode": "projected_final",
                    },
                )
                assert (
                    result.structuredContent["data"]["calculation"]["classification"]
                    == "hypothetical_scenario"
                )
                ttl = 60
                result = await session.call_tool(
                    "calculate_course_grade", {"connection_id": seeded, "course_id": grade_data}
                )
                assert (
                    result.structuredContent["data"]["calculation"]["calculated_percentage"]
                    == "86.0000"
                )
                wire = result.structuredContent
                jsonschema.validate(wire, schemas["calculate_course_grade"])
                assert wire == json.loads(result.content[0].text)
                scopes = {c["resource"]: c for c in wire["meta"]["coverage"]}
                assert wire["meta"]["freshness"] == "live"
                assert scopes["grade_calculation_inputs"]["state"] == "complete"
                assert wire["data"]["coverage"]["visible_assignment_collection_complete"]
                assert wire["data"]["calculation"]["basis"]["evidence_complete"]
                assert scopes["grade_assignments"]["pagination_complete"]
                assert wire["evidence"][0]["coverage"] == [
                    row
                    for row in wire["meta"]["coverage"]
                    if row["resource"] != "grade_calculation_inputs"
                ]
                cached = (
                    await session.call_tool(
                        "calculate_course_grade", {"connection_id": seeded, "course_id": grade_data}
                    )
                ).structuredContent
                assert cached["meta"]["freshness"] == "cached"
                assert bridge.upstream_cache.hits > 0
                assert cached["meta"]["coverage"] == wire["meta"]["coverage"]
                assert cached["data"]["calculation"] == wire["data"]["calculation"]
                result = await session.call_tool(
                    "audit_course_grade",
                    {"connection_id": seeded, "course_id": grade_data, "syllabus_material_ids": []},
                )
                assert (
                    result.structuredContent["data"]["syllabus_calculation"][
                        "calculated_percentage"
                    ]
                    is None
                )
                assert (
                    result.structuredContent["data"]["reconciliation"]["outcome"]
                    == "insufficient_evidence"
                )

                jsonschema.validate(result.structuredContent, schemas["audit_course_grade"])

                syllabus = result.structuredContent["data"]["syllabus_policy"]
                confirmed = await session.call_tool(
                    "audit_course_grade",
                    {
                        "connection_id": seeded,
                        "course_id": grade_data,
                        "syllabus_material_ids": [],
                        "policy_review": {
                            "policy_version": syllabus["policy_version"],
                            "confirmed_rule_ids": [rule["id"] for rule in syllabus["rules"]],
                            "complete_policy_confirmed": True,
                            "applicability_confirmed": True,
                        },
                    },
                )
                jsonschema.validate(confirmed.structuredContent, schemas["audit_course_grade"])
                assert confirmed.structuredContent["status"] == "ok"

                denied = await session.call_tool(
                    "audit_course_grade", {"connection_id": "foreign", "course_id": grade_data}
                )
                jsonschema.validate(denied.structuredContent, schemas["audit_course_grade"])
                assert denied.structuredContent["status"] == "permission_denied"

                async def slow_collection(*args):
                    await asyncio.sleep(1)

                monkeypatch.setattr("canvas_bridge.grade_audit.collect", slow_collection)
                monkeypatch.setattr("canvas_bridge.grade_audit.GRADE_REQUEST_SECONDS", 0.01)
                timed = await session.call_tool(
                    "audit_course_grade", {"connection_id": seeded, "course_id": grade_data}
                )
                wire = timed.structuredContent
                jsonschema.validate(wire, schemas["audit_course_grade"])
                assert (
                    wire["status"] == "partial_data"
                    and wire["meta"]["freshness"] == "not_refreshed"
                )
                assert wire["data"]["classification"] == "indeterminate"
                assert wire["data"]["reason_code"] == "TASK_BUDGET_EXCEEDED"
                assert wire["data"]["timeout_stage"] == "grade_input_collection"
                assert "calculated_percentage" not in json.dumps(wire)


@pytest.mark.parametrize(
    "failure,reason,pages,state",
    [
        ("not_refreshed", "INVENTORY_NOT_ATTEMPTED", 0, "not_refreshed"),
        ("permission_denied", "RESOURCE_PERMISSION_DENIED", 0, "permission_denied"),
        ("retry_later", "UPSTREAM_REQUEST_TIMEOUT", 1, "partial"),
    ],
)
async def test_grade_assignment_collection_gap(
    bridge, owner, seeded, grade_data, monkeypatch, failure, reason, pages, state
):
    from canvas_bridge.canvas import CanvasClient, Collection
    from canvas_bridge.domain import utcnow
    from canvas_bridge.policy import Endpoint

    original = CanvasClient.collection

    async def collection(client, endpoint, **kwargs):
        if endpoint == Endpoint.ASSIGNMENTS:
            return Collection(
                pages=pages,
                failure=failure,
                reason_code=reason,
                page_receipts=[(0, {"source": "upstream", "retrieved_at": utcnow().isoformat()})]
                * pages,
            )
        return await original(client, endpoint, **kwargs)

    monkeypatch.setattr(CanvasClient, "collection", collection)
    result = await grading_request(bridge, owner, seeded, grade_data, "calculate")
    scopes = {c.resource: c for c in result.meta.coverage}
    assignments = scopes["grade_assignments"]
    assert assignments.state == state and assignments.reason_code == reason
    assert assignments.pages_consumed == pages and not assignments.pagination_complete
    assert scopes["grade_assignment_details"].state == "not_refreshed"
    assert not result.data["coverage"]["visible_assignment_collection_complete"]
    assert not result.data["calculation"]["basis"]["evidence_complete"]
    assert scopes["grade_calculation_inputs"].state == "partial"
    assert result.data["calculation"]["calculated_percentage"] is None
    assert result.evidence[0]["coverage"] == [
        scope.model_dump(mode="json")
        for scope in result.meta.coverage
        if scope.resource != "grade_calculation_inputs"
    ]


async def test_missing_enrollment_summary_is_separate_from_grade_inputs(
    bridge, owner, seeded, grade_data, monkeypatch
):
    from canvas_bridge.canvas import CanvasClient, Collection
    from canvas_bridge.policy import Endpoint

    original = CanvasClient.collection

    async def collection(client, endpoint, **kwargs):
        # Entitlement is independently verified. Only the reported-grade source fails.
        if endpoint == Endpoint.ENROLLMENTS and kwargs.get("record_page_receipts"):
            return Collection(
                failure="permission_denied",
                reason_code="RESOURCE_PERMISSION_DENIED",
                upstream_http_status=403,
            )
        return await original(client, endpoint, **kwargs)

    monkeypatch.setattr(CanvasClient, "collection", collection)
    result = await grading_request(bridge, owner, seeded, grade_data, "calculate")
    scopes = {c.resource: c for c in result.meta.coverage}
    assert scopes["own_grade_enrollments"].state == "permission_denied"
    assert scopes["grade_calculation_inputs"].state == "complete"
    assert result.data["canvas"]["reported_rows"] == []
    assert result.data["calculation"]["calculated_percentage"] == "86.0000"
    assert scopes["own_grade_enrollments"].model_dump(mode="json") in result.evidence[0]["coverage"]


async def test_grade_input_with_missing_receipt_keeps_coverage_and_unknown_time(
    bridge, owner, seeded, grade_data, monkeypatch
):
    from canvas_bridge.canvas import CanvasClient
    from canvas_bridge.policy import Endpoint
    from canvas_bridge.providers.canvas import AuthorizedCanvasProvider
    from canvas_bridge.providers.canvas_grades import collect

    original = CanvasClient.collection

    async def collection(client, endpoint, **kwargs):
        rows = await original(client, endpoint, **kwargs)
        if endpoint == Endpoint.ASSIGNMENT_GROUPS:
            rows.page_receipts.clear()
        return rows

    monkeypatch.setattr(CanvasClient, "collection", collection)
    evidence = await collect(bridge, owner, seeded, grade_data)
    assert evidence["complete"] and evidence["meta"].freshness == "unknown"
    assert evidence["canvas_evidence"]["retrieved_at"] is None
    assert evidence["sources"][0].uncertainty
    provider = AuthorizedCanvasProvider(bridge, owner, seeded)
    packet = provider.calculation_input(evidence, evidence["policy"])
    dataset = provider.gateway.consume(packet)
    assert dataset.assessments and dataset.complete
    assert all(a.provenance.verified_at is None for a in dataset.assessments)
    result = await grading_request(bridge, owner, seeded, grade_data, "audit", material_ids=[])
    assert result.meta.freshness == "not_refreshed"
    assert any("receipts" in warning for warning in result.meta.warnings)
    assert result.data["canvas"]["retrieved_at"] is None


async def test_syllabus_discovery_budget_preserves_indeterminate_audit(
    bridge, owner, seeded, grade_data, monkeypatch
):
    cancelled = False

    async def stalled(*args):
        nonlocal cancelled
        try:
            await asyncio.sleep(10)
        finally:
            cancelled = True

    monkeypatch.setattr("canvas_bridge.grade_audit.syllabus_documents", stalled)
    monkeypatch.setattr("canvas_bridge.grade_audit.AUTOMATIC_SYLLABUS_SECONDS", 0.01)
    result = await grading_request(bridge, owner, seeded, grade_data, "audit")
    assert cancelled and result.status == "partial_data"
    assert result.data["classification"] == "indeterminate"
    assert result.data["reason_code"] == "TASK_BUDGET_EXCEEDED"
    assert result.data["timeout_stage"] == "syllabus_discovery_and_read"
    assert "material IDs" in result.data["next_action"]
    assert "calculation" not in json.dumps(result.data)
