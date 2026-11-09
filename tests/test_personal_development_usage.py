import pytest
from pydantic import ValidationError

from canvas_bridge.config import Settings
from canvas_bridge.domain import DomainError
from canvas_bridge.usage.ledger import UpstreamUsageGovernor
from canvas_bridge.usage.policy import PartnerBudgetContract, personal_development_policy
from canvas_bridge.usage.transport import OPERATIONS
from tests.test_usage_governor import ctx
from tests.test_usage_governor import ledger as ledger


def test_development_ceiling_persists_and_disabling_denies(ledger):
    p = personal_development_policy(2)
    g = UpstreamUsageGovernor(ledger, development_policy=p)
    c = ctx()
    g.reserve(
        c, authorize=lambda: None, operation=OPERATIONS[c.operation], mode="personal_development"
    )
    g.sent(c.attempt_id, lambda: None)
    g.finish(c.attempt_id, status=200)
    g = UpstreamUsageGovernor(ledger, development_policy=p)
    c = ctx()
    with pytest.raises(DomainError) as error:
        g.reserve(
            c,
            authorize=lambda: None,
            operation=OPERATIONS[c.operation],
            mode="personal_development",
        )
    assert error.value.reason_code == "UPSTREAM_BUDGET_EXHAUSTED"
    with g.transaction() as db:
        assert g.policy(db).billing.signed_allowance is None
    report = g.report()
    assert report["unit"] == "local_request"
    assert report["vendor_allowance_verified"] is False
    with UpstreamUsageGovernor(ledger).transaction() as db:
        with pytest.raises(DomainError) as error:
            UpstreamUsageGovernor(ledger).policy(db)
        assert error.value.reason_code == "PROVIDER_NOT_AUTHORIZED"


def test_development_does_not_skip_authorization(ledger):
    g = UpstreamUsageGovernor(ledger, development_policy=personal_development_policy())
    c = ctx()

    def deny():
        raise DomainError("permission_denied", "Not authorized")

    with pytest.raises(DomainError):
        g.reserve(c, authorize=deny, operation=OPERATIONS[c.operation], mode="personal_development")
    assert g.report()["state"] == "no_usage"


@pytest.mark.parametrize("profile", ["synthetic", "hosted"])
def test_other_profiles_cannot_enable_development(profile):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, profile=profile, personal_development_usage=True)


def test_local_accounting_cannot_be_a_commercial_policy():
    data = personal_development_policy().model_dump(mode="json")
    data["mode"] = "production_approved"
    with pytest.raises(ValidationError):
        PartnerBudgetContract.model_validate(data)


def test_lower_ceiling_keeps_consumption(ledger):
    g = UpstreamUsageGovernor(ledger, development_policy=personal_development_policy(100))
    c = ctx()
    g.reserve(
        c, authorize=lambda: None, operation=OPERATIONS[c.operation], mode="personal_development"
    )
    g.sent(c.attempt_id, lambda: None)
    g.finish(c.attempt_id, status=200)
    g = UpstreamUsageGovernor(ledger, development_policy=personal_development_policy(1))
    c = ctx()
    with pytest.raises(DomainError):
        g.reserve(
            c,
            authorize=lambda: None,
            operation=OPERATIONS[c.operation],
            mode="personal_development",
        )
    assert g.report()["settled"] == 1


def test_development_limit_update_keeps_existing_attempts(ledger):
    from canvas_bridge.usage.policy import Limits

    p = personal_development_policy(100, 2147483647)
    old = p.model_copy(update={"limits": Limits(per_owner_hour_attempts=120)})
    g = UpstreamUsageGovernor(ledger, development_policy=old)
    c = ctx()
    g.reserve(
        c, authorize=lambda: None, operation=OPERATIONS[c.operation], mode="personal_development"
    )
    g.sent(c.attempt_id, lambda: None)
    g.finish(c.attempt_id, status=200)
    g = UpstreamUsageGovernor(ledger, development_policy=p)
    with g.transaction() as db:
        assert g.policy(db).limits.per_owner_hour_attempts == 2147483647
    assert g.report()["settled"] == 1


def test_private_owner_limits_accept_requested_integer_maximum():
    p = personal_development_policy(2147483647, 2147483647)
    assert p.billing.monthly_allowance == 2147483647
    assert p.limits.per_owner_minute_attempts == 2147483647
    assert p.limits.per_owner_hour_attempts == 2147483647
    assert p.limits.per_owner_daily_attempts == 2147483647
    assert p.limits.max_concurrency_per_token == 2
    assert p.limits.retries_per_attempt == 2
    with pytest.raises(ValidationError):
        personal_development_policy(2147483648)


def test_development_two_requests_progress_third_waits_and_authorization_remains(ledger):
    g = UpstreamUsageGovernor(ledger, development_policy=personal_development_policy())
    first, second, third = (ctx(token_key="shared-test-token") for _ in range(3))
    checks = []

    def admit(c):
        g.reserve(
            c,
            authorize=lambda: checks.append(c.attempt_id),
            operation=OPERATIONS[c.operation],
            mode="personal_development",
        )

    admit(first)
    admit(second)
    with pytest.raises(DomainError) as error:
        admit(third)
    assert error.value.reason_code == "LOCAL_REQUEST_BUSY"
    assert checks == [first.attempt_id, second.attempt_id, third.attempt_id]
    g.finish(first.attempt_id, status=200)
    admit(third)
    assert checks[-1] == third.attempt_id


@pytest.mark.parametrize("value", [0, 5, True, 2.5])
def test_development_concurrency_is_bounded(value):
    with pytest.raises(ValueError):
        personal_development_policy(max_concurrency=value)


def test_default_production_limit_is_unchanged():
    from canvas_bridge.usage.policy import Limits

    assert Limits().max_concurrency_per_token == 1
    assert Limits().max_download_attempts_per_task == 6
    assert personal_development_policy(max_concurrency=1).limits.max_concurrency_per_token == 1
    assert personal_development_policy(max_concurrency=4).limits.max_concurrency_per_owner == 4


def test_development_redirected_documents_share_bounded_task_and_keep_accounting(ledger):
    from sqlalchemy import func, select

    from canvas_bridge.usage import models as m

    p = personal_development_policy(owner_request_limit=100)
    g = UpstreamUsageGovernor(ledger, development_policy=p)

    def attempt(operation, status, *, task="reader-call", body_bytes=0):
        c = ctx(operation=operation, task_id=task)
        g.reserve(
            c, authorize=lambda: None, operation=OPERATIONS[operation], mode="personal_development"
        )
        g.sent(c.attempt_id, lambda: None)
        g.finish(c.attempt_id, status=status, body_bytes=body_bytes)

    # Membership, policy discovery and file metadata precede document downloads.
    for _ in range(10):
        attempt("canvas.file", 200, body_bytes=1000)
    for _ in range(6):
        for _ in range(3):
            attempt("canvas.file_download", 302)
        attempt("canvas.file_download", 200, body_bytes=366181)
    with pytest.raises(DomainError) as error:
        attempt("canvas.file_download", 200)
    assert error.value.reason_code == "TASK_BUDGET_EXCEEDED"
    # A new call has its own task allowance, without resetting usage history.
    attempt("canvas.file_download", 200, task="next-reader-call")
    with ledger.connect() as db:
        assert db.scalar(select(func.count()).select_from(m.attempts)) == 35
    assert p.limits.max_attempts_per_task == 40
    assert p.limits.task_seconds == 120


def test_development_download_limit_upgrade_preserves_attempts(ledger):
    from canvas_bridge.usage.policy import Limits

    old = personal_development_policy().model_copy(update={"limits": Limits()})
    g = UpstreamUsageGovernor(ledger, development_policy=old)
    for _ in range(6):
        c = ctx(operation="canvas.file_download", task_id="reader-call")
        g.reserve(
            c,
            authorize=lambda: None,
            operation=OPERATIONS[c.operation],
            mode="personal_development",
        )
        g.sent(c.attempt_id, lambda: None)
        g.finish(c.attempt_id, status=302)
    g = UpstreamUsageGovernor(ledger, development_policy=personal_development_policy())
    c = ctx(operation="canvas.file_download", task_id="reader-call")
    g.reserve(
        c, authorize=lambda: None, operation=OPERATIONS[c.operation], mode="personal_development"
    )
    g.sent(c.attempt_id, lambda: None)
    g.finish(c.attempt_id, status=200)
    assert g.report()["settled"] == 7
