"""Bind output to owned source records; never accept classification from payload text."""

import hashlib
from dataclasses import replace
from urllib.parse import urlsplit

from sqlalchemy import select

from canvas_bridge.authorization import request_authorization
from canvas_bridge.domain import DomainError, Result
from canvas_bridge.egress_models import ContentClassification as CC
from canvas_bridge.egress_models import RecipientIdentity, SourceContext, Transfer
from canvas_bridge.egress_policy import privacy_filter
from canvas_bridge.error_guidance import public_coverage_warning
from canvas_bridge.integrity.surfaces import TOOLS as INTEGRITY_TOOLS
from canvas_bridge.policy import Endpoint
from canvas_bridge.processes.surfaces import TOOLS as PROCESS_TOOLS
from canvas_bridge.storage import Course, Material, Work

PURPOSES = {
    "get_library_status": "metadata",
    "get_library_item": "metadata",
    "list_library_items": "metadata",
    "read_library_item": "document_reading",
    "search_library": "document_reading",
    "render_library_item": "visual_analysis",
    "prepare_library_download": "metadata",
    "run_local_study_workflow": "study",
    "run_independent_academic_workflow": "study",
    **{name: "study" for name in PROCESS_TOOLS},
    **{name: "study" for name in INTEGRITY_TOOLS},
    "prepare_study_session": "study",
    "submit_practice_response": "study",
    "run_academic_workflow": "study",
    "get_semester_overview": "study",
    "get_academic_analytics": "study",
    "save_academic_analytics": "study",
    "record_academic_measurement": "study",
    "acknowledge_semester_findings": "study",
    "list_local_documents": "metadata",
    "read_local_document": "document_reading",
    "search_local_documents": "document_reading",
    "render_local_document_page": "visual_analysis",
    "get_local_document_status": "metadata",
    "prepare_local_study_materials": "study",
    "get_local_study_preferences": "preferences",
    "update_local_study_preferences": "preferences",
    "get_connection_status": "status",
    "update_study_preferences": "preferences",
    "get_workload": "schedule",
    "get_changes": "schedule",
    "propose_study_plan": "schedule",
    "propose_course_study_plan": "schedule",
    "propose_calendar_sync": "schedule",
    "save_study_plan": "schedule",
    "get_gradebook": "grade_planning",
    "get_course_grading_policy": "grade_planning",
    "calculate_course_grade": "grade_planning",
    "audit_course_grade": "grade_planning",
    "simulate_grade_scenario": "grade_planning",
    "list_courses": "metadata",
    "list_course_discussions": "study",
    "read_discussion_topic": "study",
    "get_my_discussion_participation": "study",
    "audit_permission_consistency": "diagnostics",
    "get_course_outline": "metadata",
    "list_course_files": "metadata",
    "get_file_extraction_status": "metadata",
    "read_course_file": "document_reading",
    "fetch_course_material": "document_reading",
    "search_course_files": "document_reading",
    "search_course_materials": "document_reading",
    "render_course_file_page": "visual_analysis",
    "render_course_slide": "visual_analysis",
    "inspect_course_figure": "visual_analysis",
    "record_course_figure_observation": "visual_analysis",
    "interpret_course_schedule": "visual_analysis",
    "prepare_course_file_download": "original_download",
    "get_course_file_download_payload": "original_download",
    "download_original": "original_download",
    "get_assignment_details": "study",
    "get_course_obligations": "study",
    "reconcile_course_deadlines": "study",
    "review_assignment_requirements": "study",
    "prepare_for_assessment": "study",
    "audit_course_consistency": "study",
    "get_saved_study_state": "study",
    "record_personal_progress": "study",
}

SOURCE_RESOURCES = {
    "module_requirement": "modules",
    "syllabus": "syllabus",
    "announcement": "announcements",
    "canvas_assignment": "assignments",
    "assignment_rubric": "assignments",
    "assignments": "assignments",
    "classic_quizzes": "quizzes",
    "discussion_topics": "discussions",
    "calendar_assignments": "calendar",
    "calendar_events": "calendar",
}


def scalar_refs(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {
                "id",
                "file_id",
                "material_id",
                "material_ref",
                "resource_id",
                "work_id",
                "course_id",
            } and isinstance(item, str):
                yield item
            elif isinstance(item, (dict, list)):
                yield from scalar_refs(item)
    elif isinstance(value, list):
        for item in value:
            yield from scalar_refs(item)


def resolve_sources(engine, owner, arguments, result, tool):
    from canvas_bridge.library.contracts import TOOLS as LIBRARY_TOOLS

    if tool in LIBRARY_TOOLS:
        return engine.bridge.library.sources(owner, result), None
    if tool == "run_local_study_workflow":
        return engine.bridge.usefulness.resolve_sources(owner, result), None
    if tool == "run_independent_academic_workflow":
        from canvas_bridge.independent_intelligence import resolve_sources as independent_sources

        return independent_sources(engine.bridge, owner, arguments, result), None
    if tool in PROCESS_TOOLS:
        from canvas_bridge.processes.surfaces import resolve_process_sources

        return resolve_process_sources(engine, owner, arguments, result, tool)
    bridge = engine.bridge
    if tool in INTEGRITY_TOOLS:
        from canvas_bridge.integrity.surfaces import resolve_integrity_sources

        return resolve_integrity_sources(engine, owner, arguments, result)
    from canvas_bridge.source_authorization import LOCAL_DOCUMENT_TOOLS, PREFERENCE_TOOLS

    if tool in LOCAL_DOCUMENT_TOOLS:
        return bridge.independent.sources(owner, arguments, result), None
    if tool in PREFERENCE_TOOLS or (
        tool == "get_saved_study_state" and not arguments.get("include_institutional")
    ):
        return (
            SourceContext(
                "__public__", owner, "preferences", "", "preferences", CC.PUBLIC_OR_APPROVED
            ),
        ), None
    if tool in {"get_connection_status", "update_study_preferences"}:
        kind = "safe_status" if tool == "get_connection_status" else "preferences"
        return (SourceContext("__public__", owner, kind, "", kind, CC.PUBLIC_OR_APPROVED),), None
    ref = arguments.get("connection_id")
    if not ref:
        return (SourceContext("unknown", owner, "unknown", "", "unknown"),), None
    with bridge.store.transaction() as session:
        conn = bridge.store.connection(session, owner, ref)
        if tool in {
            "get_academic_analytics",
            "save_academic_analytics",
            "record_academic_measurement",
        }:
            from canvas_bridge.analytics.egress import contexts

            return contexts(engine, session, conn, arguments, result, tool), conn.canvas_user
        if tool == "audit_permission_consistency":
            # This tool emits reconstructed permission states, not course content.
            # Bind even empty reports to the authenticated owner's exact connection.
            return (
                SourceContext(
                    conn.institution,
                    owner,
                    ref,
                    "",
                    "permission_diagnostics",
                    CC.FIRST_PARTY_EDUCATIONAL_RECORD,
                    subject=owner,
                    data_category="courses",
                ),
            ), conn
        if tool == "list_courses" and not result.data.get("courses"):
            # An empty/incomplete listing still has an exact authenticated
            # connection source. Do not turn a refresh failure into unknown
            # content classification. The normal private-list grant is required.
            return (
                SourceContext(
                    conn.institution,
                    owner,
                    ref,
                    "",
                    "course",
                    CC.FIRST_PARTY_EDUCATIONAL_RECORD,
                    subject=owner,
                    data_category="courses",
                ),
            ), conn.canvas_user
        if tool == "list_course_files":
            course = bridge.store.owned(session, Course, owner, ref, arguments.get("course_id"))
            bridge.authorize(
                owner, ref, course.id, "files", "inventory_metadata", session=session
            ).require()
            inventory_source = SourceContext(
                conn.institution,
                owner,
                course.id,
                "",
                "material_inventory",
                CC.FIRST_PARTY_EDUCATIONAL_RECORD,
                subject=owner,
                authorization_resource=course.id,
                data_category="files",
            )
            inventory_sources = [inventory_source]
            # Metadata grants cannot erase a known restriction on a listed
            # source. In particular, filenames can disclose assessment content.
            reviews = engine.source_reviews(conn.institution)
            for item in result.data.get("files", []):
                file_ref = item.get("file_id")
                row = bridge.store.owned(session, Material, owner, ref, file_ref)
                if row.course_id != course.id:
                    raise DomainError("permission_denied", "Inventory source scope mismatch.")
                related_sources = {
                    row.id,
                    *item.get("assignments", []),
                    *row.file_state.get("inventory_assignment_refs", []),
                }
                for review in reviews:
                    if review.source_id in related_sources and review.classification in {
                        CC.UNKNOWN_OR_UNCLASSIFIED,
                        CC.RESTRICTED_ASSESSMENT,
                        CC.CONFIDENTIAL_RESEARCH,
                        CC.THIRD_PARTY_EDUCATIONAL_RECORD,
                    }:
                        inventory_sources.append(
                            replace(
                                inventory_source,
                                source_id=review.source_id,
                                classification=review.classification,
                            )
                        )
                if bridge.settings.profile == "synthetic" and bridge.synthetic is not None:
                    for source_ref in related_sources:
                        overrides = getattr(bridge.synthetic, "egress_contexts", {}).get(source_ref)
                        if overrides:
                            inventory_sources.append(
                                replace(inventory_source, source_id=source_ref, **overrides)
                            )
            return tuple(inventory_sources), conn.canvas_user
        material_ids = (
            set(scalar_refs(arguments))
            | set(scalar_refs(result.data))
            | {s.id for s in result.sources}
            | {s.resource_id for s in result.sources if s.resource_id}
            | {s.course_id for s in result.sources if s.course_id}
        )
        if tool == "get_workload":
            # Empty windows still depend on the requested courses. Coverage carries
            # the server-resolved course scope when no explicit filter was supplied.
            material_ids.update(arguments.get("course_ids") or [])
            material_ids.update(c.course_ref for c in result.meta.coverage)
        if arguments.get("delivery_id"):
            delivery = bridge.original_files.lookup(arguments["delivery_id"], owner, ref)
            material_ids.add(delivery.file)
        materials = list(
            session.scalars(
                select(Material).where(
                    Material.owner == owner,
                    Material.connection_id == ref,
                    Material.id.in_(material_ids),
                )
            )
        )
        works = list(
            session.scalars(
                select(Work).where(
                    Work.owner == owner, Work.connection_id == ref, Work.id.in_(material_ids)
                )
            )
        )
        courses = list(
            session.scalars(
                select(Course).where(
                    Course.owner == owner, Course.connection_id == ref, Course.id.in_(material_ids)
                )
            )
        )
        sources = []
        content_reviews = engine.source_reviews(conn.institution)
        synthetic = bridge.settings.profile == "synthetic" and bridge.synthetic is not None
        for row in materials:
            bridge.authorize(
                owner,
                ref,
                row.course_id,
                "files" if row.kind == "file" else "pages",
                "inventory_metadata"
                if row.kind == "file" and tool == "get_course_outline"
                else Endpoint.FILE
                if row.kind == "file"
                else "read",
            ).require()
            version = (
                row.file_state.get("governance_source_version")
                or row.file_state.get("version")
                or row.version_hash
            )
            # Text, image and original-byte source bindings share the current source
            # metadata version. A content change invalidates every reviewed modality.
            classification = CC.UNKNOWN_OR_UNCLASSIFIED
            if synthetic:
                classification = CC.PUBLIC_OR_APPROVED
            review = (
                next(
                    (r for r in content_reviews if r.source_id == row.id and r.version == version),
                    None,
                )
                if content_reviews
                else None
            )
            if review:
                classification = review.classification
            content_sha256 = row.version_hash or None
            observed = next((s for s in result.sources if s.id == row.id and s.content_hash), None)
            if observed:
                content_sha256 = observed.content_hash
            if (
                arguments.get("file_id") == row.id
                or arguments.get("material_id") == row.id
                or result.data.get("file_id") == row.id
                or arguments.get("delivery_id")
            ):
                content_sha256 = (
                    result.data.get("source_content_hash")
                    or result.data.get("bytes_sha256")
                    or result.data.get("content_hash")
                    or content_sha256
                )
            bound_output = (
                arguments.get("file_id") == row.id
                or result.data.get("file_id") == row.id
                or arguments.get("material_id") == row.id
            )
            # Cached state cannot authorize a different source version returned by
            # a concurrent/fresh read. A stale result must be read again.
            returned_version = result.data.get("source_version") if bound_output else None
            version_conflict = (returned_version and returned_version != version) or (
                row.kind != "file" and content_sha256 and content_sha256 != version
            )
            if version_conflict:
                classification = CC.UNKNOWN_OR_UNCLASSIFIED
            source = SourceContext(
                conn.institution,
                owner,
                row.id,
                version,
                row.kind,
                classification,
                content_sha256=content_sha256,
                extracted_text_sha256=hashlib.sha256(row.text.encode()).hexdigest(),
                version_consistent=not bool(version_conflict),
                authorization_resource=row.course_id,
                data_category="files" if row.kind == "file" else "pages",
            )
            # Only the in-process fixture provider may declare fictional overrides.
            # No Canvas field, filename, instruction or ordinary-user option is read.
            if synthetic:
                overrides = getattr(bridge.synthetic, "egress_contexts", {}).get(row.id, {})
                source = replace(source, **overrides)
            sources.append(source)
            for parent in row.file_state.get("inventory_assignment_refs", []):
                for parent_review in content_reviews or ():
                    if parent_review.source_id == parent and parent_review.classification in {
                        CC.UNKNOWN_OR_UNCLASSIFIED,
                        CC.RESTRICTED_ASSESSMENT,
                        CC.CONFIDENTIAL_RESEARCH,
                        CC.THIRD_PARTY_EDUCATIONAL_RECORD,
                    }:
                        sources.append(
                            replace(
                                source,
                                source_id=parent,
                                classification=parent_review.classification,
                            )
                        )
                if synthetic and (
                    override := getattr(bridge.synthetic, "egress_contexts", {}).get(parent)
                ):
                    sources.append(replace(source, source_id=parent, **override))
        for row in works:
            bridge.authorize(owner, ref, row.course_id, "assignments").require()
            limited = tool == "get_workload"
            version = row.payload.get("source", {}).get("content_hash") or ""
            observed = next((s for s in result.sources if s.id == row.id and s.content_hash), None)
            if observed:
                version = observed.content_hash
            source_reviews = (
                [r for r in content_reviews if r.source_id == row.id] if content_reviews else []
            )
            review = next((r for r in source_reviews if r.version == version), None)
            source = SourceContext(
                conn.institution,
                owner,
                row.id,
                version,
                "deadline" if limited else "assignment_content",
                CC.FIRST_PARTY_EDUCATIONAL_RECORD
                if limited
                else CC.INSTRUCTOR_OWNED_COURSE_CONTENT,
                subject=owner if limited else None,
                derived=limited,
                authorization_resource=row.course_id,
                data_category="assignments",
            )
            if synthetic and not limited:
                source = replace(source, classification=CC.PUBLIC_OR_APPROVED)
            if review:
                # Derivation cannot erase a source's reviewed restrictions.
                source = replace(source, classification=review.classification)
            elif source_reviews:
                source = replace(source, classification=CC.UNKNOWN_OR_UNCLASSIFIED)
            if synthetic:
                source = replace(
                    source, **getattr(bridge.synthetic, "egress_contexts", {}).get(row.id, {})
                )
            sources.append(source)
        if not materials and not works:
            for row in courses:
                if tool == "get_workload":
                    bridge.authorize(owner, ref, row.id, "assignments").require()
                if tool == "get_gradebook":
                    bridge.authorize(owner, ref, row.id, "grades").require()
                known = tool in {
                    "list_courses",
                    "get_workload",
                    "get_gradebook",
                    "audit_permission_consistency",
                    "list_course_discussions",
                    "read_discussion_topic",
                    "get_my_discussion_participation",
                    "acknowledge_semester_findings",
                    "get_semester_overview",
                }
                classification = (
                    CC.FIRST_PARTY_EDUCATIONAL_RECORD if known else CC.UNKNOWN_OR_UNCLASSIFIED
                )
                if synthetic:
                    classification = CC.PUBLIC_OR_APPROVED
                source = SourceContext(
                    conn.institution,
                    owner,
                    row.id,
                    "",
                    "grade" if tool == "get_gradebook" else "course",
                    classification,
                    subject=owner,
                    authorization_resource=row.id,
                    data_category="grades" if tool == "get_gradebook" else "courses",
                )
                if synthetic:
                    source = replace(
                        source, **getattr(bridge.synthetic, "egress_contexts", {}).get(row.id, {})
                    )
                sources.append(source)
        resolved_ids = {s.source_id for s in sources}
        # Provenance-bearing output with an unresolved source is never classified by
        # its title, asserted license, text content or the tool's advertised purpose.
        for item in result.sources:
            if (
                item.id in resolved_ids
                or item.resource_id in resolved_ids
                or item.id in {c.id for c in courses}
            ):
                continue
            resource = SOURCE_RESOURCES.get(item.source_type)
            course = next((c for c in courses if c.id == item.course_id), None)
            origin = bridge.registry.entries[conn.institution].origin
            known_origin = (
                urlsplit(item.url).netloc == urlsplit(origin).netloc
                and urlsplit(item.url).scheme == "https"
            )
            if resource and course and known_origin and item.content_hash:
                # Some evidence (syllabus/announcement/obligation) is deliberately
                # ephemeral. Bind it to its authorized course and content digest.
                bridge.authorize(owner, ref, course.id, resource).require()
                review = (
                    next(
                        (
                            r
                            for r in content_reviews
                            if r.source_id == item.id and r.version == item.content_hash
                        ),
                        None,
                    )
                    if content_reviews
                    else None
                )
                classification = (
                    CC.PUBLIC_OR_APPROVED
                    if synthetic
                    else review.classification
                    if review
                    else CC.UNKNOWN_OR_UNCLASSIFIED
                )
                source = SourceContext(
                    conn.institution,
                    owner,
                    item.id,
                    item.content_hash,
                    "syllabus" if resource == "syllabus" else "assignment_content",
                    classification,
                    content_sha256=item.content_hash,
                    authorization_resource=course.id,
                    data_category=resource,
                )
                if synthetic:
                    source = replace(
                        source, **getattr(bridge.synthetic, "egress_contexts", {}).get(item.id, {})
                    )
                sources.append(source)
            else:
                sources.append(SourceContext(conn.institution, owner, item.id, "", "unknown"))
        if not sources:
            # Empty discovery has no content. Synthetic derived tools use exclusively
            # locally produced fixture records; live unbound derivations need review.
            classification = CC.PUBLIC_OR_APPROVED if synthetic else CC.UNKNOWN_OR_UNCLASSIFIED
            sources.append(
                SourceContext(
                    conn.institution, owner, ref, "", "derived", classification, derived=True
                )
            )
        return tuple(sources), conn.canvas_user


SCHEDULE_FIELDS = {
    "id",
    "connection_id",
    "course_id",
    "title",
    "kind",
    "effective_due",
    "display_due",
    "due_date_status",
    "schedule_status",
    "availability_state",
    "submission_state",
    "section",
    "window_relationship",
    "personal_progress",
    "effort_remaining",
    "points_possible",
}


def minimize(result, tool, *, live):
    from canvas_bridge.membership import MEMBERSHIP_FIELDS

    # Reconstruct known minimum outputs; a scheduling result cannot smuggle a raw
    # document in a new field. The inherited source classification is unchanged.
    if not live:
        return result, False
    data = result.data
    if tool == "list_course_files":
        from canvas_bridge.egress_errors import safe_error_result

        fields = {
            "file_id",
            "canvas_file_id",
            "source_version",
            "course_id",
            "title",
            "filename",
            "type",
            "size",
            "extraction_state",
            "access_state",
            "indexed",
        }
        safe = {
            "files": [
                {k: v for k, v in row.items() if k in fields}
                for row in data.get("files", [])[:200]
                if isinstance(row, dict)
            ]
        }
        if result.status == "retry_later" and data.get("reason_code"):
            safe.update(safe_error_result(result).data)
        rows = (row for row in data.get("files", [])[:200] if isinstance(row, dict))
        for row, clean in zip(rows, safe["files"], strict=True):
            for key, allowed in {
                "inventory_freshness": ("retained", "fresh"),
                "access_verification": (
                    "not_rechecked",
                    "course_file_metadata",
                    "file_list_visibility",
                ),
            }.items():
                if row.get(key) in allowed:
                    clean[key] = row[key]
        if "coverage" in data:
            safe["coverage"] = {
                key: value
                for key, value in data["coverage"].items()
                if key in {"files", "modules", "pages", "folders", "assignments"}
                and value
                in {
                    "complete",
                    "partial",
                    "unavailable",
                    "permission_denied",
                    "unsupported",
                    "not_refreshed",
                }
            }
        if data.get("inventory_operation") in {
            "files",
            "folders",
            "modules",
            "module_items",
            "folder_files",
            "assignments",
            "file",
        }:
            safe["inventory_operation"] = data["inventory_operation"]
        page_identity = data.get("page_identity")
        if (
            isinstance(page_identity, str)
            and len(page_identity) == 64
            and all(c in "0123456789abcdef" for c in page_identity)
        ):
            safe["page_identity"] = page_identity
        if "folder_graph" in data:

            def folder_reference(value):
                return (
                    isinstance(value, str)
                    and len(value) == 40
                    and all(c in "0123456789abcdef" for c in value)
                )

            safe["folder_graph"] = [
                {"id": node["id"], "parent_id": node.get("parent_id")}
                for node in data["folder_graph"][:100]
                if isinstance(node, dict)
                and folder_reference(node.get("id"))
                and (node.get("parent_id") is None or folder_reference(node.get("parent_id")))
            ]
        progress = data.get("inventory_progress")
        if isinstance(progress, dict) and isinstance(progress.get("collections"), dict):
            cleaned_progress = {
                "collections": {
                    key: value
                    for key, value in progress["collections"].items()
                    if key in {"files", "modules", "pages", "folders", "assignments"}
                    and isinstance(value, str)
                    and value
                    in {
                        "complete",
                        "complete_nonempty",
                        "complete_empty",
                        "partial",
                        "unavailable",
                        "unsupported",
                        "permission_denied",
                        "not_refreshed",
                    }
                },
                "count_is_lower_bound": progress.get("count_is_lower_bound") is not False,
            }
            for key, limit in (
                ("distinct_verified_files", 100_000),
                ("branches_attempted", 5),
                ("branches_completed", 5),
            ):
                value = progress.get(key)
                if type(value) is int and 0 <= value <= limit:
                    cleaned_progress[key] = value
            safe["inventory_progress"] = cleaned_progress
        if "inventory_reason_codes" in data:

            def branch_fields(value):
                fields = safe_error_result(
                    Result(status="partial_data", summary="", data=value)
                ).data
                ident = value.get("request_id")
                if (
                    isinstance(ident, str)
                    and len(ident) == 32
                    and all(c in "0123456789abcdef" for c in ident)
                ):
                    fields["request_id"] = ident
                return fields

            safe["inventory_reason_codes"] = {
                key: branch_fields(value)
                for key, value in data["inventory_reason_codes"].items()
                if key in {"files", "modules", "pages", "folders", "assignments"}
                and isinstance(value, dict)
            }
        if len(data.get("files", [])) > 200:
            safe.setdefault("coverage", {})["files"] = "partial"
        for original, cleaned in zip(data.get("files", []), safe["files"], strict=False):
            if isinstance(original, dict) and original.get("folders"):
                cleaned["folders"] = [
                    identity
                    for identity in original["folders"]
                    if isinstance(identity, str)
                    and len(identity) == 40
                    and all(c in "0123456789abcdef" for c in identity)
                ]
            if isinstance(original, dict) and original.get("assignments"):
                cleaned["assignments"] = [
                    identity
                    for identity in original["assignments"]
                    if isinstance(identity, str)
                    and len(identity) == 40
                    and all(c in "0123456789abcdef" for c in identity)
                ]
            if isinstance(original, dict) and original.get("modules"):
                cleaned["modules"] = [
                    {"id": module["id"]}
                    for module in original["modules"]
                    if isinstance(module, dict) and isinstance(module.get("id"), str)
                ]
        return result.model_copy(
            update={
                "summary": "Minimized authorized file inventory; listing does not grant text or binary sharing.",
                "data": safe,
                "sources": [],
                "evidence": [],
            },
            deep=True,
        ), True
    if tool == "audit_permission_consistency":
        fields = {
            "connection_state",
            "credential_state",
            "scope_consistency",
            "scope_snapshot_version",
            "current_scope_snapshot_version",
            "scope_evaluated_at",
            "current_scope_evaluated_at",
            *MEMBERSHIP_FIELDS,
            "recommended_action",
            "recommended_actions",
            "upstream_checks_requested",
            "upstream_requests",
            "state_modified",
        }
        check_fields = {
            "course_id",
            "resource",
            "advertised_selected",
            "connection_owned",
            "identifier_state",
            "scope_authorized",
            "resource_capability",
            "authorization_freshness",
            "scope_evaluated_at",
            "scope_snapshot_version",
            "upstream_permission",
            "upstream_http_status",
            "result",
            "reason_code",
            "recommended_action",
        }
        from canvas_bridge.permission_recovery import recovery_actions

        safe = {key: value for key, value in data.items() if key in fields}

        ids = safe.get("recommended_actions", [])
        safe["recovery_actions"] = recovery_actions(ids if isinstance(ids, list) else [])
        safe["checks"] = [
            {key: value for key, value in row.items() if key in check_fields}
            for row in data.get("checks", [])[:210]
            if isinstance(row, dict)
        ]
        action_ids = [action["action_id"] for action in safe["recovery_actions"]]
        safe["recommended_actions"] = action_ids
        safe["recommended_action"] = action_ids[0] if action_ids else "none"
        for check in safe["checks"]:
            if "recommended_action" in check and check["recommended_action"] not in action_ids:
                check["recommended_action"] = "none"
        return result.model_copy(
            update={
                "summary": "Minimized permission diagnostics; unchecked upstream access remains unknown.",
                "data": safe,
                "sources": [],
                "evidence": [],
            },
            deep=True,
        ), True
    if tool in {"get_workload", "get_gradebook", "list_courses", "get_connection_status"}:
        result = result.model_copy(deep=True)
        result.meta.warnings = (
            ["Some source coverage is incomplete; review the coverage states."]
            if result.meta.warnings
            else []
        )
        result.meta.coverage = [
            c.model_copy(update={"warning": public_coverage_warning(c.reason_code or c.warning)})
            for c in result.meta.coverage
        ]
    if tool == "get_workload":
        data = {
            "items": [
                {k: v for k, v in item.items() if k in SCHEDULE_FIELDS}
                for item in data.get("items", [])
            ],
            "coverage": "See response metadata; omitted fields were not transmitted.",
        }
        result = result.model_copy(
            update={
                "data": data,
                "sources": [],
                "evidence": [],
                "summary": "Some courses could not be fully checked and may contain additional obligations. See course coverage."
                if result.status == "partial_data"
                else "Minimized assignment deadlines and personal work status.",
            },
            deep=True,
        )
        return result, True
    if tool == "get_gradebook":
        allowed = {"current_score", "final_score", "current_grade", "final_grade"}
        data = {
            "reported": {k: v for k, v in data.get("reported", {}).items() if k in allowed},
            "policy": "Exact grade calculations require independently verified grading rules.",
        }
        return result.model_copy(
            update={
                "data": data,
                "sources": [],
                "evidence": [],
                "summary": "Your minimized Canvas-reported grade fields.",
            },
            deep=True,
        ), True
    if tool == "list_courses":
        from canvas_bridge.egress_errors import safe_error_result

        diagnostics = safe_error_result(result).data if result.data.get("reason_code") else {}
        data = {
            **diagnostics,
            **{
                k: data[k] for k in (*MEMBERSHIP_FIELDS, "membership_evidence_renewed") if k in data
            },
            "courses": [
                {
                    k: v
                    for k, v in row.items()
                    if k in {"id", "name", "selected", "accessible", "enrollment_state"}
                }
                for row in data.get("courses", [])
            ],
        }
        return result.model_copy(
            update={
                "data": data,
                "sources": [],
                "evidence": [],
                "summary": "Your authorized course list.",
            },
            deep=True,
        ), True
    if tool == "get_connection_status":
        data = {
            "profile": data.get("profile"),
            "connections": [
                {
                    k: row[k]
                    for k in (
                        "id",
                        "institution",
                        "state",
                        "authentication_state",
                        "last_successful_refresh",
                        "last_complete_assignment_refresh_at",
                        "scope_evaluated_at",
                        "scope_snapshot_version",
                        *MEMBERSHIP_FIELDS,
                        "live_integration",
                        "authorization_policy",
                    )
                    if k in row
                }
                for row in data.get("connections", [])
            ],
        }
        return Result(
            summary="Connection and authorization status; academic content is omitted.",
            data=data,
            meta=result.meta,
        ), True
    return result, False


def prepare_transfer(engine, result, owner, arguments, tool, channel, opaque_bytes):
    context = request_authorization.get()
    identity = (
        context.egress_identity
        if context and context.egress_identity
        else RecipientIdentity("unverified")
    )
    sources, canvas_user = resolve_sources(engine, owner, arguments, result, tool)
    from canvas_bridge.privacy.output import source_refs

    resolved = {source.source_id for source in sources}
    source_refs.set(
        frozenset(
            resolved
            | {s.authorization_resource for s in sources if s.authorization_resource}
            | {s.resource_id for s in result.sources if s.id in resolved and s.resource_id}
        )
    )
    # Privacy scanning precedes projection so removal cannot erase evidence of a
    # third-party record or a disguised attachment path.
    filtered, redacted, third_party, hidden = privacy_filter(
        result.model_dump(mode="json"), own_canvas_user=canvas_user
    )
    cleaned, minimized = Result.model_validate(filtered), False
    if engine.bridge.settings.egress_mode != "permissive":
        cleaned, minimized = minimize(
            cleaned, tool, live=engine.bridge.settings.profile != "synthetic"
        )
    if third_party:
        sources += (
            SourceContext(
                sources[0].institution,
                owner,
                "third-party",
                "",
                "record",
                CC.THIRD_PARTY_EDUCATIONAL_RECORD,
            ),
        )
    purpose = PURPOSES.get(tool, "unclassified")
    if tool == "run_independent_academic_workflow":
        from canvas_bridge.academic.independent_models import IndependentRequest
        from canvas_bridge.independent_intelligence import PURPOSES as INDEPENDENT_PURPOSES

        request = arguments.get("request")
        if not isinstance(request, IndependentRequest):
            request = IndependentRequest.model_validate(request)
        purpose = INDEPENDENT_PURPOSES[request.capability]
    if tool == "run_local_study_workflow":
        request = arguments.get("request")
        operation = (
            request.get("operation")
            if isinstance(request, dict)
            else getattr(request, "operation", None)
        )
        if operation in {"obligations", "changes"}:
            purpose = "schedule"
    if tool == "run_academic_workflow":
        from canvas_bridge.workflow_registry import WORKFLOWS, WorkflowRequest

        request = arguments.get("request")
        if not isinstance(request, WorkflowRequest):
            request = WorkflowRequest.model_validate(request)
        purpose = WORKFLOWS[request.workflow].purpose
    if purpose == "original_download":
        channel = "original" if channel == "structured" else channel
    if purpose == "document_reading":
        channel = "text"
    # This inventory response may carry an owner-bound resume cursor. Include
    # the actual cursor and reviewed diagnostic in the ordinary policy budget.
    if (
        tool == "list_course_files"
        and cleaned.status == "retry_later"
        and not cleaned.data.get("files")
    ):
        from canvas_bridge.egress_errors import safe_error_result
        from canvas_bridge.failure_diagnostics import describe

        retry = safe_error_result(
            result
        )  # Reconstruct reviewed facts before unknown fields are lost.
        describe(retry, "allow")
        operation = cleaned.data.get("inventory_operation")
        cleaned.data = {"files": [], **retry.data}
        if operation in (
            "files",
            "folders",
            "modules",
            "module_items",
            "folder_files",
            "assignments",
            "file",
        ):
            cleaned.data["inventory_operation"] = operation
        cleaned.summary = retry.summary
    if tool == "list_course_files":
        from canvas_bridge.inventory_recovery import project_recovery

        cleaned.data.pop("inventory_recovery", None)
        recovery = project_recovery(result, arguments)
        if recovery:
            cleaned.data["inventory_recovery"] = recovery
    # Some tools return partial collections or permission audits instead of raising.
    # Preserve their coverage and review the diagnostic within the same transfer budget.
    from canvas_bridge.auth_diagnostics import result_observation
    from canvas_bridge.failure_diagnostics import current

    if (attempt := current.get()) and attempt.operation == tool:
        auth = result_observation(tool, result, attempt)
        if auth:
            attempt.auth_observation = auth
            cleaned.data["authentication_diagnostic"] = auth.model_dump()
            if tool in {"get_connection_status", "list_courses"}:
                cleaned.summary = auth.explanation
    amount = len(cleaned.model_dump_json().encode()) + opaque_bytes
    transfer = Transfer(
        owner, identity, purpose, channel, sources, amount, True, True, minimized, redacted
    )
    if hidden:
        from canvas_bridge.egress_policy import RD, classify

        engine.decision(
            transfer, RD.DENY, "EGRESS_HIDDEN_FILE_REFERENCE", [classify(s) for s in sources]
        ).require()
    return cleaned, transfer
