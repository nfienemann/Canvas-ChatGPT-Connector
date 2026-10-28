"""Projections of existing collectors/calculators; no new text or grade engine."""

import re
from itertools import combinations

from canvas_bridge.academic.evidence_graph import Builder, Scope
from canvas_bridge.academic.evidence_graph import EntityKind as E
from canvas_bridge.academic.evidence_graph import RelationKind as R
from canvas_bridge.academic.grade_engine import GradeAssessment, GradeGroup, GradePolicy
from canvas_bridge.academic.models import SourceReference
from canvas_bridge.academic_dates import compare_deadline


def dataset_builder(dataset):
    if len(dataset.courses) != 1:
        raise ValueError("An evidence snapshot must contain exactly one course.")
    course = dataset.courses[0]
    permission = course.permission
    scope = Scope(
        principal=permission.principal,
        institution=permission.tenant,
        connection=permission.connection,
        course_id=course.id,
    )
    builder = Builder(scope, complete=dataset.complete, limitations=dataset.limitations)
    course_entity = builder.entity(E.COURSE, course.id)
    parents = []
    for record in dataset.records():
        p = record.provenance
        uncertainty = list(p.uncertainty)
        if p.source.locator is None:
            uncertainty.append("The normalized input does not record an original source locator.")
        if p.source.version in {"not-returned", "not-recorded"}:
            uncertainty.append("The original source version was not recorded.")
        if p.source_type is None:
            uncertainty.append("Original source type is not recorded by this normalized adapter.")
        source = builder.observe(
            source=p.source,
            source_type=p.source_type,
            course_id=course.id,
            observed_at=p.observed_at,
            verified_at=p.verified_at,
            fresh_until=p.fresh_until,
            permission=record.permission,
            restrictions=record.restrictions,
            complete=p.complete,
            uncertainty=tuple(uncertainty),
        )
        # Preserve every declared upstream source, including syllabus amendments.
        sources = [source]
        for upstream in p.derived_from:
            if upstream == p.source:
                continue
            sources.append(
                builder.observe(
                    source=upstream,
                    source_type=None,
                    course_id=course.id,
                    observed_at=p.observed_at,
                    permission=record.permission,
                    restrictions=record.restrictions,
                    complete=False,
                    uncertainty=(
                        "Upstream reference lacks independent observation/coverage metadata.",
                    ),
                )
            )
        kind, predicate = {
            "Course": (E.COURSE, "course_metadata"),
            "Assignment": (E.ASSIGNMENT, "deadline"),
            "Assessment": (E.ASSESSMENT, "grade_input"),
            "GradeCategory": (E.GRADING_CATEGORY, "grade_rule"),
            "CourseCalendarEvent": (E.CALENDAR_EVENT, "schedule"),
            "AcademicDocument": (E.DOCUMENT, "document_metadata"),
            "DocumentPart": (E.DOCUMENT_PASSAGE, "passage"),
        }[type(record).__name__]
        entity = builder.entity(kind, record.id)
        value = record.model_dump(
            mode="json",
            exclude={"id", "provenance", "permission", "restrictions", "schema_version", "parts"},
        )
        if predicate == "deadline":
            value = value["deadline"]
        dependencies = ()
        basis = "user_provided" if p.basis == "user_supplied" else "explicit"
        if p.basis == "derived":
            # A legacy derived record supplies source references but no factual
            # derivation steps. Preserve that gap rather than relabeling it explicit.
            manifest = builder.assert_fact(
                entity,
                "upstream_reference_manifest",
                [s.model_dump(mode="json") for s in p.derived_from],
                sources=sources,
            )
            dependencies, basis = (manifest,), "inferred"
            uncertainty.append("Upstream fact-level derivation steps were not supplied.")
        fact = builder.assert_fact(
            entity,
            predicate,
            value,
            sources=sources,
            basis=basis,
            parents=dependencies,
            uncertainty=uncertainty,
        )
        parents.append(fact)
        if entity != course_entity:
            builder.link(R.BELONGS_TO, entity, course_entity, (fact,))
    if dataset.grading_rules is not None:
        # GradingRules has no independent provenance field. Describe the policy
        # used by the calculation as derived input, never as a verified instructor rule.
        rule = builder.assert_fact(
            builder.entity(E.GRADE_RULE, "calculation-policy"),
            "calculation_policy",
            dataset.grading_rules.model_dump(mode="json"),
            parents=parents,
            basis="inferred",
            uncertainty=(
                "Calculation policy is adapter-supplied; field-level policy provenance is not independently established.",
            ),
        )
        parents.append(rule)
    return builder, course_entity, parents


def grade_graph(dataset, calculation):
    builder, course, parents = dataset_builder(dataset)
    builder.assert_fact(
        course,
        "grade_calculation",
        calculation,
        parents=parents,
        basis="calculated",
        uncertainty=("Arithmetic result is not instructor policy verification.",),
    )
    return builder.build()


def grade_inputs(graph):
    """Consume a validated graph inside the authorized service; not an access API."""
    entities = {e.id: e for e in graph.entities}
    sources = {s.id: s for s in graph.observations}
    policies = [a for a in graph.assertions if a.predicate == "calculation_policy"]
    if len(policies) != 1:
        raise ValueError("Exactly one declared calculation policy is required.")
    rule = policies[0].value
    groups, assessments = [], []
    for a in graph.assertions:
        entity, value = entities[a.subject], a.value
        if entity.kind == E.GRADING_CATEGORY and a.predicate == "grade_rule":
            groups.append(
                GradeGroup(
                    id=entity.reference,
                    name=value["title"],
                    weight=value["weight"],
                    drop_lowest=value["drop_lowest"],
                    drop_highest=value["drop_highest"],
                    never_drop=value["never_drop"],
                )
            )
        elif entity.kind == E.ASSESSMENT and a.predicate == "grade_input":
            source = sources[a.sources[0]].source
            assessments.append(
                GradeAssessment(
                    id=entity.reference,
                    title=value["title"],
                    group_id=value["category_id"],
                    possible=value["possible"],
                    score=value["result"]["score"],
                    score_state=value["result"]["state"],
                    excluded_reason=value["excluded_reason"],
                    eligibility_verified=value["eligibility_verified"],
                    submission_state=value["submission_state"],
                    missing=value["missing"],
                    late=value["late"],
                    source_url=source.uri or "",
                    source_version=source.version,
                )
            )
    return GradePolicy(
        **{
            k: rule[k]
            for k in ("basis", "method", "empty_categories", "blockers", "rule_ids", "version")
        },
        groups=groups,
    ), assessments


def deadline_graph(
    *, scope, permission, restrictions, documents, items, report, timezone, complete
):
    """Consume deadline_findings output. Never re-extract dates or fuzzy-match IDs."""
    builder = Builder(scope, complete=complete, limitations=report["limitations"])
    course = builder.entity(E.COURSE, scope.course_id)
    facts, entities, temporal = {}, {}, {}

    def observe(source, locator=None, extraction_complete=False):
        if source.get("course_id") != scope.course_id:
            raise ValueError("Deadline source belongs to another course.")
        version = source.get("document_version") or source.get("content_hash") or "not-recorded"
        unknown = [] if version != "not-recorded" else ["Source version was not recorded."]
        location = locator or source.get("locator")
        if location is None:
            unknown.append("Original source locator was not recorded.")
        return builder.observe(
            source=SourceReference(
                provider="canvas",
                id=source.get("source_id") or source["id"],
                version=version,
                locator=location,
                uri=source.get("source_url") or source.get("url") or None,
            ),
            source_type=source.get("source_type"),
            course_id=scope.course_id,
            observed_at=source["retrieved_at"],
            permission=permission,
            restrictions=restrictions,
            complete=extraction_complete,
            uncertainty=tuple(unknown),
        )

    for item in items:
        if item.get("course_id") != scope.course_id:
            raise ValueError("Deadline item belongs to another course.")
        subject = entities[item["id"]] = builder.entity(E.ASSIGNMENT, item["id"])
        source = observe(item["source"], extraction_complete=complete)
        fact = builder.assert_fact(
            subject,
            "deadline",
            item["effective_due"],
            sources=(source,),
            uncertainty=tuple(item["effective_due"].get("uncertainty", ())),
        )
        facts[item["id"]] = fact
        temporal[fact] = item["effective_due"]
        builder.link(R.BELONGS_TO, subject, course, (fact,))
    # Match identities come only from the existing reconciliation function.
    matches = {x["obligation_id"]: x["work_id"] for x in report["comparisons"]}
    matches.update(
        {x["obligation"]["id"]: x["work_id"] for x in report["findings"] if x.get("work_id")}
    )
    for obligation in report["obligations"]:
        evidence = obligation["evidence"]
        source = observe(
            evidence,
            locator=f"{evidence['locator']}; offset {evidence['offset']}",
            extraction_complete=evidence["extraction_status"] == "complete_text",
        )
        work = matches.get(obligation["id"])
        subject = entities[work] if work else builder.entity(E.STUDY_OBLIGATION, obligation["id"])
        value = {
            "kind": "timestamp"
            if obligation["precision"] == "timestamp" and obligation.get("date")
            else "local_date"
            if obligation["precision"] == "date" and obligation.get("date")
            else "unsupported",
            "timestamp": obligation["date"] if obligation["precision"] == "timestamp" else None,
            "local_date": obligation["date"] if obligation["precision"] == "date" else None,
            "timezone": obligation.get("timezone"),
        }
        fact = builder.assert_fact(
            subject,
            "deadline",
            value,
            sources=(source,),
            uncertainty=(
                "Document date is a candidate; assessment applicability and authority require review.",
            ),
        )
        temporal[fact] = value
        doc = builder.entity(E.DOCUMENT, evidence["source_id"])
        passage = builder.entity(E.DOCUMENT_PASSAGE, source)
        passage_fact = builder.assert_fact(
            passage, "passage", evidence["passage"], sources=(source,)
        )
        builder.link(R.DESCRIBES, passage, subject, (fact,))
        builder.link(R.BELONGS_TO, passage, doc, (passage_fact,))
        # Amendment wording is a candidate signal only; it does not change authority.
        if work and re.search(
            r"\b(?:extended|supersedes|replaces|amended)\b", evidence["passage"], re.I
        ):
            builder.link(R.SUPERSEDES, fact, facts[work], (fact,), status="candidate")
    grouped = {}
    for fact in builder.assertions.values():
        if fact.predicate == "deadline":
            grouped.setdefault(fact.subject, []).append(fact)
    for assertions in grouped.values():
        for left, right in combinations(assertions, 2):
            a, b = temporal[left.id], temporal[right.id]
            if a["kind"] not in {"timestamp", "local_date"} or b["kind"] not in {
                "timestamp",
                "local_date",
            }:
                continue
            comparison = compare_deadline(
                {
                    "date": a.get("timestamp") or a.get("local_date"),
                    "precision": "timestamp" if a["kind"] == "timestamp" else "date",
                },
                b,
                timezone,
            )
            if comparison["outcome"] != "indeterminate":
                builder.link(
                    R.CONTRADICTS if comparison["outcome"] == "different" else R.SUPPORTS,
                    left.id,
                    right.id,
                    (left.id, right.id),
                )
    return builder.build()
