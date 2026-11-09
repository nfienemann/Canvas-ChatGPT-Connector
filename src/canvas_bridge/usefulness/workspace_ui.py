"""Workspace portability uses only authenticated, CSRF-protected settings forms."""

import secrets
from urllib.parse import urlsplit

from starlette.responses import Response

from canvas_bridge.domain import DomainError
from canvas_bridge.usefulness.workspace import Workspace
from canvas_bridge.usefulness.workspace_package import LIMIT


def register(bridge, route, identity, form, page, hidden):
    from canvas_bridge.usefulness.ui import esc

    workspace = Workspace(bridge)

    @route("/settings/materials/workspace", ["GET"])
    async def selection(request):
        session = await identity(request)
        bridge.usefulness.enabled()
        course = request.query_params.get("course", "independent")
        body = (
            '<form method="get"><label>Course <input name="course" maxlength="100" value="'
            + esc(course)
            + '"></label><button>Choose course</button></form>'
        )
        body += (
            '<form method="post" action="/settings/materials/workspace/export">'
            + hidden("csrf", session.csrf)
            + hidden("course", course)
        )
        for doc in bridge.independent.list(session.owner).data["documents"]:
            if doc["course"] == course:
                body += (
                    '<label><input type="checkbox" name="document" value="'
                    + esc(doc["document_id"])
                    + '">'
                    + esc(doc["filename"])
                    + "</label>"
                )
        state = workspace.repo.inventory(session.owner)
        for record in state["records"]:
            if record.get("course") == course:
                body += (
                    '<label><input type="checkbox" name="record" value="'
                    + esc(record["id"])
                    + '">'
                    + esc(record["kind"] + " · " + record["id"])
                    + "</label>"
                )
        body += '<label><input type="checkbox" name="originals">Include eligible original source bytes</label><label><input type="checkbox" name="preferences">Include personal study preferences</label><button>Download selection</button></form>'
        body += (
            '<h2>Restore a selection</h2><form method="post" enctype="multipart/form-data" action="/settings/materials/workspace/preview">'
            + hidden("csrf", session.csrf)
            + '<label>Course workspace file<input type="file" name="bundle" required></label><button>Preview restore</button></form>'
        )
        return page("Course workspace export and restore", body)

    @route("/settings/materials/workspace/export", ["POST"])
    async def export(request):
        session = await identity(request, True)
        values = await form(request, session)
        raw = workspace.export(
            session.owner,
            str(values.get("course", "")),
            values.getlist("record"),
            values.getlist("document"),
            originals=values.get("originals") == "on",
            preferences=values.get("preferences") == "on",
            recipient=session.egress_identity,
            generation=request.state.validate_bridge_session(),
        )
        return Response(
            raw,
            media_type="application/zip",
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": 'attachment; filename="course-workspace.cbworkspace"',
            },
        )

    @route("/settings/materials/workspace/preview", ["POST"])
    @route("/settings/materials/workspace/restore", ["POST"])
    async def restore(request):
        session = await identity(request, True)
        bridge.usefulness.enabled()
        root = urlsplit(bridge.settings.resource_url)
        if request.headers.get("origin") != f"{root.scheme}://{root.netloc}":
            raise DomainError("permission_denied", "Review the workspace from signed-in settings.")
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > LIMIT + 16_000:
                raise DomainError("needs_input", "Choose a smaller course workspace.")
            body.extend(chunk)
        request._body = bytes(body)
        async with request.form(max_files=1, max_fields=100, max_part_size=16_000) as values:
            if not secrets.compare_digest(str(values.get("csrf", "")), session.csrf):
                raise DomainError("permission_denied", "Reload the signed-in restore form.")
            upload = values.get("bundle")
            if upload is None or not hasattr(upload, "read"):
                raise DomainError("needs_input", "Select the exact exported workspace.")
            raw = await upload.read(LIMIT + 1)
            commit = request.url.path.endswith("/restore")
            confirmation = str(values.get("confirmation", "")) if commit else None
            if commit and not confirmation:
                raise DomainError("needs_input", "Review an exact restore preview first.")
            choices = values.getlist("replace")
            result = workspace.restore(
                session.owner,
                raw,
                generation=request.state.validate_bridge_session(),
                choices=choices,
                confirmation=confirmation,
                key=values.get("key"),
            )
        history = {
            "current_store": "this installation",
            "paired_live_sqlite": "the paired live origin",
        }.get(result.get("history_authority"))
        assurance = (
            "<p>Source and deletion history verified against " + history + ".</p>"
            if history
            else ""
        )
        if commit:
            body = (
                "<p>"
                + esc(result["status"])
                + " · "
                + str(result["document_count"])
                + " sources created, "
                + str(result["record_count"])
                + " records written.</p>"
                + assurance
            )
            outcomes = result.get("outcomes", {})
        else:
            body = (
                "<p>Eligible records commit together. Unresolved records stay in the selected file.</p>"
                + assurance
            )
            outcomes = result
        for group in ("documents", "records"):
            for ident, item in outcomes.get(group, {}).items():
                body += (
                    "<p>"
                    + esc(ident)
                    + " · "
                    + esc(item["action"])
                    + " "
                    + esc(item.get("reason", ""))
                    + "</p>"
                )
        if outcomes.get("preferences"):
            body += "<p>Preferences · " + esc(outcomes["preferences"]["action"]) + "</p>"
        for item in outcomes.get("omitted", []):
            body += "<p>" + esc(item["id"]) + " · " + esc(item["reason"]) + "</p>"
        if commit:
            return page("Restore receipt", body)
        for endpoint in ("preview", "restore"):
            body += (
                '<form method="post" enctype="multipart/form-data" action="/settings/materials/workspace/'
                + endpoint
                + '">'
                + hidden("csrf", session.csrf)
            )
            if endpoint == "restore":
                body += hidden("confirmation", result["preview_id"]) + hidden(
                    "key", secrets.token_urlsafe(24)
                )
                body += "".join(hidden("replace", c) for c in choices)
            else:
                items = result["records"] | (
                    {"preferences": result["preferences"]} if result["preferences"] else {}
                )
                for ident, item in items.items():
                    if item["action"] in {"conflict", "replace"}:
                        body += (
                            '<label><input type="checkbox" name="replace" value="'
                            + esc(ident)
                            + '">Replace '
                            + esc(ident)
                            + "</label>"
                        )
            body += (
                '<label>Reselect the reviewed workspace file<input type="file" name="bundle" required></label><button>'
                + (
                    "Review conflict choices"
                    if endpoint == "preview"
                    else "Confirm eligible changes"
                )
                + "</button></form>"
            )
        return page("Review workspace restore", body)
