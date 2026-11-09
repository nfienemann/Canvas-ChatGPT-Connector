"""Actual authorized synthetic/live-provider-adapter and independent-import workflows."""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import select

from canvas_bridge.authorization import RequestAuthorization, request_authorization
from canvas_bridge.domain import DomainError, Result, utcnow
from canvas_bridge.egress_models import RecipientIdentity
from canvas_bridge.integrity.discovery import InstitutionalReview, public_policy_sources
from canvas_bridge.integrity.models import Activity as A
from canvas_bridge.integrity.models import AssistanceRequest, Scope
from canvas_bridge.integrity.surfaces import guard_result
from canvas_bridge.storage import IndependentResource
from tests.test_integrity_engine import policy
from tests.test_mcp_contract import running as running
from tests.test_recovery_independence import parsed_locally as parsed_locally

pytestmark = pytest.mark.usefixtures("parsed_locally")


@pytest.fixture
def verified_recipient():
    token = request_authorization.set(
        RequestAuthorization("integrity-fixture", egress_identity=RecipientIdentity("chatgpt"))
    )
    try:
        yield
    finally:
        request_authorization.reset(token)


async def configured(bridge, owner, seeded, text):
    course = bridge.selected(owner, seeded)[1][0]
    bridge.synthetic.data["course_details"] = {
        "11": {"id": 11, "time_zone": "UTC", "syllabus_body": f"<p>{text}</p>"}
    }
    bridge.synthetic.data["announcements"] = {"11": []}
    work = await bridge.workload(
        owner, seeded, utcnow() - timedelta(days=3), utcnow() + timedelta(days=10), "UTC"
    )
    item = next(i for i in work.data["items"] if i["course_id"] == course.id)
    return Scope(connection_id=seeded, course_id=course.id, assessment_id=item["id"])


async def imported(bridge, owner, text, name="fictional.txt"):
    return await bridge.independent.ingest(
        owner, text.encode(), name, "text/plain", own_material=True, share_text=True
    )


async def test_provider_prohibition_blocks_package_but_not_administration(bridge, owner, seeded):
    scope = await configured(bridge, owner, seeded, "Generative AI is prohibited on assignments.")
    request = AssistanceRequest(scope=scope, activity=A.DRAFT)
    checked = await bridge.integrity.check(owner, request)
    assert checked.data["decision"]["state"] == "PROHIBITED_CONFIRMED"
    with pytest.raises(DomainError, match="Academic permission"):
        await bridge.integrity.prepare(owner, request)
    with pytest.raises(DomainError) as error:
        await bridge.integrity.acknowledge(owner, checked.data["decision"]["id"], True)
    assert error.value.reason_code == "INTEGRITY_ACKNOWLEDGMENT_INELIGIBLE"
    admin = await bridge.integrity.check(
        owner, AssistanceRequest(scope=scope, activity=A.ADMINISTRATION)
    )
    assert admin.data["decision"]["allowed"]
    detail = await bridge.assignment_details(owner, seeded, scope.assessment_id)
    guarded = guard_result(
        bridge,
        owner,
        "get_assignment_details",
        {"connection_id": seeded, "work_id": scope.assessment_id},
        detail,
    )
    assert guarded.status in {"ok", "partial_data"}
    assert guarded.data["integrity_boundary"]["substantive_content"] == "withheld"
    assert "requirements_text" not in guarded.data


async def test_limited_permission_is_activity_scoped_in_real_collector(bridge, owner, seeded):
    scope = await configured(
        bridge, owner, seeded, "AI may be used for brainstorming but not writing."
    )
    allowed = await bridge.integrity.prepare(
        owner, AssistanceRequest(scope=scope, activity=A.BRAINSTORM)
    )
    assert allowed.data["allowed_activity_scope"] == ["brainstorming"]
    assert allowed.data["assistance_evidence"]
    assert allowed.data["editable_disclosure_template"]
    with pytest.raises(DomainError):
        await bridge.integrity.prepare(
            owner,
            AssistanceRequest(
                scope=scope, activity=A.DRAFT, continuation_id=allowed.data["decision"]["id"]
            ),
        )


async def test_conditional_analysis_permission_blocks_package_and_acknowledgment(
    bridge, owner, seeded
):
    scope = await configured(
        bridge, owner, seeded, "AI may be used for data analysis only if the work is unassessed."
    )
    request = AssistanceRequest(scope=scope, activity=A.ANALYSIS)
    checked = await bridge.integrity.check(owner, request)
    decision = checked.data["decision"]
    assert decision["state"] == "REVIEW_REQUIRED"
    assert not decision["allowed"] and not decision["permission_established"]
    assert not decision["acknowledgment_eligible"]
    with pytest.raises(DomainError, match="Academic permission"):
        await bridge.integrity.prepare(owner, request)
    with pytest.raises(DomainError) as error:
        await bridge.integrity.acknowledge(owner, decision["id"], True)
    assert error.value.reason_code == "INTEGRITY_ACKNOWLEDGMENT_INELIGIBLE"


async def test_offline_restriction_and_known_copy_cannot_escape_by_switching_tools(bridge, owner):
    doc = await imported(
        bridge, owner, "AI is prohibited on this assignment.\n\nFictional assessed essay prompt."
    )
    scope = Scope(
        document_ids=[doc],
        local_course="fictional-course",
        assessment_id="fictional-essay",
        institution="synthetic",
    )
    result = await bridge.integrity.check(owner, AssistanceRequest(scope=scope, activity=A.DRAFT))
    assert result.data["decision"]["state"] == "REVIEW_REQUIRED"
    assert result.data["decision"]["reason_code"] == "INTEGRITY_UNVERIFIED_RESTRICTION"
    for tool in (
        "read_local_document",
        "search_local_documents",
        "prepare_local_study_materials",
        "render_local_document_page",
    ):
        with pytest.raises(DomainError):
            guard_result(
                bridge, owner, tool, {"document_id": doc}, bridge.independent.read(owner, doc)
            )
    duplicate = await imported(
        bridge,
        owner,
        "AI is prohibited on this assignment.\n\nFictional assessed essay prompt.",
        "renamed.txt",
    )
    other = Scope(
        document_ids=[duplicate],
        local_course="unrelated-label",
        assessment_id="other",
        institution="synthetic",
    )
    with pytest.raises(DomainError):
        await bridge.integrity.prepare(owner, AssistanceRequest(scope=other, activity=A.DRAFT))
    # Independent general science remains ordinary learning.
    paper = await imported(
        bridge, owner, "Diffusion moves molecules along a concentration gradient."
    )
    assert guard_result(
        bridge,
        owner,
        "read_local_document",
        {"document_id": paper},
        bridge.independent.read(owner, paper),
    ).data["parts"]


async def test_eligible_acknowledgment_owner_scope_expiry_and_policy_change(
    bridge, owner, verified_recipient
):
    doc = await imported(
        bridge,
        owner,
        "Fictional assignment instructions. No guidance on artificial intelligence is stated.",
    )
    scope = Scope(
        document_ids=[doc], local_course="fictional", assessment_id="essay", institution="synthetic"
    )
    request = AssistanceRequest(scope=scope, activity=A.BRAINSTORM)
    checked = await bridge.integrity.check(owner, request)
    assert checked.data["decision"]["acknowledgment_eligible"]
    with pytest.raises(DomainError):
        await bridge.integrity.acknowledge(owner, checked.data["decision"]["id"], False)
    acknowledged = await bridge.integrity.acknowledge(owner, checked.data["decision"]["id"], True)
    ack = acknowledged.data["acknowledgment_id"]
    allowed = await bridge.integrity.prepare(
        owner, request.model_copy(update={"acknowledgment_id": ack})
    )
    assert (
        allowed.data["decision"]["allowed"]
        and not allowed.data["decision"]["permission_established"]
    )
    assert allowed.data["decision"]["state"] != "PERMITTED_EXPLICIT"
    with pytest.raises(DomainError):
        await bridge.integrity.prepare(
            "other-owner", request.model_copy(update={"acknowledgment_id": ack})
        )
    with pytest.raises(DomainError) as error:
        await bridge.integrity.prepare(
            owner, request.model_copy(update={"activity": A.DRAFT, "acknowledgment_id": ack})
        )
    assert error.value.reason_code == "INTEGRITY_ACKNOWLEDGMENT_SCOPE_MISMATCH"
    # New guidance in the same local course reevaluates the original acknowledgment.
    restriction = await imported(bridge, owner, "AI is prohibited on assignments.")
    changed = scope.model_copy(update={"document_ids": [doc, restriction]})
    await bridge.integrity.check(owner, AssistanceRequest(scope=changed, activity=A.DRAFT))
    with pytest.raises(DomainError):
        await bridge.integrity.prepare(owner, request.model_copy(update={"acknowledgment_id": ack}))
    history = bridge.integrity.acknowledgment_history(owner)
    assert history.data["acknowledgments"][0]["id"] == ack
    bridge.integrity.acknowledgment_history(owner, ack)
    assert not bridge.integrity.acknowledgment_history(owner).data["acknowledgments"]


async def test_unavailable_lookup_and_permission_evidence_do_not_invent_authority(bridge, owner):
    doc = await imported(bridge, owner, "AI is permitted for this assignment.")
    scope = Scope(document_ids=[doc], local_course="fictional", assessment_id="essay")
    result = await bridge.integrity.provide_evidence(owner, scope, doc)
    assert result.data["public_policy_lookup"] == "LOOKUP_UNAVAILABLE"
    assert result.data["permission_evidence_status"] == "STUDENT_SUPPLIED_UNVERIFIED"
    assert not result.data["decision"]["allowed"]
    assert not result.data["decision"]["acknowledgment_eligible"]


async def test_revoked_source_and_minimal_encrypted_receipts(bridge, owner, seeded):
    scope = await configured(bridge, owner, seeded, "AI is permitted.")
    checked = await bridge.integrity.check(
        owner, AssistanceRequest(scope=scope, activity=A.BRAINSTORM)
    )
    with bridge.store.transaction() as session:
        rows = list(
            session.scalars(
                select(IndependentResource).where(IndependentResource.kind == "integrity_decision")
            )
        )
        assert rows and all(
            "passage" not in json.dumps(r.content) and "Compare active" not in json.dumps(r.content)
            for r in rows
        )
    with bridge.store.engine.connect() as sql:
        encrypted = sql.exec_driver_sql(
            "SELECT content, provenance FROM independent_resources WHERE kind = 'integrity_decision'"
        ).all()
        assert encrypted and all(
            value.startswith("bridge-sealed-v1:") for row in encrypted for value in row
        )
    bridge.select_courses(owner, seeded, [], "UTC")
    with pytest.raises(DomainError):
        await bridge.integrity.get_decision(owner, checked.data["decision"]["id"])
    assert "scope" not in bridge.integrity.acknowledgment_history(owner).model_dump_json()


def test_integrity_receipt_storage_budget_and_expiry_sweep(bridge, owner):
    with pytest.raises(DomainError) as denied:
        bridge.integrity.write_record(owner, "integrity_context", {"text": "x" * (256 * 1024)})
    assert denied.value.reason_code == "INTEGRITY_RECEIPT_LIMIT"
    ident = bridge.integrity.write_record(
        owner,
        "integrity_ack",
        {"activity": "brainstorming"},
        expires=utcnow() - timedelta(seconds=1),
    )
    with pytest.raises(DomainError):
        bridge.integrity.read_record(owner, ident, "integrity_ack")
    bridge.independent.sweep()
    with bridge.store.transaction() as session:
        assert session.get(IndependentResource, ident) is None


def test_integrity_inventory_declares_conditional_network_and_owned_history():
    from canvas_bridge.source_authorization import operation_contract

    local_or_live = operation_contract("prepare_academic_assistance")
    assert local_or_live["offline_supported"]
    assert local_or_live["conditional_institutional_dependencies"]
    assert "no_upstream_network" in local_or_live["conditional_authorization"]["local_scope"]
    for name in ("get_integrity_acknowledgments", "revoke_integrity_acknowledgment"):
        history = operation_contract(name)
        assert not history["upstream_network"]
        assert history["authorization"] == ["owned_integrity_receipt"]


def test_public_review_has_no_fetch_or_override_and_hash_binds_content(bridge, tmp_path):
    from canvas_bridge.evidence import fingerprint

    source = policy(
        "Students must obtain instructor permission before using AI.",
        id="public-university",
        authority="institution",
        course_id=None,
        uri="https://policy.example.invalid/integrity",
    )
    source.version = fingerprint(source.parts)
    data = {
        "institution": "fictional-university",
        "official_hosts": ["policy.example.invalid"],
        "checked_at": utcnow().isoformat(),
        "review_due_at": (utcnow() + timedelta(days=7)).isoformat(),
        "sources": [source.model_dump(mode="json")],
    }
    InstitutionalReview.model_validate(data)
    path = tmp_path / "public-review.json"
    path.write_text(json.dumps([data]))
    bridge.settings.integrity_policy_reviews_file = path
    sources, lookup = public_policy_sources(bridge, "fictional-university")
    assert lookup == "REVIEWED_OFFLINE_REFERENCE"
    assert sources[0].authority == "institution"
    data["sources"][0]["parts"][0]["text"] = "AI is permitted."
    path.write_text(json.dumps([data]))
    assert public_policy_sources(bridge, "fictional-university")[1] == "REVIEW_REQUIRED"


def test_rowan_reference_profile_requires_permission_and_expires(bridge, tmp_path):
    from canvas_bridge.evidence import fingerprint
    from canvas_bridge.integrity.engine import evaluate_academic_assistance
    from canvas_bridge.integrity.models import Coverage, State

    checked = datetime(2026, 10, 28, tzinfo=UTC)
    bridge.retention.clock = lambda: checked
    # Public Attachment 7 excerpt checked 2026-10-28. All coursework is fictional.
    # This bounded excerpt does not claim complete extraction of the whole policy.
    reference = policy(
        "Students are responsible for obtaining permission from instructors before using generative AI in their course work.",
        id="rowan-public-reference",
        kind="institution_policy",
        authority="institution",
        course_id=None,
        issuer="Rowan University",
        retrieved_at=checked,
        coverage=Coverage.READ_PARTIAL,
        uri="https://confluence.rowan.edu/spaces/POLICY/pages/61426359/Academic%2BIntegrity%2BPolicy",
        limitation="Attachment 7 permission excerpt only; remaining policy requires review.",
    )
    reference.parts[0]["locator"] = "Attachment 7; revision 2026-10-19"
    reference.version = fingerprint(reference.parts)
    review = InstitutionalReview(
        institution="rowan",
        official_hosts={"confluence.rowan.edu"},
        checked_at=checked,
        review_due_at=checked + timedelta(days=30),
        sources=[reference],
    )
    path = tmp_path / "rowan-public-reference.json"
    path.write_text(json.dumps([review.model_dump(mode="json")]), encoding="utf-8")
    bridge.settings.integrity_policy_reviews_file = path
    sources, lookup = public_policy_sources(bridge, "rowan")
    decision = evaluate_academic_assistance(A.DRAFT, sources, now=checked)
    assert lookup == "REVIEWED_OFFLINE_REFERENCE"
    assert decision.state == State.PERMISSION_REQUIRED and not decision.acknowledgment_eligible
    assert public_policy_sources(bridge, "unrelated-institution")[1] == "LOOKUP_UNAVAILABLE"
    bridge.retention.clock = lambda: checked + timedelta(days=31)
    assert public_policy_sources(bridge, "rowan")[1] == "STALE"


@pytest.mark.contract
async def test_real_mcp_denial_acknowledgment_scope_and_offline_tools(
    running, bridge, owner, token_factory, seeded
):
    scope = await configured(bridge, owner, seeded, "Generative AI is prohibited on assignments.")
    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {token_factory()}"}) as http:
        async with streamable_http_client(running + "/mcp", http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                catalog = await session.list_tools()
                names = {t.name for t in catalog.tools}
                assert {
                    "get_academic_integrity_policy",
                    "prepare_academic_assistance",
                    "record_integrity_acknowledgment",
                } <= names
                request = AssistanceRequest(scope=scope, activity=A.DRAFT).model_dump(mode="json")
                checked = await session.call_tool(
                    "check_academic_assistance_permission", {"request": request}
                )
                assert checked.structuredContent["status"] == "ok", checked
                assert (
                    checked.structuredContent["data"]["decision"]["state"] == "PROHIBITED_CONFIRMED"
                )
                denied = await session.call_tool(
                    "prepare_academic_assistance", {"request": request}
                )
                assert denied.structuredContent["status"] == "permission_denied"
                assert (
                    denied.structuredContent["data"]["reason_code"]
                    == "INTEGRITY_EXPLICIT_PROHIBITION"
                )
                assert "Compare active" not in str(denied)
                administrative = await session.call_tool(
                    "get_assignment_details",
                    {"connection_id": seeded, "work_id": scope.assessment_id},
                )
                assert administrative.structuredContent["status"] in {"ok", "partial_data"}
                assert (
                    administrative.structuredContent["data"]["integrity_boundary"][
                        "substantive_content"
                    ]
                    == "withheld"
                )
                assert all(
                    t.annotations.readOnlyHint is False
                    for t in catalog.tools
                    if t.name
                    in {"record_integrity_acknowledgment", "provide_instructor_permission_evidence"}
                )


def test_future_unclassified_tool_fails_closed(bridge, owner):
    with pytest.raises(DomainError) as error:
        guard_result(bridge, owner, "friendly_new_document_tool", {}, Result(summary="Fixture"))
    assert error.value.reason_code == "INTEGRITY_TOOL_UNCLASSIFIED"


async def test_automatic_reader_discovery_enforces_broad_learning_prohibition(
    bridge, owner, seeded
):
    from canvas_bridge.integrity.surfaces import before_tool

    scope = await configured(bridge, owner, seeded, "All AI use is prohibited in this course.")
    # No prior policy endpoint call is necessary to activate the check.
    with pytest.raises(DomainError) as error:
        await before_tool(
            bridge,
            owner,
            "read_course_file",
            {"connection_id": seeded, "course_id": scope.course_id},
        )
    assert error.value.reason_code == "INTEGRITY_EXPLICIT_PROHIBITION"


async def test_administrative_label_never_releases_completion_package(bridge, owner, seeded):
    scope = await configured(bridge, owner, seeded, "AI is prohibited on assignments.")
    for activity in (A.ADMINISTRATION, A.PLANNING, A.REQUIREMENTS):
        result = await bridge.integrity.prepare(
            owner, AssistanceRequest(scope=scope, activity=activity)
        )
        assert result.data["assistance_evidence"] == []
        assert "Compare active" not in result.model_dump_json()


async def test_acknowledgment_expiration_egress_denial_and_source_deletion(
    bridge, owner, verified_recipient
):
    doc = await imported(bridge, owner, "Fictional instructions for an exercise.")
    scope = Scope(document_ids=[doc], assessment_id="exercise", institution="synthetic")
    request = AssistanceRequest(scope=scope, activity=A.BRAINSTORM)
    result = await bridge.integrity.check(owner, request)
    # Sharing revocation cannot be bypassed by acknowledging academic uncertainty.
    with bridge.store.transaction() as session:
        row = session.get(IndependentResource, doc)
        row.provenance = {**row.provenance, "share_text": False}
    with pytest.raises(DomainError):
        await bridge.integrity.acknowledge(owner, result.data["decision"]["id"], True)
    assert not bridge.integrity.acknowledgment_history(owner).data["acknowledgments"]
    with bridge.store.transaction() as session:
        row = session.get(IndependentResource, doc)
        row.provenance = {**row.provenance, "share_text": True}
    acknowledged = await bridge.integrity.acknowledge(owner, result.data["decision"]["id"], True)
    ack = acknowledged.data["acknowledgment_id"]
    now = bridge.retention.clock()
    bridge.retention.clock = lambda: now + timedelta(minutes=16)
    with pytest.raises(DomainError) as error:
        await bridge.integrity.prepare(owner, request.model_copy(update={"acknowledgment_id": ack}))
    assert error.value.reason_code == "INTEGRITY_REFERENCE_INVALID"
    bridge.retention.clock = lambda: now
    bridge.independent.delete(owner, doc)
    with pytest.raises(DomainError):
        await bridge.integrity.check(owner, request)


@pytest.mark.contract
async def test_offline_mcp_acknowledgment_and_denied_category_change(
    running, bridge, owner, token_factory, monkeypatch
):
    doc = await imported(bridge, owner, "Fictional exercise instructions with no AI rule.")
    scope = Scope(
        document_ids=[doc], local_course="fictional", assessment_id="essay", institution="synthetic"
    )

    def no_network(*args, **kwargs):
        raise AssertionError("Independent integrity workflow must not contact an institution")

    monkeypatch.setattr(bridge, "client", no_network)
    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {token_factory()}"}) as http:
        async with streamable_http_client(running + "/mcp", http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                request = AssistanceRequest(scope=scope, activity=A.BRAINSTORM).model_dump(
                    mode="json"
                )
                checked = await session.call_tool(
                    "check_academic_assistance_permission", {"request": request}
                )
                d = checked.structuredContent["data"]["decision"]
                assert d["acknowledgment_eligible"] and not d["permission_established"]
                acked = await session.call_tool(
                    "record_integrity_acknowledgment",
                    {"decision_id": d["id"], "explicitly_acknowledged": True},
                )
                ack = acked.structuredContent["data"]["acknowledgment_id"]
                prepared = await session.call_tool(
                    "prepare_academic_assistance",
                    {"request": {**request, "acknowledgment_id": ack}},
                )
                data = prepared.structuredContent["data"]
                assert (
                    data["decision"]["allowed"] and not data["decision"]["permission_established"]
                )
                assert data["assistance_evidence"] and data["allowed_activity_scope"] == [
                    "brainstorming"
                ]
                wrong = await session.call_tool(
                    "prepare_academic_assistance",
                    {
                        "request": {
                            **request,
                            "activity": "submission_drafting",
                            "acknowledgment_id": ack,
                        }
                    },
                )
                assert (
                    wrong.structuredContent["data"]["reason_code"]
                    == "INTEGRITY_ACKNOWLEDGMENT_SCOPE_MISMATCH"
                )
