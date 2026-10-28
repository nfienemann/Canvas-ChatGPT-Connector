"""Approved Canvas adapter, reusing the existing identity/policy/egress foundation."""

from datetime import timedelta

from canvas_bridge.academic.gateway import AcademicRequest, denied
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
from canvas_bridge.authorization import request_authorization
from canvas_bridge.domain import DomainError, Result, utcnow
from canvas_bridge.egress_models import ContentClassification as CC
from canvas_bridge.providers.base import AcademicProvider


class AuthorizedCanvasProvider(AcademicProvider):
    provider_id = "authorized-canvas"
    api_version = "1.0.0"
    supported = frozenset({"get_grade_summary"})
    capability_fields = {
        "get_grade_summary": ("courses", "categories", "assessments", "grading_rules")
    }
    permission_requirements = (
        "provider_approval",
        "institution_approval",
        "authenticated_user",
        "selected_course",
        "grade_scope",
        "recipient_egress",
    )
    freshness = "upstream_scope_verified"
    downstream_model_sharing = "per_request_authorization"

    def __init__(self, bridge, owner, connection, *, clock=utcnow):
        self.bridge, self.owner, self.connection = bridge, owner, connection
        self._records = {}
        self._epoch = None
        self._egress_evidence = None
        self._classifications = frozenset()
        super().__init__(clock=clock)

    def request(self, course):
        with self.bridge.store.transaction() as session:
            conn = self.bridge.store.connection(session, self.owner, self.connection)
            tenant = conn.institution
        context = request_authorization.get()
        return AcademicRequest(
            self.owner,
            tenant,
            self.connection,
            course,
            recipient=context.recipient if context else "local",
        )

    def require(self, request, *, phase):
        if (
            request.principal != self.owner
            or request.connection != self.connection
            or not request.resource
            or request.purpose != "grade_planning"
        ):
            denied()
        self.bridge.connection_policy(
            self.owner, self.connection, {"grades", "assignments"}, resource=request.resource
        )
        with self.bridge.store.transaction() as session:
            conn = self.bridge.store.connection(session, self.owner, self.connection)
            if conn.institution != request.tenant or (
                self._epoch is not None and conn.epoch != self._epoch
            ):
                denied()
        if phase != "retrieve":
            self.bridge.selected(
                self.owner,
                self.connection,
                [request.resource],
                resource_type="grades",
                operation="read",
            )
            if (
                self._egress_evidence is not None
                and not self.current_classifications(request) <= self._classifications
            ):
                denied()
        if request.recipient != "local":
            context = request_authorization.get()
            if (
                not context
                or context.recipient != request.recipient
                or context.egress_principal != self.owner
            ):
                denied()
            if self._egress_evidence is not None and phase != "retrieve":
                # Same engine used by final MCP serialization; no recipient-specific
                # policy is invented by the adapter or normalized metadata.
                self.bridge.egress.release(
                    self._egress_evidence,
                    self.owner,
                    {"connection_id": self.connection, "course_id": request.resource},
                    tool_name="calculate_course_grade",
                )

    def verify_record(self, record, request):
        if self._records.get(record.id) != record:
            denied()

    def current_classifications(self, request):
        from canvas_bridge.egress_policy import classify
        from canvas_bridge.egress_sources import resolve_sources

        sources, _ = resolve_sources(
            self.bridge.egress,
            self.owner,
            {"connection_id": self.connection, "course_id": request.resource},
            self._egress_evidence,
            "calculate_course_grade",
        )
        return frozenset(classify(source) for source in sources) or frozenset(
            {CC.UNKNOWN_OR_UNCLASSIFIED}
        )

    async def retrieve(self, operation, request):
        self.require(request, phase="retrieve")
        if operation != "get_grade_summary":
            raise DomainError(
                "unsupported_feature", "This adapter currently supports grading evidence only."
            )
        from canvas_bridge.providers.canvas_grades import collect

        evidence = await collect(self.bridge, self.owner, self.connection, request.resource)
        return self.normalize(evidence, evidence["policy"], request)

    def normalize(self, evidence, policy, request):
        self.require(request, phase="retrieve")
        course, conn = evidence["course"], evidence["connection"]
        if (
            course.id != request.resource
            or conn.id != self.connection
            or conn.owner != self.owner
            or conn.institution != request.tenant
        ):
            denied()
        self._epoch = conn.epoch
        now = self.gateway.clock()
        source = evidence["sources"][0]
        context = request_authorization.get()
        permission = PermissionContext(
            principal=self.owner,
            tenant=conn.institution,
            connection=conn.id,
            scope={"grade_planning"},
            decision_reference=context.request_id if context else "trusted-local-call",
            expires_at=now + timedelta(seconds=30),
        )
        classes = {CC.FIRST_PARTY_EDUCATIONAL_RECORD}
        self._egress_evidence = Result(
            summary="Authorized grading evidence for local calculation.",
            data={
                "course_id": course.id,
                "assessment_evidence": [a.model_dump(mode="json") for a in evidence["assessments"]],
            },
            sources=evidence["sources"],
        )
        classes.update(self.current_classifications(request))
        if policy.basis == "syllabus":
            classes.add(CC.INSTRUCTOR_OWNED_COURSE_CONTENT)
        self._classifications = frozenset(classes)
        restrictions = Restrictions(
            classifications=classes,
            purposes={"grade_planning"},
            recipients={request.recipient},
            copyright="unknown",
        )
        derived = tuple(
            SourceReference(
                provider=self.provider_id,
                id=s.id,
                version=s.content_hash or "not-returned",
                uri=s.url or None,
            )
            for s in evidence["sources"]
        )

        def fields(
            ref, version, uri=None, *, complete=True, source_type="normalized_canvas_grading_policy"
        ):
            verified = complete and evidence["complete"] and not policy.blockers and bool(version)
            return dict(
                id=ref,
                permission=permission,
                restrictions=restrictions,
                provenance=Provenance(
                    source_type=source_type,
                    source=SourceReference(
                        provider=self.provider_id,
                        id=ref,
                        version=version or "not-returned",
                        uri=uri,
                    ),
                    observed_at=now,
                    verified_at=source.retrieved_at if verified else None,
                    basis="source_fact",
                    complete=verified,
                    derived_from=derived,
                    uncertainty=()
                    if verified
                    else ("Some source evidence is incomplete or unverified.",),
                ),
            )

        normalized_course = Course(
            **fields(course.id, policy.version, source.url), title=course.name
        )
        groups = tuple(
            GradeCategory(
                **fields(g.id, policy.version),
                course_id=course.id,
                title=g.name,
                weight=g.weight,
                drop_lowest=g.drop_lowest,
                drop_highest=g.drop_highest,
                never_drop=tuple(g.never_drop),
            )
            for g in policy.groups
        )
        assessments = tuple(
            Assessment(
                **fields(
                    a.id,
                    a.source_version,
                    a.source_url or None,
                    complete=a.score_state not in {"unavailable", "conflicting"},
                    source_type="canvas_assignment",
                ),
                course_id=course.id,
                title=a.title,
                category_id=a.group_id,
                possible=a.possible,
                result=GradeResult(
                    score=a.score if a.score_state == "posted" else None, state=a.score_state
                ),
                excluded_reason=a.excluded_reason,
                eligibility_verified=a.eligibility_verified,
                submission_state=a.submission_state,
                missing=a.missing,
                late=a.late,
            )
            for a in evidence["assessments"]
        )
        # Missing category references stay explicit incomplete evidence, not invented groups.
        group_ids = {g.id for g in groups}
        missing = any(a.category_id and a.category_id not in group_ids for a in assessments)
        if missing:
            assessments = tuple(
                a.model_copy(update={"category_id": None}) if a.category_id not in group_ids else a
                for a in assessments
            )
        rules = GradingRules(
            method=policy.method,
            basis=policy.basis,
            empty_categories=policy.empty_categories,
            blockers=tuple(policy.blockers)
            + (("An assessment category is missing.",) if missing else ()),
            rule_ids=tuple(policy.rule_ids),
            version=policy.version,
        )
        dataset = AcademicDataset(
            provider=self.provider_id,
            courses=(normalized_course,),
            categories=groups,
            assessments=assessments,
            grading_rules=rules,
            complete=evidence["complete"] and not missing,
            limitations=tuple(evidence["canvas_evidence"]["limitations"]),
        )
        self._records = {r.id: r for r in dataset.records()}
        return dataset

    def calculation_input(self, evidence, policy):
        request = self.request(evidence["course"].id)
        dataset = self.normalize(evidence, policy, request)
        return self.gateway._issue(dataset, request, "get_grade_summary")
