import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from tests.test_file_reading import readable as readable
from tests.test_mcp_contract import running as running


@pytest.mark.contract
async def test_T11_T12_actual_mcp_file_tools_return_pdf_content(
    running, token_factory, seeded, readable
):
    course, ref = readable
    async with httpx.AsyncClient(
        headers={"Authorization": "Bearer " + token_factory(scope="academic:read")}
    ) as http:
        async with streamable_http_client(running + "/mcp", http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                catalog = await session.list_tools()
                assert {
                    "list_course_files",
                    "read_course_file",
                    "search_course_files",
                    "get_file_extraction_status",
                } <= {t.name for t in catalog.tools}
                listing = await session.call_tool(
                    "list_course_files", {"connection_id": seeded, "course_id": course.id}
                )
                assert listing.structuredContent["data"]["files"][0]["file_id"] == ref
                result = await session.call_tool(
                    "read_course_file", {"connection_id": seeded, "file_id": ref, "page_start": 2}
                )
                assert not result.isError and "Methods:" in result.structuredContent["data"]["text"]
                assert result.structuredContent["data"]["passages"][0]["page"] == 2
                old = await session.call_tool(
                    "fetch_course_material", {"connection_id": seeded, "material_id": ref}
                )
                assert "Conclusions:" in old.structuredContent["data"]["text"]
                state = await session.call_tool(
                    "get_file_extraction_status", {"connection_id": seeded, "file_id": ref}
                )
                assert state.structuredContent["data"]["state"] == "parsed"
                found = await session.call_tool(
                    "search_course_files",
                    {"connection_id": seeded, "course_id": course.id, "query": "replication"},
                )
                assert found.structuredContent["data"]["results"][0]["page"] == 3
