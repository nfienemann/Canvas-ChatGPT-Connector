"""Trusted bridge adapter for the bounded deadline evidence graph."""

from datetime import timedelta
from decimal import Decimal
from itertools import combinations

from canvas_bridge.academic.evidence_adapters import deadline_graph
from canvas_bridge.academic.evidence_graph import Builder, Scope
from canvas_bridge.academic.evidence_graph import EntityKind as E
from canvas_bridge.academic.evidence_graph import RelationKind as R
from canvas_bridge.academic.models import PermissionContext, Restrictions, SourceReference
from canvas_bridge.authorization import request_authorization
from canvas_bridge.domain import Result, utcnow
from canvas_bridge.egress_models import ContentClassification as CC
from canvas_bridge.egress_policy import classify
from canvas_bridge.egress_sources import resolve_sources


def course_deadline_graph(bridge, owner, ref, bundle, report):
    course, conn = bundle["course"], bundle["connection"]
    context = request_authorization.get()
    source_contexts, _ = resolve_sources(
        bridge.egress,
        owner,
        {"connection_id": ref, "course_id": course.id},
        Result(summary="Collected deadline evidence.", sources=bundle["sources"]),
        "reconcile_course_deadlines",
    )
    classifications = {classify(s) for s in source_contexts} or {CC.UNKNOWN_OR_UNCLASSIFIED}
    permission = PermissionContext(
        principal=owner,
        tenant=conn.institution,
        connection=ref,
        scope={"study"},
        decision_reference=context.request_id if context else "trusted-local-call",
        expires_at=utcnow() + timedelta(seconds=30),
    )
    # Conservatively inherit the union of every participating source classification.
    # Final MCP release still performs exact-source recipient/content authorization.
    restrictions = Restrictions(
        classifications=classifications,
        purposes={"study"},
        recipients={context.recipient if context else "local"},
    )
    graph = deadline_graph(
        scope=Scope(
            principal=owner, institution=conn.institution, connection=ref, course_id=course.id
        ),
        permission=permission,
        restrictions=restrictions,
        documents=bundle["documents"],
        items=bundle["items"],
        report=report,
        timezone=bundle["timezone"],
        complete=bundle["assignments_complete"] and all(d["complete"] for d in bundle["documents"]),
    )
    return {
        **graph.view(),
        "queries": [
            {"work_id": entity.reference, "result": graph.query(entity.id, "deadline")}
            for entity in graph.entities
            if entity.kind == E.ASSIGNMENT
        ],
    }


def course_grade_rule_graph(bridge, owner, ref, evidence, syllabus, documents):
    """Wrap the existing syllabus parser and Canvas policy; never interpret new text."""
    course, conn = evidence["course"], evidence["connection"]
    context = request_authorization.get()
    source_contexts, _ = resolve_sources(
        bridge.egress,
        owner,
        {"connection_id": ref, "course_id": course.id},
        Result(summary="Collected grading rule evidence.", sources=evidence["sources"]),
        "get_course_grading_policy",
    )
    classes = {classify(s) for s in source_contexts} or {CC.UNKNOWN_OR_UNCLASSIFIED}
    permission = PermissionContext(
        principal=owner,
        tenant=conn.institution,
        connection=ref,
        scope={"grade_planning"},
        decision_reference=context.request_id if context else "trusted-local-call",
        expires_at=utcnow() + timedelta(seconds=30),
    )
    restrictions = Restrictions(
        classifications=classes,
        purposes={"grade_planning"},
        recipients={context.recipient if context else "local"},
    )
    builder = Builder(
        Scope(principal=owner, institution=conn.institution, connection=ref, course_id=course.id),
        complete=evidence["complete"] and all(d["complete"] for d in documents),
        limitations=tuple(syllabus["missing_information"]),
    )
    policy = evidence["policy"]
    source = evidence["sources"][0]

    def observe(source_ref, source_type, observed_at, complete, uncertainty=()):
        return builder.observe(
            source=source_ref,
            source_type=source_type,
            course_id=course.id,
            observed_at=observed_at,
            permission=permission,
            restrictions=restrictions,
            complete=complete,
            uncertainty=uncertainty,
        )

    for group in policy.groups:
        entity = builder.entity(E.GRADING_CATEGORY, group.id)
        for predicate, value in (
            ("category_weight", str(group.weight) if group.weight is not None else None),
            ("drop_lowest", group.drop_lowest),
            ("drop_highest", group.drop_highest),
        ):
            origin = observe(
                SourceReference(
                    provider="canvas",
                    id=source.id,
                    version=policy.version,
                    uri=source.url,
                    locator=f"normalized category {group.id}: {predicate}",
                ),
                "normalized_canvas_grading_policy",
                source.retrieved_at,
                evidence["complete"],
                (
                    "Version and locator describe normalized Canvas grading fields; an original provider version is not returned.",
                ),
            )
            builder.assert_fact(
                entity,
                predicate,
                value,
                sources=(origin,),
                uncertainty=("Category weight was not returned.",) if value is None else (),
            )
    docs = {d["id"]: d for d in documents}
    for rule in syllabus["rules"]:
        doc = docs[rule["source_document"]]
        if doc.get("course_id") != course.id or rule["document_version"] != doc["version"]:
            raise ValueError("Grading rule source scope/version mismatch.")
        origin = observe(
            SourceReference(
                provider="canvas",
                id=doc["id"],
                version=doc["version"],
                uri=doc["url"],
                locator=rule["source_location"]["locator"]
                + f"; offset {rule['source_location']['offset']}",
            ),
            doc["source_type"],
            doc["retrieved_at"],
            doc["complete"],
        )
        value = rule["value"]
        group_id = value.get("group_id")
        entity = (
            builder.entity(E.GRADING_CATEGORY, group_id)
            if group_id
            else builder.entity(E.GRADE_RULE, rule["id"])
        )
        if rule["rule_type"] == "category_weight" and group_id:
            value = value["weight"]
        elif rule["rule_type"] == "drop_lowest" and group_id:
            value = value["count"]
        builder.assert_fact(
            entity,
            rule["rule_type"],
            value,
            sources=(origin,),
            uncertainty=("Syllabus rule applicability requires review.",)
            if rule["student_confirmation_needed"]
            else (),
            basis="explicit",
        )
    grouped = {}
    for fact in builder.assertions.values():
        grouped.setdefault((fact.subject, fact.predicate), []).append(fact)
    for (_subject, predicate), facts in grouped.items():
        if predicate not in {"category_weight", "drop_lowest", "drop_highest"}:
            continue
        for left, right in combinations(facts, 2):
            if left.value is None or right.value is None:
                continue
            same = Decimal(str(left.value)) == Decimal(str(right.value))
            builder.link(
                R.SUPPORTS if same else R.CONTRADICTS, left.id, right.id, (left.id, right.id)
            )
    graph = builder.build()
    return {**graph.view(), "uncertain_rules": graph.uncertain_rules()}
