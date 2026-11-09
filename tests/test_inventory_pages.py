"""Synthetic pagination at the ordinary Canvas HTTP/authorization boundary."""

import httpx
import pytest

from canvas_bridge.canvas import CanvasClient, inventory_page_identity
from canvas_bridge.domain import DomainError
from canvas_bridge.policy import Endpoint, Institution


def institution():
    return Institution(
        id="paged",
        name="Fictional",
        origin="https://canvas.fixture.invalid",
        status="personal_testing",
    )


@pytest.mark.parametrize("context", [11, 12])
async def test_folder_file_route_requires_fresh_matching_course(settings, context):
    requests = []

    def handle(request):
        requests.append(request.url.path)
        if request.url.path == "/api/v1/courses/11/folders/3":
            return httpx.Response(
                200, json={"id": 3, "context_type": "Course", "context_id": context}
            )
        return httpx.Response(200, json=[{"id": 51, "folder_id": 3}])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        client = CanvasClient(institution(), "synthetic-only", settings, http)
        with pytest.raises(DomainError):
            client.check_request("GET", client.url(Endpoint.FOLDER_FILES, folder="3"))
        if context == 11:
            rows, cursor, _ = await client.folder_files_page("11", "3")
            assert rows[0]["id"] == 51 and cursor is None
            assert len(requests) == 2
        else:
            with pytest.raises(DomainError) as error:
                await client.folder_files_page("11", "3")
            assert error.value.reason_code == "RESOURCE_PERMISSION_DENIED"
            assert len(requests) == 1
        with pytest.raises(DomainError):
            client.check_request("GET", client.url(Endpoint.FOLDER_FILES, folder="3"))
        await client.close()


async def test_inventory_pages_continue_beyond_collection_budget_without_expansions(settings):
    settings.max_pages = 1
    requests, authorizations = [], []

    def handle(request):
        requests.append(request)
        page = int(request.url.params.get("page", "1"))
        headers = (
            {
                "Link": f'<https://canvas.fixture.invalid/api/v1/courses/11/assignments?per_page=100&page={page + 1}>; rel="next"'
            }
            if page < 23
            else {}
        )
        return httpx.Response(
            200,
            json=[{"id": page, "description": "Fictional", "secret": "never retain"}],
            headers=headers,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        client = CanvasClient(institution(), "synthetic-only", settings, http)
        client.authorize = lambda endpoint, ids, resource=None: authorizations.append(
            (endpoint, ids)
        )
        cursor, seen, identifiers = None, set(), []
        for _ in range(23):
            rows, cursor, page_id = await client.inventory_page(
                Endpoint.ASSIGNMENTS, cursor=cursor, course="11"
            )
            assert page_id not in seen
            seen.add(page_id)
            identifiers.extend(row["id"] for row in rows)
            assert all("secret" not in row for row in rows)
        assert cursor is None and identifiers == list(range(1, 24))
        assert len(authorizations) >= 46
        assert all("include[]" not in request.url.params for request in requests)
        await client.close()


@pytest.mark.parametrize(
    "next_link,reason",
    [
        ("https://canvas.fixture.invalid/api/v1/courses/12/files?per_page=100&page=2", None),
        ("https://other.fixture.invalid/api/v1/courses/11/files?per_page=100&page=2", None),
        (
            "https://canvas.fixture.invalid/api/v1/courses/11/files?per_page=100&page=2&include[]=submission",
            None,
        ),
        (
            "https://canvas.fixture.invalid/api/v1/courses/11/files?page=01&per_page=100",
            "INVENTORY_PAGINATION_CYCLE",
        ),
    ],
)
async def test_inventory_next_page_cannot_change_route_query_or_repeat(settings, next_link, reason):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=[], headers={"Link": f'<{next_link}>; rel="next"'})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        client = CanvasClient(institution(), "synthetic-only", settings, http)
        with pytest.raises(DomainError) as error:
            await client.inventory_page(Endpoint.FILES, course="11")
        assert len(requests) == 1
        if reason:
            assert error.value.reason_code == reason
        else:
            assert error.value.status == "permission_denied"
        await client.close()


def test_inventory_page_identity_normalizes_default_and_reordered_queries():
    base = "https://canvas.fixture.invalid/api/v1/courses/11/files"
    assert inventory_page_identity(base) == inventory_page_identity(base + "?page=01&per_page=100")
    assert inventory_page_identity(base + "?page=2") != inventory_page_identity(base)


async def test_inventory_page_reauthorizes_before_releasing_rows(settings):
    calls = 0

    def authorize(*args):
        nonlocal calls
        calls += 1
        if calls >= 3:
            raise DomainError(
                "permission_denied", "Selection revoked.", reason_code="COURSE_NOT_SELECTED"
            )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[{"id": 1}]))
    ) as http:
        client = CanvasClient(institution(), "synthetic-only", settings, http)
        client.authorize = authorize
        with pytest.raises(DomainError) as error:
            await client.inventory_page(Endpoint.FILES, course="11")
        assert error.value.reason_code == "COURSE_NOT_SELECTED"
        await client.close()


async def test_mixed_relation_and_opaque_page_token_preserve_inventory(settings):
    def handle(request):
        if "page" in request.url.params:
            assert request.url.params["page"] == "bookmark:fixture-2"
            return httpx.Response(200, json=[{"id": 2}])
        target = request.url.copy_set_param("page", "bookmark:fixture-2")
        return httpx.Response(
            200, json=[{"id": 1}], headers={"Link": f'<{target}>; rel="last NeXt"'}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        client = CanvasClient(institution(), "synthetic-only", settings, http)
        try:
            first, cursor, first_id = await client.inventory_page(Endpoint.FILES, course="11")
            assert cursor
            second, cursor, second_id = await client.inventory_page(
                Endpoint.FILES, course="11", cursor=cursor
            )
            assert [row["id"] for row in first + second] == [1, 2]
            assert cursor is None and first_id != second_id
        finally:
            await client.close()
