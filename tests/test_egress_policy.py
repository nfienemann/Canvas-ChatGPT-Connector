import json
from dataclasses import replace
from datetime import timedelta

import pytest

from canvas_bridge.authorization import RequestAuthorization, request_authorization
from canvas_bridge.domain import DomainError, Result, utcnow
from canvas_bridge.egress_models import ContentClassification as CC
from canvas_bridge.egress_models import RecipientIdentity, SourceContext, Transfer
from canvas_bridge.egress_models import ReleaseDecision as RD
from canvas_bridge.egress_policy import dangerous_reference
from tests.approval_fixtures import install_approvals
from tests.egress_fixtures import ENVIRONMENT, WORKSPACE, install_governance
from tests.test_academic_intelligence import academic as academic
from tests.test_approval_policy import live_fixture


@pytest.fixture
def governance(bridge):
    approvals = install_approvals(bridge)
    policy = install_governance(bridge, approvals)
    live_fixture(bridge)
    return approvals, policy


def transfer(
    bridge, owner, *, kind="grade", classification=CC.FIRST_PARTY_EDUCATIONAL_RECORD, **source_flags
):
    source = SourceContext(
        "synthetic",
        owner,
        "fixture-source",
        "a" * 64,
        kind,
        classification,
        content_sha256="c" * 64,
        **source_flags,
    )
    identity = RecipientIdentity(
        "chatgpt", bridge.settings.issuer_url, "fixture-chatgpt-client", ENVIRONMENT, WORKSPACE
    )
    return Transfer(owner, identity, "grade_planning", "structured", (source,), 200, True, True)


@pytest.mark.parametrize(
    "case,kind,classification,flags,expected",
    [
        ("public_documentation", "page", CC.PUBLIC_OR_APPROVED, {}, RD.ALLOW),
        ("own_grade", "grade", CC.FIRST_PARTY_EDUCATIONAL_RECORD, {}, RD.ALLOW),
        (
            "another_students_grade",
            "grade",
            CC.FIRST_PARTY_EDUCATIONAL_RECORD,
            {"subject": "another-owner"},
            RD.DENY,
        ),
        (
            "copyrighted_lecture_slide",
            "file",
            CC.INSTRUCTOR_OWNED_COURSE_CONTENT,
            {},
            RD.REQUIRES_AUTHORIZED_REVIEW,
        ),
        ("unreleased_exam", "file", CC.PUBLIC_OR_APPROVED, {"restricted": True}, RD.DENY),
        (
            "private_instructor_feedback",
            "feedback",
            CC.FIRST_PARTY_EDUCATIONAL_RECORD,
            {},
            RD.REQUIRES_AUTHORIZED_REVIEW,
        ),
        (
            "confidential_research",
            "research",
            CC.PUBLIC_OR_APPROVED,
            {"confidential": True},
            RD.DENY,
        ),
        ("unknown_file", "file", CC.UNKNOWN_OR_UNCLASSIFIED, {}, RD.REQUIRES_AUTHORIZED_REVIEW),
        (
            "derived_deadline",
            "deadline",
            CC.FIRST_PARTY_EDUCATIONAL_RECORD,
            {"derived": True},
            RD.ALLOW_MINIMIZED,
        ),
    ],
)
def test_required_content_fixtures(
    bridge, owner, governance, case, kind, classification, flags, expected
):
    approvals, policy = governance
    if case == "public_documentation":
        policy["content_reviews"] = [
            {
                "source_id": "fixture-source",
                "version": "a" * 64,
                "classification": "PUBLIC_OR_APPROVED",
                "purposes": ["grade_planning"],
                "reviewed_channels": ["structured"],
                "privacy_reviewed_channels": ["structured"],
                "privacy_review_reference": "fictional privacy review",
            }
        ]
        approvals.save()
    item = transfer(bridge, owner, kind=kind, classification=classification, **flags)
    if case == "derived_deadline":
        item = replace(item, purpose="schedule", minimized=True)
    assert bridge.egress.evaluate(item).decision == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://canvas.synthetic.invalid/files/51/download",
        "https%3A%2F%2Fcanvas.synthetic.invalid%2Ffiles%2F51%2Fdownload",
        "https://canvas.synthetic.invalid/files/51?download_frd=1",
        "https://bridge.invalid/course-file-download/secret",
        "https://storage.invalid/a?X-Amz-Signature=private",
        "https:\\/\\/bridge.invalid\\/course-file-original\\/x",
    ],
)
async def test_disguised_original_file_url_in_derived_metadata(bridge, owner, seeded, url, caplog):
    assert dangerous_reference(url)
    result = Result(summary="A supposedly harmless deadline", data={"harmless_label": url})
    with (
        caplog.at_level("INFO", logger="canvas_bridge.data_egress"),
        pytest.raises(DomainError) as error,
    ):
        bridge.egress.release(result, owner, {"connection_id": seeded}, tool_name="get_workload")
    assert error.value.reason_code == "EGRESS_HIDDEN_FILE_REFERENCE"
    assert url not in caplog.text


@pytest.mark.parametrize(
    "change",
    [
        {"environment": "fictional-consumer-plan"},
        {"workspace": "another-workspace"},
        {"client_id": "unapproved-client"},
        {"issuer": "https://another-issuer.invalid"},
        {"environment": ""},
        {"recipient": "external_ai"},
    ],
)
def test_recipient_plan_workspace_and_identity_are_independent(bridge, owner, governance, change):
    item = transfer(bridge, owner)
    item = replace(item, recipient=replace(item.recipient, **change))
    expected = (
        "EGRESS_INSTITUTIONAL_APPROVAL_DENIED"
        if change.get("recipient") == "external_ai"
        else "EGRESS_RECIPIENT_UNVERIFIED"
    )
    assert bridge.egress.evaluate(item).reason_code == expected


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"retention_days": 8}, "EGRESS_PROCESSING_RESTRICTION"),
        ({"training": True}, "EGRESS_PROCESSING_RESTRICTION"),
        ({"downstream_processing": ["indexing"]}, "EGRESS_PROCESSING_RESTRICTION"),
        ({"max_output_bytes": 100}, "EGRESS_AMOUNT_EXCEEDED"),
        ({"purposes": ["schedule"]}, "EGRESS_RECIPIENT_SCOPE_DENIED"),
    ],
)
def test_retention_processing_purpose_and_amount_constraints(
    bridge, owner, governance, change, reason
):
    approvals, policy = governance
    policy["recipients"][0].update(change)
    approvals.save()
    assert bridge.egress.evaluate(transfer(bridge, owner)).reason_code == reason


def test_text_review_does_not_authorize_pixels_or_original_bytes(bridge, owner, governance):
    approvals, policy = governance
    policy["content_reviews"] = [
        {
            "source_id": "fixture-source",
            "version": "a" * 64,
            "classification": "INSTRUCTOR_OWNED_COURSE_CONTENT",
            "purposes": ["document_reading", "visual_analysis", "original_download"],
            "content_sha256": "c" * 64,
            "reviewed_channels": ["text"],
            "privacy_reviewed_channels": ["text"],
            "privacy_review_reference": "fictional privacy review",
            "content_owner_permission_reference": "Fictional explicit owner authorization",
        }
    ]
    approvals.save()
    item = transfer(bridge, owner, kind="file", classification=CC.INSTRUCTOR_OWNED_COURSE_CONTENT)
    assert bridge.egress.evaluate(replace(item, purpose="document_reading", channel="text")).allowed
    changed_bytes = replace(item.sources[0], content_sha256="d" * 64)
    assert (
        bridge.egress.evaluate(
            replace(item, sources=(changed_bytes,), purpose="document_reading", channel="text")
        ).reason_code
        == "EGRESS_CONTENT_HASH_REVIEW_REQUIRED"
    )
    for purpose, channel in [
        ("visual_analysis", "visual"),
        ("original_download", "original"),
        ("original_download", "temporary_url"),
    ]:
        assert (
            bridge.egress.evaluate(replace(item, purpose=purpose, channel=channel)).reason_code
            == "EGRESS_MODALITY_REVIEW_REQUIRED"
        )
    changed = replace(item.sources[0], version="b" * 64)
    assert not bridge.egress.evaluate(replace(item, sources=(changed,))).allowed


@pytest.mark.parametrize(
    "classification",
    [
        CC.THIRD_PARTY_EDUCATIONAL_RECORD,
        CC.RESTRICTED_ASSESSMENT,
        CC.CONFIDENTIAL_RESEARCH,
        CC.UNKNOWN_OR_UNCLASSIFIED,
    ],
)
def test_derived_summary_embedding_and_screenshot_inherit_restrictions(
    bridge, owner, governance, classification
):
    item = transfer(bridge, owner, kind="derived", classification=classification, derived=True)
    for channel in ("text", "structured", "visual"):
        assert not bridge.egress.evaluate(
            replace(item, channel=channel, minimized=True, redacted=True)
        ).allowed


def test_privacy_and_user_checks_cannot_be_replaced_by_content_permissions(
    bridge, owner, governance
):
    item = transfer(bridge, owner)
    assert not bridge.egress.evaluate(replace(item, authorized=False)).allowed
    assert not bridge.egress.evaluate(replace(item, privacy_filtered=False)).allowed
    assert not bridge.egress.evaluate(replace(item, principal="another-owner")).allowed


def test_minimal_audit_event_never_contains_raw_data_or_sensitive_ids(
    bridge, owner, governance, caplog
):
    with caplog.at_level("INFO", logger="canvas_bridge.data_egress"):
        bridge.egress.evaluate(transfer(bridge, owner))
    events = [
        json.loads(r.message.split("data_egress_decision ", 1)[1])
        for r in caplog.records
        if r.name == "canvas_bridge.data_egress"
    ]
    assert len(events) == 1
    assert set(events[0]) == {
        "policy_version",
        "classifications",
        "recipient_category",
        "decision",
        "reason_code",
    }
    assert all(
        private not in str(events) for private in (owner, WORKSPACE, ENVIRONMENT, "fixture-source")
    )


def test_errors_never_echo_source_content_credentials_or_capabilities(bridge):
    result = Result(
        status="permission_denied",
        summary="PRIVATE-EXAM-ANSWERS Bearer secret-token-value",
        data={
            "reason_code": "PRIVATE_STUDENT_ID",
            "source": "https://bridge.invalid/course-file-download/private",
            "text": "CLASSMATE-GRADE",
        },
    )
    clean = bridge.egress.safe_error(result).model_dump_json()
    for private in (
        "PRIVATE-EXAM",
        "secret-token",
        "PRIVATE_STUDENT_ID",
        "CLASSMATE",
        "course-file-download",
    ):
        assert private not in clean


def test_revoked_or_expired_institutional_grant_stops_egress(bridge, owner, governance):
    approvals, _ = governance
    assert bridge.egress.evaluate(transfer(bridge, owner)).allowed
    approvals.records[1]["expires_at"] = (utcnow() - timedelta(seconds=1)).isoformat()
    approvals.save()
    assert (
        bridge.egress.evaluate(transfer(bridge, owner)).reason_code
        == "EGRESS_INSTITUTIONAL_APPROVAL_DENIED"
    )


async def test_authorized_minimized_schedule_works_without_raw_documents(
    bridge, owner, seeded, governance
):
    context = RequestAuthorization("get_workload", recipient="chatgpt")
    context.egress_identity = transfer(bridge, owner).recipient
    token = request_authorization.set(context)
    try:
        result = await bridge.workload(owner, seeded, utcnow(), utcnow() + timedelta(days=7), "UTC")
        result.data["full_document"] = "PRIVATE RAW LECTURE CONTENT"
        clean = bridge.egress.release(
            result, owner, {"connection_id": seeded}, tool_name="get_workload"
        )
        assert clean.data["items"] and "PRIVATE RAW" not in clean.model_dump_json()
        assert clean.meta.egress["decision"] == "ALLOW_REDACTED"
        assert "FIRST_PARTY_EDUCATIONAL_RECORD" in clean.meta.egress["classifications"]
    finally:
        request_authorization.reset(token)


def test_external_processors_have_no_implicit_transmission_path(bridge, owner, governance):
    with pytest.raises(DomainError) as error:
        bridge.egress.external_processing(transfer(bridge, owner))
    assert error.value.reason_code == "EGRESS_EXTERNAL_PROCESSOR_DISABLED"


def test_egress_honors_specific_course_approval_scope(bridge, owner, governance):
    approvals, _ = governance
    for record in approvals.records:
        record["conditions"] = {"resource_allowlist": ["approved-course"]}
    approvals.save()
    item = transfer(bridge, owner, authorization_resource="approved-course")
    assert bridge.egress.evaluate(item).allowed
    other = replace(item.sources[0], authorization_resource="other-course")
    assert not bridge.egress.evaluate(replace(item, sources=(other,))).allowed


@pytest.mark.parametrize("value", [["PRIVATE"], {"PRIVATE": "content"}, 17, None])
def test_malformed_error_details_are_reconstructed_without_echo(bridge, value):
    clean = bridge.egress.safe_error(
        Result(
            status="permission_denied",
            summary="PRIVATE",
            data={"reason_code": value, "processing_stage": value, "egress": value},
        )
    )
    assert "PRIVATE" not in clean.model_dump_json()


async def test_synthetic_ephemeral_syllabus_sources_remain_available(
    bridge, owner, seeded, academic
):
    from canvas_bridge.academic_intelligence import academic_request
    from canvas_bridge.egress_sources import resolve_sources

    result = await academic_request(bridge, owner, seeded, academic.id)
    sources, _ = resolve_sources(
        bridge.egress,
        owner,
        {"connection_id": seeded, "course_id": academic.id},
        result,
        "reconcile_course_deadlines",
    )
    assert all(s.classification != CC.UNKNOWN_OR_UNCLASSIFIED for s in sources), (
        sources,
        [
            (s.id, s.resource_id, s.course_id, s.source_type, s.content_hash, s.url)
            for s in result.sources
        ],
    )


async def test_derived_deadlines_keep_signed_source_restrictions(bridge, owner, seeded, governance):
    approvals, policy = governance
    result = await bridge.workload(owner, seeded, utcnow(), utcnow() + timedelta(days=7), "UTC")
    item = result.data["items"][0]
    policy["content_reviews"] = [
        {
            "source_id": item["id"],
            "version": item["source"]["content_hash"],
            "classification": "RESTRICTED_ASSESSMENT",
            "purposes": ["schedule"],
            "reviewed_channels": ["structured"],
            "privacy_reviewed_channels": ["structured"],
            "privacy_review_reference": "fictional privacy review",
        }
    ]
    approvals.save()
    context = RequestAuthorization(
        "get_workload", recipient="chatgpt", egress_identity=transfer(bridge, owner).recipient
    )
    token = request_authorization.set(context)
    try:
        with pytest.raises(DomainError) as error:
            bridge.egress.release(
                result, owner, {"connection_id": seeded}, tool_name="get_workload"
            )
        assert error.value.reason_code == "EGRESS_RESTRICTED_CONTENT"
        policy["content_reviews"][0]["version"] = "b" * 64
        approvals.save()
        with pytest.raises(DomainError) as error:
            bridge.egress.release(
                result, owner, {"connection_id": seeded}, tool_name="get_workload"
            )
        assert error.value.reason_code == "EGRESS_CLASSIFICATION_UNKNOWN"
    finally:
        request_authorization.reset(token)


async def test_output_version_cannot_borrow_cached_source_review(bridge, owner, seeded, governance):
    from canvas_bridge.egress_sources import resolve_sources

    approvals, policy = governance
    result = await bridge.workload(owner, seeded, utcnow(), utcnow() + timedelta(days=7), "UTC")
    item = result.data["items"][0]
    policy["content_reviews"] = [
        {
            "source_id": item["id"],
            "version": item["source"]["content_hash"],
            "classification": "PUBLIC_OR_APPROVED",
            "purposes": ["study"],
            "reviewed_channels": ["structured"],
            "privacy_reviewed_channels": ["structured"],
            "privacy_review_reference": "fictional privacy review",
        }
    ]
    approvals.save()
    from canvas_bridge.domain import Source

    observed = Source.model_validate(item["source"]).model_copy(update={"content_hash": "b" * 64})
    output = Result(
        summary="Fresh source version", data={"work_id": item["id"]}, sources=[observed]
    )
    sources, _ = resolve_sources(
        bridge.egress, owner, {"connection_id": seeded}, output, "get_assignment_details"
    )
    assert sources[0].version == "b" * 64
    assert sources[0].classification == CC.UNKNOWN_OR_UNCLASSIFIED
