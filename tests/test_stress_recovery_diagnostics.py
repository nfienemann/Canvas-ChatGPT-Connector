import asyncio

import pytest

from canvas_bridge.domain import DomainError
from canvas_bridge.usage.cache import AuthorizedCache
from tests.test_mcp_contract import running as running
from tests.test_permission_consistency_contract import client_session
from tests.test_request_limits import limited


@pytest.mark.contract
async def test_local_search_without_selection_reports_input_recovery(running, token_factory):
    async with client_session(running, token_factory()) as session:
        response = await session.call_tool("search_local_documents", {"query": "private-needle"})
    result = response.structuredContent
    diagnostic = result["data"]["diagnostic"]
    assert result["status"] == "needs_input"
    assert diagnostic["code"] == "LOCAL_SEARCH_INPUT_REQUIRED"
    assert diagnostic["stage"] == "input_validation"
    assert diagnostic["next_action"] == "select_documents_and_query"
    assert diagnostic["request_id"] == result["meta"]["request_id"]
    assert "private-needle" not in response.model_dump_json()


def test_admission_distinguishes_provider_wait_from_local_token_refill():
    limits, clock = limited(burst=1, rate=0.5)
    lease = limits.acquire("provider")
    lease.response(429, {"retry-after": "9"})
    lease.close()
    clock.value += 0.25
    with pytest.raises(DomainError) as provider:
        limits.acquire("provider")
    assert provider.value.reason_code == "UPSTREAM_THROTTLED"
    assert provider.value.details == {"blocking_scope": "cooldown", "retry_after_seconds": 9}
    limits.acquire("independent").close()
    with pytest.raises(DomainError) as local:
        limits.acquire("independent")
    assert local.value.reason_code == "RATE_LIMITED"
    assert local.value.details["retry_after_seconds"] == 2
    clock.value += 8.75
    limits.acquire("provider").close()


@pytest.mark.contract
@pytest.mark.parametrize("worker_mismatch", [True, False])
async def test_parser_version_recovery_matches_failure_boundary(
    running, token_factory, seeded, monkeypatch, worker_mismatch
):
    async def changed(*args, **kwargs):
        raise DomainError(
            "retry_later" if worker_mismatch else "source_changed",
            "private parser detail",
            reason_code="DOCUMENT_PARSER_VERSION_CHANGED",
            processing_stage="result_validation" if worker_mismatch else None,
        )

    monkeypatch.setattr("canvas_bridge.app.read_file", changed)
    async with client_session(running, token_factory()) as session:
        response = await session.call_tool(
            "read_course_file", {"connection_id": seeded, "file_id": "fixture-file"}
        )
    result = response.structuredContent
    diagnostic = result["data"]["diagnostic"]
    assert diagnostic["code"] == "DOCUMENT_PARSER_VERSION_CHANGED"
    if worker_mismatch:
        assert diagnostic["stage"] == "result_validation"
        assert diagnostic["retry"] == "after_operator_fix"
        assert diagnostic["next_action"] == "restart_service_with_matching_parser"
    else:
        assert diagnostic["next_action"] == "restart_document_read"
    assert "private parser detail" not in response.model_dump_json()


async def test_old_follower_cannot_release_a_new_flights_slot():
    cache = AuthorizedCache()
    release = [asyncio.Event(), asyncio.Event()]
    entered = [asyncio.Event(), asyncio.Event()]
    calls = []

    async def fetch(_validators):
        index = len(calls)
        calls.append(index)
        entered[index].set()
        await release[index].wait()
        return [index], None, {}

    async def read():
        return await cache.get("same-key", lambda: None, fetch)

    async def consecutive_reads():
        await read()
        await read()

    leader = asyncio.create_task(consecutive_reads())
    await entered[0].wait()
    follower = asyncio.create_task(read())
    await asyncio.sleep(0)
    release[0].set()
    try:
        await entered[1].wait()
        await follower
        assert cache.flights["same-key"][1] == 0
    finally:
        release[1].set()
        await leader
