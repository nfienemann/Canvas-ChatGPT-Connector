"""Bind every contributing parent, including those omitted from bounded detail."""

from dataclasses import replace

from canvas_bridge.domain import DomainError
from canvas_bridge.egress_models import ContentClassification as CC
from canvas_bridge.egress_models import SourceContext
from canvas_bridge.storage import Work


def contexts(engine, session, conn, arguments, result, tool):
    bridge = engine.bridge
    synthetic = bridge.settings.profile == "synthetic" and bridge.synthetic is not None
    if tool == "record_academic_measurement":
        m = arguments["measurement"]
        payload = m.model_dump() if hasattr(m, "model_dump") else m
        course_ids = [payload["course_id"]]
        bindings = []
        if payload.get("work_id"):
            work = bridge.store.owned(session, Work, conn.owner, conn.id, payload["work_id"])
            bindings.append(
                (work.course_id, work.id, work.payload["source"].get("content_hash") or "")
            )
    else:
        course_ids = result.data["course_ids"]
        bindings = getattr(result, "_analytics_bindings", None)
        if bindings is None:
            raise DomainError("permission_denied", "Analytics source bindings are unavailable.")
    for course in course_ids:
        bridge.authorize(conn.owner, conn.id, course, "assignments", session=session).require()
    sources = []
    reviews = engine.source_reviews(conn.institution) or ()
    for course, key, version in sorted(set(bindings) | {(c, c, "") for c in course_ids}):
        if course not in course_ids:
            raise DomainError("permission_denied", "Analytics sources changed scope.")
        source = SourceContext(
            conn.institution,
            conn.owner,
            key,
            version,
            "academic_review",
            CC.PUBLIC_OR_APPROVED if synthetic else CC.FIRST_PARTY_EDUCATIONAL_RECORD,
            subject=conn.owner,
            derived=True,
            authorization_resource=course,
            data_category="assignments",
        )
        matched = [r for r in reviews if r.source_id == key]
        denied = [
            r
            for r in matched
            if r.classification
            in {
                CC.RESTRICTED_ASSESSMENT,
                CC.THIRD_PARTY_EDUCATIONAL_RECORD,
                CC.CONFIDENTIAL_RESEARCH,
            }
        ]
        if denied:
            source = replace(source, classification=denied[0].classification)
        elif matched:
            exact = next((r for r in matched if r.version == version), None)
            source = replace(
                source, classification=exact.classification if exact else CC.UNKNOWN_OR_UNCLASSIFIED
            )
        if synthetic:
            source = replace(
                source, **getattr(bridge.synthetic, "egress_contexts", {}).get(key, {})
            )
        sources.append(source)
    return tuple(sources)
