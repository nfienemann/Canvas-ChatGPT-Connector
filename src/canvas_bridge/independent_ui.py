"""Authenticated import and deletion; no model-callable upload or arbitrary paths."""

import html
import secrets
from urllib.parse import unquote, urlsplit

from starlette.responses import RedirectResponse

from canvas_bridge.document_policy import LOCAL_IMPORT_BYTES, SOURCE_BYTES, local_import_limit
from canvas_bridge.domain import DomainError


def register_import_routes(bridge, route, identity, form, page, hidden):
    @route("/settings/documents", ["GET"])
    async def documents(request):
        session = await identity(request)
        nonce = secrets.token_urlsafe(24)
        body = "<p>Import your own permitted study materials here, then use the document ID in ChatGPT. ChatGPT attachments are not automatically transferred to Bridge.</p>"
        body += "<p>Imports are encrypted, expire within 24 hours, and can be deleted below. Extraction runs locally in bounded workers. The selected recipient must also be configured by the operator.</p>"
        profile = bridge.independent.profile()
        body += (
            "<p>Model sharing: "
            + (
                "configured; per-document consent required"
                if profile
                else "unavailable until the operator reviews the exact recipient"
            )
            + ".</p>"
        )
        body += '<form id="upload">' + hidden("csrf", session.csrf)
        body += f'<label>Document (PPTX: {LOCAL_IMPORT_BYTES // 1_000_000} MB maximum; other formats: {SOURCE_BYTES // 1_000_000} MB)<input type="file" name="document" accept=".pdf,.docx,.pptx,.txt,.md,.xlsx" required></label>'
        body += '<label><input type="checkbox" name="own" required>I have permission to process this document. It is independently supplied, not restricted institutional content, an exam, confidential research, or another person’s educational record.</label>'
        body += '<label><input type="checkbox" name="share">Allow extracted text to be sent to the configured ChatGPT recipient for this document.</label>'
        body += '<label><input type="checkbox" name="analysis">Also allow grade calculations, study planning and schedule proposals from this document. These remain read-only analyses.</label>'
        body += '<label><input type="checkbox" name="visual">Allow PDF page images to be sent too. I have reviewed the entire pages for private information and have permission to share them.</label>'
        body += '<button>Import document</button><p id="result" role="status"></p></form>'
        body += f'''<script nonce="{nonce}">
document.querySelector('#upload').addEventListener('submit',async e=>{{
e.preventDefault();const f=e.target, file=f.document.files[0], out=document.querySelector('#result');
const limit=file?.name.toLowerCase().endsWith('.pptx')?{LOCAL_IMPORT_BYTES}:{SOURCE_BYTES};
if(!file||file.size>limit){{out.textContent=`Choose a document no larger than ${{limit/1000000}} MB.`;return;}}
f.querySelector('button').disabled=true;out.textContent='Processing locally…';
try{{const r=await fetch('/settings/documents/import',{{method:'POST',credentials:'same-origin',
headers:{{'Content-Type':file.type||'application/octet-stream','X-Bridge-CSRF':f.csrf.value,'X-Bridge-Filename':encodeURIComponent(file.name),'X-Bridge-Own':String(f.own.checked),'X-Bridge-Share':String(f.share.checked),'X-Bridge-Visual':String(f.visual.checked),'X-Bridge-Analysis':String(f.analysis.checked)}},body:file}});
if(r.ok)location.assign('/settings/documents');else out.textContent='Import was withheld. Check ownership, format, privacy and sharing permissions.';
}}catch{{out.textContent='Import did not complete. Check document status before retrying.';}}finally{{f.querySelector('button').disabled=false;}}
}});</script>'''
        for doc in bridge.independent.list(session.owner).data["documents"]:
            row = bridge.independent.require(session.owner, doc["document_id"])
            body += (
                '<section class="card"><h2>Imported document</h2><p>ID: <code>'
                + html.escape(row.id)
                + "</code></p><p>Expires: "
                + html.escape(doc["expires_at"])
                + "</p>"
            )
            body += (
                "<p>Extraction coverage: "
                + html.escape(str(row.content["parsed"].get("coverage", "unknown")))
                + "</p>"
            )
            body += (
                '<form method="post" action="/settings/documents/delete">'
                + hidden("csrf", session.csrf)
                + hidden("document_id", row.id)
            )
            body += '<label><input type="checkbox" name="confirm" value="delete" required>Delete this import and its stored extraction</label><button class="danger">Delete document</button></form></section>'
        response = page("Independent documents", body)
        response.headers["Content-Security-Policy"] += (
            f"; script-src 'nonce-{nonce}'; connect-src 'self'"
        )
        return response

    @route("/settings/documents/import", ["POST"])
    async def upload(request):
        session = await identity(request, True)
        root = urlsplit(bridge.settings.resource_url)
        if request.headers.get(
            "origin"
        ) != f"{root.scheme}://{root.netloc}" or not secrets.compare_digest(
            request.headers.get("x-bridge-csrf", ""), session.csrf
        ):
            raise DomainError("permission_denied", "Start from the signed-in import page.")
        filename = unquote(request.headers.get("x-bridge-filename", ""))
        limit = local_import_limit(filename.rsplit(".", 1)[-1].lower())
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > limit:
                raise DomainError("needs_input", f"The import exceeds {limit // 1_000_000} MB.")
            raw.extend(chunk)
        await bridge.independent.ingest(
            session.owner,
            bytes(raw),
            filename,
            request.headers.get("content-type", ""),
            own_material=request.headers.get("x-bridge-own") == "true",
            share_text=request.headers.get("x-bridge-share") == "true",
            share_visual=request.headers.get("x-bridge-visual") == "true",
            allow_academic_analysis=request.headers.get("x-bridge-analysis") == "true",
            validate_session=request.state.validate_bridge_session,
        )
        return page(
            "Import complete",
            '<p>Use the document ID from <a href="/settings/documents">your imports</a>.</p>',
        )

    @route("/settings/documents/delete", ["POST"])
    async def remove_document(request):
        session = await identity(request, True)
        values = await form(request, session)
        if values.get("confirm") != "delete":
            raise DomainError("needs_input", "Explicit deletion confirmation is required.")
        request.state.validate_bridge_session()
        bridge.independent.delete(session.owner, str(values.get("document_id", "")))
        return RedirectResponse("/settings/documents", status_code=303)
