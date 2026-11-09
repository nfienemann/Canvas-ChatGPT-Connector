"""Authenticated local import/review forms; no separate academic dashboard."""

import html
import secrets
from urllib.parse import quote, unquote, urlsplit

from pydantic import ValidationError
from sqlalchemy import select as sa_select
from starlette.responses import JSONResponse, RedirectResponse

from canvas_bridge.academic.independent_models import IndependentWork
from canvas_bridge.domain import DomainError, FactDate
from canvas_bridge.egress_models import RecipientPolicy
from canvas_bridge.evidence import fingerprint
from canvas_bridge.storage import IndependentResource
from canvas_bridge.usefulness.imports import ZIP_BYTES, candidates


def esc(value):
    return html.escape(str(value), quote=True)


def field(name, label, value="", kind="text", **attrs):
    extra = " ".join(f'{esc(k)}="{esc(v)}"' for k, v in attrs.items())
    return f'<label>{esc(label)}<input name="{esc(name)}" type="{esc(kind)}" value="{esc(value)}" {extra}></label>'


def select(name, label, values, selected=None):
    return (
        f'<label>{esc(label)}<select name="{esc(name)}" aria-label="{esc(label)}">'
        + "".join(
            f'<option value="{esc(v)}"{" selected" if v == selected else ""}>{esc(v.replace("_", " "))}</option>'
            for v in values
        )
        + "</select></label>"
    )


def sharing():
    return '<label><input type="checkbox" name="share" value="yes">Allow this selected record to be shared with the configured ChatGPT recipient.</label>'


def due_value(value):
    if not value:
        return FactDate().model_dump(mode="json")
    return (
        FactDate(kind="timestamp", timestamp=value).model_dump(mode="json")
        if "T" in value
        else FactDate(kind="local_date", local_date=value).model_dump(mode="json")
    )


def register_routes(bridge, route, identity, form, page, hidden):
    from canvas_bridge.usefulness.workspace_ui import register

    register(bridge, route, identity, form, page, hidden)
    service = bridge.usefulness

    def plan_choices(owner, course):
        from canvas_bridge.usefulness.service import scoped_work_id

        choices = {}
        reviews = service.records.rows(owner, course, "import_review")
        for record in reviews:
            document = next(s.id for s in record.sources if s.origin == "local_document")
            for work in record.data["value"]["dataset"]["work"]:
                choices[scoped_work_id(document, work["key"])] = (work["title"], record)
        return choices, fingerprint([(r.id, r.revision) for r in reviews])

    def start_form(session, action, **values):
        return (
            '<form method="post" action="'
            + action
            + '">'
            + hidden("csrf", session.csrf)
            + hidden("key", secrets.token_urlsafe(24))
            + "".join(hidden(k, str(v)) for k, v in values.items())
        )

    @route("/settings/materials", ["GET"])
    async def materials(request):
        session = await identity(request)
        service.enabled()
        nonce = secrets.token_urlsafe(24)
        body = "<p>Add course materials, inspect them locally, and review only the facts you want to use. ChatGPT attachments are not automatically transferred.</p>"
        body += "<p>Files and extracted text expire within 24 hours. Local study records expire within 30 days; source-dependent records remain usable only while their sources are permitted. Processing and ChatGPT sharing are separate choices.</p>"
        body += '<form id="batch">' + hidden("csrf", session.csrf)
        body += field(
            "course",
            "Course (choose an existing label or enter a new one)",
            "independent",
            maxlength=100,
            required="required",
        )
        body += field("term", "Packet term", "unspecified", maxlength=100)
        body += '<label>Expected packet paths, one per line (optional)<textarea name="expected" maxlength="4000"></textarea></label>'
        body += select(
            "purpose",
            "Purpose",
            [
                "material",
                "syllabus",
                "schedule",
                "lecture",
                "reading",
                "instructions",
                "own_feedback",
            ],
        )
        body += '<label>Choose up to twenty files or one bounded ZIP<input type="file" name="files" multiple accept=".pdf,.docx,.pptx,.xlsx,.txt,.md,.zip" required></label>'
        body += '<label><input type="checkbox" name="own" required>I have permission to process these selected independent materials, which are not restricted assessments, confidential research or other people’s records.</label>'
        body += '<label><input type="checkbox" name="share">Allow selected extracted text to be shared with the configured ChatGPT recipient.</label>'
        body += '<label><input type="checkbox" name="analysis">Allow planning, grade and schedule analysis of these selected materials.</label>'
        body += '<label><input type="checkbox" name="visual">Allow reviewed page/slide images to be shared where rendering is supported.</label>'
        body += '<ul id="selection"></ul><button>Import selected files</button> <button type="button" id="cancel">Cancel pending work</button><p id="status" role="status"></p></form>'
        body += "<p>Limit: 10 MB per document, 50 MB per ZIP, twenty stored documents. Completed items are retained after cancellation; failed files can be retried with the same selection.</p>"
        body += f'<script nonce="{nonce}" src="/settings/materials/script"></script>'
        for doc in bridge.independent.list(session.owner).data["documents"]:
            body += f'<section class="card"><h2>{esc(doc["filename"])}</h2><p>Course: {esc(doc["course"])}</p><a href="/settings/materials/review?document_id={quote(doc["document_id"])}">Inspect, review, correct or remove</a></section>'
        with bridge.store.transaction() as database:
            batches = list(
                database.scalars(
                    sa_select(IndependentResource)
                    .where(
                        IndependentResource.owner == session.owner,
                        IndependentResource.kind == "import_batch",
                        IndependentResource.expires_at > bridge.retention.clock(),
                    )
                    .limit(40)
                )
            )
        for batch in batches:
            body += (
                "<details><summary>Import receipt: "
                + esc(batch.content["state"])
                + "</summary><ul>"
            )
            for item in batch.content["items"]:
                body += (
                    "<li>"
                    + esc(item["filename"])
                    + ": "
                    + esc(item["state"])
                    + " "
                    + esc(item.get("disposition", ""))
                    + " "
                    + esc(item.get("extraction", ""))
                    + " "
                    + esc(item.get("next_action", ""))
                    + "</li>"
                )
            for item in batch.content.get("excluded", []):
                body += "<li>Unsupported entry excluded: " + esc(item) + "</li>"
            body += (
                "</ul>"
                + start_form(session, "/settings/materials/cancel", batch_id=batch.id)
                + "<button>Cancel unfinished items</button></form></details>"
            )
        body += '<p><a href="/settings/materials/workspace">Export or restore a course workspace</a></p>'
        body += '<p><a href="/settings/study">Selected study records and privacy controls</a></p>'
        response = page("Add course materials", body)
        response.headers["Content-Security-Policy"] += (
            f"; script-src 'nonce-{nonce}'; connect-src 'self'"
        )
        return response

    @route("/settings/materials/script", ["GET"])
    async def script(request):
        from pathlib import Path

        from starlette.responses import Response

        return Response(
            Path(__file__).with_name("imports.js").read_text(encoding="utf-8"),
            media_type="application/javascript",
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    @route("/settings/materials/import", ["POST"])
    async def upload(request):
        session = await identity(request, True)
        service.enabled()
        origin = urlsplit(bridge.settings.resource_url)
        if request.headers.get(
            "origin"
        ) != f"{origin.scheme}://{origin.netloc}" or not secrets.compare_digest(
            request.headers.get("x-bridge-csrf", ""), session.csrf
        ):
            raise DomainError("permission_denied", "Start from the signed-in file picker.")
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > ZIP_BYTES:
                raise DomainError("needs_input", "The upload exceeds the byte limit.")
            raw.extend(chunk)
        import json

        try:
            decisions = json.loads(unquote(request.headers.get("x-bridge-mappings", "{}")))
            expected = json.loads(unquote(request.headers.get("x-bridge-expected", "{}")))
        except (ValueError, RecursionError):
            raise DomainError("needs_input", "Review the selected source references.") from None
        result = await service.imports.run(
            session.owner,
            bytes(raw),
            unquote(request.headers.get("x-bridge-filename", "")),
            request.headers.get("content-type", ""),
            course=unquote(request.headers.get("x-bridge-course", "independent")),
            purpose=request.headers.get("x-bridge-purpose", "material"),
            term=unquote(request.headers.get("x-bridge-term", "unspecified")),
            preview_only=request.headers.get("x-bridge-preview") == "true",
            confirmation=request.headers.get("x-bridge-confirmation"),
            decisions=decisions,
            expected=expected,
            key=request.headers.get("x-bridge-key", ""),
            permissions={
                "own_material": request.headers.get("x-bridge-own") == "true",
                "share_text": request.headers.get("x-bridge-share") == "true",
                "share_visual": request.headers.get("x-bridge-visual") == "true",
                "allow_academic_analysis": request.headers.get("x-bridge-analysis") == "true",
            },
            validate_session=request.state.validate_bridge_session,
        )
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    @route("/settings/materials/cancel", ["POST"])
    async def cancel(request):
        session = await identity(request, True)
        values = await form(request, session)
        ident = values.get("batch_id") or fingerprint(
            [session.owner, "import-batch", str(values.get("key", ""))]
        )
        service.imports.cancel(session.owner, ident)
        return RedirectResponse("/settings/materials", status_code=303)

    @route("/settings/materials/review", ["GET"])
    async def review(request):
        session = await identity(request)
        row = bridge.independent.require(session.owner, request.query_params.get("document_id", ""))
        start = max(0, min(50, int(request.query_params.get("start", 0))))
        found = candidates(row)
        prior = (
            row.content.get("review")
            or (row.content.get("version_history") or [{}])[-1].get("review")
            or {}
        )
        prior_record = service.records.state(session.owner).records.get(prior.get("record_id"))
        old_work = prior_record.data["value"]["dataset"]["work"] if prior_record else []
        old_decisions = (
            {d["candidate"]["id"]: d for d in prior_record.data["value"]["decisions"]}
            if prior_record
            else {}
        )
        body = f"<p>{esc(row.content.get('filename', 'Imported document'))} · {esc(row.content.get('course', 'independent'))}</p>"
        body += "<p>This preview remains local. Candidate passages are untrusted source data; acceptance records your review, not instructor authority. Unknown times stay unknown. No grading policy is inferred.</p>"
        if prior_record and prior_record.state == "stale":
            body += "<p>Source revised. Review the remaining work against the new version.</p><ul>"
            for work in old_work:
                body += (
                    "<li>"
                    + esc(work["title"])
                    + " · previous personal progress: "
                    + esc(work.get("progress", "unknown"))
                    + "</li>"
                )
            body += "</ul>"
        body += start_form(
            session,
            "/settings/materials/review",
            document_id=row.id,
            expected_hash=row.version_hash,
            expected_revision=prior_record.revision if prior_record else prior.get("revision", 0),
        )
        for candidate in found[start : start + 4]:
            ident = candidate["id"]
            old_decision = old_decisions.get(ident, {})
            reviewed_work = old_decision.get("correction") or {}
            body += (
                "<fieldset><legend>"
                + esc(candidate["locator"])
                + "</legend><blockquote>"
                + esc(candidate["quote"])
                + "</blockquote>"
            )
            body += select(
                "action_" + ident,
                "Review decision",
                ["omit", "accept", "edit"],
                old_decision.get("action", "omit"),
            )
            body += field(
                "title_" + ident,
                "Activity title",
                reviewed_work.get("title", candidate["title"]),
                maxlength=500,
            )
            due = reviewed_work.get("due") or candidate["due"]
            body += field(
                "due_" + ident,
                "Due date or timestamp with UTC offset; leave blank if unknown",
                due.get("local_date") or due.get("timestamp") or "",
            )
            body += select(
                "required_" + ident,
                "Requirement",
                ["required", "student_chosen", "optional", "unresolved"],
                reviewed_work.get("requirement", "unresolved"),
            )
            body += select(
                "kind_" + ident,
                "Activity kind",
                [
                    "assignment",
                    "lab",
                    "peer_review",
                    "initial_post",
                    "reply",
                    "revision",
                    "in_class",
                    "preparation",
                    "module",
                    "personal",
                    "reading",
                    "quiz",
                ],
                reviewed_work.get("activity_kind", "assignment"),
            )
            for candidate_field in candidate.get("fields", []):
                body += (
                    "<p>Unverified "
                    + esc(candidate_field["kind"].replace("_", " "))
                    + ": "
                    + esc(candidate_field["quote"])
                    + ". Review the original passage; this does not establish a complete grading policy.</p>"
                )
            body += field(
                "effort_" + ident,
                "Your remaining effort estimate in minutes (optional)",
                (reviewed_work.get("effort") or {}).get("maximum_minutes", ""),
                "number",
                min=1,
                max=100000,
            )
            body += "<details><summary>Link activity and review progress (optional)</summary>"
            body += select(
                "responsibility_" + ident,
                "Your responsibility",
                ["self", "group_unassigned", "unknown"],
                reviewed_work.get("responsibility", "self"),
            )
            body += field(
                "completion_" + ident,
                "Explicit completion rule (optional)",
                reviewed_work.get("completion_rule") or "",
                maxlength=500,
            )
            for name in ("opens", "closes"):
                timing = reviewed_work.get(name) or {}
                body += field(
                    name + "_" + ident,
                    name.capitalize() + " date or timestamp (optional)",
                    timing.get("timestamp") or timing.get("local_date") or "",
                )
            body += (
                '<label>Activity identity<select name="work_'
                + ident
                + '" aria-label="Activity identity">'
            )
            chosen_key = reviewed_work.get("key", ident[:32])
            choices = {ident[:32]: "New activity: " + candidate["title"]} | {
                w["key"]: "Previously reviewed: " + w["title"] for w in old_work
            }
            body += (
                "".join(
                    '<option value="'
                    + esc(k)
                    + '"'
                    + (" selected" if k == chosen_key else "")
                    + ">"
                    + esc(label)
                    + "</option>"
                    for k, label in choices.items()
                )
                + "</select></label>"
            )
            body += field(
                "parent_" + ident,
                "Parent activity key (optional)",
                reviewed_work.get("parent_key") or "",
                maxlength=60,
            )
            body += field(
                "aliases_" + ident,
                "Reviewed alias keys, separated by commas (optional)",
                ", ".join(reviewed_work.get("aliases", [])),
                maxlength=500,
            )
            body += field(
                "prerequisites_" + ident,
                "Prerequisite keys, separated by commas (optional)",
                ", ".join(reviewed_work.get("prerequisites", [])),
                maxlength=500,
            )
            body += select(
                "progress_" + ident,
                "Your progress assertion",
                ["unknown", "not_started", "in_progress", "student_marked_done"],
                reviewed_work.get("progress", "unknown"),
            )
            body += select(
                "reported_" + ident,
                "Your report of official state (not a receipt)",
                ["unknown", "submitted", "graded", "excused"],
                reviewed_work.get("reported_status", "unknown"),
            )
            body += (
                '<label><input type="checkbox" name="revision_'
                + ident
                + '" value="yes"'
                + (" checked" if reviewed_work.get("revision_requested") else "")
                + ">An explicit revision is still required</label>"
            )
            body += "</details>"
            body += "</fieldset>"
        body += "<details><summary>Reviewed selection rule (optional)</summary>"
        body += field(
            "group_members", "Keys of explicitly interchangeable activities, separated by commas"
        )
        body += field("group_minimum", "Minimum required count", "", "number", min=1, max=30)
        body += field("group_selected", "Your selected activity keys, separated by commas")
        body += field(
            "group_basis",
            "Exact requirement basis (a best-scores grading rule is insufficient)",
            maxlength=500,
        )
        body += "</details>"
        body += "<button>Save these reviewed selections</button></form>"
        if start + 4 < len(found):
            body += f'<p><a href="?document_id={quote(row.id)}&start={start + 4}">Next candidate passages</a></p>'
        if not found:
            body += "<p>No supported deterministic candidates were found. The document remains available for permitted reading and search.</p>"
        body += "<details><summary>Inspect locally without sharing</summary>"
        for part in row.content["parsed"].get("pages", [])[:5]:
            body += (
                '<pre style="white-space:pre-wrap">' + esc(part.get("text", "")[:8000]) + "</pre>"
            )
        body += "</details>"
        body += start_form(
            session,
            "/settings/materials/metadata",
            document_id=row.id,
            expected_hash=row.version_hash,
            metadata_revision=row.content.get("metadata_revision", 0),
        )
        body += field(
            "course",
            "Correct course",
            row.content.get("course", "independent"),
            maxlength=100,
            required="required",
        )
        if row.content.get("purpose") == "own_feedback":
            body += field(
                "feedback_work",
                "Explicit work key for your own posted feedback",
                row.content.get("feedback_work", ""),
                maxlength=100,
            )
            body += '<label><input type="checkbox" name="own_feedback" value="yes" required>This is my own visible feedback, not peer work, hidden feedback or rubric descriptions alone.</label>'
        body += "<button>Save reviewed links</button></form>"
        primary = bridge.independent.profile()
        bound_primary = row.provenance.get("egress_policy")
        body += start_form(
            session,
            "/settings/materials/sharing",
            primary_review=primary.review_digest() if primary else "",
            document_id=row.id,
            expected_hash=row.version_hash,
            permission_version=row.provenance.get("permission_version", 0),
        )
        body += "<p>Change sharing for this exact document. Revocation removes dependent saved records.</p>"
        body += (
            '<label><input type="checkbox" name="share" value="yes"'
            + (
                " checked"
                if primary
                and bound_primary
                and RecipientPolicy.model_validate(bound_primary) == primary
                and row.provenance.get("share_text")
                else ""
            )
            + f">Allow extracted text with the configured ChatGPT recipient ({esc(primary.policy_id if primary else 'unavailable')})</label>"
        )
        body += (
            '<label><input type="checkbox" name="analysis" value="yes"'
            + (" checked" if "schedule" in row.provenance.get("scope", []) else "")
            + ">Allow planning, grade and schedule analysis</label>"
        )
        body += (
            '<label><input type="checkbox" name="visual" value="yes"'
            + (" checked" if row.provenance.get("share_visual") else "")
            + ">Allow reviewed page/slide images</label>"
        )
        external = bridge.independent.external_profile()
        if external:
            bound = row.provenance.get("external_egress_policy")
            checked = (
                " checked" if bound and RecipientPolicy.model_validate(bound) == external else ""
            )
            body += (
                f'<label><input type="checkbox" name="external_review" value="{external.review_digest()}"{checked}>'
                f"Also allow text and structured results for {esc(external.policy_id)} "
                f"({esc(external.client_id)}, {esc(external.environment)}, {esc(external.workspace)})</label>"
            )
        body += '<label><input type="checkbox" name="confirm" value="reviewed" required>I reviewed this selection and have permission for these uses</label><button>Save exact sharing choices</button></form>'
        body += "<p>Replacing a document requires its exact current version. The file picker below retains its identity and invalidates affected reviews.</p>"
        body += start_form(
            session,
            "/settings/materials/replace",
            document_id=row.id,
            expected_hash=row.version_hash,
        ).replace('<form method="post"', '<form method="post" enctype="multipart/form-data"')
        body += '<label>Replacement file<input type="file" name="document" required></label><label><input type="checkbox" name="own" value="yes" required>I have permission to process this replacement under the existing restrictions.</label><button>Replace this version</button></form>'
        body += start_form(session, "/settings/documents/delete", document_id=row.id)
        body += '<label><input type="checkbox" name="confirm" value="delete" required>Delete source and dependent records</label><button class="danger">Delete</button></form>'
        return page("Review imported evidence", body)

    @route("/settings/materials/review", ["POST"])
    async def save_review(request):
        session = await identity(request, True)
        values = await form(request, session)
        row = bridge.independent.require(session.owner, str(values.get("document_id", "")))
        decisions = {}
        prior = row.content.get("review")
        if prior:
            record = service.records.repo.read(session.owner, prior["record_id"])
            decisions = {
                d["candidate"]["id"]: {"action": d["action"], "work": d["correction"]}
                for d in record.data["value"]["decisions"]
            }
        try:
            for candidate in candidates(row):
                ident = candidate["id"]
                if "action_" + ident not in values:
                    continue
                action = values["action_" + ident]
                work = {
                    "key": values.get("work_" + ident, ident[:32]),
                    "title": values.get("title_" + ident, candidate["title"]),
                    "due": due_value(values.get("due_" + ident, "")),
                    "requirement": values.get("required_" + ident, "unresolved"),
                    "activity_kind": values.get("kind_" + ident, "assignment"),
                    "parent_key": values.get("parent_" + ident) or None,
                    "aliases": [
                        k.strip()
                        for k in str(values.get("aliases_" + ident, "")).split(",")
                        if k.strip()
                    ],
                    "prerequisites": [
                        k.strip()
                        for k in str(values.get("prerequisites_" + ident, "")).split(",")
                        if k.strip()
                    ],
                    "progress": values.get("progress_" + ident, "unknown"),
                    "reported_status": values.get("reported_" + ident, "unknown"),
                    "revision_requested": values.get("revision_" + ident) == "yes",
                    "responsibility": values.get("responsibility_" + ident, "self"),
                    "completion_rule": values.get("completion_" + ident) or None,
                    "opens": due_value(values.get("opens_" + ident, "")),
                    "closes": due_value(values.get("closes_" + ident, "")),
                }
                if values.get("effort_" + ident):
                    minutes = int(values["effort_" + ident])
                    work["effort"] = {
                        "minimum_minutes": minutes,
                        "maximum_minutes": minutes,
                        "origin": "student_estimate",
                    }
                decisions[ident] = {"action": action, "work": work if action != "omit" else None}
            service.save_review(
                session.owner,
                row.id,
                str(values.get("expected_hash", "")),
                decisions,
                expected_revision=int(values.get("expected_revision", 0)),
                key=str(values.get("key", "")),
                groups=[
                    {
                        "key": "reviewed_selection",
                        "members": [
                            k.strip() for k in values["group_members"].split(",") if k.strip()
                        ],
                        "minimum": int(values.get("group_minimum", 0)),
                        "selected": [
                            k.strip()
                            for k in str(values.get("group_selected", "")).split(",")
                            if k.strip()
                        ],
                        "basis": str(values.get("group_basis", "")),
                    }
                ]
                if values.get("group_members")
                else None,
                validate_session=request.state.validate_bridge_session,
            )
        except (ValidationError, ValueError):
            raise DomainError(
                "needs_input",
                "Review titles, distinct activity keys, dates and effort; timestamps need an explicit offset.",
            ) from None
        return RedirectResponse(
            "/settings/materials/review?document_id=" + quote(row.id), status_code=303
        )

    @route("/settings/materials/metadata", ["POST"])
    async def metadata(request):
        session = await identity(request, True)
        values = await form(request, session)
        row = bridge.independent.require(session.owner, str(values.get("document_id", "")))
        course = str(values.get("course", ""))
        if not 1 <= len(course) <= 100 or len(str(values.get("feedback_work", ""))) > 100:
            raise DomainError("needs_input", "Use bounded course and work labels.")
        generation = request.state.validate_bridge_session()
        with bridge.store.transaction() as database:
            principal = bridge.store.principal(database, session.owner)
            current = database.get(IndependentResource, row.id)
            if (
                principal.generation != generation
                or not current
                or current.version_hash != values.get("expected_hash")
                or current.content.get("metadata_revision", 0)
                != int(values.get("metadata_revision", -1))
            ):
                raise DomainError("source_changed", "Refresh the source before changing its links.")
            content = dict(current.content)
            feedback_changed = (
                content.get("purpose") == "own_feedback"
                and values.get("own_feedback") == "yes"
                and content.get("feedback_work", "") != str(values.get("feedback_work", ""))
            )
            if content.get("packet") and content.get("course") != course:
                raise DomainError(
                    "needs_input", "Import the packet under the new course as a separate binding."
                )
            if content.get("course", "independent") != course or feedback_changed:
                from canvas_bridge.processes.purge import purge_sources

                purge_sources(database, session.owner, source_ids=(row.id,))
                content = {
                    k: v
                    for k, v in content.items()
                    if k not in {"review", "reviewed_dataset", "version_history"}
                }
            content["course"] = course
            content["metadata_revision"] = content.get("metadata_revision", 0) + 1
            if content.get("purpose") == "own_feedback" and values.get("own_feedback") == "yes":
                content["feedback_work"] = str(values.get("feedback_work", ""))
            current.content = content
        return RedirectResponse(
            "/settings/materials/review?document_id=" + quote(row.id), status_code=303
        )

    @route("/settings/materials/replace", ["POST"])
    async def replace(request):
        session = await identity(request, True)
        # Bound streamed bytes before multipart parsing; session/CSRF validation still uses the standard form helper.
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > 10_100_000:
                raise DomainError("needs_input", "Replacement exceeds 10 MB.")
            raw.extend(chunk)
        request._body = bytes(raw)
        # Content length includes the file. The standard helper's 16 KB limit is for text forms.
        from urllib.parse import urlsplit

        root = urlsplit(bridge.settings.resource_url)
        if request.headers.get("origin") != f"{root.scheme}://{root.netloc}":
            raise DomainError("permission_denied", "Use the signed-in replacement form.")
        values = await request.form(max_files=1, max_fields=10, max_part_size=10_000_000)
        if (
            not secrets.compare_digest(str(values.get("csrf", "")), session.csrf)
            or values.get("own") != "yes"
        ):
            raise DomainError(
                "permission_denied", "Review replacement permission in the signed-in form."
            )
        row = bridge.independent.require(session.owner, str(values.get("document_id", "")))
        upload = values.get("document")
        if upload is None or not hasattr(upload, "read"):
            raise DomainError("needs_input", "Choose replacement file bytes.")
        try:
            data = await upload.read(10_000_001)
            if len(data) > 10_000_000:
                raise DomainError("needs_input", "Replacement exceeds 10 MB.")
            await bridge.independent.ingest(
                session.owner,
                data,
                upload.filename,
                upload.content_type or "application/octet-stream",
                own_material=True,
                share_text=row.provenance.get("share_text", False),
                share_visual=row.provenance.get("share_visual", False),
                allow_academic_analysis="schedule" in row.provenance.get("scope", []),
                course=row.content.get("course", "independent"),
                purpose=row.content.get("purpose", "material"),
                replace_id=row.id,
                expected_hash=str(values.get("expected_hash", "")),
                validate_session=request.state.validate_bridge_session,
            )
        finally:
            await values.close()
        return RedirectResponse(
            "/settings/materials/review?document_id=" + quote(row.id), status_code=303
        )

    @route("/settings/materials/sharing", ["POST"])
    async def change_sharing(request):
        session = await identity(request, True)
        values = await form(request, session)
        row = bridge.independent.require(session.owner, str(values.get("document_id", "")))
        if values.get("confirm") != "reviewed":
            raise DomainError("needs_input", "Review the exact sharing selection.")
        generation = request.state.validate_bridge_session()
        with bridge.store.transaction() as database:
            principal = bridge.store.principal(database, session.owner)
            current = database.get(IndependentResource, row.id)
            if (
                principal.generation != generation
                or not current
                or current.version_hash != values.get("expected_hash")
                or current.provenance.get("permission_version", 0)
                != int(values.get("permission_version", -1))
            ):
                raise DomainError("source_changed", "Refresh document permissions before saving.")
            profile = bridge.independent.profile()
            share = values.get("share") == "yes"
            external = bridge.independent.external_profile()
            selected = values.get("external_review")
            if (
                share
                and (selected or "primary_review" in values)
                and (not profile or values.get("primary_review") != profile.review_digest())
            ):
                raise DomainError(
                    "needs_input", "Refresh the configured ChatGPT recipient before sharing."
                )
            if selected and (not share or not external or selected != external.review_digest()):
                raise DomainError(
                    "needs_input",
                    "Refresh and review the exact recipients and text sharing selection.",
                )
            visual = share and values.get("visual") == "yes"
            if visual and current.content["parsed"].get("privacy", {}).get("page_content_filtered"):
                raise DomainError(
                    "permission_denied",
                    "Filtered source pages require a separate reviewed source before visual sharing.",
                )
            scope = ["document_reading", "study", "visual_analysis"] + (
                ["grade_planning", "schedule"] if values.get("analysis") == "yes" else []
            )
            from canvas_bridge.usefulness.workspace_authority import require_original_grant

            require_original_grant(
                bridge,
                database,
                current,
                share=share,
                visual=visual,
                scope=scope,
                profile=profile,
                external=external if selected else None,
            )
            old = current.provenance
            if (
                old.get("share_text")
                and not share
                or old.get("share_visual")
                and not visual
                or old.get("external_egress_policy")
                and not selected
                or set(old.get("scope", [])) - set(scope)
            ):
                from canvas_bridge.processes.purge import purge_sources

                purge_sources(database, session.owner, source_ids=(row.id,))
                current.content = {
                    k: v
                    for k, v in current.content.items()
                    if k not in {"review", "reviewed_dataset", "version_history"}
                }
            current.provenance = old | {
                "share_text": share,
                "share_visual": visual,
                "scope": scope,
                "permission_version": int(values["permission_version"]) + 1,
                "external_egress_policy": external.model_dump(mode="json") if selected else None,
                "egress_policy": profile.model_dump(mode="json") if profile and share else None,
            }
        return RedirectResponse(
            "/settings/materials/review?document_id=" + quote(row.id), status_code=303
        )

    @route("/settings/study", ["GET"])
    async def study(request):
        session = await identity(request)
        course = request.query_params.get("course", "independent")
        body = "<p>Only explicit saves create study history. These controls also work when MCP tools are read-only. Disabling collection and deleting existing history are separate actions.</p>"
        body += (
            '<form method="get">'
            + field("course", "Course", course, maxlength=100)
            + "<button>Choose course</button></form>"
        )
        for subtype, label in (("goal", "Save a selected goal"), ("task", "Add a personal task")):
            body += (
                "<h2>"
                + label
                + "</h2>"
                + start_form(session, "/settings/study/save", subtype=subtype, course=course)
            )
            body += field("text", "Concept or task title", maxlength=500, required="required")
            if subtype == "task":
                body += field("due", "Due date or timestamp (optional)")
                body += field(
                    "effort",
                    "Estimated remaining minutes (optional)",
                    "",
                    "number",
                    min=1,
                    max=100000,
                )
            body += sharing() + "<button>Save this selection</button></form>"
        goals = service.records.rows(session.owner, course, "goal")
        if goals:
            body += "<h2>Save an attempted practice outcome</h2>" + start_form(
                session, "/settings/study/save", subtype="attempt", course=course
            )
            body += (
                '<label>Goal<select name="goal_id">'
                + "".join(
                    f'<option value="{esc(g.id)}">{esc(g.data["value"]["concept"])}</option>'
                    for g in goals
                )
                + "</select></label>"
            )
            body += field("session_id", "Session label", secrets.token_hex(8), maxlength=100)
            body += field("prompt", "Attempted prompt", maxlength=1500, required="required")
            body += '<label>Selected response excerpt<textarea name="response" maxlength="3000"></textarea></label>'
            body += select(
                "evidence_kind",
                "Evidence kind",
                ["self_report", "practice_response", "deterministic_check", "host_interpretation"],
            )
            body += select("check", "Optional bounded check", ["none", "control_purpose"])
            body += field("observation", "Observation or uncertainty", maxlength=1000)
            body += field("next_exercise", "Selected next exercise (optional)", maxlength=1000)
            body += '<label><input type="checkbox" name="permitted" value="yes" required>This selected excerpt is mine and permitted; it contains no restricted source material.</label>'
            for document in bridge.independent.list(session.owner).data["documents"]:
                if document["course"] == course:
                    body += (
                        '<label><input type="checkbox" name="document_id" value="'
                        + esc(document["document_id"])
                        + '">Retain dependency on '
                        + esc(document["filename"])
                        + "</label>"
                    )
            body += "<p>Select every source used by this outcome. Leave the selection empty only for genuinely independent student-authored evidence.</p>"
            body += sharing() + "<button>Save selected outcome</button></form>"
        feedback = [
            bridge.independent.require(session.owner, d["document_id"])
            for d in bridge.independent.list(session.owner).data["documents"]
            if d["course"] == course
        ]
        feedback = [
            d
            for d in feedback
            if d.content.get("purpose") == "own_feedback" and d.content.get("feedback_work")
        ]
        if feedback:
            body += "<h2>Save a selected feedback improvement</h2>" + start_form(
                session, "/settings/study/save", subtype="improvement", course=course
            )
            body += (
                '<label>Own linked feedback<select name="document_id">'
                + "".join(
                    '<option value="'
                    + esc(d.id)
                    + '">'
                    + esc(d.content.get("filename", d.id))
                    + "</option>"
                    for d in feedback
                )
                + "</select></label>"
            )
            body += field(
                "quote",
                "Exact feedback passage (from the first part)",
                maxlength=2000,
                required="required",
            )
            body += field(
                "action", "Your selected concrete improvement", maxlength=1000, required="required"
            )
            body += select(
                "practice",
                "Optional generated practice",
                [
                    "control_purpose",
                    "result_implication",
                    "claim_evidence",
                    "axis_units",
                    "clarify",
                ],
            )
            body += sharing() + "<button>Save this interpretation and source link</button></form>"
        choices, inventory = plan_choices(session.owner, course)
        if choices:
            body += "<h2>Save a reviewed plan block</h2>" + start_form(
                session, "/settings/study/save", subtype="plan", course=course, inventory=inventory
            )
            body += (
                '<label>Reviewed activity<select name="work_id" aria-label="Reviewed activity">'
                + "".join(
                    '<option value="' + esc(k) + '">' + esc(v[0]) + "</option>"
                    for k, v in choices.items()
                )
                + "</select></label>"
            )
            body += field("start", "Block start (timestamp with offset)", required="required")
            body += field("end", "Block end (timestamp with offset)", required="required")
            body += sharing() + "<button>Save local block for change review</button></form>"
        collection = service.records.rows(session.owner, course, "collection")
        body += "<h2>History collection</h2>" + start_form(
            session,
            "/settings/study/save",
            subtype="collection",
            course=course,
            expected_revision=collection[-1].revision if collection else 0,
        )
        body += (
            select(
                "enabled",
                "Future collection",
                ["disabled", "enabled"],
                "enabled"
                if not collection or collection[-1].data["value"]["enabled"]
                else "disabled",
            )
            + "<button>Save collection preference</button></form>"
        )
        for record in service.records.rows(session.owner, course, include_unavailable=True):
            value = record.data["value"]
            body += (
                "<details><summary>"
                + esc(record.data["subtype"].replace("_", " "))
                + " · "
                + esc(
                    value.get("concept")
                    or value.get("title")
                    or value.get("prompt")
                    or "Selected record"
                )
                + "</summary>"
            )
            for key in (
                "concept",
                "title",
                "prompt",
                "response",
                "observation",
                "next_exercise",
                "action",
                "state",
                "enabled",
            ):
                if key in value:
                    body += (
                        "<p><strong>"
                        + esc(key.replace("_", " ").capitalize())
                        + ":</strong> "
                        + esc(value[key])
                        + "</p>"
                    )
            if record.data["subtype"] == "import_review":
                body += (
                    "<p>"
                    + str(len(value["dataset"]["work"]))
                    + " reviewed activities. Open the imported document to correct its evidence.</p>"
                )
            if value.get("evaluation"):
                body += (
                    "<p>Assessment: "
                    + esc(
                        value["evaluation"]
                        .get("outcome", "unverified observation")
                        .replace("_", " ")
                    )
                    + ". This does not establish mastery.</p>"
                )
            if value.get("rejected"):
                body += "<p>This interpretation was rejected and is excluded from resumption.</p>"
            if record.data["subtype"] == "attempt":
                body += start_form(
                    session,
                    "/settings/study/reject",
                    record_id=record.id,
                    expected_revision=record.revision,
                )
                body += "<button>Reject this interpretation</button></form>"
                body += start_form(
                    session,
                    "/settings/study/save",
                    subtype="attempt",
                    course=course,
                    record_id=record.id,
                    expected_revision=record.revision,
                    goal_id=value["goal_id"],
                    session_id=value["session_id"],
                    permitted="yes",
                )
                body += field("prompt", "Correct attempted prompt", value["prompt"], maxlength=1500)
                body += field(
                    "response", "Correct selected response", value["response"], maxlength=3000
                )
                body += select(
                    "evidence_kind",
                    "Evidence kind",
                    [
                        "self_report",
                        "practice_response",
                        "deterministic_check",
                        "host_interpretation",
                    ],
                    value["evidence_kind"],
                )
                body += select(
                    "check", "Bounded check", ["none", "control_purpose"], value["check"]
                )
                body += field(
                    "observation", "Correct observation", value["observation"], maxlength=1000
                )
                body += field(
                    "next_exercise", "Next exercise", value["next_exercise"], maxlength=1000
                )
                body += sharing() + "<button>Save a versioned correction</button></form>"
                body += start_form(
                    session,
                    "/settings/study/forget",
                    course=course,
                    session_id=value["session_id"],
                    expected_version=service.records.state(session.owner).version,
                )
                body += '<label><input type="checkbox" name="confirm" value="delete" required>Forget all saved attempts in this session</label><button class="danger">Forget this session</button></form>'
            body += start_form(
                session,
                "/settings/study/delete",
                record_id=record.id,
                expected_revision=record.revision,
            )
            body += '<label><input type="checkbox" name="confirm" value="delete" required>Delete this record and its dependent history</label><button class="danger">Delete</button></form></details>'
        body += (
            '<p><a href="/settings/study/export?course='
            + quote(course)
            + '">Export remaining permitted local state</a> · <a href="/settings/changes?course='
            + quote(course)
            + '">Review changes</a> · <a href="/settings/materials">Add course materials</a></p>'
        )
        return page("Selected study records", body)

    @route("/settings/study/save", ["POST"])
    async def save(request):
        session = await identity(request, True)
        service.enabled()
        values = await form(request, session)
        course, subtype = str(values.get("course", "")), str(values.get("subtype", ""))
        if not 1 <= len(course) <= 100:
            raise DomainError("needs_input", "Choose a bounded course label.")
        kwargs = {
            "key": str(values.get("key", "")),
            "share": values.get("share") == "yes",
            "validate_session": request.state.validate_bridge_session,
        }
        try:
            if subtype == "attempt":
                if values.get("permitted") != "yes":
                    raise DomainError(
                        "permission_denied", "Review the selected excerpt's permission."
                    )
                goal = service.records.repo.read(session.owner, str(values.get("goal_id", "")))
                service.save_attempt(
                    session.owner,
                    course,
                    {
                        k: str(values.get(k, ""))
                        for k in (
                            "goal_id",
                            "session_id",
                            "prompt",
                            "response",
                            "evidence_kind",
                            "observation",
                            "next_exercise",
                            "check",
                        )
                    }
                    | {"concept": goal.data["value"]["concept"]},
                    record_id=values.get("record_id") or None,
                    expected_revision=int(values.get("expected_revision", 0)),
                    document_ids=values.getlist("document_id")[:5],
                    **kwargs,
                )
            elif subtype == "improvement":
                from canvas_bridge.usefulness.models import Improvement, Passage

                row = bridge.independent.require(session.owner, str(values.get("document_id", "")))
                if (
                    row.content.get("purpose") != "own_feedback"
                    or not row.content.get("feedback_work")
                    or row.content.get("course") != course
                ):
                    raise DomainError("needs_input", "Review your own feedback work link first.")
                passage = str(values.get("quote", ""))
                text = row.content["parsed"].get("pages", [{}])[0].get("text", "")
                offset = text.find(passage)
                if offset < 0:
                    raise DomainError(
                        "source_changed", "The feedback passage does not match the current source."
                    )
                improvement = Improvement(
                    feedback=Passage(
                        document_id=row.id,
                        expected_hash=row.version_hash,
                        part=1,
                        start=offset,
                        end=offset + len(passage),
                        quote=passage,
                    ),
                    work_key=row.content["feedback_work"],
                    kind="suggestion",
                    action=str(values.get("action", "")),
                    practice=values.get("practice"),
                )
                service.records.save(
                    session.owner,
                    course,
                    "improvement",
                    improvement.model_dump(mode="json")
                    | {
                        "interpretation_status": "student_reviewed_interpretation_not_instructor_requirement"
                    },
                    idempotency_key=kwargs.pop("key"),
                    sources=[service.records.document_tag(session.owner, row)],
                    **kwargs,
                )
            else:
                record_id, revision = None, 0
                if subtype == "goal":
                    text = str(values.get("text", ""))
                    if not 1 <= len(text) <= 200:
                        raise ValueError
                    value = {"concept": text}
                elif subtype == "task":
                    value = {
                        "key": fingerprint([session.owner, str(values.get("key", ""))])[:24],
                        "title": values.get("text"),
                        "activity_kind": "personal",
                        "requirement": "student_chosen",
                        "due": due_value(values.get("due", "")),
                    }
                    if values.get("effort"):
                        minutes = int(values["effort"])
                        value["effort"] = {
                            "minimum_minutes": minutes,
                            "maximum_minutes": minutes,
                            "origin": "student_estimate",
                        }
                    value = IndependentWork.model_validate(value).model_dump(mode="json")
                elif subtype == "collection":
                    value = {"enabled": values.get("enabled") == "enabled"}
                    kwargs["identity_hint"] = "collection:" + course
                    prior = service.records.rows(session.owner, course, "collection")
                    if prior:
                        record_id, revision = prior[-1].id, int(values.get("expected_revision", 0))
                elif subtype == "plan":
                    from canvas_bridge.planning import PinnedBlock

                    choices, inventory = plan_choices(session.owner, course)
                    if values.get("inventory") != inventory or values.get("work_id") not in choices:
                        raise DomainError(
                            "source_changed", "Refresh and choose a currently reviewed activity."
                        )
                    parent = choices[values["work_id"]][1]
                    kwargs["sources"] = parent.sources
                    block = PinnedBlock(
                        work_id=str(values.get("work_id", "")),
                        start=values.get("start"),
                        end=values.get("end"),
                    )
                    value = {"blocks": [block.model_dump(mode="json")], "calendar_action": False}
                else:
                    raise ValueError
                service.records.save(
                    session.owner,
                    course,
                    subtype,
                    value,
                    record_id=record_id,
                    expected_revision=revision,
                    idempotency_key=kwargs.pop("key"),
                    **kwargs,
                )
        except (ValueError, ValidationError):
            raise DomainError(
                "needs_input", "Review the selected fields and bounded input sizes."
            ) from None
        return RedirectResponse("/settings/study?course=" + quote(course), status_code=303)

    @route("/settings/study/reject", ["POST"])
    async def reject(request):
        session = await identity(request, True)
        values = await form(request, session)
        record = service.records.repo.read(session.owner, str(values.get("record_id", "")))
        if record.data.get("subtype") != "attempt":
            raise DomainError("needs_input", "Select a saved attempt interpretation.")
        value = record.data["value"] | {"rejected": True}
        service.records.save(
            session.owner,
            record.scope.course,
            "attempt",
            value,
            record_id=record.id,
            expected_revision=int(values.get("expected_revision", 0)),
            idempotency_key=str(values.get("key", "")),
            share=record.data["share"],
            sources=record.sources,
            depends_on=record.depends_on,
            validate_session=request.state.validate_bridge_session,
        )
        return RedirectResponse(
            "/settings/study?course=" + quote(record.scope.course), status_code=303
        )

    @route("/settings/study/delete", ["POST"])
    async def delete(request):
        session = await identity(request, True)
        values = await form(request, session)
        if values.get("confirm") != "delete":
            raise DomainError("needs_input", "Review the deletion selection.")
        service.records.delete(
            session.owner,
            str(values.get("record_id", "")),
            int(values.get("expected_revision", 0)),
            validate_session=request.state.validate_bridge_session,
        )
        return RedirectResponse("/settings/study", status_code=303)

    @route("/settings/study/export", ["GET"])
    async def export(request):
        session = await identity(request)
        rows = service.records.rows(
            session.owner, request.query_params.get("course", "independent")
        )
        return JSONResponse(
            {
                "schema": "usefulness-export-1",
                "records": [r.model_dump(mode="json", exclude={"scope"}) for r in rows],
            },
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": 'attachment; filename="selected-study-records.json"',
            },
        )

    @route("/settings/changes", ["GET"])
    async def changes(request):
        from canvas_bridge.usefulness.models import UsefulnessRequest

        session = await identity(request)
        course = request.query_params.get("course", "independent")
        result = service.changes(
            session.owner,
            UsefulnessRequest(
                operation="changes",
                course=course,
                cursor=request.query_params.get("cursor"),
                limit=5,
            ),
            [],
            local=True,
        )
        body = (
            "<p>"
            + esc(result.summary)
            + "</p><p>Viewing does not acknowledge a change. Notifications and live refresh remain disabled.</p>"
        )
        acks = service.records.rows(session.owner, course, "change_ack")
        for event in result.data.get("events", []):
            body += (
                '<section class="card"><h2>'
                + esc(event["category"].replace("_", " "))
                + "</h2><p>"
                + esc(event["recommended_action"])
                + "</p>"
            )
            for label, name in (("Old evidence", "old_evidence"), ("New evidence", "new_evidence")):
                body += "<h3>" + label + "</h3>"
                for evidence in event.get(name, []):
                    body += (
                        "<blockquote>"
                        + esc(evidence.get("quote", ""))
                        + "</blockquote><p>"
                        + esc(evidence.get("locator", "Reviewed source passage"))
                        + "</p>"
                    )
            body += (
                "<p>Review state: " + esc(event.get("acknowledgment", "unacknowledged")) + "</p>"
            )
            ack = next((r for r in acks if r.data["value"]["event_id"] == event["event_id"]), None)
            body += start_form(
                session,
                "/settings/changes/acknowledge",
                course=course,
                event_id=event["event_id"],
                expected_revision=ack.revision if ack else 0,
            )
            body += select("state", "Explicit action", ["acknowledged", "snoozed"])
            body += field("until", "Snooze until (timestamp with offset, optional)")
            body += sharing() + "<button>Save this action</button></form></section>"
        if result.data.get("next_cursor"):
            body += (
                '<a href="?course='
                + quote(course)
                + "&cursor="
                + quote(result.data["next_cursor"])
                + '">Next changes</a>'
            )
        return page("Review consequential changes", body)

    @route("/settings/changes/acknowledge", ["POST"])
    async def acknowledge(request):
        from datetime import datetime

        from canvas_bridge.usefulness.models import UsefulnessRequest

        session = await identity(request, True)
        values = await form(request, session)
        course = str(values.get("course", ""))
        # Reconstruct the exact event from current retained evidence, never caller claims.
        query = UsefulnessRequest(operation="changes", course=course, limit=20)
        events = []
        for _ in range(5):
            result = service.changes(session.owner, query, [], local=True)
            events.extend(result.data.get("events", []))
            if not result.data.get("next_cursor"):
                break
            query = query.model_copy(update={"cursor": result.data["next_cursor"]})
        event = next((e for e in events if e["event_id"] == values.get("event_id")), None)
        state = values.get("state")
        if not event or state not in {"acknowledged", "snoozed"}:
            raise DomainError(
                "source_changed", "Refresh the displayed change before acknowledging it."
            )
        until = None
        if state == "snoozed":
            try:
                until = datetime.fromisoformat(str(values.get("until", "")))
                if until.tzinfo is None or until <= bridge.retention.clock():
                    raise ValueError
            except ValueError:
                raise DomainError(
                    "needs_input", "Choose a future snooze time with an explicit timezone offset."
                ) from None
        previous = next(
            (
                r
                for r in service.records.rows(session.owner, course, "change_ack")
                if r.data["value"]["event_id"] == event["event_id"]
            ),
            None,
        )
        reviews = service.records.rows(session.owner, course, "import_review")
        sources = tuple({s.key: s for r in reviews for s in r.sources}.values())
        service.records.save(
            session.owner,
            course,
            "change_ack",
            {
                "event_id": event["event_id"],
                "state": state,
                "until": until.isoformat() if until else None,
            },
            record_id=previous.id if previous else None,
            expected_revision=int(values.get("expected_revision", 0)),
            idempotency_key=str(values.get("key", "")),
            share=values.get("share") == "yes",
            sources=sources,
            identity_hint=event["event_id"],
            validate_session=request.state.validate_bridge_session,
        )
        return RedirectResponse("/settings/changes?course=" + quote(course), status_code=303)

    @route("/settings/study/forget", ["POST"])
    async def forget(request):
        from canvas_bridge.processes.state import apply, preview

        session = await identity(request, True)
        values = await form(request, session)
        if values.get("confirm") != "delete":
            raise DomainError("needs_input", "Review the session deletion.")
        generation = request.state.validate_bridge_session()
        repo = service.records.repo
        with bridge.store.transaction() as database:
            principal = bridge.store.principal(database, session.owner)
            row, state = repo._load(database, session.owner)
            if principal.generation != generation or state.version != int(
                values.get("expected_version", -1)
            ):
                raise DomainError("source_changed", "Refresh saved sessions before deleting.")
            ids = [
                r.id
                for r in state.records.values()
                if r.scope.course == values.get("course")
                and r.data.get("schema") == "usefulness-1"
                and r.data.get("subtype") == "attempt"
                and r.data["value"]["session_id"] == values.get("session_id")
            ]
            for ident in ids:
                state = apply(
                    state,
                    preview(
                        state, session.owner, ident, None, "delete", now=bridge.retention.clock()
                    ),
                    now=bridge.retention.clock(),
                )
            if ids:
                repo._save(database, session.owner, row, state)
        return RedirectResponse("/settings/study", status_code=303)
