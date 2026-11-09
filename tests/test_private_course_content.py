from dataclasses import replace

import pytest

from canvas_bridge.authorization import RequestAuthorization, request_authorization
from canvas_bridge.egress_models import ContentClassification as CC
from canvas_bridge.egress_models import PrivateCourseContentGrant
from tests.test_file_delivery import original as original
from tests.test_mcp_contract import running as running
from tests.test_private_course_listing import setup as setup


@pytest.fixture
def content(setup):
    engine, transfer, settings, state = setup
    record = engine.bridge.approval_gateway.store.load()[0][0]
    record.private_course_listing.course_content = PrivateCourseContentGrant(
        course_ids={"course-one"},
        permission_evidence_sha256="e" * 64,
        channels={"text", "structured", "visual"},
    )
    source = replace(
        transfer.sources[0],
        kind="file",
        classification=CC.UNKNOWN_OR_UNCLASSIFIED,
        source_id="file-one",
        version="a" * 64,
        content_sha256="b" * 64,
        authorization_resource="course-one",
        data_category="files",
    )
    transfer = replace(
        transfer, purpose="document_reading", channel="text", sources=(source,), minimized=False
    )
    token = request_authorization.set(RequestAuthorization("read_course_file"))
    try:
        yield engine, transfer, settings, state, record
    finally:
        request_authorization.reset(token)


def test_explicit_private_grant_classifies_without_fabricating_source_review(content):
    engine, transfer, _, _, record = content
    decision = engine.evaluate(transfer)
    assert decision.allowed
    assert decision.classifications == (CC.OWNER_AUTHORIZED_PRIVATE_COURSE_CONTENT,)
    assert not getattr(record, "private_text_reviews", [])
    record.private_course_listing.course_content = None
    assert not engine.evaluate(transfer).allowed


@pytest.mark.parametrize(
    "changes",
    [
        {"owner": "other"},
        {"subject": "other"},
        {"restricted": True},
        {"confidential": True},
        {"authorization_resource": "other-course"},
        {"kind": "submission"},
        {"data_category": "grades"},
        {"version_consistent": False},
        {"content_sha256": None},
        {"version": ""},
        {"classification": CC.RESTRICTED_ASSESSMENT},
        {"classification": CC.THIRD_PARTY_EDUCATIONAL_RECORD},
    ],
)
def test_source_denials_remain_denied(content, changes):
    engine, transfer, *_ = content
    assert not engine.evaluate(
        replace(transfer, sources=(replace(transfer.sources[0], **changes),))
    ).allowed


@pytest.mark.parametrize(
    "changes",
    [
        {"authorized": False},
        {"privacy_filtered": False},
        {"channel": "original"},
        {"channel": "temporary_url"},
        {"purpose": "original_download"},
        {"amount": 20_000_001},
    ],
)
def test_transfer_boundaries(content, changes):
    engine, transfer, *_ = content
    assert not engine.evaluate(replace(transfer, **changes)).allowed


@pytest.mark.parametrize(
    "field,value",
    [
        ("profile", "hosted"),
        ("host", "0.0.0.0"),  # noqa: S104 - rejection fixture
        ("mcp_read_only", False),
        ("personal_subject", "other"),
    ],
)
def test_deployment_boundaries(content, field, value):
    engine, transfer, settings, *_ = content
    setattr(settings, field, value)
    assert not engine.evaluate(transfer).allowed


def test_upstream_institution_sharing_and_signature_denials_are_retained(content):
    engine, transfer, _, state, _ = content
    state["allowed"] = False
    assert not engine.evaluate(transfer).allowed
    state["allowed"] = True
    state["error"] = "APPROVAL_RECORDS_INVALID"
    assert not engine.evaluate(transfer).allowed


def test_visual_channel_is_explicit_and_wrong_tool_cannot_borrow_grant(content):
    engine, transfer, _, _, record = content
    token = request_authorization.set(RequestAuthorization("render_course_file_page"))
    try:
        visual = replace(transfer, purpose="visual_analysis", channel="visual")
        assert engine.evaluate(visual).allowed
        record.private_course_listing.course_content.channels = frozenset({"text"})
        assert not engine.evaluate(visual).allowed
        assert not engine.evaluate(transfer).allowed
    finally:
        request_authorization.reset(token)


def test_other_recipient_cannot_borrow_private_grant(content):
    engine, transfer, *_ = content
    for change in (
        {"client_id": "other"},
        {"issuer": "https://other.invalid"},
        {"recipient": "external_ai"},
    ):
        assert not engine.evaluate(
            replace(transfer, recipient=replace(transfer.recipient, **change))
        ).allowed


def test_private_extraction_status_allows_cold_metadata_only(content):
    engine, transfer, _, _, record = content
    source = replace(transfer.sources[0], content_sha256=None)
    metadata = replace(transfer, sources=(source,), purpose="metadata", channel="structured")
    token = request_authorization.set(RequestAuthorization("get_file_extraction_status"))
    try:
        assert engine.evaluate(metadata).allowed
        assert not engine.evaluate(replace(metadata, channel="text")).allowed
        assert not engine.evaluate(replace(metadata, authorized=False)).allowed
        assert not engine.evaluate(
            replace(metadata, sources=(replace(source, version=""),))
        ).allowed
        assert not engine.evaluate(
            replace(metadata, sources=(replace(source, authorization_resource="other"),))
        ).allowed
        record.private_course_listing.course_content.channels = frozenset({"text"})
        assert not engine.evaluate(metadata).allowed
    finally:
        request_authorization.reset(token)
    assert not engine.evaluate(replace(transfer, sources=(source,))).allowed


def test_private_consent_does_not_override_known_restricted_review(content):
    from canvas_bridge.egress_models import ContentReview

    engine, transfer, _, _, record = content
    record.private_text_reviews = [
        ContentReview(
            source_id="file-one",
            version="c" * 64,
            classification=CC.RESTRICTED_ASSESSMENT,
            purposes={"document_reading"},
            reviewed_channels={"text"},
        )
    ]
    assert not engine.evaluate(transfer).allowed


@pytest.mark.contract
async def test_signed_private_grant_through_real_mcp_and_revocation(
    running, token_factory, bridge, seeded, owner, original, monkeypatch
):
    import hashlib

    from tests.approval_fixtures import install_approvals
    from tests.test_approval_policy import live_fixture
    from tests.test_permission_consistency_contract import client_session

    course, file_id, _ = original
    bridge.settings.file_reading_enabled = True
    bridge.settings.mcp_read_only = True
    from canvas_bridge.parser_worker import extract

    parser_calls = []

    async def fixture_parser(data, kind, settings, page_range=None):
        parser_calls.append(kind)
        return extract(data, kind, page_range)

    monkeypatch.setattr("canvas_bridge.course_files.extract_document", fixture_parser)
    approvals = install_approvals(bridge)
    approvals.records[2]["private_course_listing"] = dict(
        owner=owner,
        issuer=bridge.settings.issuer_url,
        client_id="fixture-chatgpt-client",
        course_content=dict(
            course_ids=[course.id],
            channels=["text", "structured"],
            permission_evidence_sha256=hashlib.sha256(approvals.evidence).hexdigest(),
        ),
    )
    approvals.save()
    async with client_session(
        running, token_factory(azp="fixture-chatgpt-client"), read_timeout=60
    ) as session:
        live_fixture(bridge)
        cold = (
            await session.call_tool(
                "get_file_extraction_status", dict(connection_id=seeded, file_id=file_id)
            )
        ).structuredContent
        assert cold["status"] == "ok", cold
        assert cold["data"]["indexed"] is False
        assert not cold["data"].get("text")
        result = (
            await session.call_tool("read_course_file", dict(connection_id=seeded, file_id=file_id))
        ).structuredContent
        assert result["status"] in {"ok", "partial_data"}, result
        assert result["data"]["text"]
        assert (
            "OWNER_AUTHORIZED_PRIVATE_COURSE_CONTENT" in result["meta"]["egress"]["classifications"]
        )
        warm = (
            await session.call_tool(
                "get_file_extraction_status", dict(connection_id=seeded, file_id=file_id)
            )
        ).structuredContent
        assert warm["status"] == "ok", warm
        assert warm["data"]["indexed"] is True
        repeated = (
            await session.call_tool(
                "read_course_file",
                dict(
                    connection_id=seeded,
                    file_id=file_id,
                    expected_hash=result["data"]["content_hash"],
                ),
            )
        ).structuredContent
        assert repeated["status"] in {"ok", "partial_data"}, repeated
        assert repeated["data"]["content_hash"] == result["data"]["content_hash"]
        assert parser_calls == ["xlsx"]
        bridge.synthetic.data["files"]["11"][0]["locked_for_user"] = True
        status_denied = (
            await session.call_tool(
                "get_file_extraction_status", dict(connection_id=seeded, file_id=file_id)
            )
        ).structuredContent
        assert status_denied["status"] == "permission_denied"
        assert status_denied["data"]["reason_code"] == "RESOURCE_PERMISSION_DENIED"
        source_denied = (
            await session.call_tool("read_course_file", dict(connection_id=seeded, file_id=file_id))
        ).structuredContent
        assert source_denied["status"] == "permission_denied"
        assert source_denied["data"]["reason_code"] == "RESOURCE_PERMISSION_DENIED"
        bridge.synthetic.data["files"]["11"][0]["locked_for_user"] = False
        approvals.records[2]["private_course_listing"]["course_content"]["course_ids"] = [
            "unselected-other-course"
        ]
        approvals.save()
        denied = (
            await session.call_tool("read_course_file", dict(connection_id=seeded, file_id=file_id))
        ).structuredContent
        assert denied["status"] == "permission_denied"
        assert not denied.get("data", {}).get("text")
        from canvas_bridge.approval_policy import ApprovalStore

        approvals.records[2]["private_course_listing"]["course_content"][
            "permission_evidence_sha256"
        ] = "0" * 64
        approvals.save()
        assert ApprovalStore(bridge.settings).load()[1] == "APPROVAL_RECORDS_INVALID"
