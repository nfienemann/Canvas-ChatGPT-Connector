from dataclasses import replace
from types import SimpleNamespace

import pytest

from canvas_bridge.auth import principal_id
from canvas_bridge.authorization import RequestAuthorization, request_authorization
from canvas_bridge.egress_models import (
    ContentClassification as CC,
)
from canvas_bridge.egress_models import (
    PrivateCourseListing,
    RecipientIdentity,
    SourceContext,
    Transfer,
)
from canvas_bridge.egress_policy import DataEgressPolicyEngine


@pytest.fixture
def setup():
    owner = principal_id("https://issuer.invalid", "fictional-owner")
    grant = PrivateCourseListing(
        owner=owner, issuer="https://issuer.invalid", client_id="private-client"
    )
    record = SimpleNamespace(
        authority="sharing", institutions={"fictional"}, egress=None, private_course_listing=grant
    )
    state = {"allowed": True, "error": None}
    gateway = SimpleNamespace(
        store=SimpleNamespace(load=lambda: ([record], state["error"])),
        evaluate=lambda request: SimpleNamespace(allowed=state["allowed"]),
    )
    settings = SimpleNamespace(
        profile="personal",
        egress_mode="strict",
        mcp_read_only=True,
        host="127.0.0.1",
        personal_subject="fictional-owner",
        issuer_url="https://issuer.invalid",
        mcp_chatgpt_client_ids={"private-client"},
    )
    bridge = SimpleNamespace(settings=settings, approval_gateway=gateway)
    source = SourceContext(
        "fictional", owner, "course", "", "course", CC.FIRST_PARTY_EDUCATIONAL_RECORD
    )
    transfer = Transfer(
        owner,
        RecipientIdentity("chatgpt", "https://issuer.invalid", "private-client"),
        "metadata",
        "structured",
        (source,),
        100,
        True,
        True,
        minimized=True,
    )
    token = request_authorization.set(RequestAuthorization("list_courses"))
    try:
        yield DataEgressPolicyEngine(bridge), transfer, settings, state
    finally:
        request_authorization.reset(token)


def test_exact_private_minimized_listing_allowed(setup):
    engine, transfer, _, _ = setup
    assert engine.evaluate(transfer).allowed


def test_private_text_and_inventory_grants_do_not_authorize_outline(setup):
    engine, transfer, _, _ = setup
    record = engine.bridge.approval_gateway.store.load()[0][0]
    record.private_course_listing = record.private_course_listing.model_copy(
        update={"scope": "reviewed_private_text", "allow_course_material_inventory": True}
    )
    token = request_authorization.set(RequestAuthorization("get_course_outline"))
    try:
        assert engine.evaluate(transfer).reason_code == "EGRESS_GOVERNANCE_MISSING"
        unknown = replace(transfer.sources[0], classification=CC.UNKNOWN_OR_UNCLASSIFIED)
        assert engine.evaluate(replace(transfer, sources=(unknown,))).reason_code == (
            "EGRESS_CLASSIFICATION_UNKNOWN"
        )
    finally:
        request_authorization.reset(token)


@pytest.mark.parametrize(
    "changes",
    [
        {"minimized": False},
        {"channel": "visual"},
        {"purpose": "grade_planning"},
        {"amount": 100001},
        {"authorized": False},
        {"privacy_filtered": False},
        {"recipient": RecipientIdentity("chatgpt", "https://issuer.invalid", "different-client")},
        {"principal": "different-owner"},
    ],
)
def test_private_grant_does_not_widen_transfer_scope(setup, changes):
    engine, transfer, _, _ = setup
    assert not engine.evaluate(replace(transfer, **changes)).allowed


@pytest.mark.parametrize("kind", ["grade", "file", "assignment_content", "page"])
def test_documents_and_grades_stay_blocked(setup, kind):
    engine, transfer, _, _ = setup
    assert not engine.evaluate(
        replace(transfer, sources=(replace(transfer.sources[0], kind=kind),))
    ).allowed


def test_revocation_hosted_mode_and_other_tools_deny(setup):
    engine, transfer, settings, state = setup
    state["allowed"] = False
    assert not engine.evaluate(transfer).allowed
    state["allowed"] = True
    settings.profile = "hosted"
    assert not engine.evaluate(transfer).allowed
    settings.profile = "personal"
    token = request_authorization.set(RequestAuthorization("get_gradebook"))
    try:
        assert not engine.evaluate(transfer).allowed
    finally:
        request_authorization.reset(token)


def test_study_metadata_requires_explicit_extended_grant(setup):
    engine, transfer, _, _ = setup
    transfer = replace(
        transfer, purpose="schedule", sources=(replace(transfer.sources[0], kind="deadline"),)
    )
    token = request_authorization.set(RequestAuthorization("get_workload"))
    try:
        assert not engine.evaluate(transfer).allowed
        record = engine.bridge.approval_gateway.store.load()[0][0]
        record.private_course_listing = record.private_course_listing.model_copy(
            update={"scope": "minimized_study_metadata"}
        )
        assert engine.evaluate(transfer).allowed
        restricted = replace(transfer.sources[0], restricted=True)
        assert not engine.evaluate(replace(transfer, sources=(restricted,))).allowed
        assert not engine.evaluate(
            replace(transfer, sources=(replace(transfer.sources[0], kind="file"),))
        ).allowed
    finally:
        request_authorization.reset(token)


@pytest.mark.parametrize("explicit_filter", [True, False])
async def test_empty_workload_preserves_authorized_course_sources(
    bridge, owner, seeded, explicit_filter
):
    from canvas_bridge.domain import Coverage, Result
    from canvas_bridge.egress_sources import resolve_sources

    _, courses = bridge.selected(owner, seeded)
    course = courses[0]
    arguments = {"connection_id": seeded}
    if explicit_filter:
        arguments["course_ids"] = [course.id]
    result = Result(
        summary="Empty workload",
        data={"items": []},
        meta=bridge.meta(
            coverage=[Coverage(course_ref=course.id, resource="assignments", state="complete")]
        ),
    )
    sources, _ = resolve_sources(bridge.egress, owner, arguments, result, "get_workload")
    assert len(sources) == 1 and sources[0].kind == "course" and sources[0].source_id == course.id


@pytest.mark.parametrize("missing", ["none", "privacy", "rights", "hash", "version"])
def test_private_document_text_requires_actual_bound_review(setup, missing):
    from canvas_bridge.egress_models import ContentReview

    engine, transfer, _, _ = setup
    record = engine.bridge.approval_gateway.store.load()[0][0]
    record.private_course_listing = record.private_course_listing.model_copy(
        update={"scope": "reviewed_private_text"}
    )
    review = ContentReview(
        source_id="document",
        version="a" * 64,
        content_sha256="b" * 64,
        extracted_text_sha256="d" * 64,
        classification=CC.INSTRUCTOR_OWNED_COURSE_CONTENT,
        purposes={"document_reading"},
        reviewed_channels={"structured"},
        privacy_reviewed_channels={"structured"},
        privacy_review_reference="fictional-human-review",
        content_owner_permission_reference="fictional-written-rights",
    )
    if missing == "privacy":
        review = review.model_copy(update={"privacy_review_reference": None})
    if missing == "rights":
        review = review.model_copy(update={"content_owner_permission_reference": None})
    if missing == "hash":
        review = review.model_copy(update={"content_sha256": "c" * 64})
    if missing == "version":
        review = review.model_copy(update={"version": "c" * 64})
    record.private_text_reviews = [review] if missing != "none" else []
    source = replace(
        transfer.sources[0],
        source_id="document",
        kind="file",
        version="a" * 64,
        content_sha256="b" * 64,
        extracted_text_sha256="d" * 64,
        classification=CC.INSTRUCTOR_OWNED_COURSE_CONTENT,
    )
    transfer = replace(transfer, sources=(source,), minimized=False, purpose="document_reading")
    token = request_authorization.set(RequestAuthorization("read_course_file"))
    try:
        assert not engine.evaluate(transfer).allowed
        record.private_text_reviews = [
            review.model_copy(
                update={
                    "version": "a" * 64,
                    "content_sha256": "b" * 64,
                    "privacy_review_reference": "fictional-review",
                    "content_owner_permission_reference": "fictional-rights",
                }
            )
        ]
        assert engine.evaluate(transfer).allowed
        record.private_text_reviews[0] = record.private_text_reviews[0].model_copy(
            update={
                "reviewed_channels": {"structured", "text"},
                "privacy_reviewed_channels": {"structured", "text"},
            }
        )
        assert engine.evaluate(replace(transfer, channel="text")).allowed
        assert not engine.evaluate(
            replace(transfer, sources=(replace(source, extracted_text_sha256="e" * 64),))
        ).allowed
        assert not engine.evaluate(replace(transfer, channel="visual")).allowed
        assert not engine.evaluate(
            replace(transfer, sources=(replace(source, restricted=True),))
        ).allowed
    finally:
        request_authorization.reset(token)


def test_diagnostics_require_explicit_private_grant(setup):
    engine, transfer, _, state = setup
    transfer = replace(
        transfer,
        purpose="diagnostics",
        sources=(replace(transfer.sources[0], kind="permission_diagnostics"),),
    )
    token = request_authorization.set(RequestAuthorization("audit_permission_consistency"))
    try:
        assert not engine.evaluate(transfer).allowed
        record = engine.bridge.approval_gateway.store.load()[0][0]
        record.private_course_listing = record.private_course_listing.model_copy(
            update={"allow_permission_diagnostics": True}
        )
        assert engine.evaluate(transfer).allowed
        assert not engine.evaluate(replace(transfer, minimized=False)).allowed
        state["allowed"] = False
        assert not engine.evaluate(transfer).allowed
    finally:
        request_authorization.reset(token)


def test_audit_minimizer_drops_source_text_and_unknown_fields():
    from canvas_bridge.domain import Result
    from canvas_bridge.egress_sources import minimize

    source = Result(
        summary="PRIVATE DESCRIPTION",
        data={
            "scope_consistency": "consistent",
            "arbitrary": "SECRET",
            "checks": [
                {
                    "resource": "files",
                    "scope_authorized": True,
                    "description": "PRIVATE SOURCE TEXT",
                }
            ],
        },
    )
    clean, minimized = minimize(source, "audit_permission_consistency", live=True)
    assert minimized and clean.data["scope_consistency"] == "consistent"
    assert clean.data["checks"] == [{"resource": "files", "scope_authorized": True}]
    assert "PRIVATE" not in clean.model_dump_json() and "SECRET" not in clean.model_dump_json()


def test_audit_operational_flags_survive_privacy_filter():
    from canvas_bridge.privacy.output import filter_output

    output, _, _, _ = filter_output(
        {
            "scope_consistency": "consistent",
            "upstream_requests": 0,
            "state_modified": False,
            "upstream_checks_requested": False,
            "recommended_action": "none",
            "unreviewed_text": "SECRET",
        }
    )
    assert output["upstream_requests"] == 0 and output["state_modified"] is False
    assert output["scope_consistency"] == "consistent"
    assert "SECRET" not in str(output)


def test_inventory_requires_explicit_grant_and_minimization(setup):
    engine, transfer, _, _ = setup
    transfer = replace(transfer, sources=(replace(transfer.sources[0], kind="material_inventory"),))
    token = request_authorization.set(RequestAuthorization("list_course_files"))
    try:
        assert not engine.evaluate(transfer).allowed
        record = engine.bridge.approval_gateway.store.load()[0][0]
        record.private_course_listing = record.private_course_listing.model_copy(
            update={"allow_course_material_inventory": True}
        )
        assert engine.evaluate(transfer).allowed
        assert not engine.evaluate(replace(transfer, minimized=False)).allowed
        assert not engine.evaluate(replace(transfer, channel="text")).allowed
    finally:
        request_authorization.reset(token)


def test_inventory_minimizer_omits_contents_urls_and_unknown_fields():
    from canvas_bridge.domain import Result
    from canvas_bridge.egress_sources import minimize

    r = Result(
        summary="PRIVATE",
        data={
            "files": [
                {
                    "file_id": "opaque",
                    "title": "Fictional syllabus",
                    "text": "SECRET",
                    "url": "SECRET",
                    "private": "SECRET",
                }
            ],
            "modules": [{"text": "SECRET"}],
        },
    )
    clean, minimized = minimize(r, "list_course_files", live=True)
    assert minimized and clean.data == {
        "files": [{"file_id": "opaque", "title": "Fictional syllabus"}]
    }
    assert "SECRET" not in clean.model_dump_json()
