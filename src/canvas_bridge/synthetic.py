"""Fictional provider, including failures, used by local demo and tests only."""

from datetime import timedelta
from urllib.parse import parse_qs

import httpx

from canvas_bridge.domain import utcnow


def dataset() -> dict:
    now = utcnow().replace(second=0, microsecond=0)

    def iso(days):
        return (now + timedelta(days=days)).isoformat()

    return {
        "user": {"id": 101},
        "courses": [
            {
                "id": 11,
                "name": "Synthetic Cell Biology",
                "enrollments": [{"type": "student", "enrollment_state": "active", "user_id": 101}],
            },
            {
                "id": 12,
                "name": "Synthetic Research Methods",
                "enrollments": [{"type": "student", "enrollment_state": "active", "user_id": 101}],
            },
        ],
        "assignments": {
            "11": [
                {
                    "id": 1,
                    "name": "Membrane transport analysis",
                    "due_at": iso(1),
                    "unlock_at": None,
                    "lock_at": iso(3),
                    "locked_for_user": False,
                    "published": True,
                    "points_possible": 40,
                    "submission_types": ["online_upload"],
                    "description": "<h2>Analysis</h2><p>Compare active and passive transport. Explain the evidence.</p>",
                    "submission": {
                        "user_id": 101,
                        "workflow_state": "unsubmitted",
                        "missing": False,
                    },
                },
                {
                    "id": 2,
                    "name": "Laboratory notebook review",
                    "due_at": None,
                    "unlock_at": None,
                    "lock_at": None,
                    "locked_for_user": False,
                    "submission_types": ["on_paper"],
                    "points_possible": 10,
                    "description": "<p>Bring your notebook to the next laboratory meeting.</p>",
                },
                {
                    "id": 3,
                    "name": "Microscopy reflection",
                    "due_at": iso(-1),
                    "unlock_at": None,
                    "lock_at": iso(2),
                    "locked_for_user": False,
                    "submission_types": ["online_text_entry"],
                    "points_possible": 20,
                    "submission": {
                        "user_id": 101,
                        "workflow_state": "submitted",
                        "submitted_at": iso(-2),
                        "late": False,
                        "attempt": 1,
                    },
                },
            ],
            "12": [
                {
                    "id": 1,
                    "name": "Study design proposal",
                    "due_at": iso(2),
                    "unlock_at": None,
                    "lock_at": iso(2),
                    "locked_for_user": False,
                    "submission_types": ["online_upload"],
                    "points_possible": 100,
                    "description": "<p>State a testable question, controls and limitations.</p>",
                    "submission": {"user_id": 101, "workflow_state": "unsubmitted"},
                },
                {
                    "id": 4,
                    "name": "Recoverable literature notes",
                    "due_at": iso(-1),
                    "unlock_at": None,
                    "lock_at": iso(1),
                    "locked_for_user": False,
                    "submission_types": ["online_upload"],
                    "points_possible": 15,
                    "submission": {
                        "user_id": 101,
                        "workflow_state": "unsubmitted",
                        "missing": True,
                    },
                },
            ],
        },
        "enrollments": [
            {
                "course_id": 11,
                "user_id": 101,
                "type": "StudentEnrollment",
                "grades": {"current_score": 80, "final_score": 64, "current_grade": "B-"},
            },
            {
                "course_id": 12,
                "user_id": 101,
                "type": "StudentEnrollment",
                "grades": {"current_score": None, "final_score": None},
            },
        ],
    }


class SyntheticProvider:
    def __init__(self, data: dict | None = None):
        self.data = data if data is not None else dataset()
        self.failures: dict[str, int] = {}
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.method != "GET":
            return httpx.Response(405)
        if path in self.failures:
            return httpx.Response(self.failures[path])
        if path == "/api/v1/users/self/profile":
            return httpx.Response(200, json=self.data["user"])
        if path == "/api/v1/courses":
            return httpx.Response(200, json=self.data["courses"])
        if path == "/api/v1/users/self/enrollments":
            return httpx.Response(200, json=self.data["enrollments"])
        parts = path.split("/")
        if len(parts) >= 6 and parts[3] == "courses":
            course = parts[4]
            if parts[5] == "assignments":
                items = self.data["assignments"].get(course, [])
                if len(parts) == 7:
                    item = next((a for a in items if str(a["id"]) == parts[6]), None)
                    return httpx.Response(200, json=item) if item else httpx.Response(404)
                query = parse_qs(request.url.query.decode())
                page = int(query.get("page", ["1"])[0])
                size = 2
                subset = items[(page - 1) * size : page * size]
                headers = {}
                if page * size < len(items):
                    nxt = request.url.copy_set_param("page", str(page + 1))
                    headers["Link"] = f'<{nxt}>; rel="next"'
                return httpx.Response(200, json=subset, headers=headers)
            if parts[5] == "modules":
                if len(parts) == 6:
                    return httpx.Response(
                        200,
                        json=[
                            {
                                "id": 21,
                                "name": "Foundations",
                                "position": 1,
                                "items_count": 1,
                                "state": "unlocked",
                                "prerequisite_module_ids": [],
                            }
                        ],
                    )
                if len(parts) == 8 and parts[7] == "items":
                    return httpx.Response(
                        200,
                        json=[
                            {
                                "id": 31,
                                "title": "Course syllabus",
                                "position": 1,
                                "type": "Page",
                                "page_url": "syllabus",
                            }
                        ],
                    )
            if parts[5] == "pages":
                if len(parts) == 6:
                    return httpx.Response(
                        200,
                        json=[
                            {
                                "page_id": 41,
                                "title": "Course syllabus",
                                "url": "syllabus",
                                "published": True,
                                "locked_for_user": False,
                            }
                        ],
                    )
                return httpx.Response(
                    200,
                    json={
                        "page_id": 41,
                        "title": "Course syllabus",
                        "published": True,
                        "locked_for_user": False,
                        "body": "<h1>Synthetic syllabus</h1><p>Bring a notebook. "
                        "Discuss research methods and limitations in class.</p>",
                    },
                )
        return httpx.Response(404)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handle), follow_redirects=False)
