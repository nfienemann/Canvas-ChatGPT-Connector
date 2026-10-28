"""Run process commit/revocation races in CI's disposable PostgreSQL database."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from canvas_bridge.domain import DomainError
from canvas_bridge.processes.purge import purge_sources
from canvas_bridge.processes.state import ProcessRepository
from tests.test_postgres import pg_bridge as pg_bridge
from tests.test_process_evidence import NOW, SCOPE, source
from tests.test_process_state import record, save

pytestmark = pytest.mark.postgres


def test_process_revocation_racing_unrelated_correction_preserves_both_boundaries(pg_bridge):
    repo = ProcessRepository(pg_bridge.store, clock=lambda: NOW, authorize=lambda *args: None)
    save(repo, record())
    local = record("independent", sources=(source(id="other-notes"),))
    save(repo, local)
    change = repo.propose(
        SCOPE.principal,
        local.id,
        local.model_copy(update={"revision": 2, "data": {"deadline": "2030-10-09"}}),
        "correction",
    )
    ready = Barrier(2)

    def correct():
        ready.wait(timeout=10)
        try:
            repo.commit(SCOPE.principal, change, confirmed=True, idempotency_key="correct")
            return "committed"
        except DomainError:
            return "conflict"

    def revoke():
        ready.wait(timeout=10)
        with repo.store.transaction() as session:
            repo.store.principal(session, SCOPE.principal)
            purge_sources(session, SCOPE.principal, source_ids=("syllabus",))

    with ThreadPoolExecutor(max_workers=2) as pool:
        correction, revocation = pool.submit(correct), pool.submit(revoke)
        result = correction.result(timeout=20)
        revocation.result(timeout=20)
    assert [r["id"] for r in repo.inventory(SCOPE.principal)["records"]] == ["independent"]
    if result == "committed":
        assert repo.read(SCOPE.principal, local.id).revision == 2
    else:
        assert repo.read(SCOPE.principal, local.id).revision == 1
