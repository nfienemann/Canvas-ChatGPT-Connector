"""Unread scientific document search with authenticated, bounded continuation."""

import asyncio
from datetime import timedelta

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from canvas_bridge import course_files, document_search
from canvas_bridge.course_files import read_file, search_files
from canvas_bridge.domain import DomainError, utcnow
from canvas_bridge.parser_worker import extract
from canvas_bridge.storage import Connection, Material
from tests.conftest import seed
from tests.test_course_files import file_record
from tests.test_file_reading import readable as readable
from tests.test_file_reading import scientific_pdf
from tests.test_mcp_contract import running as running


async def search(bridge, owner, seeded, course, query="differentiation", **kwargs):
    return await search_files(
        bridge, owner, seeded, course.id, query, include_unread=True, **kwargs
    )


def downloads(bridge):
    return [r for r in bridge.synthetic.requests if r.url.path.endswith("/download")]


def add_pdf(bridge, number, text="Methods: differentiation in synthetic cultures."):
    body = scientific_pdf([text])
    bridge.synthetic.data["files"]["11"].append(
        file_record(
            id=number,
            size=len(body),
            updated_at="2026-10-20T12:00:00Z",
            url=f"https://canvas.synthetic.invalid/files/{number}/download",
        )
    )
    bridge.synthetic.data["file_bodies"][str(number)] = body


async def test_T11_T12_T13_unread_pdf_search_returns_actual_scientific_passage(
    bridge, owner, seeded, readable
):
    course, ref = readable
    before = await search_files(bridge, owner, seeded, course.id, "differentiation")
    assert not before.data["results"] and not downloads(bridge)
    result = await search(bridge, owner, seeded, course)
    hit = result.data["results"][0]
    assert hit["file_id"] == ref and hit["page"] == 1 and hit["locator"] == "PDF page 1"
    assert "controlled cultures" in hit["passage"] and hit["content_hash"]
    assert result.data["unread_documents_searched"]
    assert result.data["search_pass_finished"]
    assert result.data["text_coverage_complete_in_bounded_inventory"]
    assert len(result.evidence) == 1 and result.evidence[0]["content_hash"] == hit["content_hash"]
    assert result.sources[0].source_updated_at.isoformat() == "2026-10-20T12:00:00+00:00"
    assert len(downloads(bridge)) == 1
    again = await search(bridge, owner, seeded, course)
    assert again.data["results"] == result.data["results"]
    assert not again.data["unread_documents_searched"] and len(downloads(bridge)) == 1
    assert again.sources[0].source_updated_at == result.sources[0].source_updated_at
    body = result.model_dump_json()
    assert "fixture-provider-token" not in body and "verifier=" not in body
    assert all(r.method == "GET" for r in bridge.synthetic.requests)


async def test_T11_T25_page_and_file_continuation_never_redownloads_or_skips(
    bridge, owner, seeded, readable
):
    course, _ = readable
    data = scientific_pdf(["Cell differentiation " + str(i) for i in range(5)])
    bridge.synthetic.data["file_bodies"]["51"] = data
    bridge.synthetic.data["files"]["11"][0]["size"] = len(data)
    add_pdf(bridge, 52)
    result = await search(bridge, owner, seeded, course, limit=2, max_documents=1)
    hits = list(result.data["results"])
    responses = 1
    while result.data["next_cursor"]:
        assert responses < 6
        result = await search(
            bridge,
            owner,
            seeded,
            course,
            limit=2,
            max_documents=1,
            cursor=result.data["next_cursor"],
        )
        hits.extend(result.data["results"])
        responses += 1
    assert len(hits) == 6 and len({(h["file_id"], h["page"]) for h in hits}) == 6
    assert len(downloads(bridge)) == 2
    assert result.data["pass_progress"]["completed_documents"] == 2
    assert result.data["text_coverage_complete_in_bounded_inventory"]


async def test_T25_changed_inventory_and_content_refuse_stale_cursor(
    bridge, owner, seeded, readable
):
    course, ref = readable
    result = await search(bridge, owner, seeded, course, "cultures", limit=1)
    assert result.data["next_cursor"]
    assert not result.data["unindexed_documents"]  # Parsed already; only search positions remain.
    bridge.synthetic.data["files"]["11"][0]["updated_at"] = "2026-10-21T12:00:00Z"
    with pytest.raises(DomainError) as error:
        await search(
            bridge, owner, seeded, course, "cultures", limit=1, cursor=result.data["next_cursor"]
        )
    assert error.value.status == "source_changed"
    assert len(downloads(bridge)) == 1
    with bridge.store.transaction() as session:
        assert not session.get(Material, ref).text


@pytest.mark.parametrize("change", ["query", "limit", "epoch", "parser"])
async def test_T13_T25_continuation_binding(bridge, owner, seeded, readable, monkeypatch, change):
    course, _ = readable
    first = await search(bridge, owner, seeded, course, "cultures", limit=1)
    query, limit = "cultures", 1
    if change == "query":
        query = "methods"
    elif change == "limit":
        limit = 2
    elif change == "epoch":
        with bridge.store.transaction() as session:
            session.get(Connection, seeded).epoch += 1
    else:
        monkeypatch.setattr(document_search, "PARSER", "future-parser")
    with pytest.raises(DomainError) as error:
        await search(
            bridge, owner, seeded, course, query, limit=limit, cursor=first.data["next_cursor"]
        )
    assert error.value.status == "source_changed"


async def test_T13_cursor_tampering_expiry_and_other_owner_rejected(
    bridge, owner, seeded, readable
):
    course, _ = readable
    result = await search(bridge, owner, seeded, course, "cultures", limit=1)
    cursor = result.data["next_cursor"]
    data = bridge.vault.open(cursor, owner, seeded + ":document-search")
    data["expires"] = (utcnow() - timedelta(seconds=1)).timestamp()
    expired = bridge.vault.seal(data, owner, seeded + ":document-search")
    for invalid in (cursor[:10] + "invalid", expired, "x" * 4097):
        with pytest.raises(DomainError) as error:
            await search(bridge, owner, seeded, course, "cultures", limit=1, cursor=invalid)
        assert error.value.status == "permission_denied"
    other = await seed(bridge, "another-owner", "another-connection")
    other_course = bridge.selected("another-owner", other)[1][0]
    with pytest.raises(DomainError):
        await search(
            bridge, "another-owner", other, other_course, "cultures", limit=1, cursor=cursor
        )
    with pytest.raises(DomainError):
        await search(bridge, "another-owner", seeded, course)
    with pytest.raises(DomainError):
        await search_files(bridge, owner, seeded, course.id, "cultures", cursor=cursor)


@pytest.mark.parametrize(
    "kind", ["scanned", "unsupported", "failed", "timeout", "disabled", "unversioned"]
)
async def test_T13_T25_T26_incomplete_extraction_never_means_empty_success(
    bridge, owner, seeded, readable, monkeypatch, kind
):
    course, _ = readable
    if kind == "unsupported":
        bridge.synthetic.data["files"]["11"][0].update(
            filename="archive.zip", **{"content-type": "application/zip"}
        )
    elif kind == "failed":

        async def failed(*args):
            raise DomainError(
                "unsupported_feature",
                "Document extraction failed or exceeded sandbox resource limits.",
            )

        monkeypatch.setattr(course_files, "extract_document", failed)
    elif kind == "timeout":
        inventory = await course_files.list_files(bridge, owner, seeded, course.id)

        async def ready(*args, **kwargs):
            return inventory

        monkeypatch.setattr(document_search, "list_files", ready)

        async def slow(*args, **kwargs):
            await asyncio.Event().wait()

        monkeypatch.setattr(document_search, "read_file", slow)
        monkeypatch.setattr(document_search, "SEARCH_SECONDS", 0.1)
    elif kind == "disabled":
        bridge.settings.file_reading_enabled = False
    elif kind == "unversioned":
        bridge.synthetic.data["files"]["11"][0].pop("updated_at")
    else:

        async def scanned(data, fmt, settings):
            result = extract(data, fmt)
            result.update(
                coverage="partial", warnings=["Scanned page: no text; OCR is unavailable."]
            )
            for page in result["pages"]:
                page["text"] = ""
            return result

        monkeypatch.setattr(course_files, "extract_document", scanned)
    result = await search(bridge, owner, seeded, course)
    assert result.status == "partial_data"
    assert not result.data["text_coverage_complete_in_bounded_inventory"]
    assert result.data["search_pass_finished"]
    progress = result.data["pass_progress"]
    if kind == "scanned":
        assert progress["partially_extracted_documents"] == 1 and not result.data["results"]
    elif kind == "unversioned":
        assert progress["unversioned_document_seen"] and result.data["results"]
    else:
        assert progress["failed_documents"] == 1 and not result.data["results"]


async def test_T15_T25_partial_inventory_remains_partial_after_search(
    bridge, owner, seeded, readable
):
    course, _ = readable
    bridge.synthetic.failures["/api/v1/courses/11/files"] = 403
    result = await search(bridge, owner, seeded, course)
    assert result.data["results"]
    assert result.data["inventory_coverage"]["files"] == "partial"
    assert (
        result.status == "partial_data"
        and not result.data["text_coverage_complete_in_bounded_inventory"]
    )


@pytest.mark.parametrize("mode", [False, True])
async def test_T14_T43_expired_connection_discards_prior_hits(
    bridge, owner, seeded, readable, monkeypatch, mode
):
    course, _ = readable
    add_pdf(bridge, 52)
    for item in (await course_files.list_files(bridge, owner, seeded, course.id)).data["files"]:
        await read_file(bridge, owner, seeded, item["file_id"])
    original = course_files.read_file
    count = 0

    async def revoked(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            raise DomainError("reconnect_required", "Reconnect Canvas.")
        return await original(*args, **kwargs)

    monkeypatch.setattr(document_search if mode else course_files, "read_file", revoked)
    with pytest.raises(DomainError) as error:
        await search_files(bridge, owner, seeded, course.id, "differentiation", include_unread=mode)
    assert error.value.status == "reconnect_required" and count == 2


@pytest.mark.parametrize("mode", [False, True])
async def test_T13_T43_selection_race_discards_search(
    bridge, owner, seeded, readable, monkeypatch, mode
):
    course, ref = readable
    await read_file(bridge, owner, seeded, ref)
    original = course_files.read_file

    async def changed(*args, **kwargs):
        result = await original(*args, **kwargs)
        with bridge.store.transaction() as session:
            session.get(Connection, seeded).epoch += 1
        return result

    monkeypatch.setattr(document_search if mode else course_files, "read_file", changed)
    with pytest.raises(DomainError):
        await search_files(bridge, owner, seeded, course.id, "differentiation", include_unread=mode)


async def test_T25_metadata_changes_between_listing_and_read_fail_closed(
    bridge, owner, seeded, readable, monkeypatch
):
    course, _ = readable
    original = document_search.read_file

    async def changed(*args, **kwargs):
        bridge.synthetic.data["files"]["11"][0]["updated_at"] = "2026-10-22T12:00:00Z"
        return await original(*args, **kwargs)

    monkeypatch.setattr(document_search, "read_file", changed)
    with pytest.raises(DomainError) as error:
        await search(bridge, owner, seeded, course)
    assert error.value.status == "source_changed"


async def test_T13_hidden_file_and_same_title_in_other_course_never_leak(
    bridge, owner, seeded, readable
):
    course, _ = readable
    bridge.synthetic.data["files"]["12"] = bridge.synthetic.data["files"]["11"].copy()
    result = await search(bridge, owner, seeded, course)
    other_course = bridge.selected(owner, seeded)[1][1]
    other = await search(bridge, owner, seeded, other_course)
    assert result.data["results"][0]["file_id"] != other.data["results"][0]["file_id"]
    bridge.synthetic.data["files"]["11"][0]["hidden_for_user"] = True
    assert not (await search(bridge, owner, seeded, course)).data["results"]
    bridge.select_courses(owner, seeded, [other_course.id], "UTC")
    with pytest.raises(DomainError):
        await search(bridge, owner, seeded, course)


async def test_T11_T35_document_budget_and_inventory_continuation(bridge, owner, seeded, readable):
    course, _ = readable
    for number in range(52, 57):
        add_pdf(bridge, number)
    result = await search(bridge, owner, seeded, course, max_documents=3)
    assert len(result.data["document_statuses"]) == 3 and len(downloads(bridge)) == 3
    assert result.data["next_cursor"] and result.status == "partial_data"
    second = await search(bridge, owner, seeded, course, cursor=result.data["next_cursor"])
    assert len(downloads(bridge)) == 6 and second.data["search_pass_finished"]
    assert second.data["pass_progress"]["completed_documents"] == 6


async def test_T15_inventory_timeout_is_retry_not_empty_success(
    bridge, owner, seeded, readable, monkeypatch
):
    course, _ = readable

    async def slow(*args, **kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(document_search, "list_files", slow)
    monkeypatch.setattr(document_search, "SEARCH_SECONDS", 0.01)
    with pytest.raises(DomainError) as error:
        await search(bridge, owner, seeded, course)
    assert error.value.status == "retry_later"


async def test_T26_cached_scanned_content_reports_partial(bridge, owner, seeded, readable):
    course, ref = readable
    await read_file(bridge, owner, seeded, ref)
    with bridge.store.transaction() as session:
        row = session.get(Material, ref)
        row.file_state = {**row.file_state, "stage": "partially_parsed", "coverage": "partial"}
    result = await search_files(bridge, owner, seeded, course.id, "differentiation")
    assert result.status == "partial_data" and result.data["partially_extracted_documents"] == 1


async def test_T25_failed_documents_remain_in_pass_coverage(bridge, owner, seeded, readable):
    course, _ = readable
    add_pdf(bridge, 52)
    inventory = await course_files.list_files(bridge, owner, seeded, course.id)
    first = min(inventory.data["files"], key=lambda f: f["file_id"])
    raw = next(
        f for f in bridge.synthetic.data["files"]["11"] if str(f["id"]) == first["canvas_file_id"]
    )
    raw.update(filename="unsupported.zip", **{"content-type": "application/zip"})
    result = await search(bridge, owner, seeded, course, max_documents=1)
    assert result.data["pass_progress"]["failed_documents"] == 1
    result = await search(
        bridge, owner, seeded, course, max_documents=1, cursor=result.data["next_cursor"]
    )
    assert result.data["results"] and result.data["search_pass_finished"]
    assert result.status == "partial_data"
    assert result.data["pass_progress"]["failed_documents"] == 1
    assert result.data["pass_progress"]["completed_documents"] == 1


async def test_T25_signed_url_rotation_does_not_break_content_continuation(
    bridge, owner, seeded, readable
):
    course, _ = readable
    result = await search(bridge, owner, seeded, course, "cultures", limit=1)
    bridge.synthetic.data["files"]["11"][0]["url"] += "?verifier=rotated-private-url"
    following = await search(
        bridge, owner, seeded, course, "cultures", limit=1, cursor=result.data["next_cursor"]
    )
    assert following.data["results"][0]["page"] == 2
    assert len(downloads(bridge)) == 1 and "rotated-private-url" not in following.model_dump_json()


async def test_T13_unicode_offsets_and_literal_regex_query(bridge, owner, seeded, readable):
    course, _ = readable
    body = ("ß" * 200 + "TARGET[0] methods").encode()
    bridge.synthetic.data["file_bodies"]["51"] = body
    bridge.synthetic.data["file_types"] = {"51": "text/plain"}
    bridge.synthetic.data["files"]["11"][0].update(
        size=len(body), filename="methods.txt", **{"content-type": "text/plain"}
    )
    result = await search(bridge, owner, seeded, course, "target[0]")
    assert result.data["results"][0]["page_offset"] == 40
    assert "TARGET[0] methods" in result.data["results"][0]["passage"]


@pytest.mark.contract
async def test_T12_T25_T36_native_http_search_reads_unread_pdf(
    running, bridge, owner, seeded, readable, token_factory
):
    course, _ = readable
    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token_factory(scope='academic:read')}"}
    ) as http:
        async with streamable_http_client(running + "/mcp", http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                result = await session.call_tool(
                    "search_course_files",
                    {
                        "connection_id": seeded,
                        "course_id": course.id,
                        "query": "differentiation",
                        "include_unread": True,
                    },
                )
                assert not result.isError and result.structuredContent["data"]["results"]
                assert result.structuredContent["data"]["unread_documents_searched"]
                assert result.structuredContent["evidence"]
