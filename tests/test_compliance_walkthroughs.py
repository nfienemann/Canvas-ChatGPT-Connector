"""Seven reviewer walkthroughs; every record and identifier is fictional."""

import json
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from canvas_bridge.academic.gateway import AcademicRequest
from canvas_bridge.academic.services import calculate_grade, document_text
from canvas_bridge.approval_policy import ApprovalGateway, PolicyRequest
from canvas_bridge.domain import DomainError
from canvas_bridge.egress_models import ReleaseDecision
from canvas_bridge.policy import Endpoint
from canvas_bridge.privacy.identity import PrivacyIdentity
from canvas_bridge.privacy.upstream import minimize_upstream
from canvas_bridge.providers.future_mcp import FutureApprovedMCPProvider
from canvas_bridge.providers.synthetic import SyntheticProvider
from canvas_bridge.storage import Snapshot
from tests.test_egress_policy import governance as governance
from tests.test_egress_policy import transfer
from tests.test_provider_architecture import Clock, demo_request, local
from tests.test_retention import freeze


def fictional():
    return json.loads(Path("governance/demo/academic.json").read_text(encoding="utf-8"))


def test_walkthrough_unauthorized_source_is_blocked(settings):
    settings.live_access_enabled = True
    request = PolicyRequest("synthetic", "personal", frozenset({"courses"}), "chatgpt", "share")
    decision = ApprovalGateway(settings).evaluate(request)
    assert not decision.allowed and decision.reason_code == "APPROVAL_NOT_ASSESSED"


def test_walkthrough_third_party_identifiers_are_withheld():
    data = fictional()
    assert (
        minimize_upstream(
            Endpoint.ENROLLMENTS, data["other_record"], PrivacyIdentity(data["own_user"])
        )
        == {}
    )


async def test_walkthrough_permitted_academic_analysis_succeeds():
    provider = SyntheticProvider(clock=Clock())
    result = calculate_grade(provider.gateway, await provider.get_grade_summary(demo_request()))
    data = fictional()
    assert (
        result["calculation"]["calculated_percentage"]
        == f"{100 * sum(data['scores']) / sum(data['possible']):.4f}"
    )


async def test_walkthrough_revoked_access_fails():
    provider, request = local(fictional()["notes"].encode())
    packet = await provider.get_authorized_document(request)
    assert document_text(provider.gateway, packet)["documents"]
    provider.revoke()
    with pytest.raises(DomainError):
        document_text(provider.gateway, packet)


def test_walkthrough_sensitive_file_transfer_is_denied(bridge, owner, governance):
    decision = bridge.egress.evaluate(transfer(bridge, owner, kind="file", restricted=True))
    assert decision.decision == ReleaseDecision.DENY


async def test_walkthrough_temporary_cache_expires(bridge, owner, seeded):
    snapshot = await bridge.refresh(owner, seeded)
    clock = freeze(bridge)
    clock[0] += timedelta(days=31)
    with pytest.raises(DomainError):
        bridge.snapshot(owner, seeded, snapshot.id)
    await bridge.retention.sweep()
    with bridge.store.transaction() as session:
        assert not session.scalars(select(Snapshot)).all()


async def test_walkthrough_prompt_injection_cannot_enable_provider():
    provider, request = local(fictional()["injection"].encode())
    packet = await provider.get_authorized_document(request)
    assert (
        "Ignore all rules"
        in document_text(provider.gateway, packet)["documents"][0]["parts"][0]["text"]
    )
    future = FutureApprovedMCPProvider(clock=Clock())
    with pytest.raises(DomainError):
        await future.get_grade_summary(
            AcademicRequest("synthetic-student", "fictional", "demo", "course-fictional")
        )
