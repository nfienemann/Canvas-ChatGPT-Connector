"""CB-04/06/13/15 atomic state and source-revocation regressions."""

from datetime import timedelta

import pytest
from sqlalchemy import select, text

from canvas_bridge.domain import DomainError
from canvas_bridge.processes.models import AcademicRecord, ProcessState
from canvas_bridge.processes.state import ProcessRepository, read_portable_export
from canvas_bridge.storage import IndependentResource
from tests.test_process_evidence import NOW, SCOPE, source


@pytest.fixture
def repo(bridge):
    denied = set()

    def authorize(session, owner, tag, purpose):
        if tag.id in denied:
            raise DomainError("permission_denied", "Fixture source revoked.")
        if tag.scope.principal != owner:
            raise AssertionError("Cross owner source")

    result = ProcessRepository(bridge.store, clock=lambda: NOW, authorize=authorize)
    result.denied = denied
    return result


def record(ident="due", **updates):
    fields = dict(
        id=ident,
        kind="claim",
        scope=SCOPE,
        data={"deadline": "2030-10-10"},
        sources=(source(),),
        updated_at=NOW,
    )
    return AcademicRecord(**(fields | updates))


def save(repo, item, key=None):
    change = repo.propose(SCOPE.principal, item.id, item, "create")
    return repo.commit(SCOPE.principal, change, confirmed=True, idempotency_key=key or item.id)


def test_cb04_corrected_date_invalidates_plan_and_atomic_retry_is_idempotent(repo):
    due = record()
    save(repo, due)
    save(repo, record("plan", kind="plan", depends_on=(due.id,)))
    changed = due.model_copy(update={"revision": 2, "data": {"deadline": "2030-10-08"}})
    preview = repo.propose(SCOPE.principal, due.id, changed, "correction")
    assert preview.affected == ("plan",)
    first = repo.commit(SCOPE.principal, preview, confirmed=True, idempotency_key="change")
    restarted = ProcessRepository(repo.store, clock=lambda: NOW, authorize=repo.authorize)
    assert (
        restarted.commit(SCOPE.principal, preview, confirmed=True, idempotency_key="change")
        == first
    )
    assert restarted.read(SCOPE.principal, "due").data["deadline"] == "2030-10-08"
    with pytest.raises(DomainError, match="Refresh"):
        restarted.read(SCOPE.principal, "plan")


def test_cb04_rollback_checks_source_authorization_and_does_not_resurrect_revoked_content(repo):
    item = record()
    save(repo, item)
    change = repo.propose(
        SCOPE.principal,
        item.id,
        item.model_copy(update={"revision": 2, "data": {"deadline": "2030-10-08"}}),
        "correction",
    )
    repo.commit(SCOPE.principal, change, confirmed=True, idempotency_key="change")
    restored = repo.rollback_preview(SCOPE.principal, change.id)
    assert restored.after.data == item.data and restored.after.revision == 3
    repo.denied.add("syllabus")
    with pytest.raises(DomainError):
        repo.commit(SCOPE.principal, restored, confirmed=True, idempotency_key="undo")


def test_cb04_failed_commit_rolls_back_and_resume_preserves_data(repo, monkeypatch):
    change = repo.propose(SCOPE.principal, "due", record(), "create")
    original = repo._save

    def crash(*args):
        original(*args)
        args[0].flush()
        raise RuntimeError("synthetic interrupted transaction")

    monkeypatch.setattr(repo, "_save", crash)
    with pytest.raises(RuntimeError):
        repo.commit(SCOPE.principal, change, confirmed=True, idempotency_key="create")
    assert repo.inventory(SCOPE.principal)["records"] == []
    monkeypatch.setattr(repo, "_save", original)
    assert (
        repo.commit(SCOPE.principal, change, confirmed=True, idempotency_key="create")["version"]
        == 1
    )


def test_cb04_stale_preview_and_idempotency_collision_are_rejected(repo):
    first = repo.propose(SCOPE.principal, "due", record(), "create")
    other = repo.propose(SCOPE.principal, "other", record("other"), "create")
    with pytest.raises(DomainError):
        repo.commit(SCOPE.principal, first, confirmed=False, idempotency_key="create")
    repo.commit(SCOPE.principal, first, confirmed=True, idempotency_key="create")
    with pytest.raises(DomainError):
        repo.commit(SCOPE.principal, other, confirmed=True, idempotency_key="create")
    with pytest.raises(DomainError):
        repo.commit(SCOPE.principal, other, confirmed=True, idempotency_key="other")


def test_invalidated_plan_can_be_repaired_with_fresh_preview(repo):
    due = record()
    save(repo, due)
    plan = record("plan", kind="plan", depends_on=(due.id,))
    save(repo, plan)
    change = repo.propose(
        SCOPE.principal,
        due.id,
        due.model_copy(update={"revision": 2, "data": {"deadline": "2030-10-09"}}),
        "correction",
    )
    repo.commit(SCOPE.principal, change, confirmed=True, idempotency_key="correct")
    repair = repo.propose(
        SCOPE.principal,
        plan.id,
        plan.model_copy(update={"revision": 3, "data": {"deadline": "2030-10-09"}}),
        "correction",
    )
    repo.commit(SCOPE.principal, repair, confirmed=True, idempotency_key="repair")
    assert repo.read(SCOPE.principal, plan.id).revision == 3


def test_cb06_mixed_source_revocation_keeps_independent_notes(repo):
    restricted = source("restricted")
    independent = source("notes").model_copy(update={"origin": "local_document"})
    save(repo, record("notes", sources=(independent,)))
    save(repo, record("institutional", sources=(restricted,)))
    save(
        repo,
        record(
            "mixed",
            kind="plan",
            sources=(restricted, independent),
            depends_on=("notes", "institutional"),
        ),
    )
    result = repo.revoke(SCOPE.principal, "restricted", delete=False)
    assert result["affected_count"] == 2
    assert repo.read(SCOPE.principal, "notes").sources == (independent,)
    with pytest.raises(DomainError):
        repo.read(SCOPE.principal, "mixed")
    repo.revoke(SCOPE.principal, "restricted")
    assert [r["id"] for r in repo.inventory(SCOPE.principal)["records"]] == ["notes"]


def test_lineage_cannot_drop_parent_restrictions_or_cross_users(repo):
    save(repo, record())
    with pytest.raises(DomainError):
        repo.propose(
            SCOPE.principal,
            "child",
            record("child", depends_on=("due",), sources=(source("other"),)),
            "create",
        )
    with pytest.raises(DomainError):
        repo.read("another-student", "due")
    with pytest.raises(DomainError):
        repo.propose("another-student", "due", record(), "create")


def test_cb13_unknown_schema_corruption_and_old_preview_refuse_writes(repo):
    save(repo, record())
    with repo.store.transaction() as session:
        row = session.scalar(
            select(IndependentResource).where(IndependentResource.kind == "academic_process_state")
        )
        row.content = row.content | {"schema_version": "academic-processes-999"}
    with pytest.raises(DomainError) as error:
        repo.inventory(SCOPE.principal)
    assert error.value.reason_code == "PROCESS_SCHEMA_UNSUPPORTED"


def test_cb15_encrypted_inventory_export_roundtrip_and_deletion_purge_history(repo):
    save(repo, record())
    save(repo, record("plan", kind="plan", depends_on=("due",)))
    rows = repo.inventory(SCOPE.principal)["records"]
    assert rows[0]["sources"][0]["locator"] == "page 1"
    exported = repo.export(SCOPE.principal, ["due", "plan"])
    assert [r.id for r in read_portable_export(exported, owner=SCOPE.principal)] == ["due", "plan"]
    with repo.store.engine.connect() as connection:
        raw = connection.execute(text("SELECT content FROM independent_resources")).scalar_one()
        assert "2030-10-10" not in raw and raw.startswith("bridge-sealed-v1:")
    change = repo.propose(SCOPE.principal, "due", None, "delete")
    repo.commit(SCOPE.principal, change, confirmed=True, idempotency_key="delete")
    assert repo.inventory(SCOPE.principal)["records"] == []
    with repo.store.transaction() as session:
        row = session.scalar(
            select(IndependentResource).where(IndependentResource.kind == "academic_process_state")
        )
        assert "2030-10-10" not in str(row.content)
        assert ProcessState.model_validate(row.content).dependents == {}


def test_cb15_export_rechecks_revoked_and_expired_sources(repo):
    save(repo, record())
    repo.denied.add("syllabus")
    with pytest.raises(DomainError):
        repo.export(SCOPE.principal, ["due"])
    assert repo.inventory(SCOPE.principal)["records"] == [{"id": "due", "state": "unavailable"}]
    repo.denied.clear()
    repo.clock = lambda: NOW + timedelta(days=2)
    with pytest.raises(DomainError):
        repo.read(SCOPE.principal, "due")


def test_concurrent_file_database_commits_cannot_overwrite_each_other(tmp_path, bridge):
    from concurrent.futures import ThreadPoolExecutor

    from canvas_bridge.storage import Store

    store = Store("sqlite:///" + (tmp_path / "process-concurrency.db").as_posix())
    store.create_fixture_schema()
    store.protect(bridge.vault)
    repo = ProcessRepository(store, clock=lambda: NOW, authorize=lambda *args: None)
    try:
        first = repo.propose(SCOPE.principal, "one", record("one"), "create")
        second = repo.propose(SCOPE.principal, "two", record("two"), "create")

        def commit(change):
            try:
                return repo.commit(
                    SCOPE.principal, change, confirmed=True, idempotency_key=change.id
                )
            except DomainError:
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(commit, [first, second]))
        assert results.count("conflict") == 1
        assert len(repo.inventory(SCOPE.principal)["records"]) == 1
    finally:
        store.close()


def test_cosmetic_title_correction_keeps_dependent_plan_valid(repo):
    due = record()
    save(repo, due)
    save(repo, record("plan", kind="plan", depends_on=(due.id,)))
    updated = due.model_copy(update={"revision": 2, "data": due.data | {"title": "Cosmetic title"}})
    change = repo.propose(SCOPE.principal, due.id, updated, "correction")
    assert not change.affected
    repo.commit(SCOPE.principal, change, confirmed=True, idempotency_key="title")
    assert repo.read(SCOPE.principal, "plan").state == "valid"
    assert repo.impacts(SCOPE.principal, due.id)[0]["classification"] == "informational"


def test_full_revision_and_receipt_journals_allow_correction_and_deletion(repo):
    save(repo, record())
    with repo.store.transaction() as session:
        row, state = repo._load(session, SCOPE.principal)
        revision = state.revisions[0]
        receipt = next(iter(state.receipts.values()))
        saturated = state.model_copy(
            update={
                "revisions": tuple(
                    revision.model_copy(update={"id": f"revision-{i}"}) for i in range(500)
                ),
                "receipts": {f"receipt-{i}": receipt for i in range(500)},
            }
        )
        repo._save(session, SCOPE.principal, row, saturated)
    changed = record(revision=2, data={"deadline": "2030-10-09"})
    preview = repo.propose(SCOPE.principal, "due", changed, "correction")
    repo.commit(SCOPE.principal, preview, confirmed=True, idempotency_key="correction")
    with repo.store.transaction() as session:
        _, state = repo._load(session, SCOPE.principal)
        assert len(state.receipts) == len(state.revisions) == 500
        assert "receipt-0" not in state.receipts
    deletion = repo.propose(SCOPE.principal, "due", None, "delete")
    repo.commit(SCOPE.principal, deletion, confirmed=True, idempotency_key="delete")
    assert not repo.inventory(SCOPE.principal)["records"]
