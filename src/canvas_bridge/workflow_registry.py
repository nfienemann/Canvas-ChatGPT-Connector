"""Reviewed, declarative read-only workflows. Source documents cannot edit this registry."""

from dataclasses import asdict, dataclass
from datetime import timedelta
from types import MappingProxyType
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, Field, model_validator

from canvas_bridge.calendar_sync import CalendarContext
from canvas_bridge.domain import Model
from canvas_bridge.evidence import fingerprint
from canvas_bridge.figure_observations import FigureObservation
from canvas_bridge.grading_engine import GradeScenario
from canvas_bridge.planning import PlanRequest

WorkflowName = Literal[
    "daily_academic_brief",
    "weekly_course_priorities",
    "exam_preparation_pack",
    "grade_outlook",
    "course_discrepancy_review",
    "lecture_comprehension",
    "calendar_preparation",
]
Ref = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")]


class VisualReport(Model):
    file_id: Ref
    render_receipt: str = Field(min_length=1, max_length=16000)
    observation: FigureObservation


class WorkflowRequest(Model):
    workflow: WorkflowName
    course_ids: list[Ref] | None = Field(default=None, max_length=5)
    timezone: str = Field(default="UTC", max_length=100)
    start: AwareDatetime | None = None
    end: AwareDatetime | None = None
    since: AwareDatetime | None = None
    assessment_id: Ref | None = None
    material_ids: list[Ref] = Field(default_factory=list, max_length=3)
    plan: PlanRequest | None = None
    calendar: CalendarContext | None = None
    scenario: GradeScenario | None = None
    scenario_mode: Literal["projected_final", "required_score"] = "projected_final"
    visual_reports: list[VisualReport] = Field(default_factory=list, max_length=2)

    @model_validator(mode="after")
    def bounded(self):
        try:
            ZoneInfo(self.timezone)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("Use a valid IANA timezone.") from exc
        if len(self.model_dump_json().encode()) > 64_000:
            raise ValueError("Workflow inputs exceed 64 KB; narrow the request.")
        if bool(self.start) != bool(self.end) or (
            self.start and not timedelta(0) < self.end - self.start <= timedelta(days=31)
        ):
            raise ValueError("Use both aware window bounds, at most 31 days apart.")
        if self.course_ids == []:
            raise ValueError("Choose a course or omit course_ids to use current selection.")
        if self.course_ids:
            self.course_ids = list(dict.fromkeys(self.course_ids))
        self.material_ids = list(dict.fromkeys(self.material_ids))
        if self.visual_reports and self.workflow != "lecture_comprehension":
            raise ValueError("Visual reports belong only to Lecture Comprehension.")
        return self


@dataclass(frozen=True)
class Limits:
    max_steps: int = 24
    http_calls: int = 120
    api_bytes: int = 4_000_000
    document_bytes: int = 30_000_000
    files: int = 3
    total_seconds: float = 90
    step_seconds: float = 30
    output_bytes: int = 40_000
    output_token_upper_bound: int = 40_000
    parallelism: int = 1


@dataclass(frozen=True)
class Step:
    name: str
    operation: str
    dependencies: tuple[str, ...] = ()
    optional: bool = False


@dataclass(frozen=True)
class Workflow:
    name: str
    title: str
    steps: tuple[Step, ...]
    required_capabilities: tuple[str, ...]
    optional_capabilities: tuple[str, ...] = ()
    per_course: bool = False
    max_courses: int = 5
    purpose: str = "study"
    limits: Limits = Limits()
    version: str = "academic-workflows-1"
    authorization: str = (
        "existing_tool_policy_and_course_resource_gateway_before_and_after_each_step"
    )
    output_schema: str = "academic-workflow-result-1"
    partial_behavior: str = "retain_independently_valid_results; withhold_on_authorization_change"
    consequential_actions: str = "none; existing_calendar_preview_approval_commit_flow_only"

    def public(self):
        return asdict(self)

    @property
    def digest(self):
        return fingerprint(self.public())


WORKFLOWS = MappingProxyType(
    {
        "daily_academic_brief": Workflow(
            "daily_academic_brief",
            "Daily Academic Brief",
            (
                Step("obligations", "workload"),
                Step("changes", "changes", ("obligations",), True),
                Step("availability", "calendar", optional=True),
                Step("priorities", "priorities", ("obligations",)),
            ),
            ("workload",),
            ("changes", "calendar"),
        ),
        "weekly_course_priorities": Workflow(
            "weekly_course_priorities",
            "Weekly Course Priorities",
            (
                Step("obligations", "workload"),
                Step("availability", "calendar", optional=True),
                Step("priorities", "priorities", ("obligations",)),
            ),
            ("workload",),
            ("calendar",),
        ),
        "exam_preparation_pack": Workflow(
            "exam_preparation_pack",
            "Exam Preparation Pack",
            (
                Step("assessment", "exam"),
                Step("availability", "calendar", optional=True),
                Step("study_outline", "exam_outline", ("assessment",)),
            ),
            ("exam",),
            ("calendar",),
            True,
            1,
        ),
        "grade_outlook": Workflow(
            "grade_outlook",
            "Grade Outlook",
            (
                Step("grade_evidence", "grade_evidence"),
                Step("current_grade", "current_grade", ("grade_evidence",)),
                Step("scenario", "scenario", ("grade_evidence",), True),
            ),
            ("grade_evidence",),
            ("scenario",),
            True,
            3,
            "grade_planning",
        ),
        "course_discrepancy_review": Workflow(
            "course_discrepancy_review",
            "Course Discrepancy Review",
            (
                Step("course_review", "course_review"),
                Step("grading_review", "grading_review", optional=True),
            ),
            ("course_review",),
            ("grading_review",),
            True,
            1,
        ),
        "lecture_comprehension": Workflow(
            "lecture_comprehension",
            "Lecture Comprehension",
            (
                Step("materials", "materials"),
                Step("reading", "reading", ("materials",)),
                Step("interpretation", "interpretation", ("reading",)),
            ),
            ("materials", "reading"),
            ("visual_client",),
            True,
            1,
            "document_reading",
        ),
        "calendar_preparation": Workflow(
            "calendar_preparation",
            "Calendar Preparation",
            (
                Step("obligations", "workload"),
                Step("availability", "calendar", optional=True),
                Step("event_proposals", "event_proposals", ("obligations", "availability")),
            ),
            ("workload", "calendar_proposals"),
            ("calendar",),
            purpose="schedule",
        ),
    }
)


def validate_registry():
    for key, workflow in WORKFLOWS.items():
        seen = set()
        if key != workflow.name or not workflow.steps:
            raise ValueError("Invalid workflow identity")
        for step in workflow.steps:
            if step.name in seen or not set(step.dependencies) <= seen:
                raise ValueError("Workflow dependencies must be unique and topologically ordered")
            seen.add(step.name)


validate_registry()
