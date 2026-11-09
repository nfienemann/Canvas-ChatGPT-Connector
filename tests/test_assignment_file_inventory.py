"""Synthetic assignment-only discovery through the ordinary file-list service."""

import pytest

from canvas_bridge.course_files import list_files
from canvas_bridge.egress_sources import minimize
from canvas_bridge.normalize import canonical_id
from tests.test_course_files import file_record


def test_flat_folder_graph_includes_ancestors_and_detects_cycles():
    from canvas_bridge.inventory_folders import folder_paths

    def folder(identity, parent=None, course=11):
        return {
            "id": identity,
            "parent_folder_id": parent,
            "context_type": "Course",
            "context_id": course,
        }

    paths, error = folder_paths([folder(1), folder(2, 1), folder(3, 2)], "11")
    assert paths["3"] == ["1", "2", "3"] and error is None
    assert folder_paths([folder(1, 2), folder(2, 1)], "11")[1] == "INVENTORY_FOLDER_CYCLE"
    assert folder_paths([folder(1, 2)], "11")[1] == "INVENTORY_FOLDER_PARENT_MISSING"
    assert folder_paths([folder(1, course=12)], "11")[1] == "INVENTORY_FOLDER_CONTEXT_MISMATCH"


async def test_folder_paths_survive_minimization_and_denial_stays_incomplete(bridge, owner, seeded):
    _, courses = bridge.selected(owner, seeded)
    bridge.synthetic.data["files"] = {"11": [file_record(folder_id=2)]}
    bridge.synthetic.data["folders"] = {
        "11": [
            {"id": 1, "context_type": "Course", "context_id": 11},
            {"id": 2, "parent_folder_id": 1, "context_type": "Course", "context_id": 11},
        ]
    }
    result = await list_files(bridge, owner, seeded, courses[0].id)
    clean, _ = minimize(result, "list_course_files", live=True)
    from canvas_bridge.privacy.output import filter_output

    projected, *_ = filter_output(clean.model_dump(mode="json"))
    assert projected["data"]["coverage"]["folders"] == "complete"
    assert len(projected["data"]["files"][0]["folders"]) == 2
    assert clean.data["coverage"]["folders"] == "complete"
    assert clean.data["files"][0]["folders"] == [
        canonical_id(owner, seeded, "folder", f"11:{i}") for i in (1, 2)
    ]
    bridge.synthetic.failures["/api/v1/courses/11/folders"] = 403
    result = await list_files(bridge, owner, seeded, courses[0].id)
    assert result.data["coverage"]["folders"] == "partial"
    assert (
        result.data["inventory_reason_codes"]["folders"]["reason_code"]
        == "RESOURCE_PERMISSION_DENIED"
    )


async def test_assignment_only_file_is_resolved_and_provenance_survives_egress(
    bridge, owner, seeded
):
    _, courses = bridge.selected(owner, seeded)
    course = courses[0]
    bridge.synthetic.data["files"] = {"11": [file_record()]}
    bridge.synthetic.failures["/api/v1/courses/11/files"] = 403
    bridge.synthetic.data["assignments"]["11"] = [
        {
            "id": 71,
            "course_id": 11,
            "name": "Fictional assignment",
            "description": '<a href="/courses/11/files/51?verifier=DO_NOT_LOG">Handout</a>'
            '<a href="/courses/11/files/51">Duplicate</a>'
            '<a href="/courses/12/files/52">Different course</a>',
        }
    ]
    result = await list_files(bridge, owner, seeded, course.id)
    assert result.data["coverage"]["files"] == "partial"
    assert result.data["coverage"]["assignments"] == "complete"
    assert len(result.data["files"]) == 1
    file = result.data["files"][0]
    assert file["canvas_file_id"] == "51"
    assert file["assignments"] == [canonical_id(owner, seeded, "assignment", "11:71")]
    clean, _ = minimize(result, "list_course_files", live=True)
    assert clean.data["files"][0]["assignments"] == file["assignments"]
    assert "DO_NOT_LOG" not in clean.model_dump_json()
    assert not any(
        "/files/52" in r.url.path or "/download" in r.url.path for r in bridge.synthetic.requests
    )


@pytest.mark.parametrize("case", ["denied_listing", "truncated_anchors", "denied_file"])
async def test_assignment_discovery_failures_are_never_empty_complete(bridge, owner, seeded, case):
    _, courses = bridge.selected(owner, seeded)
    bridge.synthetic.data["files"] = {"11": [file_record()]}
    bridge.synthetic.data["assignments"]["11"] = [
        {
            "id": 71,
            "course_id": 11,
            "description": '<a href="/courses/11/files/51">Handout</a>'
            * (21 if case == "truncated_anchors" else 1),
        }
    ]
    if case == "denied_listing":
        bridge.synthetic.failures["/api/v1/courses/11/assignments"] = 403
    if case == "denied_file":
        bridge.synthetic.failures["/api/v1/courses/11/files"] = 403
        bridge.synthetic.failures["/api/v1/courses/11/files/51"] = 403
    result = await list_files(bridge, owner, seeded, courses[0].id)
    assert result.status == "partial_data"
    assert result.data["coverage"]["assignments"] == "partial"
    assert (
        result.data["inventory_reason_codes"]["assignments"]["reason_code"]
        == {
            "denied_listing": "RESOURCE_PERMISSION_DENIED",
            "truncated_anchors": "INVENTORY_ASSIGNMENT_LINK_LIMIT",
            "denied_file": "INVENTORY_ASSIGNMENT_FILE_UNRESOLVED",
        }[case]
    )
    if case == "denied_file":
        assert not result.data["files"]
    cleaned, _ = minimize(result, "list_course_files", live=True)
    assert (
        cleaned.data["inventory_reason_codes"]["assignments"]["reason_code"]
        == result.data["inventory_reason_codes"]["assignments"]["reason_code"]
    )
