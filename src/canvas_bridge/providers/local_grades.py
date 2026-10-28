"""Explicit numeric imports, with the existing local ownership and revocation contract."""

from decimal import Decimal
from typing import Literal

from pydantic import Field, ValidationError, model_validator

from canvas_bridge.academic.contracts import Contract, unsupported
from canvas_bridge.academic.models import (
    AcademicDataset,
    Assessment,
    Course,
    GradeCategory,
    GradeResult,
    GradingRules,
    PermissionContext,
    Provenance,
    Restrictions,
    SourceReference,
)
from canvas_bridge.domain import utcnow
from canvas_bridge.egress_models import ContentClassification as CC
from canvas_bridge.providers.local_document import LocalDocumentProvider, require_local_import


class GradeRow(Contract):
    possible: Decimal | None = Field(
        default=None, ge=0, le=1_000_000, max_digits=16, decimal_places=6, allow_inf_nan=False
    )
    result: GradeResult

    @model_validator(mode="after")
    def bounded_score(self):
        score = self.result.score
        if score is not None and (
            score < 0
            or score > 1_000_000
            or len(score.as_tuple().digits) > 16
            or abs(score.as_tuple().exponent) > 6
        ):
            raise ValueError("Score exceeds the numeric import budget.")
        return self


class GradeImport(Contract):
    schema_version: Literal["local-grades-1"]
    complete: bool
    rows: tuple[GradeRow, ...] = Field(min_length=1, max_length=100)


class LocalGradeProvider(LocalDocumentProvider):
    provider_id = "local-grades"
    supported = frozenset({"get_grade_summary"})
    capability_fields = {
        "get_grade_summary": ("courses", "categories", "assessments", "grading_rules")
    }

    def __init__(self, data, permit, *, clock=utcnow):
        super().__init__(data, "grade-json", permit, clock=clock)

    def require(self, request, *, phase):
        require_local_import(
            self._data, self.permit, request, self.gateway.clock(), "grade_planning"
        )
        if len(self._data) > 64_000:
            unsupported("The numeric grade import exceeds its size limit.")

    async def retrieve(self, operation, request):
        self.require(request, phase="retrieve")
        if operation != "get_grade_summary":
            unsupported()
        try:
            data = GradeImport.model_validate_json(self._data)
        except (ValidationError, ValueError):
            unsupported("The numeric grade import is invalid.")
        permit = self.permit
        permission = PermissionContext(
            principal=permit.principal,
            tenant="local",
            connection="local-import",
            scope={"grade_planning"},
            decision_reference="local-user-attestation",
            expires_at=permit.expires_at,
        )
        restrictions = Restrictions(
            classifications={CC.FIRST_PARTY_EDUCATIONAL_RECORD},
            purposes={"grade_planning"},
            recipients={"local"},
            copyright="owner_attested",
        )
        now = self.gateway.clock()

        def context(ref):
            return dict(
                id=ref,
                permission=permission,
                restrictions=restrictions,
                provenance=Provenance(
                    source_type="user_provided_grade_json",
                    source=SourceReference(
                        provider=self.provider_id, id=ref, version=permit.content_sha256
                    ),
                    observed_at=now,
                    fresh_until=permit.expires_at,
                    basis="user_supplied",
                    complete=data.complete,
                    uncertainty=(
                        "User-supplied points and completeness; instructor policy and external sharing are not verified.",
                    ),
                ),
            )

        course = Course(**context(permit.source_id), title="Locally supplied points course")
        category = GradeCategory(
            **context(permit.source_id + "-group"),
            course_id=course.id,
            title="User-supplied points",
        )
        assessments = tuple(
            Assessment(
                **context(f"{permit.source_id}-row-{i}"),
                course_id=course.id,
                title=f"Imported assessment {i}",
                category_id=category.id,
                possible=row.possible,
                result=row.result,
                eligibility_verified=True,
            )
            for i, row in enumerate(data.rows, 1)
        )
        dataset = AcademicDataset(
            provider=self.provider_id,
            courses=(course,),
            categories=(category,),
            assessments=assessments,
            grading_rules=GradingRules(
                method="points", basis="student_input", version="local-points-1"
            ),
            complete=data.complete,
            limitations=(
                "Numeric import only; points-policy applicability is user attested, not institution verified.",
            ),
        )
        self._records = {r.id: r for r in dataset.records()}
        return dataset
