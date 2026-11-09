"""Permissive private operation does not imply public release approval."""

from dataclasses import replace

import pytest

from canvas_bridge.config import Settings
from canvas_bridge.domain import Result
from canvas_bridge.egress_models import ContentClassification as CC
from canvas_bridge.egress_models import RecipientIdentity
from tests.test_egress_policy import transfer


def test_unknown_unreviewed_recipient_allowed_only_when_enabled(bridge, owner):
    request = replace(
        transfer(bridge, owner, kind="file", classification=CC.UNKNOWN_OR_UNCLASSIFIED),
        recipient=RecipientIdentity("unverified"),
    )
    assert not bridge.egress.evaluate(request).allowed
    bridge.settings.egress_mode = "permissive"
    decision = bridge.egress.evaluate(request)
    assert decision.allowed
    assert decision.reason_code == "EGRESS_PERMISSIVE_MODE"
    assert decision.classifications == (CC.UNKNOWN_OR_UNCLASSIFIED,)


@pytest.mark.parametrize("change", ["owner", "authorization", "privacy", "restricted"])
def test_permissive_preserves_access_and_privacy(bridge, owner, change):
    bridge.settings.egress_mode = "permissive"
    request = transfer(bridge, owner)
    if change == "owner":
        request = replace(request, principal="another-owner")
    elif change == "authorization":
        request = replace(request, authorized=False)
    elif change == "privacy":
        request = replace(request, privacy_filtered=False)
    else:
        request = replace(request, sources=(replace(request.sources[0], restricted=True),))
    assert not bridge.egress.evaluate(request).allowed


def test_permissive_release_still_filters_credentials(bridge, owner):
    bridge.settings.egress_mode = "permissive"
    result = bridge.egress.release(
        Result(summary="Study information", data={"access_token": "secret-fixture"}),
        owner,
        {},
        tool_name="get_local_study_preferences",
    )
    assert "secret-fixture" not in result.model_dump_json()
    assert result.meta.egress["reason_code"] == "EGRESS_PERMISSIVE_MODE"


def test_hosted_cannot_enable_permissive_mode():
    with pytest.raises(ValueError, match="Permissive egress"):
        Settings(_env_file=None, profile="hosted", egress_mode="permissive")
