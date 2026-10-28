"""Closed fictional dataset, independent of Canvas transports, tokens and accounts."""

from datetime import timedelta
from decimal import Decimal

from canvas_bridge.academic.gateway import denied
from canvas_bridge.academic.models import (
    AcademicDataset,
    Assessment,
    Assignment,
    Course,
    Deadline,
    GradeCategory,
    GradeResult,
    GradingRules,
    PermissionContext,
    Provenance,
    Restrictions,
    SourceReference,
)
from canvas_bridge.domain import DomainError, utcnow
from canvas_bridge.egress_models import ContentClassification as CC
from canvas_bridge.providers.base import AcademicProvider


class SyntheticProvider(AcademicProvider):
    provider_id = "fictional-academics"
    api_version = "1.0.0"
    supported = frozenset({"list_courses", "get_assignments", "get_grade_summary"})
    capability_fields = {
        "list_courses": ("courses",),
        "get_assignments": ("courses", "assignments", "assignments.deadline"),
        "get_grade_summary": ("courses", "categories", "assessments", "grading_rules"),
    }
    permission_requirements = ("fictional_fixture_scope", "recipient_and_purpose")
    freshness = "fictional_at_request"
    downstream_model_sharing = "per_request_authorization"

    def __init__(self, *, principal="synthetic-student", clock=utcnow):
        self.principal = principal
        self._records = {}
        super().__init__(clock=clock)

    def require(self, request, *, phase):
        if (
            (request.principal, request.tenant, request.connection)
            != (self.principal, "fictional", "demo")
            or request.resource not in {None, "course-fictional"}
            or request.recipient not in {"local", "chatgpt"}
            or request.purpose not in {"grade_planning", "study", "metadata"}
        ):
            denied()

    def verify_record(self, record, request):
        if self._records.get(record.id) != record:
            denied()

    async def retrieve(self, operation, request):
        self.require(request, phase="retrieve")
        if operation not in self.supported:
            raise DomainError(
                "unsupported_feature", "This fictional source does not implement that capability."
            )
        now = self.gateway.clock()
        permission = PermissionContext(
            principal=self.principal,
            tenant="fictional",
            connection="demo",
            scope={"grade_planning", "study", "metadata"},
            decision_reference="fictional-fixture-v1",
            expires_at=now + timedelta(hours=1),
        )
        restrictions = Restrictions(
            classifications={CC.PUBLIC_OR_APPROVED},
            purposes=permission.scope,
            recipients={"local", "chatgpt"},
            copyright="fictional",
        )

        def context(ref):
            return dict(
                id=ref,
                permission=permission,
                restrictions=restrictions,
                provenance=Provenance(
                    source_type="synthetic_fixture",
                    source=SourceReference(provider=self.provider_id, id=ref, version="fixture-1"),
                    observed_at=now,
                    fresh_until=now + timedelta(hours=1),
                    basis="synthetic",
                    complete=True,
                ),
            )

        course = Course(**context("course-fictional"), title="Fictional Academic Methods")
        category = GradeCategory(
            **context("category-fictional"), course_id=course.id, title="Practice"
        )
        assessments = tuple(
            Assessment(
                **context(f"assessment-{i}"),
                course_id=course.id,
                title=f"Fictional exercise {i}",
                category_id=category.id,
                possible=Decimal(100),
                result=GradeResult(score=Decimal(score), state="posted"),
                eligibility_verified=True,
            )
            for i, score in enumerate((80, 90), 1)
        )
        assignment = Assignment(
            **context("assignment-fictional"),
            course_id=course.id,
            title="Fictional practice report",
            deadline=Deadline(kind="timestamp", timestamp=now + timedelta(days=2)),
        )
        data = AcademicDataset(
            provider=self.provider_id,
            courses=(course,),
            assignments=(assignment,) if operation == "get_assignments" else (),
            categories=(category,) if operation == "get_grade_summary" else (),
            assessments=assessments if operation == "get_grade_summary" else (),
            grading_rules=GradingRules(method="points", version="fictional-points-v1")
            if operation == "get_grade_summary"
            else None,
            complete=True,
            limitations=(
                "Entirely fictional demonstration; no institution-controlled records were consulted.",
            ),
        )
        self._records = {r.id: r for r in data.records()}
        return data
